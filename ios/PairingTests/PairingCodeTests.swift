import XCTest
@testable import CompanionPairing
final class PairingCodeTests: XCTestCase {
    func value() -> [String: Any] { ["v":1,"server_id":String(repeating:"a",count:32),"name":"Fixture Mac","url":"https://192.0.2.20:8769","fingerprint":String(repeating:"b",count:64),"secret":String(repeating:"c",count:43)] }
    func json(_ object: [String: Any]) throws -> String { String(data: try JSONSerialization.data(withJSONObject: object), encoding: .utf8)! }
    func testAcceptsDesktopJSONAndKeepsInvitation() throws {
        let code = try PairInfo.pairingCode("\n " + json(value()) + "\n")
        XCTAssertEqual(code.name,"Fixture Mac");XCTAssertEqual(code.secret,String(repeating:"c",count:43))
    }
    func testAcceptsAppPairingLink() throws {
        var link = URLComponents();link.scheme = "stellar-secretary";link.host = "pair"
        link.queryItems = [URLQueryItem(name:"data",value:Data(try json(value()).utf8).base64EncodedString())]
        XCTAssertEqual(try PairInfo.pairingCode(link.string!).server_id,String(repeating:"a",count:32))
    }
    func testOrdinaryQRCodesAndMalformedCodesNeverBecomePairingRequests() {
        for code in ["https://example.com", "WIFI:T:WPA;S:fixture;;", "hello", "{}", "[]", "stellar-secretary://other?data=e30=", "stellar-secretary://pair?data=not-base64", String(repeating:"a",count:16385)] {
            XCTAssertThrowsError(try PairInfo.pairingCode(code),code)
        }
    }
    func testInvalidFingerprintSecretVersionAndEndpointRejected() throws {
        for (key,replacement) in [("fingerprint","wrong" as Any),("secret",""),("server_id","wrong"),("v",2),("url","http://192.0.2.20:8769"),("url","https://user:password@192.0.2.20:8769"),("url","https://192.0.2.20:8769?other=value"),("url","https://192.0.2.20:8769/path")] {
            var object = value();object[key] = replacement;XCTAssertThrowsError(try PairInfo.pairingCode(json(object)))
        }
    }
    func testConnectionFailuresAreActionableAndNeverPrintPrivateURL() {
        let timeout = NSError(domain:NSURLErrorDomain,code:NSURLErrorTimedOut,userInfo:[NSURLErrorFailingURLStringErrorKey:"https://example.invalid/pair?secret=private"])
        let message = PairingConnectionFailure.message(timeout)
        XCTAssertTrue(message.contains("超时"));XCTAssertTrue(message.contains("-1001"));XCTAssertFalse(message.contains("private"))
        XCTAssertTrue(PairingConnectionFailure.message(URLError(.notConnectedToInternet)).contains("本地网络"))
        XCTAssertTrue(PairingConnectionFailure.message(URLError(.cannotConnectToHost)).contains("刷新配对码"))
        XCTAssertTrue(PairingConnectionFailure.message(URLError(.serverCertificateUntrusted)).contains("加密身份校验"))
        XCTAssertTrue(PairingConnectionFailure.message(CancellationError()).contains("已取消"))
    }

    func testAlternateEndpointsRemainBoundToTheSameSecurePort() throws {
        var object = value();object["urls"] = [object["url"]!, "https://100.64.1.2:8769", "https://169.254.1.2:8769", "https://[fe80::1234]:8769"]
        let info = try PairInfo.pairingCode(json(object));XCTAssertEqual(info.connectionURLs.count,4);XCTAssertTrue(info.connectionURLs.contains("https://[fe80::1234%25en0]:8769"))
        for invalid in ["http://100.64.1.2:8769", "https://user:pass@100.64.1.2:8769", "https://100.64.1.2:9999", "https://100.64.1.2:8769/path"] {
            object["urls"] = [invalid];XCTAssertThrowsError(try PairInfo.pairingCode(json(object)))
        }
    }

}

import Network
final class PairingNetworkTests: XCTestCase {
    func testLocalTCPConnectionAndCancellation() async throws {
        let listener = try NWListener(using: .tcp, on: .any)
        let ready = expectation(description: "Listener ready")
        let queue = DispatchQueue(label: "fixture.listener")
        listener.stateUpdateHandler = { state in if case .ready = state { ready.fulfill() } }
        listener.newConnectionHandler = { connection in connection.start(queue: queue);connection.cancel() }
        listener.start(queue: queue);defer { listener.cancel() }
        await fulfillment(of: [ready], timeout: 3)
        let url = URL(string: "https://127.0.0.1:\(listener.port!.rawValue)")!
        try await PairingNetworkProbe(url: url).check()
        let selected = try await PairingNetworkProbe.firstReachable(["https://127.0.0.1:1",url.absoluteString],timeout:0.3)
        XCTAssertEqual(selected,url.absoluteString)
        let task = Task { try await PairingNetworkProbe(url: url).check() }
        task.cancel()
        do { try await task.value;XCTFail("Cancelled probe must not continue") }
        catch { XCTAssertTrue(error is CancellationError) }
    }
    func testClosedPortNeverCountsAsSuccessfulConnection() async throws {
        let listener = try NWListener(using: .tcp, on: .any)
        let ready = expectation(description: "Listener ready")
        listener.stateUpdateHandler = { state in if case .ready = state { ready.fulfill() } }
        listener.newConnectionHandler = { $0.cancel() }
        listener.start(queue: DispatchQueue(label:"fixture.closed"))
        await fulfillment(of: [ready], timeout: 3)
        let port = listener.port!.rawValue;listener.cancel()
        do {
            try await PairingNetworkProbe(url:URL(string:"https://127.0.0.1:\(port)")!,timeout:0.2).check()
            XCTFail("Closed port must not count as connected")
        } catch { XCTAssertTrue(error is PairingTransportFailure) }
    }
}

final class WiFiRelayTests: XCTestCase {
    func testLargeTransferAndHalfClosePreserveEveryByte() async throws {
        let queue=DispatchQueue(label:"fixture.wifi.echo")
        let echo=try NWListener(using:.tcp)
        var sockets:[NWConnection]=[]
        let ready=expectation(description:"Echo ready")
        echo.stateUpdateHandler={ state in if case .ready=state {ready.fulfill()} }
        echo.newConnectionHandler={ socket in
            sockets.append(socket)
            socket.start(queue:queue)
            func read() {
                socket.receive(minimumIncompleteLength:1,maximumLength:16384) {data,_,done,error in
                    if error != nil {socket.cancel();return}
                    socket.send(content:data,contentContext:done ? .finalMessage:.defaultMessage,isComplete:true,completion:.contentProcessed {error in
                        if error != nil {socket.cancel()} else if !done {read()}
                    })
                }
            };read()
        }
        echo.start(queue:queue);defer {echo.cancel();for socket in sockets {socket.cancel()}}
        await fulfillment(of:[ready],timeout:3)
        // Only the synthetic test binds to loopback. Production uses Wi-Fi-only parameters.
        let parameters=NWParameters.tcp;parameters.requiredLocalEndpoint = .hostPort(host:"127.0.0.1",port:.any)
        let relay=try WiFiRelay(serverID:UUID().uuidString.replacingOccurrences(of:"-",with:""),upstreamPort:echo.port!.rawValue,serverParameters:parameters)
        let bound=expectation(description:"Relay ready")
        relay.listener.stateUpdateHandler={state in if case .ready=state {bound.fulfill()} }
        relay.start();defer {relay.stop()}
        await fulfillment(of:[bound],timeout:3)
        let payload=Data((0..<1_048_576).map {UInt8($0 % 251)})
        let received=expectation(description:"All opaque bytes returned")
        let client=NWConnection(host:"127.0.0.1",port:relay.listener.port!,using:.tcp)
        var output=Data()
        client.stateUpdateHandler={state in
            if case .ready=state {
                client.send(content:payload,contentContext:.finalMessage,isComplete:true,completion:.contentProcessed {_ in})
            }
        }
        func read() {
            client.receive(minimumIncompleteLength:1,maximumLength:32768) {data,_,done,error in
                if let data {output.append(data)}
                if done || error != nil {received.fulfill()} else {read()}
            }
        }
        client.start(queue:queue);read();defer {client.cancel()}
        await fulfillment(of:[received],timeout:15)
        XCTAssertEqual(output,payload)
    }
}

import Foundation
import Security
import CryptoKit
private final class FixtureTrust: NSObject,URLSessionDelegate {
    let expected:String
    private let lock=NSLock()
    private var count=0
    var challenges:Int {lock.lock();defer {lock.unlock()};return count}
    init(_ expected:String) {self.expected=expected}
    func urlSession(_ session:URLSession,didReceive challenge:URLAuthenticationChallenge,completionHandler:@escaping(URLSession.AuthChallengeDisposition,URLCredential?)->Void) {
        lock.lock();count += 1;lock.unlock()
        guard let trust=challenge.protectionSpace.serverTrust,let certificate=(SecTrustCopyCertificateChain(trust) as? [SecCertificate])?.first else {completionHandler(.cancelAuthenticationChallenge,nil);return}
        let actual=SHA256.hash(data:SecCertificateCopyData(certificate) as Data).map{String(format:"%02x",$0)}.joined()
        completionHandler(actual==expected ? .useCredential:.cancelAuthenticationChallenge,actual==expected ? URLCredential(trust:trust):nil)
    }
}
extension WiFiRelayTests {
    func testRealGatewayTLSAndAuthenticatedStatusThroughRelay() async throws {
        let env=ProcessInfo.processInfo.environment
        guard let value=env["STELLAR_TLS_FIXTURE_PORT"],let port=UInt16(value),let pin=env["STELLAR_TLS_FIXTURE_PIN"],let credential=env["STELLAR_TLS_FIXTURE_CREDENTIAL"] else {throw XCTSkip("Run scripts/check_wifi_tls.py for the isolated TLS fixture")}
        let parameters=NWParameters.tcp;parameters.requiredLocalEndpoint = .hostPort(host:"127.0.0.1",port:.any)
        let relay=try WiFiRelay(serverID:String(repeating:"e",count:32),upstreamPort:port,serverParameters:parameters)
        let ready=expectation(description:"TLS relay ready")
        relay.listener.stateUpdateHandler={state in if case .ready=state {ready.fulfill()}}
        relay.start();defer {relay.stop()};await fulfillment(of:[ready],timeout:3)
        let endpoint="https://127.0.0.1:\(relay.listener.port!.rawValue)"
        let direct="https://127.0.0.1:\(port)"
        let promoted=await PairingTLSProbe.firstVerifiedDirect(["https://127.0.0.1:1",direct],fingerprint:pin,timeout:2)
        XCTAssertEqual(promoted,direct)
        let wrongPin=await PairingTLSProbe.firstVerifiedDirect([direct],fingerprint:String(repeating:"0",count:64),timeout:2)
        XCTAssertNil(wrongPin)
        let verified=try await PairingTLSProbe.verified(endpoint,fingerprint:pin)
        XCTAssertEqual(verified,endpoint,"A pinned 403 response must allow an unpaired phone to select the carrier")
        do {
            _ = try await PairingTLSProbe.verified(endpoint,fingerprint:String(repeating:"0",count:64))
            XCTFail("A different certificate must never be selected")
        } catch { }
        let configuration=URLSessionConfiguration.ephemeral;configuration.connectionProxyDictionary=[:]
        let trust=FixtureTrust(pin)
        let session=URLSession(configuration:configuration,delegate:trust,delegateQueue:nil);defer {session.invalidateAndCancel()}
        for _ in 0..<3 {
            var request=URLRequest(url:URL(string:"https://127.0.0.1:\(relay.listener.port!.rawValue)/status")!);request.timeoutInterval=5
            request.setValue("Bearer "+credential,forHTTPHeaderField:"Authorization")
            let (data,response)=try await session.data(for:request)
            XCTAssertEqual((response as? HTTPURLResponse)?.statusCode,200)
            let object=try JSONSerialization.jsonObject(with:data) as? [String:Any]
            XCTAssertEqual(object?["connected"] as? Bool,true)
        }
        XCTAssertEqual(trust.challenges,1,"Foreground requests must reuse one pinned TLS connection")
        relay.stop()
        let recovered=await PairingTLSProbe.firstVerifiedDirect([endpoint,direct],fingerprint:pin,timeout:2)
        XCTAssertEqual(recovered,direct)
        var status=URLRequest(url:URL(string:direct+"/status")!)
        status.setValue("Bearer "+credential,forHTTPHeaderField:"Authorization")
        let (_,response)=try await session.data(for:status)
        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode,200,"The original pairing must work after losing the relay")

    }
}

final class BluetoothFramingTests:XCTestCase {
    func testFramesSurviveEveryNegotiatedChunkBoundary() throws {
        let id=UUID().uuidString,payload=Data((0..<32768).map {UInt8($0 % 251)})
        let frame=try XCTUnwrap(BluetoothRelay.frame(2,id:id,payload:payload))
        let size=UInt32(frame.count)
        var packet=Data([UInt8((size>>24)&255),UInt8((size>>16)&255),UInt8((size>>8)&255),UInt8(size&255)]);packet.append(frame)
        for mtu in [1,20,182,512] {
            var decoder=BluetoothFrameBuffer(),result:[Data]=[]
            for offset in stride(from:0,to:packet.count,by:mtu) {result += try decoder.append(packet.subdata(in:offset..<min(offset+mtu,packet.count)))}
            XCTAssertEqual(result,[frame])
        }
    }
    func testMalformedRadioLengthsCannotAllocateUnboundedData() {
        for invalid in [Data([255,255,255,255]),Data([0,0,0,1]),Data(count:65619)] {
            var decoder=BluetoothFrameBuffer();XCTAssertThrowsError(try decoder.append(invalid))
        }
        XCTAssertNil(BluetoothRelay.frame(2,id:UUID().uuidString,payload:Data(count:32769)))
    }
}

extension PairingNetworkTests {
    func testRestoredGatewayIsFoundWhileOtherDiscoveryContinues() async throws {
        let queue=DispatchQueue(label:"fixture.restored")
        let reservation=try NWListener(using:.tcp)
        let ready=expectation(description:"Reserved port")
        reservation.stateUpdateHandler={state in if case .ready=state {ready.fulfill()}}
        reservation.newConnectionHandler={$0.cancel()};reservation.start(queue:queue)
        await fulfillment(of:[ready],timeout:3)
        let port=reservation.port!
        let cancelled=expectation(description:"Reservation closed")
        reservation.stateUpdateHandler={state in if case .cancelled=state {cancelled.fulfill()}}
        reservation.cancel();await fulfillment(of:[cancelled],timeout:3)
        let listener=try NWListener(using:.tcp,on:port);listener.newConnectionHandler={$0.cancel()}
        queue.asyncAfter(deadline:.now()+0.2) {listener.start(queue:queue)}
        defer {listener.cancel()}
        let url="https://127.0.0.1:\(port.rawValue)"
        let result=try await PairingNetworkProbe.reachableWhileDiscovering([url],timeout:5)
        XCTAssertEqual(result,url)
    }
}

extension PairingNetworkTests {
    func testBonjourIPv4SurvivesMissingHostnameAndDuplicateResults() {
        var address=sockaddr_in()
        address.sin_family=sa_family_t(AF_INET)
        address.sin_addr.s_addr=inet_addr("192.0.2.77")
        let data=withUnsafeBytes(of:&address) { Data($0) }
        XCTAssertEqual(discoveredLANEndpoints(addresses:[Data(),data,data],hostname:nil,port:7443),["https://192.0.2.77:7443"])
        XCTAssertEqual(discoveredLANEndpoints(addresses:[data],hostname:"mac.local.",port:7443),["https://192.0.2.77:7443","https://mac.local.:7443"])
    }
    func testTCPReadyWithoutTLSIsRejected() async throws {
        let listener=try NWListener(using:.tcp,on:.any)
        let ready=expectation(description:"TCP-only fixture")
        let queue=DispatchQueue(label:"fixture.invalid-tls")
        listener.stateUpdateHandler={if case .ready=$0 {ready.fulfill()}}
        listener.newConnectionHandler={connection in
            connection.start(queue:queue)
            connection.send(content:Data("HTTP/1.1 200 OK\r\n\r\n".utf8),completion:.contentProcessed {_ in connection.cancel()})
        }
        listener.start(queue:queue);defer {listener.cancel()}
        await fulfillment(of:[ready],timeout:3)
        let endpoint="https://127.0.0.1:\(listener.port!.rawValue)"
        try await PairingNetworkProbe(url:URL(string:endpoint)!).check()
        do {
            _ = try await PairingTLSProbe.verified(endpoint,fingerprint:String(repeating:"0",count:64))
            XCTFail("TCP readiness must not win over a working secure carrier")
        } catch { }
    }
}

final class ConnectionResumePolicyTests: XCTestCase {
    func testShortSwitchReusesAndLongBackgroundRebuilds() {
        let start=Date(timeIntervalSince1970:1000)
        var policy=ConnectionResumePolicy()
        XCTAssertFalse(policy.needsFreshTransport(at:start))
        policy.enteredBackground(at:start)
        XCTAssertFalse(policy.needsFreshTransport(at:start.addingTimeInterval(3)))
        policy.enteredBackground(at:start)
        // A repeated background notification must not postpone the expiry.
        policy.enteredBackground(at:start.addingTimeInterval(19))
        XCTAssertTrue(policy.needsFreshTransport(at:start.addingTimeInterval(20)))
        XCTAssertFalse(policy.needsFreshTransport(at:start.addingTimeInterval(21)))
        policy.enteredBackground(at:start)
        XCTAssertTrue(policy.needsFreshTransport(at:start.addingTimeInterval(3600)))
    }
}

final class LibraryCacheTests: XCTestCase {
    func testSnapshotsPersistAcrossRestartAndAreScopedToPinnedMac() throws {
        let folder=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
        defer {try? FileManager.default.removeItem(at:folder)}
        let url=folder.appendingPathComponent("library.json"),now=Date()
        var cache=LibraryCache(serverID:"mac-a",fingerprint:"pin-a")
        cache.update([Record(["id":"one","title":"Cached note","summary":"Last verified summary"])],query:"",at:now)
        cache.update([],query:"missing",at:now)
        try cache.save(to:url)
        let restored=LibraryCache.load(from:url,serverID:"mac-a",fingerprint:"pin-a")
        XCTAssertEqual(restored.snapshots[""]?.records.first?.title,"Cached note")
        XCTAssertNotNil(restored.snapshots["missing"],"Empty searches are cached too")
        XCTAssertTrue(restored.snapshots[""]!.isFresh(at:now.addingTimeInterval(10)))
        XCTAssertFalse(restored.snapshots[""]!.isFresh(at:now.addingTimeInterval(61)))
        XCTAssertEqual(restored.snapshots[""]?.records.count,1,"Expiry must not delete the displayable snapshot")
        XCTAssertTrue(LibraryCache.load(from:url,serverID:"mac-b",fingerprint:"pin-a").snapshots.isEmpty)
        XCTAssertTrue(LibraryCache.load(from:url,serverID:"mac-a",fingerprint:"pin-b").snapshots.isEmpty)
        try Data("broken".utf8).write(to:url)
        XCTAssertTrue(LibraryCache.load(from:url,serverID:"mac-a",fingerprint:"pin-a").snapshots.isEmpty)
    }
    func testQueryHistoryAndRecordCountsAreBounded() {
        let now=Date();var cache=LibraryCache(serverID:"mac",fingerprint:"pin")
        let records=(0..<70).map {Record(["id":String($0)])}
        for number in 0..<20 {cache.update(records,query:String(number),at:now.addingTimeInterval(Double(number)))}
        XCTAssertEqual(cache.snapshots.count,8)
        XCTAssertNil(cache.snapshots["0"])
        XCTAssertEqual(cache.snapshots["19"]?.records.count,50)
        cache.invalidate()
        XCTAssertFalse(cache.snapshots["19"]!.isFresh(at:now.addingTimeInterval(20)))
        XCTAssertEqual(cache.snapshots["19"]?.records.count,50,"A new archive invalidates freshness without clearing visible results")
    }
}

final class ChatStoreTests:XCTestCase {
    func testChatCacheAndPendingSendSurviveRestartWithoutCrossingPairings() throws {
        let folder=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true);defer {try? FileManager.default.removeItem(at:folder)}
        let url=folder.appendingPathComponent("chats.json")
        var cache=ChatCache(serverID:"mac",fingerprint:"pin")
        cache.selectedID="shared";cache.threads=[ChatThread(["id":"shared","title":"Desktop conversation","updated":1])]
        cache.snapshots["shared"]=ChatSnapshot(id:"shared",title:"Desktop conversation",revision:"rev",messages:[ChatMessage(["id":"a","role":"assistant","text":"Saved answer","sources":[]])],hasMore:false)
        try cache.save(url)
        XCTAssertEqual(ChatCache.load(url,serverID:"mac",fingerprint:"pin").snapshots["shared"]?.messages.first?.text,"Saved answer")
        XCTAssertTrue(ChatCache.load(url,serverID:"other",fingerprint:"pin").snapshots.isEmpty)
        XCTAssertTrue(ChatCache.load(url,serverID:"mac",fingerprint:"changed").snapshots.isEmpty)
        let first=ChatAttachment(name:"one.png",data:Data([1]))
        let second=ChatAttachment(name:"two.png",data:Data([2]))
        let pending=PendingChatMessage(serverID:"mac",fingerprint:"pin",chatID:"shared",text:"Offline continuation",attachment:first)
        let batch=PendingChatMessage(serverID:"mac",fingerprint:"pin",chatID:"shared",text:"Both photos",attachmentBatch:[first,second])
        let queue=folder.appendingPathComponent("queue.json");try ChatCache.protectedWrite(JSONEncoder().encode([pending,batch]),to:queue)
        let restored=try JSONDecoder().decode([PendingChatMessage].self,from:Data(contentsOf:queue))
        XCTAssertEqual(restored.first?.id,pending.id);XCTAssertEqual(restored.first?.text,pending.text);XCTAssertEqual(restored.first?.chatID,"shared")
        XCTAssertEqual(restored.map(\.files),[[first],[first,second]])
    }
    func testCacheTrimmingRetainsSelectedChatAndHistoryCanBeFetchedAgain() {
        var cache=ChatCache(serverID:"mac",fingerprint:"pin");cache.selectedID="selected"
        for number in 0..<10 {
            let id=number==9 ? "selected":String(number)
            cache.threads.append(ChatThread(["id":id,"title":id]))
            cache.snapshots[id]=ChatSnapshot(id:id,title:id,revision:"r",messages:(0..<150).map {ChatMessage(["id":String($0),"role":"user","text":"Message"])},hasMore:false)
        }
        cache.trim();XCTAssertEqual(cache.snapshots.count,5)
        XCTAssertEqual(cache.snapshots["selected"]?.messages.count,100)
        XCTAssertTrue(cache.snapshots["selected"]?.hasMore==true)
    }
}
