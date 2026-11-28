import Foundation
import Darwin
import Network
import Security
import CryptoKit

// Keep fresh Bonjour IPv4 addresses ahead of routes saved on a different subnet.
func discoveredLANEndpoints(addresses: [Data], hostname: String?, port: Int) -> [String] {
    guard (1...65535).contains(port) else { return [] }
    var endpoints: [String] = []
    for data in addresses where data.count >= MemoryLayout<sockaddr_in>.size {
        var address = data.withUnsafeBytes { $0.loadUnaligned(as: sockaddr_in.self) }
        guard address.sin_family == AF_INET else { continue }
        var buffer = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
        guard inet_ntop(AF_INET, &address.sin_addr, &buffer, socklen_t(buffer.count)) != nil else { continue }
        let endpoint = "https://\(String(cString: buffer)):\(port)"
        if !endpoints.contains(endpoint) { endpoints.append(endpoint) }
    }
    if let hostname, !hostname.isEmpty { endpoints.append("https://\(hostname):\(port)") }
    return endpoints
}

// A short, credential-free transport check distinguishes LAN failures from TLS/HTTP failures.
final class PairingNetworkProbe: @unchecked Sendable {
    private let connection: NWConnection
    private let queue = DispatchQueue(label: "stellar.pairing.transport")
    private let timeout: TimeInterval
    private var continuation: CheckedContinuation<Void, Error>?
    private var finished = false
    init(url: URL, timeout: TimeInterval = 5, wifiOnly: Bool = false) throws {
        guard var host = URLComponents(url:url,resolvingAgainstBaseURL:false)?.host, let number = UInt16(exactly: url.port ?? 443), let port = NWEndpoint.Port(rawValue: number) else { throw PairingCodeError.invalid }
        if host.hasPrefix("["), host.hasSuffix("]") { host=String(host.dropFirst().dropLast()) }
        let parameters=NWParameters.tcp;parameters.preferNoProxies=true
        if wifiOnly {parameters.requiredInterfaceType = .wifi;parameters.includePeerToPeer=false}
        connection = NWConnection(host: NWEndpoint.Host(host), port: port, using: parameters)
        self.timeout = timeout
    }
    func check() async throws {
        try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                queue.async {
                    guard !self.finished else { continuation.resume(throwing: CancellationError()); return }
                    self.continuation = continuation
                    self.connection.stateUpdateHandler = { [weak self] state in
                        guard let self else { return }
                        switch state {
                        case .ready: self.finish(.success(()))
                        case .waiting:
                            if self.connection.currentPath?.unsatisfiedReason == .localNetworkDenied { self.finish(.failure(PairingTransportFailure.denied)) }
                        case .failed: self.finish(.failure(PairingTransportFailure.unreachable))
                        case .cancelled: self.finish(.failure(CancellationError()))
                        default: break
                        }
                    }
                    self.connection.start(queue: self.queue)
                    self.queue.asyncAfter(deadline: .now() + self.timeout) { [weak self] in self?.finish(.failure(PairingTransportFailure.timedOut)) }
                }
            }
        }, onCancel: { self.queue.async { self.finish(.failure(CancellationError())) } })
    }
    private struct Outcome: @unchecked Sendable { var url: String?; var error: Error? }
    static func firstReachable(_ urls: [String], timeout: TimeInterval = 5) async throws -> String {
        try Task.checkCancellation()
        guard !urls.isEmpty, urls.count <= 9 else { throw PairingCodeError.invalid }
        return try await withThrowingTaskGroup(of: Outcome.self) { group in
            for value in urls {
                group.addTask {
                    do {
                        guard let url = URL(string: value) else { throw PairingCodeError.invalid }
                        try await PairingNetworkProbe(url: url, timeout: timeout).check()
                        return Outcome(url: value)
                    } catch { return Outcome(error: error) }
                }
            }
            var failure: Error = PairingTransportFailure.timedOut
            for try await outcome in group {
                if let url = outcome.url { group.cancelAll();return url }
                if let error = outcome.error { failure = error }
            }
            try Task.checkCancellation()
            throw failure
        }
    }
    static func reachableWhileDiscovering(_ urls:[String],timeout:TimeInterval=12) async throws -> String {
        let deadline=Date().addingTimeInterval(timeout)
        var last:Error=PairingTransportFailure.timedOut
        repeat {
            try Task.checkCancellation()
            do {return try await firstReachable(urls,timeout:min(2,max(0.1,deadline.timeIntervalSinceNow)))}
            catch {
                try Task.checkCancellation();last=error
                if let failure=error as? PairingTransportFailure,case .denied=failure {throw error}
            }
            if deadline.timeIntervalSinceNow<=0 {break}
            try await Task.sleep(nanoseconds:500_000_000)
        } while Date()<deadline
        throw last
    }
    private func finish(_ result: Result<Void, Error>) {
        guard !finished else { return };finished = true
        connection.stateUpdateHandler = nil;connection.cancel()
        continuation?.resume(with: result);continuation = nil
    }
}

enum PairingTransportFailure: LocalizedError {
    case denied, unreachable, timedOut
    var errorDescription: String? {
        switch self {
        case .denied: return "系统仍拒绝此 App 访问本地网络。请重新关闭再开启知识秘书的本地网络权限，然后重试。（局域网权限）"
        case .unreachable: return "无法建立到 Mac 的局域网连接。请刷新配对码，并检查 Wi-Fi 的设备隔离或 VPN 路由。（TCP 未连接）"
        case .timedOut: return "手机无法连通 Mac 的配对端口。即使 Wi-Fi 名称相同，访客网络、设备隔离或 VPN 也可能阻断互访。（TCP 超时）"
        }
    }
}

// A TCP accept alone can be a stale relay or an unreachable TLS upstream.
// Race carriers through an actual pinned HTTPS response before selecting one.
final class PairingTLSProbe: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    private let fingerprint: String
    init(fingerprint: String) { self.fingerprint = fingerprint.lowercased() }
    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge, completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust,
              let certificate = (SecTrustCopyCertificateChain(trust) as? [SecCertificate])?.first,
              SHA256.hash(data: SecCertificateCopyData(certificate) as Data).map({ String(format: "%02x", $0) }).joined() == fingerprint else {
            completionHandler(.cancelAuthenticationChallenge, nil);return
        }
        completionHandler(.useCredential, URLCredential(trust: trust))
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
    static func verifiedWhileDiscovering(_ endpoint: String, fingerprint: String, timeout: TimeInterval = 12) async throws -> String {
        let deadline=Date().addingTimeInterval(timeout)
        var failure:Error=PairingTransportFailure.timedOut
        repeat {
            try Task.checkCancellation()
            do {return try await verified(endpoint,fingerprint:fingerprint,timeout:min(3,max(0.1,deadline.timeIntervalSinceNow)))}
            catch {try Task.checkCancellation();failure=error}
            let remaining = deadline.timeIntervalSinceNow
            guard remaining > 0 else {break}
            try await Task.sleep(nanoseconds:UInt64(min(0.5,remaining) * 1_000_000_000))
        } while Date()<deadline
        throw failure
    }
    static func firstVerifiedDirect(_ urls: [String], fingerprint: String, timeout: TimeInterval) async -> String? {
        await withTaskGroup(of: String?.self) { group in
            for url in urls.prefix(9) {
                group.addTask { try? await verified(url, fingerprint: fingerprint, timeout: timeout) }
            }
            for await endpoint in group {
                if let endpoint { group.cancelAll(); return endpoint }
            }
            return nil
        }
    }
    static func verified(_ endpoint: String, fingerprint: String, timeout: TimeInterval = 8) async throws -> String {
        try Task.checkCancellation()
        guard let url = URL(string: endpoint + "/pair/status") else { throw PairingCodeError.invalid }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.connectionProxyDictionary = [:]
        configuration.timeoutIntervalForRequest = timeout;configuration.timeoutIntervalForResource = timeout
        let session = URLSession(configuration: configuration, delegate: PairingTLSProbe(fingerprint: fingerprint), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        let (_, response) = try await session.data(from: url)
        // This credential-free endpoint returns 403 until authorized. Its TLS
        // certificate, rather than HTTP authorization, establishes the carrier.
        guard response is HTTPURLResponse else { throw PairingTransportFailure.unreachable }
        try Task.checkCancellation()
        return endpoint
    }
}

// The gateway closes idle HTTP sockets after 20 seconds. Beyond that interval,
// resuming old radio/relay state is less reliable than rebuilding the carrier.
struct ConnectionResumePolicy {
    private var backgroundSince: Date?
    mutating func enteredBackground(at date: Date = Date()) {
        if backgroundSince == nil { backgroundSince = date }
    }
    mutating func needsFreshTransport(at date: Date = Date()) -> Bool {
        defer { backgroundSince = nil }
        guard let backgroundSince else { return false }
        return date.timeIntervalSince(backgroundSince) >= 20
    }
}

#if DEBUG
// Compare only subnet membership; do not persist network addresses or SSIDs.
func wifiSubnetMatch(_ host: String) -> String {
    var target=in_addr(), head: UnsafeMutablePointer<ifaddrs>?
    guard inet_pton(AF_INET,host,&target)==1, getifaddrs(&head)==0 else {return "unknown"}
    defer {freeifaddrs(head)}
    var cursor=head
    while let item=cursor {
        let entry=item.pointee
        cursor=entry.ifa_next
        guard String(cString:entry.ifa_name)=="en0", let addr=entry.ifa_addr, let mask=entry.ifa_netmask,
              addr.pointee.sa_family==AF_INET else {continue}
        let ip=UnsafeRawPointer(addr).loadUnaligned(as:sockaddr_in.self).sin_addr.s_addr
        let bits=UnsafeRawPointer(mask).loadUnaligned(as:sockaddr_in.self).sin_addr.s_addr
        return (ip & bits)==(target.s_addr & bits) ? "same":"different"
    }
    return "no-wifi-ipv4"
}
#endif
