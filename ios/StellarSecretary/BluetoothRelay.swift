import Foundation
import Network
import CoreBluetooth
import os

struct BluetoothFrameBuffer {
    private var input=Data()
    mutating func append(_ data:Data) throws -> [Data] {
        guard input.count+data.count<=65618 else {throw PairingCodeError.invalid}
        input.append(data);var frames:[Data]=[]
        while input.count>=4 {
            let size=input.prefix(4).reduce(0){($0<<8)|Int($1)}
            guard (37...32805).contains(size) else {throw PairingCodeError.invalid}
            guard input.count>=size+4 else {break}
            frames.append(input.subdata(in:4..<(4+size)));input=Data(input.dropFirst(4+size))
        }
        return frames
    }
}

// BLE carries only opaque, end-to-end pinned TLS streams. No IP routing is
// involved in the radio leg. Length framing, acknowledgements and bounded
// queues provide backpressure independently of the negotiated GATT MTU.
final class BluetoothRelay:NSObject,CBCentralManagerDelegate,CBPeripheralDelegate,CBPeripheralManagerDelegate,@unchecked Sendable {
    private let queue=DispatchQueue(label:"stellar.bluetooth.relay")
    private let serviceUUID:CBUUID
    private let upstream:UInt16?
    private let rxUUID=CBUUID(string:"20DB7901-EC81-4444-91D8-487174CB4B22")
    private let txUUID=CBUUID(string:"20DB7902-EC81-4444-91D8-487174CB4B22")
    private var central:CBCentralManager?
    private var peripheralManager:CBPeripheralManager?
    private var peripheral:CBPeripheral?
    private var verifiedPeripheral:CBPeripheral?
    private var tryVerifiedPeer=false
    private var writeCharacteristic:CBCharacteristic?
    private var notifyCharacteristic:CBMutableCharacteristic?
    private var listener:NWListener?
    private var localURL:String?
    private var stopped=false
    private var links:[UUID:Link]=[:]
    private var channels:[String:Channel]=[:]
    private var waiters:[UUID:CheckedContinuation<String,Error>]=[:]
    private let logger=Logger(subsystem:"io.github.stellarstar255.secretary",category:"BluetoothRelay")
    private func report(_ stage:String) {logger.notice("\(stage,privacy:.public)");diagnostic?(stage)}
    var diagnostic:(@Sendable(String)->Void)?
    var onAvailable:(@Sendable()->Void)?
    private final class Link {
        let id:UUID
        let central:CBCentral?
        var input=BluetoothFrameBuffer()
        var output=[Data]()
        var offset=0
        var writing=false
        init(_ id:UUID,_ central:CBCentral?=nil) {self.id=id;self.central=central}
    }
    private final class Channel {
        let socket:NWConnection
        let peer:UUID
        var reading=false
        var awaitingAck=false
        var eof=false
        var sentEOF=false
        var receivedEOF=false
        init(_ socket:NWConnection,_ peer:UUID) {self.socket=socket;self.peer=peer}
    }
    private final class CancellationToken:@unchecked Sendable {var cancelled=false}
    init(serverID:String,upstreamPort:UInt16?=nil) throws {
        let raw=Array(serverID);guard raw.count==32 else {throw PairingCodeError.invalid}
        serviceUUID=CBUUID(string:[String(raw[0..<8]),String(raw[8..<12]),String(raw[12..<16]),String(raw[16..<20]),String(raw[20..<32])].joined(separator:"-"))
        upstream=upstreamPort
        super.init()
        if upstreamPort==nil {
            let parameters=WiFiRelay.directParameters();parameters.requiredLocalEndpoint = .hostPort(host:"127.0.0.1",port:.any)
            listener=try NWListener(using:parameters)
            listener?.newConnectionHandler={ [weak self] in self?.accept($0) }
            listener?.stateUpdateHandler={ [weak self] state in
                guard let self else {return}
                if case .ready=state,let port=self.listener?.port {self.localURL="https://127.0.0.1:\(port.rawValue)";self.complete()}
            }
        }
    }
    func start() {queue.async {self.startOnQueue()}}
    private func startOnQueue() {
        guard !stopped else {return}
        if upstream != nil {
            if peripheralManager==nil {peripheralManager=CBPeripheralManager(delegate:self,queue:queue)}
        } else {
            if central==nil {listener?.start(queue:queue);central=CBCentralManager(delegate:self,queue:queue)}
            else {scan()}
        }
    }
    private func scan() {
        guard !stopped,central?.state == .poweredOn,peripheral==nil else {return}
        if tryVerifiedPeer,let known=verifiedPeripheral {
            tryVerifiedPeer=false;report("reconnect-known")
            connect(known,timeout:3);return
        }
        central?.scanForPeripherals(withServices:[serviceUUID],options:[CBCentralManagerScanOptionAllowDuplicatesKey:false])
    }
    func endpoint(timeout:TimeInterval=18) async throws -> String {
        let id=UUID(),token=CancellationToken()
        return try await withTaskCancellationHandler(operation:{try await withCheckedThrowingContinuation {continuation in self.queue.async {
            guard !token.cancelled,!self.stopped else {continuation.resume(throwing:CancellationError());return}
            self.startOnQueue()
            if self.central?.state == .unsupported || self.central?.state == .poweredOff {continuation.resume(throwing:PairingTransportFailure.unreachable);return}
            if let url=self.localURL,!self.links.isEmpty {continuation.resume(returning:url);return}
            self.waiters[id]=continuation
            self.queue.asyncAfter(deadline:.now()+timeout) {self.waiters.removeValue(forKey:id)?.resume(throwing:PairingTransportFailure.timedOut)}
        }}},onCancel:{self.queue.async {token.cancelled=true;self.waiters.removeValue(forKey:id)?.resume(throwing:CancellationError())}})
    }
    private func complete() {
        guard let url=localURL,!links.isEmpty else {return}
        let values=waiters.values;waiters.removeAll();for value in values {value.resume(returning:url)};onAvailable?()
    }
    func ownsEndpoint(_ url:String) async -> Bool {await withCheckedContinuation {c in queue.async {c.resume(returning:self.localURL==url)}}}
    func centralManagerDidUpdateState(_ central:CBCentralManager) {report("central-state-\(central.state.rawValue)");if central.state == .poweredOn {scan()} else {
        peripheral=nil;writeCharacteristic=nil;clearLinks()
        if central.state == .unsupported || central.state == .poweredOff {let values=waiters.values;waiters.removeAll();for value in values {value.resume(throwing:PairingTransportFailure.unreachable)}}
    }}
    func rememberVerifiedPeer() {queue.async {
        if let peripheral=self.peripheral,self.links[peripheral.identifier] != nil {self.verifiedPeripheral=peripheral}
    }}
    func reconnectKnownPeer() {queue.async {
        self.tryVerifiedPeer=true;self.startOnQueue()
    }}
    func centralManager(_ central:CBCentralManager,didDiscover peripheral:CBPeripheral,advertisementData:[String:Any],rssi RSSI:NSNumber) {
        guard self.peripheral==nil else {return};report("discovered");connect(peripheral,timeout:12)
    }
    private func connect(_ peripheral:CBPeripheral,timeout:TimeInterval) {
        self.peripheral=peripheral;peripheral.delegate=self;central?.stopScan();central?.connect(peripheral)
        queue.asyncAfter(deadline:.now()+timeout) { [weak self,weak peripheral] in
            guard let self,let peripheral,self.peripheral === peripheral,self.links[peripheral.identifier]==nil else {return};self.central?.cancelPeripheralConnection(peripheral)
        }
    }
    func centralManager(_ central:CBCentralManager,didConnect peripheral:CBPeripheral) {report("radio-connected");peripheral.discoverServices([serviceUUID])}
    func centralManager(_ central:CBCentralManager,didFailToConnect peripheral:CBPeripheral,error:Error?) {disconnected(peripheral)}
    func centralManager(_ central:CBCentralManager,didDisconnectPeripheral peripheral:CBPeripheral,error:Error?) {disconnected(peripheral)}
    private func disconnected(_ value:CBPeripheral) {
        guard peripheral===value else {return};peripheral=nil;writeCharacteristic=nil;clearLinks();report("disconnected")
        queue.asyncAfter(deadline:.now()+1) {self.scan()}
    }
    func peripheral(_ peripheral:CBPeripheral,didDiscoverServices error:Error?) {
        guard error==nil,let service=peripheral.services?.first(where:{$0.uuid==serviceUUID}) else {central?.cancelPeripheralConnection(peripheral);return}
        peripheral.discoverCharacteristics([rxUUID,txUUID],for:service)
    }
    func peripheral(_ peripheral:CBPeripheral,didDiscoverCharacteristicsFor service:CBService,error:Error?) {
        guard error==nil,let rx=service.characteristics?.first(where:{$0.uuid==rxUUID}),let tx=service.characteristics?.first(where:{$0.uuid==txUUID}) else {central?.cancelPeripheralConnection(peripheral);return}
        writeCharacteristic=rx;peripheral.setNotifyValue(true,for:tx)
    }
    func peripheral(_ peripheral:CBPeripheral,didUpdateNotificationStateFor characteristic:CBCharacteristic,error:Error?) {
        guard characteristic.uuid==txUUID,error==nil,characteristic.isNotifying else {central?.cancelPeripheralConnection(peripheral);return}
        links[peripheral.identifier]=Link(peripheral.identifier);report("connected");complete()
    }
    func peripheral(_ peripheral:CBPeripheral,didUpdateValueFor characteristic:CBCharacteristic,error:Error?) {
        guard error==nil,characteristic.uuid==txUUID,let value=characteristic.value,let link=links[peripheral.identifier] else {return};receive(value,on:link)
    }
    func peripheral(_ peripheral:CBPeripheral,didWriteValueFor characteristic:CBCharacteristic,error:Error?) {
        guard let link=links[peripheral.identifier] else {return}
        if error != nil {central?.cancelPeripheralConnection(peripheral);return}
        link.writing=false;pump(link)
    }
    func peripheralManagerDidUpdateState(_ peripheral:CBPeripheralManager) {
        report("peripheral-state-\(peripheral.state.rawValue)")
        guard peripheral.state == .poweredOn,!stopped else {clearLinks();return}
        let rx=CBMutableCharacteristic(type:rxUUID,properties:[.write],value:nil,permissions:[.writeable])
        let tx=CBMutableCharacteristic(type:txUUID,properties:[.notify],value:nil,permissions:[]);notifyCharacteristic=tx
        let service=CBMutableService(type:serviceUUID,primary:true);service.characteristics=[rx,tx];peripheral.removeAllServices();peripheral.add(service)
    }
    func peripheralManager(_ peripheral:CBPeripheralManager,didAdd service:CBService,error:Error?) {
        if error==nil,!stopped {peripheral.startAdvertising([CBAdvertisementDataServiceUUIDsKey:[serviceUUID]])}
    }
    func peripheralManagerDidStartAdvertising(_ peripheral:CBPeripheralManager,error:Error?) {report(error == nil ? "advertising-ready":"advertising-failed-\((error! as NSError).code)")}
    func peripheralManager(_ peripheral:CBPeripheralManager,central:CBCentral,didSubscribeTo characteristic:CBCharacteristic) {
        guard characteristic.uuid==txUUID,links.count<4 || links[central.identifier] != nil else {return}
        drop(central.identifier);links[central.identifier]=Link(central.identifier,central);report("subscribed")
    }
    func peripheralManager(_ peripheral:CBPeripheralManager,central:CBCentral,didUnsubscribeFrom characteristic:CBCharacteristic) {drop(central.identifier)}
    func peripheralManager(_ peripheral:CBPeripheralManager,didReceiveWrite requests:[CBATTRequest]) {
        guard let first=requests.first else {return}
        guard requests.allSatisfy({$0.characteristic.uuid==rxUUID && $0.offset==0 && ($0.value?.count ?? 0)<=512 && links[$0.central.identifier] != nil}) else {peripheral.respond(to:first,withResult:.unlikelyError);return}
        for request in requests {if let value=request.value,let link=links[request.central.identifier] {receive(value,on:link)}}
        peripheral.respond(to:first,withResult:.success)
    }
    func peripheralManagerIsReady(toUpdateSubscribers peripheral:CBPeripheralManager) {for link in links.values {pump(link)}}
    private func pump(_ link:Link) {
        while !link.writing,let first=link.output.first {
            let limit:Int
            if let subscriber=link.central {limit=min(512,subscriber.maximumUpdateValueLength)}
            else if let peripheral {limit=min(512,peripheral.maximumWriteValueLength(for:.withResponse),peripheral.maximumWriteValueLength(for:.withoutResponse))}
            else {return}
            let end=min(first.count,link.offset+max(20,limit)),chunk=first.subdata(in:link.offset..<end)
            if let subscriber=link.central,let characteristic=notifyCharacteristic {
                guard peripheralManager?.updateValue(chunk,for:characteristic,onSubscribedCentrals:[subscriber])==true else {return}
            } else if let peripheral,let characteristic=writeCharacteristic {
                link.writing=true;peripheral.writeValue(chunk,for:characteristic,type:.withResponse)
            } else {return}
            link.offset=end
            if end==first.count {link.output.removeFirst();link.offset=0}
        }
    }
    private func send(_ kind:UInt8,id:String,to peer:UUID,payload:Data=Data()) {
        guard let link=links[peer],let frame=Self.frame(kind,id:id,payload:payload),link.output.reduce(0,{$0+$1.count})+frame.count<524288 else {close(id,notify:false);return}
        let length=UInt32(frame.count)
        var packet=Data([UInt8((length>>24)&255),UInt8((length>>16)&255),UInt8((length>>8)&255),UInt8(length&255)]);packet.append(frame)
        link.output.append(packet);pump(link)
    }
    static func frame(_ kind:UInt8,id:String,payload:Data=Data()) -> Data? {
        guard (1...4).contains(kind) || kind==7,UUID(uuidString:id) != nil,id.utf8.count==36,payload.count<=32768 else {return nil}
        var data=Data([kind]);data.append(Data(id.utf8));data.append(payload);return data
    }
    private func receive(_ data:Data,on link:Link) {
        do {for frame in try link.input.append(data) {handle(frame,peer:link.id)}}
        catch {drop(link.id)}
    }
    private func accept(_ socket:NWConnection) {
        guard channels.count<8,let peer=links.keys.first else {socket.cancel();return}
        let id=UUID().uuidString,channel=Channel(socket,peer);channel.awaitingAck=true;channels[id]=channel
        socket.stateUpdateHandler={ [weak self] state in if case .failed=state {self?.close(id)} };socket.start(queue:queue);send(1,id:id,to:peer)
    }
    private func handle(_ frame:Data,peer:UUID) {
        guard let id=String(data:frame.subdata(in:1..<37),encoding:.utf8),UUID(uuidString:id) != nil else {return}
        let kind=frame[0]
        if kind==1 {
            guard upstream != nil,channels.count<32,channels[id]==nil,frame.count==37 else {return}
            let socket=NWConnection(host:"127.0.0.1",port:NWEndpoint.Port(rawValue:upstream!)!,using:WiFiRelay.directParameters())
            let channel=Channel(socket,peer);channels[id]=channel
            socket.stateUpdateHandler={ [weak self] state in
                guard let self else {return}
                if case .ready=state {self.send(3,id:id,to:peer);self.read(id)} else if case .failed=state {self.close(id)}
            };socket.start(queue:queue);return
        }
        guard let channel=channels[id],channel.peer==peer else {return}
        if kind==2 {
            channel.socket.send(content:frame.subdata(in:37..<frame.count),completion:.contentProcessed { [weak self] error in
                guard let self,self.channels[id]===channel else {return}
                if error != nil {self.close(id)} else {self.send(3,id:id,to:peer)}
            })
        } else if kind==3,frame.count==37 {channel.awaitingAck=false;read(id)}
        else if kind==4,frame.count==37 {close(id,notify:false)}
        else if kind==7,frame.count==37 {
            channel.socket.send(content:nil,contentContext:.finalMessage,isComplete:true,completion:.contentProcessed { [weak self] _ in
                guard let self,self.channels[id]===channel else {return};channel.receivedEOF=true;if channel.sentEOF {self.close(id,notify:false)}
            })
        }
    }
    private func read(_ id:String) {
        guard let channel=channels[id],!channel.reading,!channel.awaitingAck,!channel.sentEOF else {return}
        if channel.eof {channel.sentEOF=true;send(7,id:id,to:channel.peer);if channel.receivedEOF {close(id,notify:false)};return}
        channel.reading=true
        channel.socket.receive(minimumIncompleteLength:1,maximumLength:1024) { [weak self] data,_,done,error in
            guard let self,self.channels[id]===channel else {return};channel.reading=false;channel.eof=done || error != nil
            if let data,!data.isEmpty {channel.awaitingAck=true;self.send(2,id:id,to:channel.peer,payload:data)} else {self.read(id)}
        }
    }
    private func close(_ id:String,notify:Bool=true) {guard let channel=channels.removeValue(forKey:id) else {return};channel.socket.stateUpdateHandler=nil;channel.socket.cancel();if notify {send(4,id:id,to:channel.peer)}}
    private func drop(_ peer:UUID) {links.removeValue(forKey:peer);for (id,channel) in channels where channel.peer==peer {close(id,notify:false)}}
    private func clearLinks() {for peer in Array(links.keys) {drop(peer)}}
    func stop() {queue.async {
        self.stopped=true;self.verifiedPeripheral=nil;self.central?.stopScan();if let peripheral=self.peripheral {self.central?.cancelPeripheralConnection(peripheral)}
        self.peripheralManager?.stopAdvertising();self.peripheralManager?.removeAllServices();self.listener?.cancel();self.clearLinks()
        for value in self.waiters.values {value.resume(throwing:CancellationError())};self.waiters.removeAll()
    }}
}
