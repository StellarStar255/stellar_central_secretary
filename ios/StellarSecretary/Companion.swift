import SwiftUI
import Security
import CryptoKit
import PhotosUI
import AVFoundation

struct PairInfo: Codable {
    var v: Int
    var server_id: String
    var name: String
    var url: String
    var fingerprint: String
    var secret: String?
}
struct PairedMac: Codable { var info: PairInfo; var credential: String }
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
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust,
              let certificate = (SecTrustCopyCertificateChain(trust) as? [SecCertificate])?.first else { completionHandler(.cancelAuthenticationChallenge, nil); return }
        let data = SecCertificateCopyData(certificate) as Data
        let actual = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard actual == fingerprint else { completionHandler(.cancelAuthenticationChallenge, nil); return }
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
    private func configure(_ pair: PairedMac) {
        session?.invalidateAndCancel()
        let configuration = URLSessionConfiguration.ephemeral;configuration.timeoutIntervalForRequest = 15;configuration.timeoutIntervalForResource = 300
        session = URLSession(configuration:configuration,delegate:PinnedSession(pair.info.fingerprint),delegateQueue:nil)
    }
    func discover() { guard paired != nil, !discovering else { return };discovering = true;browser.searchForServices(ofType:"_stellar-sec._tcp.",inDomain:"local.") }
    func netServiceBrowser(_ browser: NetServiceBrowser, didFind service: NetService, moreComing: Bool) { services.append(service);service.delegate = self;service.resolve(withTimeout:5) }
    func netServiceBrowser(_ browser: NetServiceBrowser, didRemove service: NetService, moreComing: Bool) { services.removeAll { $0 == service } }
    func netServiceDidResolveAddress(_ sender: NetService) {
        guard var pair = paired, let host = sender.hostName else { return }
        let txt = NetService.dictionary(fromTXTRecord:sender.txtRecordData() ?? Data())
        guard let id = txt["id"], String(data:id,encoding:.utf8) == pair.info.server_id else { return }
        pair.info.url = "https://\(host):\(sender.port)"
        paired = pair;try? CredentialStore.save(pair)
        Task { await connect() }
    }
    private func request(_ path: String, body: [String:Any]? = nil, using pair: PairedMac? = nil) async throws -> [String:Any] {
        guard let pair = pair ?? paired, let url = URL(string:pair.info.url + path), let session else { throw NSError(domain:"Companion",code:1,userInfo:[NSLocalizedDescriptionKey:"请先扫码配对"]) }
        var request = URLRequest(url:url);request.setValue("Bearer " + pair.credential,forHTTPHeaderField:"Authorization")
        if let body { request.httpMethod = "POST";request.httpBody = try JSONSerialization.data(withJSONObject:body);request.setValue("application/json",forHTTPHeaderField:"Content-Type");if path == "/ask" { request.timeoutInterval = 300 } }
        let (data,response) = try await session.data(for:request)
        let result = try JSONSerialization.jsonObject(with:data) as? [String:Any] ?? [:]
        let status = (response as? HTTPURLResponse)?.statusCode ?? 500
        guard (200...299).contains(status) else { throw NSError(domain:"Companion",code:status,userInfo:[NSLocalizedDescriptionKey:result["error"] as? String ?? "连接未完成，请重试"]) }
        return result
    }
    func pair(_ raw: String) async {
        guard !waiting else { return }
        do {
            let info = try JSONDecoder().decode(PairInfo.self,from:Data(raw.utf8))
            guard info.v == 1, info.fingerprint.count == 64, info.fingerprint.allSatisfy({$0.isHexDigit}), let url = URL(string:info.url), url.scheme == "https", url.host != nil, url.user == nil, url.password == nil, info.secret != nil else { throw NSError(domain:"Pairing",code:1,userInfo:[NSLocalizedDescriptionKey:"请扫描电脑端的手机配对二维码"]) }
            let credential = (0..<48).map { _ in UInt8.random(in:0...255) };let value = Data(credential).base64EncodedString()
            let pair = PairedMac(info:info,credential:value);candidate = pair;configure(pair);error = ""
            let result = try await request("/pair",body:["secret":info.secret!,"credential":value,"name":UIDevice.current.name],using:pair)
            code = result["code"] as? String ?? "";waiting = true;status = "请在 Mac 上核对数字并允许配对"
            let deadline = Date().addingTimeInterval(300)
            while waiting && Date() < deadline {
                try await Task.sleep(for:.seconds(2));let response = try await request("/pair/status",using:pair)
                if response["approved"] as? Bool == true {
                    var saved = pair;saved.info.secret = nil;try CredentialStore.save(saved);paired = saved;candidate = nil;waiting = false;code = "";discover();await connect();return
                }
            }
            throw NSError(domain:"Pairing",code:2,userInfo:[NSLocalizedDescriptionKey:"配对已超时，请刷新二维码后重新扫码"])
        } catch { waiting = false;code = "";candidate = nil;self.error = error.localizedDescription;if let paired { configure(paired) };status = "配对未完成" }
    }
    func connect() async {
        guard !waiting, let pair = paired else { return }
        do {
            let value = try await request("/status")
            guard value["server_id"] as? String == pair.info.server_id else { throw URLError(.serverCertificateUntrusted) }
            online = true;status = "已连接 · \(pair.info.name)";discover();await flush()
        } catch { online = false;status = "Mac 离线 · 内容将保留在手机";if (error as NSError).code == 401 { self.error = "此手机已被移除，请重新配对" } }
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
    func disconnect() { browser.stop();discovering = false;services.removeAll();session?.invalidateAndCancel();try? CredentialStore.save(nil);paired = nil;online = false;status = "连接你的 Mac" }
}
