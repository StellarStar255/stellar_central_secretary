import Foundation
import Network
import os

// Wi-Fi-only opaque TCP forwarding. URLSession still pins the actual Mac TLS
// certificate end-to-end; this component never reads credentials or HTTP data.
final class WiFiRelay: @unchecked Sendable {
    static let serviceType = "_stellar-wifi._tcp"
    private let queue = DispatchQueue(label:"stellar.wifi.relay")
    private let serverID: String
    private let upstreamPort: UInt16?
    let listener: NWListener
    private var browser: NWBrowser?
    private var target: NWEndpoint?
    private var routeGeneration = UUID()
    private var targetInterface: NWInterface?
    private var retryAfter: [String:Date] = [:]
    private var keeper: NWConnection?
    private var probes: [NWEndpoint:NWConnection] = [:]
    private var started = false
    private var stopped = false
    private var suspended=false
    private var localURL: String?
    private typealias Route = (url:String, generation:UUID)
    private var waiters: [UUID: CheckedContinuation<Route,Error>] = [:]
    private var pipes: [UUID: Pipe] = [:]
    var diagnostic: (@Sendable (String) -> Void)?
    private let logger=Logger(subsystem:"io.github.stellarstar255.secretary",category:"WiFiRelay")
    private func report(_ stage:String) {logger.notice("\(stage,privacy:.public)");diagnostic?(stage)}
    var onAvailable: (@Sendable () -> Void)?
    private final class CancellationToken: @unchecked Sendable { var cancelled=false }
    private final class Pipe {
        let left: NWConnection
        let right: NWConnection
        var finished = 0
        var ready = false
        init(_ left: NWConnection,_ right: NWConnection) { self.left=left;self.right=right }
    }
    static func directParameters() -> NWParameters {
        let parameters=NWParameters.tcp;parameters.preferNoProxies=true
        return parameters
    }
    static func wirelessParameters() -> NWParameters {
        let parameters=directParameters()
        parameters.includePeerToPeer=true
        parameters.prohibitedInterfaceTypes = [.wiredEthernet,.cellular]
        let tcp=parameters.defaultProtocolStack.transportProtocol as? NWProtocolTCP.Options
        tcp?.enableKeepalive=true;tcp?.keepaliveIdle=15;tcp?.keepaliveInterval=5;tcp?.keepaliveCount=3
        return parameters
    }
    init(serverID: String,upstreamPort: UInt16? = nil, serverParameters: NWParameters? = nil) throws {
        self.serverID=serverID;self.upstreamPort=upstreamPort
        if upstreamPort != nil {
            listener=try NWListener(using:serverParameters ?? Self.wirelessParameters())
            listener.service=NWListener.Service(name:"stellar-"+serverID,type:Self.serviceType)
        } else {
            let parameters=Self.directParameters()
            parameters.requiredLocalEndpoint = .hostPort(host:"127.0.0.1",port:.any)
            listener=try NWListener(using:parameters)
        }
        listener.newConnectionHandler={ [weak self] connection in self?.accept(connection) }
        listener.stateUpdateHandler={ [weak self] state in
            guard let self else { return }
            self.report("listener-"+String(describing:state))
            if case .ready=state, self.upstreamPort == nil,let port=self.listener.port {
                self.localURL="https://127.0.0.1:\(port.rawValue)";self.completeWaiters()
            }
        }
    }
    func start() { queue.async { self.startOnQueue() } }
    private func startOnQueue() {
        guard !stopped else { return };suspended=false
        if !started { started=true;listener.start(queue:queue) }
        if upstreamPort == nil && target == nil && browser == nil { browse() }
    }
    private func browse() {
        guard !stopped,!suspended,browser == nil else { return }
        let discovery=Self.directParameters();discovery.includePeerToPeer=true
        let browser=NWBrowser(for:.bonjour(type:Self.serviceType,domain:"local."),using:discovery)
        self.browser=browser
        browser.browseResultsChangedHandler={ [weak self,weak browser] results,_ in
            guard let self,let browser,self.browser === browser,self.target == nil else {return}
            for result in results {
                guard case .service(let name,let type,let domain,_)=result.endpoint,name == "stellar-"+self.serverID else {continue}
                for interface in result.interfaces where interface.type == .wifi || interface.name.hasPrefix("awdl") {
                    guard (self.retryAfter[interface.name] ?? .distantPast) <= Date() else {continue}
                    let endpoint=NWEndpoint.service(name:name,type:type,domain:domain,interface:interface)
                    if self.probes[endpoint] == nil && self.probes.count < 8 {
                        self.check(endpoint)
                    }
                }
            }
        }
        browser.stateUpdateHandler={ [weak self,weak browser] state in
            guard let self,let browser,self.browser === browser else { return }
            self.report("browser-"+String(describing:state))
            if case .failed=state { self.browser?.cancel();self.browser=nil }
        }
        browser.start(queue:queue)
    }
    private func check(_ endpoint: NWEndpoint) {
        let parameters=Self.directParameters()
        parameters.includePeerToPeer=true
        if case .service(_,_,_,let interface)=endpoint {parameters.requiredInterface=interface}
        let connection=NWConnection(to:endpoint,using:parameters)
        probes[endpoint]=connection
        connection.stateUpdateHandler={ [weak self,weak connection] state in
            guard let self,let connection,self.probes[endpoint] === connection else {return}
            self.report("probe-"+String(describing:state))
            switch state {
            case .ready:
                self.routeGeneration=UUID()
                self.target=connection.currentPath?.remoteEndpoint ?? endpoint
                if case .service(_,_,_,let interface)=endpoint {self.targetInterface=interface}
                self.browser?.cancel();self.browser=nil
                self.keeper?.cancel();self.keeper=connection
                let old=self.probes;self.probes.removeAll()
                for probe in old.values where probe !== connection {probe.cancel()}
                self.completeWaiters()
            case .failed:
                self.expireProbe(connection,endpoint:endpoint)
            default:break
            }
        }
        connection.start(queue:queue)
        queue.asyncAfter(deadline:.now()+8) { [weak self,weak connection] in
            if let connection {self?.expireProbe(connection,endpoint:endpoint)}
        }
    }
    private func expireProbe(_ connection:NWConnection,endpoint:NWEndpoint) {
        guard probes[endpoint] === connection else {return}
        probes.removeValue(forKey:endpoint);connection.cancel()
        guard probes.isEmpty,let current=browser else {return}
        queue.asyncAfter(deadline:.now()+1) { [weak self,weak current] in
            guard let self,let current,self.browser === current,self.probes.isEmpty else {return}
            current.cancel();self.browser=nil;self.browse()
        }
    }
    private func route(timeout: TimeInterval) async throws -> Route {
        let id=UUID(),token=CancellationToken()
        return try await withTaskCancellationHandler(operation:{
            try await withCheckedThrowingContinuation { continuation in self.queue.async {
                guard !token.cancelled,!self.stopped else {continuation.resume(throwing:CancellationError());return}
                self.startOnQueue()
                if let url=self.localURL,self.target != nil {continuation.resume(returning:(url,self.routeGeneration));return}
                self.waiters[id]=continuation
                self.queue.asyncAfter(deadline:.now()+timeout) {self.waiters.removeValue(forKey:id)?.resume(throwing:PairingTransportFailure.timedOut)}
            }}
        },onCancel:{self.queue.async {token.cancelled=true;self.waiters.removeValue(forKey:id)?.resume(throwing:CancellationError())}})
    }
    func verifiedEndpoint(fingerprint:String, timeout:TimeInterval = 14) async throws -> String {
        let deadline=Date().addingTimeInterval(timeout)
        while deadline.timeIntervalSinceNow > 0 {
            let (url,generation)=try await route(timeout:max(0,deadline.timeIntervalSinceNow))
            do {
                return try await PairingTLSProbe.verified(url,fingerprint:fingerprint,
                    timeout:min(4,max(0.1,deadline.timeIntervalSinceNow)))
            } catch {
                try Task.checkCancellation()
                await withCheckedContinuation { reply in
                    queue.async { [self] in
                        if self.target != nil, self.routeGeneration == generation, let interface=self.targetInterface {
                            // TCP can accept while the peer gateway is still unreachable over this interface.
                            self.retryAfter[interface.name]=Date().addingTimeInterval(3)
                            self.retryRoute(generation)
                            self.queue.asyncAfter(deadline:.now()+3) { [weak self] in
                                guard let self, self.target == nil, self.probes.isEmpty else {return}
                                self.browser?.cancel();self.browser=nil;self.browse()
                            }
                        }
                        reply.resume()
                    }
                }
            }
        }
        throw PairingTransportFailure.timedOut
    }
    private func completeWaiters() {
        guard let url=localURL,target != nil else { return }
        let values=waiters.values;waiters.removeAll();for value in values {value.resume(returning:(url,routeGeneration))}
        onAvailable?()
    }
    private func accept(_ incoming: NWConnection) {
        guard !stopped,pipes.count<32 else {incoming.cancel();return}
        let outgoing: NWConnection
        if let port=upstreamPort {
            outgoing=NWConnection(host:"127.0.0.1",port:NWEndpoint.Port(rawValue:port)!,using:Self.directParameters())
        } else if let target {
            let parameters=Self.directParameters();parameters.includePeerToPeer=true
            parameters.requiredInterface=targetInterface
            outgoing=NWConnection(to:target,using:parameters)
        } else { incoming.cancel();startOnQueue();return }
        let generation=routeGeneration
        let id=UUID(),pipe=Pipe(incoming,outgoing);pipes[id]=pipe
        incoming.stateUpdateHandler={ [weak self] state in if case .failed=state {self?.close(id)} }
        outgoing.stateUpdateHandler={ [weak self] state in
            guard let self,self.pipes[id] === pipe else {return}
            if case .ready=state {
                pipe.ready=true
                if self.routeGeneration == generation {self.keeper?.cancel();self.keeper=nil}
                self.copy(id,from:incoming,to:outgoing);self.copy(id,from:outgoing,to:incoming)
            }
            else if case .failed=state {
                self.close(id)
                self.retryRoute(generation)
            }
        }
        incoming.start(queue:queue);outgoing.start(queue:queue)
        queue.asyncAfter(deadline:.now()+10) { [weak self] in
            guard let self,self.pipes[id] === pipe,!pipe.ready else {return}
            self.close(id);self.retryRoute(generation)
        }
    }
    private func retryRoute(_ generation:UUID) {
        guard upstreamPort == nil, !stopped, !suspended, target != nil, routeGeneration == generation else {return}
        target=nil;targetInterface=nil;keeper?.cancel();keeper=nil
        browse()
    }
    private func copy(_ id:UUID,from:NWConnection,to:NWConnection) {
        from.receive(minimumIncompleteLength:1,maximumLength:32768) { [weak self] data,_,complete,error in
            guard let self,self.pipes[id] != nil else {return}
            if error != nil {self.close(id);return}
            to.send(content:data,contentContext:complete ? .finalMessage:.defaultMessage,isComplete:true,completion:.contentProcessed { [weak self] error in
                guard let self,let pipe=self.pipes[id] else {return}
                if error != nil {self.close(id)}
                else if complete {pipe.finished += 1;if pipe.finished==2 {self.close(id)}}
                else {self.copy(id,from:from,to:to)}
            })
        }
    }
    private func close(_ id:UUID) {
        guard let pipe=pipes.removeValue(forKey:id) else {return}
        pipe.left.stateUpdateHandler=nil;pipe.right.stateUpdateHandler=nil
        pipe.left.cancel();pipe.right.cancel()
    }
    func ownsEndpoint(_ url:String) async -> Bool {
        await withCheckedContinuation { continuation in queue.async {continuation.resume(returning:self.localURL == url)} }
    }
    func suspendDiscovery() {queue.async {
        self.suspended=true;self.browser?.cancel();self.browser=nil
        self.keeper?.cancel();self.keeper=nil
        let old=self.probes;self.probes.removeAll();for value in old.values {value.cancel()}
        self.target=nil;self.targetInterface=nil
    }}
    func rediscover() {queue.async {
        self.target=nil;self.targetInterface=nil;self.keeper?.cancel();self.keeper=nil;let old=self.probes;self.probes.removeAll();for value in old.values {value.cancel()}
        self.startOnQueue()
    }}
    func stop() {queue.async {
        self.stopped=true;self.keeper?.cancel();self.keeper=nil;self.browser?.cancel();for value in self.probes.values {value.cancel()};self.probes.removeAll();self.listener.cancel()
        for id in Array(self.pipes.keys) {self.close(id)}
        for value in self.waiters.values {value.resume(throwing:CancellationError())};self.waiters.removeAll()
    }}
}
