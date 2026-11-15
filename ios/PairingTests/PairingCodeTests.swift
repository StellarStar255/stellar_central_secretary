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
        var object = value();object["urls"] = [object["url"]!, "https://100.64.1.2:8769", "https://169.254.1.2:8769"]
        let info = try PairInfo.pairingCode(json(object));XCTAssertEqual(info.connectionURLs.count,3)
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
