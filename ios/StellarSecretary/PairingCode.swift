import Foundation

struct PairInfo: Codable {
    var v: Int
    var server_id: String
    var name: String
    var url: String
    var fingerprint: String
    var secret: String?

    static func pairingCode(_ raw: String) throws -> PairInfo {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.utf8.count <= 16_384 else { throw PairingCodeError.invalid }
        var data = Data(trimmed.utf8)
        if let link = URLComponents(string: trimmed), link.scheme == "stellar-secretary" {
            guard link.host == "pair", let encoded = link.queryItems?.first(where: { $0.name == "data" })?.value,
                  let decoded = Data(base64Encoded: encoded) else { throw PairingCodeError.invalid }
            data = decoded
        }
        guard let info = try? JSONDecoder().decode(PairInfo.self, from: data), info.v == 1,
              info.server_id.count == 32, info.server_id.allSatisfy({ $0.isHexDigit }),
              !info.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, info.name.count <= 200,
              info.fingerprint.count == 64, info.fingerprint.allSatisfy({ $0.isHexDigit }),
              let address = URLComponents(string: info.url), address.scheme == "https", address.host != nil,
              address.user == nil, address.password == nil, address.query == nil, address.fragment == nil,
              address.path.isEmpty, let secret = info.secret, (32...128).contains(secret.count)
        else { throw PairingCodeError.invalid }
        return info
    }
}
enum PairingCodeError: LocalizedError {
    case invalid
    var errorDescription: String? { "这不是知识秘书配对码。请在 Mac 的“手机连接”中刷新二维码，然后重新扫描。" }
}
