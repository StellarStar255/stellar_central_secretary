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
}
