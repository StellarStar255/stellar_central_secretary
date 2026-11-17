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

struct Draft: Codable, Identifiable {
    var id = UUID().uuidString
    var serverID: String
    var fingerprint: String? = nil
    var text: String
    var filename: String?
    var data: String?
    var created = ISO8601DateFormatter().string(from: Date())
}
class PinnedSession: NSObject, URLSessionDelegate {
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
// A dedicated pinned download reports bytes and supports cancellation without
// invalidating the session used by library queries or editing.
private final class AttachmentTransfer: PinnedSession, URLSessionDownloadDelegate, @unchecked Sendable {
    private let lock=NSLock()
    private var continuation:CheckedContinuation<URL,Error>?
    private var task:URLSessionDownloadTask?
    private var transferSession:URLSession?
    private var cancelled=false
    private let destination:URL
    private let progress:@Sendable(Int64,Int64)->Void
    init(pin:String,destination:URL,progress:@escaping @Sendable(Int64,Int64)->Void) {
        self.destination=destination;self.progress=progress;super.init(pin)
    }
    func run(_ request:URLRequest) async throws -> URL {
        try await withTaskCancellationHandler(operation:{try await withCheckedThrowingContinuation {continuation in
            self.lock.lock()
            if self.cancelled {self.lock.unlock();continuation.resume(throwing:CancellationError());return}
            self.continuation=continuation
            let config=URLSessionConfiguration.ephemeral;config.connectionProxyDictionary=[:];config.timeoutIntervalForResource=900
            let session=URLSession(configuration:config,delegate:self,delegateQueue:nil)
            self.transferSession=session;let task=session.downloadTask(with:request);self.task=task
            self.lock.unlock();task.resume()
        }},onCancel:{self.lock.lock();self.cancelled=true;let task=self.task;self.lock.unlock();task?.cancel()})
    }
    private func finish(_ result:Result<URL,Error>) {
        lock.lock();let continuation=self.continuation;self.continuation=nil;let session=transferSession;transferSession=nil;task=nil;lock.unlock()
        continuation?.resume(with:result);session?.finishTasksAndInvalidate()
    }
    func urlSession(_ session:URLSession,downloadTask:URLSessionDownloadTask,didWriteData bytesWritten:Int64,totalBytesWritten:Int64,totalBytesExpectedToWrite:Int64) {
        progress(totalBytesWritten,totalBytesExpectedToWrite)
    }
    func urlSession(_ session:URLSession,downloadTask:URLSessionDownloadTask,didFinishDownloadingTo location:URL) {
        guard (downloadTask.response as? HTTPURLResponse)?.statusCode==200 else {finish(.failure(URLError(.badServerResponse)));return}
        do {
            try FileManager.default.moveItem(at:location,to:destination)
            try FileManager.default.setAttributes([.protectionKey:FileProtectionType.completeUntilFirstUserAuthentication],ofItemAtPath:destination.path)
            finish(.success(destination))
        } catch {finish(.failure(error))}
    }
    func urlSession(_ session:URLSession,task:URLSessionTask,didCompleteWithError error:Error?) {if let error {finish(.failure(error))}}
}
@MainActor final class Companion: NSObject, ObservableObject, NetServiceBrowserDelegate, NetServiceDelegate {
    @Published private(set) var paired: PairedMac?
    @Published private(set) var computers = PairedComputers()
    @Published private(set) var deviceGeneration = UUID()
    @Published private var activeWrites = 0
    @Published var captureEditor = CaptureEditor()
    @Published var chatInput = ""
    private var captureEditors: [String:CaptureEditor] = [:]
    private var chatInputs: [String:String] = [:]
    private var credentialStoreAvailable = true
    var canChangeComputer: Bool { credentialStoreAvailable && !pairingInFlight && !flushing && !chatSubmitting && activeWrites == 0 }
    var currentDrafts: [Draft] { drafts.filter { $0.serverID == paired?.info.server_id && $0.fingerprint == paired?.info.fingerprint } }
    var workspaceID: String { paired?.id ?? "unpaired" }
    private let storageFolder: URL
    @Published var online = false
    @Published var status = "连接你的 Mac"
    @Published var error = ""
    @Published var code = ""
    @Published var waiting = false
    @Published var records: [Record] = []
    @Published var libraryQuery = ""
    @Published var libraryRefreshing = false
    @Published var libraryUpdatedAt: Date?
    @Published var libraryMessage = ""
    private var libraryCache: LibraryCache?
    private var libraryTask: Task<Void, Never>?
    private var libraryRequestQuery: String?
    private var libraryGeneration = UUID()
    private var libraryCacheURL: URL {
        cacheURL("library", serverID: libraryCache?.serverID ?? "", fingerprint: libraryCache?.fingerprint ?? "")
    }
    @Published var selectedTab="archive"
    @Published var chatThreads:[ChatThread]=[]
    @Published var selectedChatID=""
    @Published var chatSnapshot:ChatSnapshot?
    @Published var pendingChatMessages:[PendingChatMessage]=[]
    @Published var chatNotice=""
    @Published var chatSubmitting=false
    @Published var chatStage=""
    @Published var chatPartial=""
    private var partialMessageID=""
    private var partialOffset=0
    private var chatCache:ChatCache?
    private var chatListSyncing=false
    private var chatFetchingID:String?
    private var chatCacheURL:URL {
        cacheURL("chat", serverID:chatCache?.serverID ?? "", fingerprint:chatCache?.fingerprint ?? "")
    }
    private let chatQueueURL:URL
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
    private var connectionTask: Task<Void, Never>?
    private var connectionGeneration = UUID()
    private var resumePolicy = ConnectionResumePolicy()
    private var inBackground = false
    private var mayRetryConnection = false
    private var discoveredURLs: [String] = []
    private var sessionEndpoint = ""
    private var wifiRelay: WiFiRelay?
    private var bluetoothRelay: BluetoothRelay?
    private var relayServerID = ""
    @Published private(set) var pairingInFlight = false
    private var pairingCancelled = false
    private let queueURL: URL
    override init() {
        let folder = FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0]
        try? FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
        queueURL = folder.appendingPathComponent("outbox.json")
        storageFolder=folder
        chatQueueURL=folder.appendingPathComponent("chat-outbox.json")
        super.init()
        do {computers = try CredentialStore.load();paired = computers.selected}
        catch {credentialStoreAvailable=false;self.error = "无法读取已保存的电脑，请解锁手机后重新打开 App"}
        if let data = try? Data(contentsOf:queueURL) { drafts = (try? JSONDecoder().decode([Draft].self,from:data)) ?? [] }
        if let data=try? Data(contentsOf:chatQueueURL) {pendingChatMessages=(try? JSONDecoder().decode([PendingChatMessage].self,from:data)) ?? []}
        // Legacy captures belonged to the original selected computer and pin.
        if let pair=paired {
            drafts = drafts.map { draft in
                var value=draft
                if value.serverID==pair.info.server_id && value.fingerprint==nil {value.fingerprint=pair.info.fingerprint}
                return value
            }
            try? persist(drafts)
            migrateCaches(pair)
        }
        browser.delegate = self
        if let pair = paired { configure(pair);status = "正在连接 \(pair.displayName)…";discover() }
    }
    private func cacheURL(_ kind:String, serverID:String, fingerprint:String) -> URL {
        storageFolder.appendingPathComponent(kind+"-"+PairedMac.identity(serverID:serverID,fingerprint:fingerprint)+".json")
    }
    private func migrateCaches(_ pair:PairedMac) {
        let library=cacheURL("library",serverID:pair.info.server_id,fingerprint:pair.info.fingerprint)
        let chat=cacheURL("chat",serverID:pair.info.server_id,fingerprint:pair.info.fingerprint)
        if !FileManager.default.fileExists(atPath:library.path) {
            let legacy=LibraryCache.load(from:storageFolder.appendingPathComponent("library-cache.json"),serverID:pair.info.server_id,fingerprint:pair.info.fingerprint)
            try? legacy.save(to:library)
        }
        if !FileManager.default.fileExists(atPath:chat.path) {
            let legacy=ChatCache.load(storageFolder.appendingPathComponent("chat-cache.json"),serverID:pair.info.server_id,fingerprint:pair.info.fingerprint)
            try? legacy.save(chat)
        }
    }
    private func remember(_ pair:PairedMac) throws {
        var next=computers;next.remember(pair)
        try CredentialStore.save(next);computers=next
    }
    private func saveInputs() {
        if let pair=paired {
            captureEditors[pair.id]=captureEditor
            chatInputs[pair.id+":"+selectedChatID]=chatInput
        }
    }
    private func activateComputer(_ pair:PairedMac?) {
        saveInputs();deviceGeneration=UUID();paired=pair
        rebuildConnectionTransport()
        candidate=nil;waiting=false;code="";mayRetryConnection=false
        libraryCache=nil;records=[];libraryQuery="";libraryUpdatedAt=nil;libraryMessage=""
        chatCache=nil;chatThreads=[];selectedChatID="";chatSnapshot=nil;chatPartial="";chatStage="";chatNotice=""
        chatFetchingID=nil;chatListSyncing=false;answer="";sources=[];error=""
        captureEditor=pair.flatMap {captureEditors[$0.id]} ?? CaptureEditor();chatInput=""
        if let pair {
            configure(pair);status="正在连接 \(pair.displayName)…";discover()
        } else {status="请选择电脑或添加新电脑"}
    }
    func selectComputer(_ id:String) async {
        guard canChangeComputer else {error="正在提交内容，请完成后再切换电脑";return}
        guard let pair=computers.computers.first(where:{$0.id==id}) else {return}
        if paired?.id==id {await connect();return}
        do {
            var next=computers;next.selectedID=id;try CredentialStore.save(next);computers=next
            activateComputer(pair);await connect()
        } catch {self.error="无法保存电脑选择，请稍后重试"}
    }
    func renameComputer(_ id:String, name:String) {
        var next=computers
        guard let index=next.computers.firstIndex(where:{$0.id==id}) else {return}
        let name=String(name.trimmingCharacters(in:.whitespacesAndNewlines).prefix(80))
        next.computers[index].nickname=name.isEmpty ? nil:name
        do {
            try CredentialStore.save(next);computers=next
            if paired?.id==id {paired=next.computers[index];status=online ? "已连接 · \(paired!.displayName)":"正在连接 \(paired!.displayName)…"}
        } catch {self.error="无法保存电脑备注"}
    }
    func removeComputer(_ id:String) {
        guard canChangeComputer else {error="正在提交内容，请完成后再移除电脑";return}
        do {
            var next=computers;next.remove(id);try CredentialStore.save(next);computers=next
            if paired?.id==id {activateComputer(nil)}
        } catch {self.error="无法移除配对，请稍后重试"}
    }
    func pendingCount(_ pair:PairedMac) -> Int {
        drafts.filter {$0.serverID==pair.info.server_id && $0.fingerprint==pair.info.fingerprint}.count + pendingChatMessages.filter {$0.serverID==pair.info.server_id && $0.fingerprint==pair.info.fingerprint}.count
    }
    func cancelPairing() {
        guard pairingInFlight else {return}
        pairingCancelled=true;waiting=false;candidate=nil;deviceGeneration=UUID()
        rebuildConnectionTransport()
        if let pair=paired {configure(pair)}
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
            if !nearbyOnly && !bluetoothOnly {
                for url in directURLs.prefix(9) { group.addTask {
                    if preferBluetooth {try await Task.sleep(for:.seconds(3))}
                    return try await PairingTLSProbe.verifiedWhileDiscovering(url,fingerprint:info.fingerprint)
                }}
            }
            if let wifi, !bluetoothOnly { group.addTask {if preferBluetooth {try await Task.sleep(for:.seconds(3))};let endpoint = try await wifi.endpoint();return try await PairingTLSProbe.verified(endpoint,fingerprint:info.fingerprint) } }
            if let bluetooth, !wifiOnly {group.addTask {if !bluetoothOnly && !preferBluetooth {try await Task.sleep(for:.seconds(4))};let endpoint = try await bluetooth.endpoint();return try await PairingTLSProbe.verified(endpoint,fingerprint:info.fingerprint)}}
            var failure: Error = PairingTransportFailure.timedOut
            while !group.isEmpty {
                do { if let endpoint = try await group.next() { group.cancelAll();return endpoint } }
                catch { failure = error }
            }
            throw failure
        }
    }
    private func configure(_ pair: PairedMac, pairing: Bool = false, endpoint: String? = nil) {
        if !pairing {activateLibraryCache(pair);activateChatCache(pair)}
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
        guard services.contains(sender), let pair = paired, let host = sender.hostName else { return }
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
        guard pair.id == (candidate ?? paired)?.id else {throw CancellationError()}
        let generation=deviceGeneration
        if body != nil {activeWrites += 1}
        defer {if body != nil {activeWrites -= 1}}
        var request = URLRequest(url:url);if path == "/status" { request.timeoutInterval = 12 };if path == "/pair" { request.timeoutInterval = 15 };request.setValue("Bearer " + pair.credential,forHTTPHeaderField:"Authorization")
        if let body { request.httpMethod = "POST";request.httpBody = try JSONSerialization.data(withJSONObject:body);request.setValue("application/json",forHTTPHeaderField:"Content-Type");if path == "/ask" { request.timeoutInterval = 300 } }
        if let timeout { request.timeoutInterval = timeout }
        let data:Data,response:URLResponse
        do {(data,response)=try await session.data(for:request)}
        catch {if generation != deviceGeneration {throw CancellationError()};throw error}
        guard generation==deviceGeneration, pair.id == (candidate ?? paired)?.id else {throw CancellationError()}
        let result = try JSONSerialization.jsonObject(with:data) as? [String:Any] ?? [:]
        let status = (response as? HTTPURLResponse)?.statusCode ?? 500
        guard (200...299).contains(status) else { throw NSError(domain:"Companion",code:status,userInfo:[NSLocalizedDescriptionKey:result["error"] as? String ?? "连接未完成，请重试"]) }
        return result
    }
    func pair(_ raw: String, requestAccepted: (() -> Void)? = nil) async {
        guard credentialStoreAvailable else {error="无法读取已保存的电脑，请解锁手机后重新打开 App";return}
        guard canChangeComputer else {error="正在提交内容，请完成后再添加电脑";return}
        if paired != nil || !computers.computers.isEmpty {selectedTab="device"}
        pairingInFlight=true;pairingCancelled=false
        defer {pairingInFlight=false}
        pairingDiagnostic("begin")
        do {
            let info=try PairInfo.pairingCode(raw)
            let identity=PairedMac.identity(serverID:info.server_id,fingerprint:info.fingerprint)
            guard computers.computers.count<10 || computers.computers.contains(where:{$0.id==identity}) else {
                throw NSError(domain:"Pairing",code:3,userInfo:[NSLocalizedDescriptionKey:"最多保存 10 台电脑，请先移除不再使用的电脑"])
            }
            deviceGeneration=UUID();rebuildConnectionTransport();error=""
            if var existing=computers.computers.first(where:{$0.id==identity}) {
                existing.info=info;existing.info.secret=nil;candidate=existing
                let endpoint=try await transport(info,urls:info.connectionURLs,preferred:existing.transport)
                guard !pairingCancelled,!Task.isCancelled else {throw CancellationError()}
                if !endpoint.hasPrefix("https://127.0.0.1:") {existing.info.url=endpoint}
                configure(existing,pairing:true,endpoint:endpoint)
                do {
                    let response=try await request("/status",using:existing)
                    guard response["server_id"] as? String==info.server_id else {throw URLError(.serverCertificateUntrusted)}
                    try remember(existing);activateComputer(computers.selected)
                    requestAccepted?();pairingInFlight=false;await connect();return
                } catch {
                    // A revoked credential needs fresh approval; the other saved
                    // computers and their credentials remain untouched.
                    guard (error as NSError).domain=="Companion",(error as NSError).code==401 else {throw error}
                }
            }
            let credential=Data((0..<48).map {_ in UInt8.random(in:0...255)}).base64EncodedString()
            let pair=PairedMac(info:info,credential:credential)
            candidate=pair
            let endpoint=try await transport(info,urls:info.connectionURLs)
            guard !pairingCancelled,!Task.isCancelled else {throw CancellationError()}
            configure(pair,pairing:true,endpoint:endpoint)
            let result=try await request("/pair",body:["secret":info.secret!,"credential":credential,"name":UIDevice.current.name],using:pair)
            guard result["server_id"] as? String==info.server_id else {throw URLError(.serverCertificateUntrusted)}
            code=result["code"] as? String ?? "";waiting=true;status="请在 Mac 上核对数字并允许配对"
            requestAccepted?()
            let deadline=Date().addingTimeInterval(300)
            while waiting && Date()<deadline {
                try await Task.sleep(for:.seconds(2))
                let response=try await request("/pair/status",using:pair)
                if response["approved"] as? Bool==true {
                    try remember(pair);activateComputer(computers.selected)
                    pairingInFlight=false;await connect();return
                }
            }
            if !waiting {throw CancellationError()}
            throw NSError(domain:"Pairing",code:2,userInfo:[NSLocalizedDescriptionKey:"配对已超时，请刷新二维码后重新扫码"])
        } catch {
            pairingDiagnostic("failed",error:error)
            waiting=false;code="";candidate=nil
            // Restore the previous active computer after a cancelled, rejected
            // or unreachable addition. Approval alone changes the saved list.
            deviceGeneration=UUID();rebuildConnectionTransport()
            if let pair=paired {configure(pair);discover();status="正在连接 \(pair.displayName)…"}
            else {status="配对未完成"}
            self.error=PairingConnectionFailure.message(error)
        }
    }
    private func canRefreshSession(after error:Error) -> Bool {
        let value=error as NSError
        return value.domain==NSURLErrorDomain && [-1001,-1004,-1005,-1009,-1200].contains(value.code)
    }
    func enteredBackground() {inBackground=true;resumePolicy.enteredBackground()}
    private func rebuildConnectionTransport() {
        // Invalidate the previous attempt before cancelling it. A completion
        // delivered after foregrounding must not overwrite the new connection.
        connectionGeneration = UUID();connectionTask?.cancel();connectionTask = nil;connecting = false
        cancelLibraryRefresh()
        session?.invalidateAndCancel();session = nil;sessionEndpoint = "";online = false
        wifiRelay?.onAvailable = nil;bluetoothRelay?.onAvailable = nil
        wifiRelay?.stop();bluetoothRelay?.stop();wifiRelay = nil;bluetoothRelay = nil;relayServerID = ""
        browser.stop();discovering = false
        for service in services {service.delegate = nil;service.stop()}
        services.removeAll();discoveredURLs.removeAll();discover()
        pairingDiagnostic("resume-transport-rebuilt")
    }
    func resumeConnection() async {
        inBackground=false
        guard let pair=paired,!waiting,!pairingInFlight else {return}
        // Let a live upload/question finish. The polling connection will apply
        // the pending foreground rebuild after that operation releases its state.
        guard !busy,!flushing,!chatSubmitting,activeWrites==0 else {return}
        let freshTransport = resumePolicy.needsFreshTransport()
        let start=Date()
        if freshTransport {
            rebuildConnectionTransport()
        } else {
            guard !connecting else {return}
            bluetoothRelay?.reconnectKnownPeer()
            if online,session != nil {
                await connect(quickResume:true)
                if online {
                    pairingDiagnostic("resume-reused-ms-\(Int(Date().timeIntervalSince(start)*1000))")
                    return
                }
                guard mayRetryConnection else {return}
                // A failed carrier must be rebuilt too, not just its TLS session.
                rebuildConnectionTransport()
            }
        }
        guard !Task.isCancelled else {return}
        status="正在连接 \(pair.displayName)…"
        await connect()
        pairingDiagnostic("resume-\(online ? "connected":"pending")-ms-\(Int(Date().timeIntervalSince(start)*1000))")
    }
    func connect(quickResume:Bool=false) async {
        guard !inBackground,!waiting,!pairingInFlight,paired != nil else {return}
        if !busy,!flushing,!chatSubmitting,activeWrites==0,resumePolicy.needsFreshTransport() {rebuildConnectionTransport()}
        guard connectionTask == nil else {return}
        let generation=UUID();connectionGeneration=generation
        let task=Task {await self.performConnect(quickResume:quickResume,generation:generation)}
        connectionTask=task
        await task.value
        if connectionGeneration==generation {connectionTask=nil}
    }
    private func performConnect(quickResume:Bool,generation:UUID) async {
        guard connectionGeneration==generation,!Task.isCancelled,!waiting,!pairingInFlight,!connecting,var pair=paired else {return}
        connecting = true;mayRetryConnection=false;defer {if connectionGeneration==generation {connecting=false}}
        do {
            let urls = Array(NSOrderedSet(array: [pair.info.url] + discoveredURLs + pair.info.connectionURLs)) as? [String] ?? [pair.info.url]
            let endpoint = online && session != nil ? sessionEndpoint : try await transport(pair.info,urls:Array(urls.prefix(9)),preferred:pair.transport)
            guard connectionGeneration==generation,!Task.isCancelled,!pairingInFlight,paired?.info.server_id==pair.info.server_id else {return}
            let nearby = endpoint.hasPrefix("https://127.0.0.1:")
            if !nearby { pair.info.url = endpoint }
            if session == nil || sessionEndpoint != endpoint { configure(pair,endpoint:endpoint) }
            let value:[String:Any]
            do {value = try await request("/status",using:pair,timeout:quickResume ? 3:nil)}
            catch {
                guard connectionGeneration==generation,quickResume,!Task.isCancelled,canRefreshSession(after:error) else {throw error}
                // A genuinely stale socket gets one fresh, still-pinned TLS
                // session on the same carrier before rediscovering the Mac.
                configure(pair,endpoint:endpoint)
                value = try await request("/status",using:pair,timeout:6)
            }
            guard connectionGeneration==generation,!Task.isCancelled,!pairingInFlight,paired?.info.server_id==pair.info.server_id else {return}
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
            guard connectionGeneration==generation,!Task.isCancelled else {return}
            pair.transport = bluetooth ? "bluetooth" : wireless ? "wifi" : "direct"
            if bluetooth {bluetoothRelay?.rememberVerifiedPeer();wifiRelay?.suspendDiscovery()}
            pairingDiagnostic(bluetooth ? "connected-bluetooth-verified" : wireless ? "connected-wifi-verified" : nearby ? "connected-nearby-verified" : "connected-direct-verified")
            try remember(pair);paired = computers.selected
            online = true;status = "已连接 · \(pair.displayName)";error = "";discover();await flush();await flushChatMessages()
        } catch {
            guard connectionGeneration==generation,!Task.isCancelled else {return}
            mayRetryConnection=canRefreshSession(after:error)
            pairingDiagnostic("connect-failed",error:error)
            wifiRelay?.rediscover()
            session?.invalidateAndCancel();session = nil
            online = false;status = "\(pair.displayName) 离线 · 内容保留在手机"
            if (error as NSError).code == 401 { self.error = "此手机已被移除，请重新配对" }
        }
    }
    private func persist(_ next: [Draft]) throws {
        let data = try JSONEncoder().encode(next);try data.write(to:queueURL,options:[.atomic,.completeFileProtectionUntilFirstUserAuthentication]);var values = URLResourceValues();values.isExcludedFromBackup = true;var url = queueURL;try? url.setResourceValues(values);drafts = next
    }
    func enqueue(text: String, filename: String? = nil, data: Data? = nil, workspace:String) async -> Bool {
        guard workspace==workspaceID else {return false}
        guard let pair = paired else { error = "请先配对电脑";return false }
        guard !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || data != nil else { return false }
        guard (data?.count ?? 0) <= 10*1024*1024, drafts.count < 50 else { error = "每份附件最多 10 MB，待发送内容最多 50 条";return false }
        do { try persist(drafts + [Draft(serverID:pair.info.server_id,fingerprint:pair.info.fingerprint,text:text,filename:filename,data:data?.base64EncodedString())]);error = "";await flush();return true }
        catch { self.error = "手机空间不足，内容尚未保存，请保留原内容";return false }
    }
    func removeDraft(_ id: String) { guard currentDrafts.contains(where:{$0.id==id}) else {return};do { try persist(drafts.filter { $0.id != id }) } catch { self.error = "无法移除待发送内容" } }
    func flush() async {
        guard online, !flushing, let pair = paired else { return };flushing = true;defer { flushing = false }
        for draft in drafts where draft.serverID == pair.info.server_id && draft.fingerprint == pair.info.fingerprint {
            var content: [String:Any] = ["text":draft.text,"note_reference":draft.created]
            if let file = draft.filename, let data = draft.data { content["filename"] = file;content["data"] = data }
            else if let url = URL(string:draft.text.trimmingCharacters(in:.whitespacesAndNewlines)), ["https","http"].contains(url.scheme ?? ""), !draft.text.contains("\n") { content["url"] = url.absoluteString;content["text"] = "" }
            do {
                _ = try await request("/ingest",body:["request_id":draft.id,"content":content],using:pair)
                try persist(drafts.filter { $0.id != draft.id })
                libraryCache?.invalidate()
                if let cache=libraryCache {try? cache.save(to:libraryCacheURL)}
            }
            catch { self.error = "待发送内容已保留：" + error.localizedDescription;return }
        }
    }
    private func activateLibraryCache(_ pair: PairedMac) {
        guard libraryCache?.belongsTo(serverID:pair.info.server_id,fingerprint:pair.info.fingerprint) != true else {return}
        cancelLibraryRefresh();libraryQuery="";records=[];libraryUpdatedAt=nil;libraryMessage=""
        libraryCache=LibraryCache.load(from:cacheURL("library",serverID:pair.info.server_id,fingerprint:pair.info.fingerprint),serverID:pair.info.server_id,fingerprint:pair.info.fingerprint)
        showLibrarySnapshot(query:"")
    }
    private func showLibrarySnapshot(query:String) {
        let snapshot=libraryCache?.snapshots[query]
        records=snapshot?.records ?? [];libraryUpdatedAt=snapshot?.updatedAt
    }
    private func cancelLibraryRefresh() {
        libraryGeneration=UUID();libraryTask?.cancel();libraryTask=nil;libraryRequestQuery=nil;libraryRefreshing=false
    }
    func openLibrary() async {await search(libraryQuery,force:false)}
    func search(_ text: String,force:Bool=true) async {
        guard let pair=paired else {return}
        activateLibraryCache(pair)
        let query=String(text.prefix(200))
        libraryQuery=query;showLibrarySnapshot(query:query)
        guard online else {
            libraryMessage=libraryUpdatedAt == nil ? "连接 Mac 后加载资料":"离线缓存 · 连接后自动更新"
            return
        }
        if let task=libraryTask,libraryRequestQuery==query {await task.value;return}
        if libraryTask != nil {cancelLibraryRefresh()}
        if !force,libraryCache?.snapshots[query]?.isFresh() == true {libraryMessage="";return}
        cancelLibraryRefresh()
        let generation=UUID();libraryGeneration=generation;libraryRequestQuery=query;libraryRefreshing=true;libraryMessage=""
        let task=Task {await self.fetchLibrary(query:query,pair:pair,generation:generation)}
        libraryTask=task
        await task.value
        if libraryGeneration==generation {libraryTask=nil;libraryRequestQuery=nil;libraryRefreshing=false}
    }
    private func fetchLibrary(query:String,pair:PairedMac,generation:UUID) async {
        do {
            let escaped=query.addingPercentEncoding(withAllowedCharacters:.urlQueryAllowed.subtracting(CharacterSet(charactersIn:"&+#?"))) ?? ""
            let value=try await request("/items?q="+escaped,using:pair,timeout:30)
            guard !Task.isCancelled,libraryGeneration==generation,paired?.info.server_id==pair.info.server_id,
                  libraryCache?.belongsTo(serverID:pair.info.server_id,fingerprint:pair.info.fingerprint)==true else {return}
            guard let items=value["items"] as? [[String:Any]] else {throw URLError(.cannotParseResponse)}
            libraryCache?.update(items.map(Record.init),query:query)
            if let cache=libraryCache {try? cache.save(to:libraryCacheURL)}
            if libraryQuery==query {showLibrarySnapshot(query:query);libraryMessage=""}
        } catch {
            guard !Task.isCancelled,libraryGeneration==generation else {return}
            libraryMessage=libraryUpdatedAt == nil ? "暂时无法加载资料，请稍后下拉重试":"更新未完成，继续显示上次的资料"
        }
    }
    func ask(_ text: String) async {
        guard online else {error="请先连接电脑";return}
        guard !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else {return}
        let generation=deviceGeneration
        if selectedChatID.isEmpty {await syncChatList()}
        guard generation==deviceGeneration else {return}
        if selectedChatID.isEmpty {await createChat()}
        guard generation==deviceGeneration else {return}
        selectedTab="chat"
        _ = await enqueueChat(text)
    }
    var currentChatQueue:[PendingChatMessage] {
        guard let pair=paired else {return []}
        return pendingChatMessages.filter {$0.serverID==pair.info.server_id && $0.fingerprint==pair.info.fingerprint}
    }
    private func activateChatCache(_ pair:PairedMac) {
        guard chatCache?.serverID != pair.info.server_id || chatCache?.fingerprint != pair.info.fingerprint else {return}
        chatCache=ChatCache.load(cacheURL("chat",serverID:pair.info.server_id,fingerprint:pair.info.fingerprint),serverID:pair.info.server_id,fingerprint:pair.info.fingerprint)
        chatThreads=chatCache?.threads ?? [];selectedChatID=chatCache?.selectedID ?? "";chatSnapshot=chatCache?.snapshots[selectedChatID]
        chatInput=chatInputs[pair.id+":"+selectedChatID] ?? ""
        chatPartial="";partialMessageID="";partialOffset=0;chatStage="";chatNotice=""
    }
    private func saveChatCache() {if var cache=chatCache {cache.selectedID=selectedChatID;try? cache.save(chatCacheURL);chatCache=cache}}
    private func chatPath(_ id:String) -> String {"/chats/"+(id.addingPercentEncoding(withAllowedCharacters:.alphanumerics) ?? "")}
    func selectChat(_ id:String) {
        if let pair=paired {chatInputs[pair.id+":"+selectedChatID]=chatInput;chatInput=chatInputs[pair.id+":"+id] ?? ""}
        selectedChatID=id;chatSnapshot=chatCache?.snapshots[id];chatPartial="";partialMessageID="";partialOffset=0;chatStage="";chatNotice="";saveChatCache()
    }
    func syncChatList() async {
        guard online,!chatListSyncing,let pair=paired else {return}
        let generation=deviceGeneration;chatListSyncing=true;defer {if generation==deviceGeneration {chatListSyncing=false}}
        do {
            let value=try await request("/chats?revision="+(chatCache?.listRevision ?? ""),using:pair)
            guard !Task.isCancelled,paired?.info.server_id==pair.info.server_id,chatCache?.fingerprint==pair.info.fingerprint else {return}
            if value["unchanged"] as? Bool != true {
                guard let chats=value["conversations"] as? [[String:Any]] else {throw URLError(.cannotParseResponse)}
                chatThreads=chats.map(ChatThread.init);chatCache?.threads=chatThreads
                let alive=Set(chatThreads.map(\.id))
                if var cache=chatCache {cache.snapshots=cache.snapshots.filter {alive.contains($0.key)};chatCache=cache}
                if !alive.contains(selectedChatID) {
                    let active=value["active_id"] as? String ?? ""
                    selectChat(alive.contains(active) ? active:chatThreads.first?.id ?? "")
                }
            }
            chatCache?.listRevision=value["revision"] as? String ?? "";saveChatCache();chatNotice=""
        } catch {if !Task.isCancelled, generation==deviceGeneration {chatNotice="对话同步暂未完成，保留手机缓存"}}
    }
    func syncSelectedChat(older:Bool=false) async {
        let id=selectedChatID
        guard online,!id.isEmpty,chatFetchingID != id,let pair=paired else {return}
        let generation=deviceGeneration
        chatFetchingID=id;defer {if generation==deviceGeneration && chatFetchingID==id {chatFetchingID=nil}}
        let before=older ? chatSnapshot?.messages.first?.id ?? "":""
        let revision=older ? "":chatSnapshot?.revision ?? ""
        do {
            let value=try await request(chatPath(id)+"?revision="+revision+"&before="+(before.addingPercentEncoding(withAllowedCharacters:.alphanumerics) ?? "")+"&partial_offset="+String(partialOffset)+"&partial_id="+(partialMessageID.addingPercentEncoding(withAllowedCharacters:.alphanumerics) ?? ""),using:pair)
            guard !Task.isCancelled,selectedChatID==id,paired?.info.server_id==pair.info.server_id,chatCache?.fingerprint==pair.info.fingerprint else {return}
            if value["unchanged"] as? Bool != true {
                guard let messages=value["messages"] as? [[String:Any]] else {throw URLError(.cannotParseResponse)}
                let incoming=messages.map(ChatMessage.init),deleted=Set(value["deleted_ids"] as? [String] ?? [])
                let old=chatSnapshot?.messages.filter {!deleted.contains($0.id)} ?? []
                let ids=Set(incoming.map(\.id))
                let combined=older ? incoming+old.filter {!ids.contains($0.id)}:old.filter {!ids.contains($0.id)}+incoming
                chatSnapshot=ChatSnapshot(id:id,title:value["title"] as? String ?? "对话",revision:older ? "":value["revision"] as? String ?? "",messages:combined,hasMore:older || old.count<=incoming.count ? value["has_more"] as? Bool ?? false:chatSnapshot?.hasMore ?? false)
                chatCache?.snapshots[id]=chatSnapshot;saveChatCache()
            }
            if let progress=value["progress"] as? [String:Any] {
                let mid=progress["message_id"] as? String ?? ""
                if mid != partialMessageID || progress["reset"] as? Bool == true {chatPartial=""}
                partialMessageID=mid;partialOffset=progress["offset"] as? Int ?? 0
                chatPartial += progress["partial"] as? String ?? "";chatStage=progress["stage"] as? String ?? ""
            } else {chatPartial="";partialMessageID="";partialOffset=0;chatStage=""}
            chatNotice=""
        } catch {
            if !Task.isCancelled,generation==deviceGeneration {
                chatNotice=error.localizedDescription
                if (error as NSError).code==400 && chatNotice.contains("会话不存在") {chatCache?.snapshots.removeValue(forKey:id);chatSnapshot=nil;await syncChatList()}
            }
        }
    }
    func createChat() async {
        guard online,let pair=paired else {chatNotice="连接电脑后可以新建对话";return}
        let generation=deviceGeneration
        do {
            let value=try await request("/chats",body:["request_id":UUID().uuidString],using:pair)
            guard let id=value["chat_id"] as? String else {throw URLError(.cannotParseResponse)}
            await syncChatList()
            guard generation==deviceGeneration else {return}
            selectChat(id);await syncSelectedChat()
        } catch {if generation==deviceGeneration {chatNotice=error.localizedDescription}}
    }
    private func persistChatQueue(_ messages:[PendingChatMessage]) throws {
        try ChatCache.protectedWrite(JSONEncoder().encode(messages),to:chatQueueURL);pendingChatMessages=messages
    }
    func enqueueChat(_ text:String, workspace:String?=nil, chatID:String?=nil) async -> Bool {
        guard workspace==nil || workspace==workspaceID, chatID==nil || chatID==selectedChatID else {return false}
        guard let pair=paired,!selectedChatID.isEmpty else {chatNotice="请先选择或新建对话";return false}
        guard !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty,text.count<=4000,pendingChatMessages.count<50 else {chatNotice="消息最多 4000 字，待发送消息最多 50 条";return false}
        do {try persistChatQueue(pendingChatMessages+[PendingChatMessage(serverID:pair.info.server_id,fingerprint:pair.info.fingerprint,chatID:selectedChatID,text:text)]);chatNotice="";await flushChatMessages();return true}
        catch {chatNotice="手机暂存失败，请保留输入内容";return false}
    }
    func retryChatMessage(_ id:String) async {
        guard currentChatQueue.contains(where:{$0.id==id}) else {return}
        var messages=pendingChatMessages
        if let index=messages.firstIndex(where:{$0.id==id}) {messages[index].lastError="";do {try persistChatQueue(messages)} catch {chatNotice="无法保存待发消息";return}}
        await flushChatMessages()
    }
    func removeQueuedChatMessage(_ id:String) {
        guard !chatSubmitting,currentChatQueue.contains(where:{$0.id==id}) else {return}
        do {try persistChatQueue(pendingChatMessages.filter {$0.id != id})} catch {chatNotice="无法移除待发消息"}
    }
    func flushChatMessages() async {
        guard online,!chatSubmitting,let pair=paired else {return};chatSubmitting=true;defer {chatSubmitting=false}
        var changed=false
        for pending in currentChatQueue where pending.lastError.isEmpty {
            if chatSnapshot?.id==pending.chatID && chatSnapshot?.running==true {continue}
            do {
                let value=try await request(chatPath(pending.chatID)+"/messages",body:["request_id":pending.id,"text":pending.text],using:pair)
                guard value["accepted"] as? Bool==true else {throw URLError(.cannotParseResponse)}
                try persistChatQueue(pendingChatMessages.filter {$0.id != pending.id});changed=true
            } catch {
                if Task.isCancelled {return}
                let ns=error as NSError
                if ns.domain=="Companion",ns.code != 409 {
                    var messages=pendingChatMessages
                    if let index=messages.firstIndex(where:{$0.id==pending.id}) {messages[index].lastError=error.localizedDescription;try? persistChatQueue(messages)}
                }
                if ns.domain != "Companion" {return}
            }
        }
        if changed {await syncSelectedChat()}
    }
    func stopChatAnswer(_ message:ChatMessage) async {
        guard online else {chatNotice="连接电脑后才能停止回答";return}
        do {_ = try await request(chatPath(selectedChatID)+"/stop",body:["message_id":message.id]);await syncSelectedChat()}
        catch {chatNotice=error.localizedDescription}
    }
    private func acceptEditedItem(_ value:[String:Any]) -> [String:Any] {
        let item=value["item"] as? [String:Any] ?? [:],record=Record(value["item"] as? [String:Any] ?? [:])
        libraryCache?.replace(record)
        if let index=records.firstIndex(where:{$0.id==record.id}) {records[index]=record}
        if let cache=libraryCache {try? cache.save(to:libraryCacheURL)}
        return item
    }
    func saveMetadata(_ id:String,title:String,tags:[String],updated:String,workspace:String) async throws -> [String:Any] {
        guard workspace==workspaceID,candidate==nil else {throw CancellationError()}
        let value=try await request("/items/"+id+"/metadata",body:["title":title,"tags":tags,"expected_updated":updated])
        return acceptEditedItem(value)
    }
    func addAttachment(_ id:String,name:String,data:Data,updated:String,requestID:String,workspace:String) async throws -> [String:Any] {
        guard workspace==workspaceID,candidate==nil else {throw CancellationError()}
        let value=try await request("/items/"+id+"/attachments",body:["filename":name,"data":data.base64EncodedString(),"expected_updated":updated,"request_id":requestID],timeout:120)
        return acceptEditedItem(value)
    }
    private var attachmentCacheFolder:URL {FileManager.default.urls(for:.cachesDirectory,in:.userDomainMask)[0].appendingPathComponent("phone-attachments",isDirectory:true)}
    func downloadAttachment(_ path:String,name:String,version:String,workspace:String,progress:@escaping @Sendable(Int64,Int64)->Void) async throws -> URL {
        guard workspace==workspaceID,candidate==nil else {throw CancellationError()}
        guard let pair=paired,path.hasPrefix("/items/"),let url=URL(string:sessionEndpoint+path) else {throw URLError(.badURL)}
        activeWrites += 1;defer {activeWrites -= 1}
        let key=SHA256.hash(data:Data((pair.info.server_id+pair.info.fingerprint+path+version).utf8)).map {String(format:"%02x",$0)}.joined()
        let folder=attachmentCacheFolder.appendingPathComponent(key,isDirectory:true)
        let target=folder.appendingPathComponent(URL(fileURLWithPath:name).lastPathComponent)
        if FileManager.default.fileExists(atPath:target.path) {return target}
        try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
        var request=URLRequest(url:url);request.setValue("Bearer "+pair.credential,forHTTPHeaderField:"Authorization");request.timeoutInterval=120
        let staging=attachmentCacheFolder.appendingPathComponent(".pending-"+UUID().uuidString,isDirectory:true)
        try FileManager.default.createDirectory(at:staging,withIntermediateDirectories:true)
        let incoming=staging.appendingPathComponent(target.lastPathComponent)
        let transfer=AttachmentTransfer(pin:pair.info.fingerprint,destination:incoming,progress:progress)
        do {
            _ = try await transfer.run(request)
            try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
            if !FileManager.default.fileExists(atPath:target.path) {try FileManager.default.moveItem(at:incoming,to:target)}
            try? FileManager.default.removeItem(at:staging)
            // Keep completed files for repeated opens, bounded to 200 MB plus
            // the currently opened file. iOS may reclaim this cache as needed.
            let files=(try? FileManager.default.contentsOfDirectory(at:attachmentCacheFolder,includingPropertiesForKeys:[.contentModificationDateKey])) ?? []
            let ordered=files.filter {!$0.lastPathComponent.hasPrefix(".pending-")}.sorted {((try? $0.resourceValues(forKeys:[.contentModificationDateKey]).contentModificationDate) ?? .distantPast) > ((try? $1.resourceValues(forKeys:[.contentModificationDateKey]).contentModificationDate) ?? .distantPast)}
            var kept=0
            for entry in [folder]+ordered.filter({$0 != folder}) {
                let children=(try? FileManager.default.contentsOfDirectory(at:entry,includingPropertiesForKeys:[.fileSizeKey])) ?? []
                let size=children.reduce(0) {$0+((try? $1.resourceValues(forKeys:[.fileSizeKey]).fileSize) ?? 0)}
                if kept+size>200*1024*1024 && entry != folder {try? FileManager.default.removeItem(at:entry)} else {kept+=size}
            }
            return target
        } catch {try? FileManager.default.removeItem(at:staging);throw error}
    }
    func detail(_ id: String,workspace:String) async throws -> [String:Any] { guard workspace==workspaceID,candidate==nil else {throw CancellationError()};let response = try await request("/items/"+id);return response["item"] as? [String:Any] ?? [:] }
    func disconnect() { if let pair=paired {removeComputer(pair.id)} }
}
