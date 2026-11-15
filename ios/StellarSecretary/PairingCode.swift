import Foundation

struct PairInfo: Codable {
    var v: Int
    var server_id: String
    var name: String
    var url: String
    var fingerprint: String
    var secret: String?
    var urls: [String]?
    var connectionURLs: [String] {
        let candidates = Array(NSOrderedSet(array: [url] + (urls ?? []))) as? [String] ?? [url]
        return candidates.map { value in
            // Link-local IPv6 scope is local to the phone, not the Mac's interface index.
            if value.lowercased().hasPrefix("https://[fe80:") && !value.contains("%") {
                return value.replacingOccurrences(of:"]",with:"%25en0]")
            }
            return value
        }
    }

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
        guard (info.urls?.count ?? 0) <= 8, info.connectionURLs.allSatisfy({ endpoint in
            guard let candidate = URLComponents(string: endpoint), candidate.scheme == "https", candidate.host != nil,
                  candidate.user == nil, candidate.password == nil, candidate.query == nil, candidate.fragment == nil,
                  candidate.path.isEmpty, (candidate.port ?? 443) == (address.port ?? 443),
                  let port = UInt16(exactly: candidate.port ?? 443), port > 0 else { return false }
            return true
        }) else { throw PairingCodeError.invalid }
        return info
    }
}
enum PairingCodeError: LocalizedError {
    case invalid
    var errorDescription: String? { "这不是知识秘书配对码。请在 Mac 的“手机连接”中刷新二维码，然后重新扫描。" }
}

// Keep actionable pairing failures visible without exposing invitation secrets.
enum PairingConnectionFailure {
    static func message(_ error: Error) -> String {
        if error is CancellationError { return "已取消连接，可重新扫码。" }
        let value = error as NSError
        guard value.domain == NSURLErrorDomain else { return error.localizedDescription }
        let hint: String
        switch value.code {
        case NSURLErrorTimedOut:
            hint = "连接 Mac 超时。请确认两台设备在同一可互通的 Wi-Fi，检查 VPN 或访客网络是否阻止设备互访，再刷新 Mac 配对码重试。"
        case NSURLErrorNotConnectedToInternet:
            hint = "无法访问局域网。请在 iPhone 设置 → 隐私与安全性 → 本地网络中允许知识秘书访问，并确认与 Mac 连接同一 Wi-Fi。"
        case NSURLErrorCannotConnectToHost, NSURLErrorCannotFindHost, NSURLErrorDNSLookupFailed, NSURLErrorNetworkConnectionLost:
            hint = "无法连接配对码中的 Mac 地址。请保持 Mac 应用运行，确认同一 Wi-Fi，并在 Mac 刷新配对码后重试。"
        case NSURLErrorSecureConnectionFailed, NSURLErrorServerCertificateUntrusted, NSURLErrorServerCertificateHasBadDate, NSURLErrorServerCertificateHasUnknownRoot, NSURLErrorServerCertificateNotYetValid:
            hint = "Mac 的加密身份校验未通过。请检查两台设备的日期时间，并刷新 Mac 配对码后重新扫描。"
        case NSURLErrorCancelled:
            return "已取消连接，可重新扫码。"
        default:
            hint = "连接未完成，请确认本地网络权限、两台设备的 Wi-Fi 和 Mac 配对服务后重试。"
        }
        return hint + "（错误 \(value.code)）"
    }
}
