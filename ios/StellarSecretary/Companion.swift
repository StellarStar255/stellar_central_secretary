import SwiftUI
import Security
import CryptoKit
import PhotosUI
import AVFoundation

func pairingDiagnostic(_ stage: String, error: Error? = nil) {
    #if DEBUG
    let details = error.map { " domain=\(($0 as NSError).domain) code=\(($0 as NSError).code)" } ?? ""
    let line = "STELLAR_PAIRING " + stage + details + "\n"
    print(line, terminator: "")
    // Only stage names and numeric errors; never URLs, invitation codes or credentials.
    if let folder = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first {
        let file = folder.appendingPathComponent("pairing-diagnostic.log")
        var log = (try? Data(contentsOf: file)) ?? Data()
        if log.count > 64_000 { log = Data() }
        log.append(Data(line.utf8));try? log.write(to: file, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }
    #endif
}

struct PairedMac: Codable { var info: PairInfo; var credential: String; var transport: String? = nil }
struct Draft: Codable, Identifiable {
    var id = UUID().uuidString
    var serverID: String
    var text: String
    var filename: String?
    var data: String?
    var created = ISO8601DateFormatter().string(from: Date())
}
struct Record: Identifiable {
    var id: String; var title: String; var summary: String
    init(_ value: [String: Any]) { id = value["id"] as? String ?? value["item_id"] as? String ?? ""; title = value["title"] as? String ?? "资料"; summary = value["summary"] as? String ?? "" }
}
final class PinnedSession: NSObject, URLSessionDelegate {
    let fingerprint: String
    init(_ fingerprint: String) { self.fingerprint = fingerprint.lowercased() }
    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge, completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        pairingDiagnostic("tls-challenge")
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust,
              let certificate = (SecTrustCopyCertificateChain(trust) as? [SecCertificate])?.first else { completionHandler(.cancelAuthenticationChallenge, nil); return }
        let data = SecCertificateCopyData(certificate) as Data
        let actual = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard actual == fingerprint else { completionHandler(.cancelAuthenticationChallenge, nil); return }
        pairingDiagnostic("tls-pin-matched")
        completionHandler(.useCredential, URLCredential(trust: trust))
    }
}
enum CredentialStore {
    static let service = "io.github.stellarstar255.secretary.companion"
    static func load() -> PairedMac? {
        let query: [String: Any] = [kSecClass as String:kSecClassGenericPassword, kSecAttrService as String:service, kSecAttrAccount as String:"paired-mac", kSecReturnData as String:true]
        var value: CFTypeRef?; guard SecItemCopyMatching(query as CFDictionary, &value) == errSecSuccess, let data = value as? Data else { return nil }
        return try? JSONDecoder().decode(PairedMac.self, from:data)
    }
    static func save(_ value: PairedMac?) throws {
        let query: [String: Any] = [kSecClass as String:kSecClassGenericPassword, kSecAttrService as String:service, kSecAttrAccount as String:"paired-mac"]
        guard let value else { SecItemDelete(query as CFDictionary); return }
        let data = try JSONEncoder().encode(value)
        let attributes: [String:Any] = [kSecValueData as String:data, kSecAttrAccessible as String:kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        var status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound { status = SecItemAdd(query.merging(attributes) { _,new in new } as CFDictionary,nil) }
        guard status == errSecSuccess else { throw NSError(domain:NSOSStatusErrorDomain,code:Int(status)) }
    }
}
@MainActor final class Companion: NSObject, ObservableObject, NetServiceBrowserDelegate, NetServiceDelegate {
    @Published var paired: PairedMac?
    @Published var online = false
    @Published var status = "连接你的 Mac"
    @Published var error = ""
    @Published var code = ""
    @Published var waiting = false
    @Published var records: [Record] = []
    @Published var answer = ""
    @Published var sources: [Record] = []
    @Published var drafts: [Draft] = []
    @Published var busy = false
    private let browser = NetServiceBrowser()
    private var services: [NetService] = []
    private var session: URLSession?
    private var candidate: PairedMac?
    private var flushing = false
    private var discovering = false
    private var connecting = false
    private var mayRetryConnection = false
    private var discoveredURLs: [String] = []
    private var sessionEndpoint = ""
    private var wifiRelay: WiFiRelay?
    private var bluetoothRelay: BluetoothRelay?
    private var relayServerID = ""
    private var pairingInFlight = false
    private let queueURL: URL
    override init() {
        let folder = FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0]
        try? FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
        queueURL = folder.appendingPathComponent("outbox.json")
        super.init();paired = CredentialStore.load()
        if let data = try? Data(contentsOf:queueURL) { drafts = (try? JSONDecoder().decode([Draft].self,from:data)) ?? [] }
        browser.delegate = self
        if let pair = paired { configure(pair);status = "正在连接 \(pair.info.name)…";discover() }
    }
    private func transport(_ info: PairInfo, urls: [String], preferred: String? = nil) async throws -> String {
        if relayServerID != info.server_id {
            wifiRelay?.stop();bluetoothRelay?.stop();wifiRelay = try? WiFiRelay(serverID:info.server_id);relayServerID = info.server_id
            bluetoothRelay = try? BluetoothRelay(serverID:info.server_id)
            bluetoothRelay?.diagnostic = {pairingDiagnostic("bluetooth-"+$0)}
            bluetoothRelay?.onAvailable = { [weak self] in Task {await self?.connect()} }
            wifiRelay?.diagnostic = {pairingDiagnostic("wifi-"+$0)}
            wifiRelay?.onAvailable = { [weak self] in Task { await self?.connect() } }
        }
        #if DEBUG
        let bluetoothOnly=ProcessInfo.processInfo.arguments.contains("--bluetooth-only")
        #else
        let bluetoothOnly=false
        #endif
        let preferBluetooth=preferred == "bluetooth"
        if !bluetoothOnly && !preferBluetooth {wifiRelay?.start()};bluetoothRelay?.start()
        let wifi = wifiRelay, bluetooth=bluetoothRelay
        return try await withThrowingTaskGroup(of:String.self) { group in
            #if DEBUG
            let wifiOnly = ProcessInfo.processInfo.arguments.contains("--wifi-only")
            let nearbyOnly = bluetoothOnly || wifiOnly || ProcessInfo.processInfo.arguments.contains("--nearby-only")
            #else
            let nearbyOnly = false, wifiOnly = false
            #endif
            let directURLs=urls.filter { !(URLComponents(string:$0)?.host?.hasPrefix("169.254.") ?? false) }
            if !nearbyOnly && !bluetoothOnly && !directURLs.isEmpty { group.addTask {if preferBluetooth {try await Task.sleep(for:.seconds(3))};return try await PairingNetworkProbe.reachableWhileDiscovering(directURLs) } }
            if let wifi, !bluetoothOnly { group.addTask {if preferBluetooth {try await Task.sleep(for:.seconds(3))};return try await wifi.endpoint() } }
            if let bluetooth, !wifiOnly {group.addTask {if !bluetoothOnly && !preferBluetooth {try await Task.sleep(for:.seconds(4))};return try await bluetooth.endpoint()}}
            var failure: Error = PairingTransportFailure.timedOut
            while !group.isEmpty {
                do { if let endpoint = try await group.next() { group.cancelAll();return endpoint } }
                catch { failure = error }
            }
            throw failure
        }
    }
    private func configure(_ pair: PairedMac, pairing: Bool = false, endpoint: String? = nil) {
        session?.invalidateAndCancel();sessionEndpoint = endpoint ?? pair.info.url
        let configuration = URLSessionConfiguration.ephemeral;configuration.timeoutIntervalForRequest = 15;configuration.timeoutIntervalForResource = pairing ? 20 : 900
        configuration.httpMaximumConnectionsPerHost = 2
        configuration.waitsForConnectivity = pairing
        configuration.connectionProxyDictionary = [:]
        session = URLSession(configuration:configuration,delegate:PinnedSession(pair.info.fingerprint),delegateQueue:nil)
    }
    func discover() { guard paired != nil, !discovering else { return };discovering = true;browser.searchForServices(ofType:"_stellar-sec._tcp.",inDomain:"local.") }
    func netServiceBrowser(_ browser: NetServiceBrowser, didFind service: NetService, moreComing: Bool) { services.append(service);service.delegate = self;service.resolve(withTimeout:5) }
    func netServiceBrowser(_ browser: NetServiceBrowser, didRemove service: NetService, moreComing: Bool) { services.removeAll { $0 == service } }
    func netServiceDidResolveAddress(_ sender: NetService) {
        guard let pair = paired, let host = sender.hostName else { return }
        let txt = NetService.dictionary(fromTXTRecord:sender.txtRecordData() ?? Data())
        guard let id = txt["id"], String(data:id,encoding:.utf8) == pair.info.server_id else { return }
        let endpoint = "https://\(host):\(sender.port)"
        // Discovery is a hint, never overwrite a verified USB/Tailscale address.
        discoveredURLs = Array(([endpoint] + pair.info.connectionURLs.map { raw in
            guard var value = URLComponents(string:raw) else { return raw };value.port = sender.port;return value.string ?? raw
        } + discoveredURLs).prefix(16))
        Task { await connect() }
    }
    private func request(_ path: String, body: [String:Any]? = nil, using pair: PairedMac? = nil, timeout: TimeInterval? = nil) async throws -> [String:Any] {
        guard let pair = pair ?? paired, let url = URL(string:sessionEndpoint + path), let session else { throw NSError(domain:"Companion",code:1,userInfo:[NSLocalizedDescriptionKey:"请先扫码配对"]) }
        var request = URLRequest(url:url);if path == "/status" { request.timeoutInterval = 12 };if path == "/pair" { request.timeoutInterval = 15 };request.setValue("Bearer " + pair.credential,forHTTPHeaderField:"Authorization")
        if let body { request.httpMethod = "POST";request.httpBody = try JSONSerialization.data(withJSONObject:body);request.setValue("application/json",forHTTPHeaderField:"Content-Type");if path == "/ask" { request.timeoutInterval = 300 } }
        if let timeout { request.timeoutInterval = timeout }
        let (data,response) = try await session.data(for:request)
        let result = try JSONSerialization.jsonObject(with:data) as? [String:Any] ?? [:]
        let status = (response as? HTTPURLResponse)?.statusCode ?? 500
        guard (200...299).contains(status) else { throw NSError(domain:"Companion",code:status,userInfo:[NSLocalizedDescriptionKey:result["error"] as? String ?? "连接未完成，请重试"]) }
        return result
    }
    func pair(_ raw: String, requestAccepted: (() -> Void)? = nil) async {
        guard !pairingInFlight else { return }
        pairingInFlight = true;defer { pairingInFlight = false }
        pairingDiagnostic("begin")
        do {
            let info = try PairInfo.pairingCode(raw)
            pairingDiagnostic("code-valid")
            if var existing = paired, existing.info.server_id == info.server_id, existing.info.fingerprint == info.fingerprint {
                existing.info = info;existing.info.secret = nil
                let endpoint = try await transport(info,urls:info.connectionURLs,preferred:existing.transport)
                if !endpoint.hasPrefix("https://127.0.0.1:") { existing.info.url = endpoint }
                configure(existing,endpoint:endpoint)
                let response = try await request("/status",using:existing)
                guard response["server_id"] as? String == info.server_id else { throw URLError(.serverCertificateUntrusted) }
                try CredentialStore.save(existing);paired = existing;online = true;status = "已连接 · \(info.name)";error = ""
                pairingDiagnostic(endpoint.hasPrefix("https://127.0.0.1:") ? "existing-pair-nearby-verified" : "existing-pair-direct-verified");requestAccepted?();discover();await flush();return
            }
            let credential = (0..<48).map { _ in UInt8.random(in:0...255) };let value = Data(credential).base64EncodedString()
            let pair = PairedMac(info:info,credential:value);error = ""
            pairingDiagnostic("tcp-start")
            let endpoint = try await transport(info,urls:info.connectionURLs)
            candidate = pair;configure(pair, pairing:true,endpoint:endpoint)
            pairingDiagnostic("tcp-ready")
            pairingDiagnostic("request-start")
            let result = try await request("/pair",body:["secret":info.secret!,"credential":value,"name":UIDevice.current.name],using:pair)
            code = result["code"] as? String ?? "";waiting = true;status = "请在 Mac 上核对数字并允许配对"
            pairingDiagnostic("awaiting-mac-approval")
            requestAccepted?()
            let deadline = Date().addingTimeInterval(300)
            while waiting && Date() < deadline {
                try await Task.sleep(for:.seconds(2));let response = try await request("/pair/status",using:pair)
                if response["approved"] as? Bool == true {
                    var saved = pair;saved.info.secret = nil;try CredentialStore.save(saved);paired = saved;candidate = nil;waiting = false;code = "";configure(saved,endpoint:sessionEndpoint);discover();pairingInFlight = false;await connect();return
                }
            }
            throw NSError(domain:"Pairing",code:2,userInfo:[NSLocalizedDescriptionKey:"配对已超时，请刷新二维码后重新扫码"])
        } catch { pairingDiagnostic("failed",error:error);waiting = false;code = "";candidate = nil;self.error = PairingConnectionFailure.message(error);if let paired { configure(paired) } else { session?.invalidateAndCancel();session = nil };status = "配对未完成" }
    }
    private func canRefreshSession(after error:Error) -> Bool {
        let value=error as NSError
        return value.domain==NSURLErrorDomain && [-1001,-1004,-1005,-1009,-1200].contains(value.code)
    }
    func resumeConnection() async {
        guard let pair=paired,!waiting,!pairingInFlight,!connecting,!busy,!flushing else {return}
        let start=Date()
        bluetoothRelay?.reconnectKnownPeer()
        // A short app switch must not tear down a working pinned TLS session.
        if online,session != nil {
            await connect(quickResume:true)
            if online {
                pairingDiagnostic("resume-reused-ms-\(Int(Date().timeIntervalSince(start)*1000))")
                return
            }
            guard mayRetryConnection else {return}
        }
        guard !Task.isCancelled else {return}
        session?.invalidateAndCancel();session=nil;online=false
        status="正在连接 \(pair.info.name)…"
        await connect()
        pairingDiagnostic("resume-\(online ? "connected":"pending")-ms-\(Int(Date().timeIntervalSince(start)*1000))")
    }
    func connect(quickResume:Bool=false) async {
        guard !waiting, !pairingInFlight, !connecting, var pair = paired else { return }
        connecting = true;mayRetryConnection=false;defer { connecting = false }
        do {
            let urls = Array(NSOrderedSet(array: [pair.info.url] + discoveredURLs + pair.info.connectionURLs)) as? [String] ?? [pair.info.url]
            let endpoint = online && session != nil ? sessionEndpoint : try await transport(pair.info,urls:Array(urls.prefix(9)),preferred:pair.transport)
            guard !Task.isCancelled, !pairingInFlight, paired?.info.server_id == pair.info.server_id else { return }
            let nearby = endpoint.hasPrefix("https://127.0.0.1:")
            if !nearby { pair.info.url = endpoint }
            if session == nil || sessionEndpoint != endpoint { configure(pair,endpoint:endpoint) }
            let value:[String:Any]
            do {value = try await request("/status",using:pair,timeout:quickResume ? 3:nil)}
            catch {
                guard quickResume,!Task.isCancelled,canRefreshSession(after:error) else {throw error}
                // A genuinely stale socket gets one fresh, still-pinned TLS
                // session on the same carrier before rediscovering the Mac.
                configure(pair,endpoint:endpoint)
                value = try await request("/status",using:pair,timeout:6)
            }
            guard !Task.isCancelled, !pairingInFlight, paired?.info.server_id == pair.info.server_id else { return }
            guard value["server_id"] as? String == pair.info.server_id else { throw URLError(.serverCertificateUntrusted) }
            if let urls = value["urls"] as? [String], urls.count <= 8 {
                let port = URLComponents(string:pair.info.url)?.port ?? 443
                pair.info.urls = urls.filter { raw in
                    guard let value = URLComponents(string:raw) else { return false }
                    return value.scheme == "https" && value.host != nil && value.user == nil && value.password == nil && value.query == nil && value.fragment == nil && value.path.isEmpty && (value.port ?? 443) == port
                }
            }
            let wireless = await wifiRelay?.ownsEndpoint(endpoint) ?? false
            let bluetooth = await bluetoothRelay?.ownsEndpoint(endpoint) ?? false
            pair.transport = bluetooth ? "bluetooth" : wireless ? "wifi" : "direct"
            if bluetooth {bluetoothRelay?.rememberVerifiedPeer();wifiRelay?.suspendDiscovery()}
            pairingDiagnostic(bluetooth ? "connected-bluetooth-verified" : wireless ? "connected-wifi-verified" : nearby ? "connected-nearby-verified" : "connected-direct-verified")
            paired = pair;try CredentialStore.save(pair)
            online = true;status = "已连接 · \(pair.info.name)";error = "";discover();await flush()
        } catch {
            if Task.isCancelled {return}
            mayRetryConnection=canRefreshSession(after:error)
            pairingDiagnostic("connect-failed",error:error)
            wifiRelay?.rediscover()
            online = false;status = "Mac 离线 · 正在自动重连，内容将保留在手机"
            if (error as NSError).code == 401 { self.error = "此手机已被移除，请重新配对" }
        }
    }
    private func persist(_ next: [Draft]) throws {
        let data = try JSONEncoder().encode(next);try data.write(to:queueURL,options:[.atomic,.completeFileProtectionUntilFirstUserAuthentication]);var values = URLResourceValues();values.isExcludedFromBackup = true;var url = queueURL;try? url.setResourceValues(values);drafts = next
    }
    func enqueue(text: String, filename: String? = nil, data: Data? = nil) async -> Bool {
        guard let pair = paired else { error = "请先配对电脑";return false }
        guard !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || data != nil else { return false }
        guard (data?.count ?? 0) <= 10*1024*1024, drafts.count < 50 else { error = "每份附件最多 10 MB，待发送内容最多 50 条";return false }
        do { try persist(drafts + [Draft(serverID:pair.info.server_id,text:text,filename:filename,data:data?.base64EncodedString())]);error = "";await flush();return true }
        catch { self.error = "手机空间不足，内容尚未保存，请保留原内容";return false }
    }
    func removeDraft(_ id: String) { do { try persist(drafts.filter { $0.id != id }) } catch { self.error = "无法移除待发送内容" } }
    func flush() async {
        guard online, !flushing, let pair = paired else { return };flushing = true;defer { flushing = false }
        for draft in drafts where draft.serverID == pair.info.server_id {
            var content: [String:Any] = ["text":draft.text,"note_reference":draft.created]
            if let file = draft.filename, let data = draft.data { content["filename"] = file;content["data"] = data }
            else if let url = URL(string:draft.text.trimmingCharacters(in:.whitespacesAndNewlines)), ["https","http"].contains(url.scheme ?? ""), !draft.text.contains("\n") { content["url"] = url.absoluteString;content["text"] = "" }
            do { _ = try await request("/ingest",body:["request_id":draft.id,"content":content]);try persist(drafts.filter { $0.id != draft.id }) }
            catch { self.error = "待发送内容已保留：" + error.localizedDescription;return }
        }
    }
    func search(_ text: String) async {
        guard online else { error = "请先连接 Mac";return };busy = true;defer { busy = false }
        do { let value = try await request("/items?q=" + (text.addingPercentEncoding(withAllowedCharacters:.urlQueryAllowed.subtracting(CharacterSet(charactersIn:"&+#?"))) ?? ""));records = (value["items"] as? [[String:Any]] ?? []).map(Record.init);error = "" }
        catch { self.error = error.localizedDescription }
    }
    func ask(_ text: String) async {
        guard online else { error = "请先连接 Mac";return };busy = true;defer { busy = false }
        do { let value = try await request("/ask",body:["question":text]);answer = value["answer"] as? String ?? "";sources = (value["sources"] as? [[String:Any]] ?? []).map(Record.init);error = "" }
        catch { self.error = error.localizedDescription }
    }
    func detail(_ id: String) async throws -> [String:Any] { let response = try await request("/items/"+id);return response["item"] as? [String:Any] ?? [:] }
    func disconnect() { bluetoothRelay?.stop();bluetoothRelay=nil;wifiRelay?.stop();wifiRelay=nil;relayServerID="";discoveredURLs=[];browser.stop();discovering = false;services.removeAll();session?.invalidateAndCancel();try? CredentialStore.save(nil);paired = nil;online = false;status = "连接你的 Mac" }
}
