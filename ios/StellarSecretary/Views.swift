import SwiftUI
import PhotosUI
import AVFoundation
import QuickLook

@main struct StellarCompanionApp: App {
    @StateObject private var model = Companion()
    @Environment(\.scenePhase) private var scene
    var body: some Scene {
        WindowGroup {
            ContentView().environmentObject(model)
                .onOpenURL { url in
                    pairingDiagnostic("url-received")
                    guard url.scheme == "stellar-secretary", url.host == "pair", let value = URLComponents(url:url,resolvingAgainstBaseURL:false)?.queryItems?.first(where:{$0.name == "data"})?.value,
                          let data = Data(base64Encoded:value), let raw = String(data:data,encoding:.utf8) else { return }
                    Task { await model.pair(raw) }
                }
                .onChange(of:scene) { _,phase in
                    pairingDiagnostic("scene-"+String(describing:phase))
                    if phase == .background {model.enteredBackground()}
                    #if DEBUG
                    if ProcessInfo.processInfo.arguments.contains("--wifi-only") || ProcessInfo.processInfo.arguments.contains("--bluetooth-only") { UIApplication.shared.isIdleTimerDisabled = phase == .active }
                    #endif
                }
                 .task(id:scene) {
                    guard scene == .active else {return}
                    await model.resumeConnection()
                    while scene == .active && !Task.isCancelled {try? await Task.sleep(for:.seconds(10));guard !Task.isCancelled else {return};await model.connect()}
                }
        }
    }
}
struct ContentView: View {
    @EnvironmentObject var model: Companion
    @State private var scan = false
    @State private var pairingTask: Task<Void, Never>?
    var body: some View {
        Group {
            if model.paired == nil {
                NavigationStack {
                    VStack(spacing:24) {
                        Image(systemName:"sparkle").font(.system(size:64,weight:.light)).foregroundStyle(.orange)
                        Text("随手存，随时查").font(.largeTitle.bold())
                        Text("与 Mac 上的 Stellar Secretary 配对，\n共用你的知识库。").multilineTextAlignment(.center).foregroundStyle(.secondary)
                        if model.waiting { Text(model.code).font(.largeTitle.monospacedDigit()).tracking(8);Text(model.status);ProgressView() }
                        else { Button { scan = true } label: { Label("扫描 Mac 配对码",systemImage:"qrcode.viewfinder").frame(maxWidth:.infinity) }.buttonStyle(.borderedProminent).controlSize(.large)
                            Text("电脑端：模型与设置 → 手机连接").font(.footnote).foregroundStyle(.secondary) }
                        if !model.error.isEmpty { Text(model.error).foregroundStyle(.orange).font(.callout) }
                    }.padding(30).navigationTitle("Stellar Secretary")
                }
            } else {
                TabView {
                    CaptureView().tabItem { Label("归档",systemImage:"square.and.pencil") }
                    LibraryView().tabItem { Label("检索",systemImage:"magnifyingglass") }
                    DeviceView().tabItem { Label("连接",systemImage:"laptopcomputer.and.iphone") }
                }.tint(.orange)
            }
        }.fullScreenCover(isPresented:$scan) {
            ScannerView(scanned: { raw, failed in
                pairingTask = Task {
                    await model.pair(raw, requestAccepted: { scan = false })
                    if scan { failed(model.error.isEmpty ? "连接未完成，请重试" : model.error) }
                    pairingTask = nil
                }
            }, cancelled: { pairingTask?.cancel();pairingTask = nil;scan = false }).ignoresSafeArea()
        }
    }
}
struct ConnectionBanner: View {
    @EnvironmentObject var model: Companion
    var body: some View { Label(model.status,systemImage:model.online ? "checkmark.circle.fill":"wifi.slash").font(.footnote).foregroundStyle(model.online ? .green:.secondary).padding(.vertical,4) }
}
struct CaptureView: View {
    @EnvironmentObject var model: Companion
    @State private var text = ""
    @State private var photo: PhotosPickerItem?
    @State private var image: Data?
    @State private var filename: String?
    @State private var importing = false
    @State private var saving = false
    @FocusState private var editing: Bool
    var body: some View {
        NavigationStack {
            Form {
                Section { ConnectionBanner() }
                Section("链接、笔记或安排") { TextEditor(text:$text).focused($editing).frame(minHeight:150).accessibilityLabel("归档内容") }
                Section {
                    PhotosPicker(selection:$photo,matching:.images) { Label("添加截图或照片",systemImage:"photo") }
                    Button { importing = true } label: { Label("添加文件",systemImage:"paperclip") }
                    if let filename { HStack { Text(filename);Spacer();Button("移除") { image = nil;self.filename = nil;photo = nil } } }
                    Button { editing = false;saving = true;Task { if await model.enqueue(text:text,filename:filename,data:image) { text = "";image = nil;filename = nil;photo = nil };saving = false } } label: { Label(model.online ? "保存到知识库":"暂存，连接后发送",systemImage:"tray.and.arrow.down").frame(maxWidth:.infinity) }.disabled(saving || (text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && image == nil))
                } footer: { Text("链接先收藏，网页正文可在电脑端继续读取。附件最多 10 MB。") }
                if !model.error.isEmpty { Section { Text(model.error).foregroundStyle(.orange) } }
                if !model.drafts.isEmpty {
                    Section("待发送 · \(model.drafts.count)") {
                        ForEach(model.drafts) { draft in VStack(alignment:.leading) { Text(draft.filename ?? draft.text).lineLimit(2);if draft.serverID != model.paired?.info.server_id { Text("属于其他 Mac，重新配对原设备后发送").font(.caption).foregroundStyle(.secondary) } }.swipeActions { Button("删除",role:.destructive) { model.removeDraft(draft.id) } } }
                        Button("重新发送") { Task { await model.connect() } }
                    }
                }
            }.navigationTitle("随手归档").scrollDismissesKeyboard(.interactively).toolbar { ToolbarItemGroup(placement:.keyboard) { Spacer();Button("完成") { editing = false } } }
            .onChange(of:photo) { _,value in Task {
                guard let value else { return }
                if let data = try? await value.loadTransferable(type:Data.self), data.count <= 10*1024*1024 {
                    image = data;let type = value.supportedContentTypes.first;filename = "Photo." + (type?.preferredFilenameExtension ?? "jpg")
                } else { model.error = "照片读取失败或超过 10 MB" }
            } }
            .fileImporter(isPresented:$importing,allowedContentTypes:[.item]) { result in
                do { let url = try result.get();let access = url.startAccessingSecurityScopedResource();defer { if access { url.stopAccessingSecurityScopedResource() } };let values = try url.resourceValues(forKeys:[.fileSizeKey]);guard (values.fileSize ?? Int.max) <= 10*1024*1024 else { model.error = "文件超过 10 MB";return };image = try Data(contentsOf:url);filename = url.lastPathComponent }
                catch { model.error = "无法读取文件" }
            }
        }
    }
}
struct LibraryView: View {
    @EnvironmentObject var model: Companion
    private var query: String { model.libraryQuery }
    @FocusState private var searching: Bool
    var body: some View {
        NavigationStack {
            List {
                Section { ConnectionBanner();TextField("搜索资料或输入问题",text:$model.libraryQuery).focused($searching).submitLabel(.search).onSubmit { searching = false;Task { await model.search(query) } }
                    HStack { Button("搜索资料") { searching = false;Task { await model.search(query) } };Spacer();Button("问知识库") { searching = false;Task { await model.ask(query) } }.disabled(query.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty) }.disabled(model.busy || !model.online)
                }
                if model.busy { Section { HStack { ProgressView();Text("正在查询 Mac 上的知识库…") } } }
                if model.libraryRefreshing {
                    Section { HStack { ProgressView();Text(model.libraryUpdatedAt == nil ? "正在加载资料…":"正在后台更新资料…") }.font(.footnote).foregroundStyle(.secondary) }
                }
                if !model.libraryMessage.isEmpty { Section { Text(model.libraryMessage).font(.footnote).foregroundStyle(.secondary) } }
                if !model.error.isEmpty { Section { Text(model.error).foregroundStyle(.orange) } }
                if !model.answer.isEmpty { Section("回答") { Text(model.answer).textSelection(.enabled);ForEach(model.sources) { item in NavigationLink(item.title) { DetailView(record:item) } } } }
                Section("资料") { ForEach(model.records) { item in NavigationLink { DetailView(record:item) } label: { VStack(alignment:.leading,spacing:5) { Text(item.title);if !item.summary.isEmpty { Text(item.summary).font(.caption).foregroundStyle(.secondary).lineLimit(2) } } } } }
            }.navigationTitle("知识库")
            .task(id:model.online) {await model.openLibrary()}
            .refreshable {await model.search(query)}
        }
    }
}
private struct PhoneAttachment: Identifiable {
    let id:String;let name:String;let path:String
    init(_ value:[String:Any]) {id=value["path"] as? String ?? "";name=value["name"] as? String ?? "附件";path=id}
}
private struct PhoneLink: Identifiable {
    let id:String;let title:String;let url:URL
    init?(_ value:[String:Any]) {
        guard let raw=value["url"] as? String,let url=URL(string:raw),["https","http"].contains(url.scheme?.lowercased() ?? "") else {return nil}
        self.url=url;id=raw;title=value["title"] as? String ?? raw
    }
}
private struct PhonePreview: Identifiable {let id=UUID();let url:URL}
private struct OriginalPreview: UIViewControllerRepresentable {
    let url:URL
    func makeCoordinator() -> Coordinator {Coordinator(url)}
    func makeUIViewController(context:Context) -> QLPreviewController {let controller=QLPreviewController();controller.dataSource=context.coordinator;return controller}
    func updateUIViewController(_ controller:QLPreviewController,context:Context) {}
    final class Coordinator:NSObject,QLPreviewControllerDataSource {
        let url:URL
        init(_ url:URL) {self.url=url}
        func numberOfPreviewItems(in controller:QLPreviewController) -> Int {1}
        func previewController(_ controller:QLPreviewController,previewItemAt index:Int) -> QLPreviewItem {url as NSURL}
    }
}
struct DetailView: View {
    @EnvironmentObject var model: Companion
    let record:Record
    @State private var title=""
    @State private var tags=""
    @State private var updated=""
    @State private var savedTitle=""
    @State private var savedTags=""
    @State private var summary=""
    @State private var text=""
    @State private var originals:[PhoneLink]=[]
    @State private var attachments:[PhoneAttachment]=[]
    @State private var loaded=false
    @State private var working=false
    @State private var error=""
    @State private var notice=""
    @State private var importing=false
    @State private var photo:PhotosPickerItem?
    @State private var pendingData:Data?
    @State private var pendingName=""
    @State private var attachmentRequestID=UUID().uuidString
    @State private var preview:PhonePreview?
    @State private var previewFolder:URL?
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:20) {
                if !originals.isEmpty || !attachments.isEmpty {
                    VStack(alignment:.leading,spacing:12) {
                        Text("原链接与原件").font(.headline)
                        ForEach(originals) {link in Link(destination:link.url) {Label(link.title,systemImage:"arrow.up.right.square").lineLimit(2)}}
                        ForEach(attachments) {file in Button {Task {await open(file)}} label:{Label("打开原件 · "+file.name,systemImage:"doc")}.disabled(working || !model.online)}
                    }.frame(maxWidth:.infinity,alignment:.leading).padding().background(.quaternary,in:RoundedRectangle(cornerRadius:14))
                }
                if !loaded {Text(record.title).font(.title2.bold());Text(record.summary).textSelection(.enabled);if working {ProgressView("正在加载资料详情…")}}
                if !error.isEmpty {Text(error).foregroundStyle(.orange)}
                if !notice.isEmpty {Text(notice).foregroundStyle(.secondary)}
                if loaded {
                    VStack(alignment:.leading,spacing:12) {
                        Text("标题与标签").font(.headline)
                        TextField("资料标题",text:$title,axis:.vertical).textFieldStyle(.roundedBorder).accessibilityIdentifier("detail-title")
                        TextField("标签，用逗号分隔",text:$tags).textFieldStyle(.roundedBorder).accessibilityIdentifier("detail-tags")
                        Button("保存标题与标签") {Task {await save()}}.buttonStyle(.borderedProminent)
                    }.disabled(working || !model.online)
                    VStack(alignment:.leading,spacing:12) {
                        Text("添加附件").font(.headline)
                        HStack {
                            PhotosPicker(selection:$photo,matching:.images) {Label("照片",systemImage:"photo")}
                            Button {importing=true} label:{Label("文件",systemImage:"paperclip")}
                        }.disabled(working || !model.online)
                        Text("追加到当前资料，保留已有原件。每个附件最多 10 MB。").font(.footnote).foregroundStyle(.secondary)
                        if pendingData != nil {
                            Text(pendingName).lineLimit(2)
                            HStack {
                                Button("添加到这份资料") {Task {await append()}}.buttonStyle(.borderedProminent)
                                Button("取消") {pendingData=nil;photo=nil}
                            }.disabled(working || !model.online)
                        }
                    }
                    if working {ProgressView("正在处理…")}
                    if !summary.isEmpty {Text("摘要").font(.headline);Text(summary).textSelection(.enabled)}
                    if !text.isEmpty {DisclosureGroup("正文与归档说明") {Text(text).frame(maxWidth:.infinity,alignment:.leading).textSelection(.enabled)}}
                }
            }.padding().frame(maxWidth:.infinity,alignment:.leading)
        }.navigationTitle("资料详情").navigationBarTitleDisplayMode(.inline)
        .toolbar {Button("重新加载") {Task {await load()}}.disabled(working)}
        .task {await load()}
        .sheet(item:$preview,onDismiss:{clearPreview()}) {value in OriginalPreview(url:value.url)}
        .onDisappear {if preview == nil {clearPreview()}}
        .onChange(of:photo) {_,value in Task {
            guard let value else {return}
            if let data=try? await value.loadTransferable(type:Data.self) {select(data,name:"Photo."+(value.supportedContentTypes.first?.preferredFilenameExtension ?? "jpg"))}
            else {error="照片读取失败，请重试"}
        }}
        .fileImporter(isPresented:$importing,allowedContentTypes:[.item]) {result in
            do {
                let url=try result.get(),access=url.startAccessingSecurityScopedResource();defer {if access {url.stopAccessingSecurityScopedResource()}}
                let size=try url.resourceValues(forKeys:[.fileSizeKey]).fileSize ?? 0
                guard size<=10*1024*1024 else {error="每个附件最多 10 MB";return}
                select(try Data(contentsOf:url),name:url.lastPathComponent)
            } catch {self.error="无法读取文件，请重新选择"}
        }
    }
    private func apply(_ value:[String:Any]) {
        title=value["title"] as? String ?? record.title;tags=(value["tags"] as? [String] ?? []).joined(separator:", ")
        savedTitle=title;savedTags=tags
        updated=value["updated"] as? String ?? "";summary=value["summary"] as? String ?? "";text=value["text"] as? String ?? ""
        var links=(value["links"] as? [[String:Any]] ?? []).compactMap(PhoneLink.init)
        if let original=PhoneLink(["url":value["url"] as? String ?? "","title":"打开原链接"]) {links.insert(original,at:0)}
        var seen=Set<String>();originals=links.filter {seen.insert($0.id).inserted}
        attachments=(value["attachments"] as? [[String:Any]] ?? []).map(PhoneAttachment.init);loaded=true
    }
    private func load() async {
        guard !working else {return};working=true;defer {working=false}
        do {apply(try await model.detail(record.id));error=""}
        catch {self.error=error.localizedDescription}
    }
    private func save() async {
        working=true;defer {working=false};notice=""
        let values=tags.components(separatedBy:CharacterSet(charactersIn:",，、\n")).map {$0.trimmingCharacters(in:.whitespacesAndNewlines)}.filter {!$0.isEmpty}
        do {apply(try await model.saveMetadata(record.id,title:title,tags:values,updated:updated));error="";notice="标题与标签已保存"}
        catch {self.error=error.localizedDescription}
    }
    private func select(_ data:Data,name:String) {
        guard data.count<=10*1024*1024 else {error="每个附件最多 10 MB";return}
        pendingData=data;pendingName=name;attachmentRequestID=UUID().uuidString;error="";notice=""
    }
    private func append() async {
        guard let data=pendingData else {return};working=true;defer {working=false};notice=""
        do {
            let draftTitle=title,draftTags=tags,titleChanged=title != savedTitle,tagsChanged=tags != savedTags
            apply(try await model.addAttachment(record.id,name:pendingName,data:data,updated:updated,requestID:attachmentRequestID))
            if titleChanged {title=draftTitle};if tagsChanged {tags=draftTags}
            pendingData=nil;photo=nil;error="";notice="附件已添加"
        } catch {self.error=error.localizedDescription}
    }
    private func open(_ file:PhoneAttachment) async {
        working=true;defer {working=false}
        do {let url=try await model.downloadAttachment(file.path,name:file.name);clearPreview();previewFolder=url.deletingLastPathComponent();preview=PhonePreview(url:url);error=""}
        catch {self.error=error.localizedDescription}
    }
    private func clearPreview() {if let folder=previewFolder {try? FileManager.default.removeItem(at:folder)};previewFolder=nil}
}
struct DeviceView: View {
    @EnvironmentObject var model: Companion
    @State private var confirm = false
    var body: some View { NavigationStack { Form { Section("已配对的 Mac") { Text(model.paired?.info.name ?? "");ConnectionBanner();Button("重新连接") { Task { await model.connect() } } };Section { Text("连接同一局域网时，App 打开后会自动寻找已配对的 Mac。电脑休眠或网络隔离时可能无法连接。手机不下载 AI 模型，检索和问答由电脑完成。").font(.callout).foregroundStyle(.secondary) };Section { Button("解除手机上的配对",role:.destructive) { confirm = true } } }.navigationTitle("连接").confirmationDialog("解除配对？待发送内容仍保留在手机，Mac 端可移除此设备。",isPresented:$confirm,titleVisibility:.visible) { Button("解除配对",role:.destructive) { model.disconnect() } } } }
}
struct ScannerView: UIViewControllerRepresentable {
    var scanned: (String, @escaping (String) -> Void) -> Void
    var cancelled: () -> Void
    func makeUIViewController(context: Context) -> ScannerController {
        let controller = ScannerController();controller.scanned = scanned;controller.cancelled = cancelled;return controller
    }
    func updateUIViewController(_ controller: ScannerController, context: Context) {}
}
final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var scanned: ((String, @escaping (String) -> Void) -> Void)?
    var cancelled: (() -> Void)?
    private let capture = AVCaptureSession()
    private let queue = DispatchQueue(label: "companion.camera")
    private var preview: AVCaptureVideoPreviewLayer?
    private var processing = false
    private var configured = false
    private var visible = false
    private var requestingPermission = false
    private var observers: [NSObjectProtocol] = []
    private let hint = UILabel()
    private let retry = UIButton(type: .system)
    private let settings = UIButton(type: .system)

    override func viewDidLoad() {
        super.viewDidLoad();view.backgroundColor = .black;view.accessibilityIdentifier = "pairing-scanner"
        let preview = AVCaptureVideoPreviewLayer(session: capture);preview.videoGravity = .resizeAspectFill
        view.layer.insertSublayer(preview, at: 0);self.preview = preview
        let cancel = UIButton(type: .system);cancel.setTitle("取消扫码", for: .normal);cancel.tintColor = .white
        cancel.accessibilityIdentifier = "scanner-cancel";cancel.addTarget(self, action: #selector(cancelScan), for: .touchUpInside)
        cancel.translatesAutoresizingMaskIntoConstraints = false;view.addSubview(cancel)
        hint.text = "将相机对准 Mac 的手机配对二维码";hint.textColor = .white;hint.numberOfLines = 0
        hint.textAlignment = .center;hint.accessibilityIdentifier = "scanner-status"
        retry.setTitle("重试扫码", for: .normal);retry.addTarget(self, action: #selector(retryScan), for: .touchUpInside);retry.isHidden = true
        settings.setTitle("打开系统设置", for: .normal);settings.addTarget(self, action: #selector(openSettings), for: .touchUpInside);settings.isHidden = true
        let stack = UIStackView(arrangedSubviews: [hint,retry,settings]);stack.axis = .vertical;stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        let card = UIView();card.backgroundColor = UIColor.black.withAlphaComponent(0.75);card.layer.cornerRadius = 16
        card.translatesAutoresizingMaskIntoConstraints = false;card.addSubview(stack);view.addSubview(card)
        NSLayoutConstraint.activate([
            cancel.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 12),cancel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),cancel.heightAnchor.constraint(greaterThanOrEqualToConstant: 44),
            card.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),card.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),card.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -24),
            stack.leadingAnchor.constraint(equalTo: card.leadingAnchor, constant: 20),stack.trailingAnchor.constraint(equalTo: card.trailingAnchor, constant: -20),stack.topAnchor.constraint(equalTo: card.topAnchor, constant: 20),stack.bottomAnchor.constraint(equalTo: card.bottomAnchor, constant: -20)
        ])
        let center = NotificationCenter.default
        observers.append(center.addObserver(forName: AVCaptureSession.wasInterruptedNotification, object: capture, queue: .main) { [weak self] _ in
            self?.showError("相机暂时被占用，请稍后重试")
        })
        observers.append(center.addObserver(forName: AVCaptureSession.interruptionEndedNotification, object: capture, queue: .main) { [weak self] _ in
            guard let self, self.visible, !self.processing else { return };self.prepareCamera()
        })
        observers.append(center.addObserver(forName: AVCaptureSession.runtimeErrorNotification, object: capture, queue: .main) { [weak self] _ in
            self?.showError("相机启动失败，请重试或检查相机权限")
        })
        observers.append(center.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in
            guard let self, self.visible, !self.processing else { return };self.prepareCamera()
        })
    }
    deinit { for observer in observers { NotificationCenter.default.removeObserver(observer) } }
    override func viewDidAppear(_ animated: Bool) { super.viewDidAppear(animated);visible = true;prepareCamera() }
    override func viewWillDisappear(_ animated: Bool) { super.viewWillDisappear(animated);visible = false;queue.async { self.capture.stopRunning() } }
    override func viewDidLayoutSubviews() { super.viewDidLayoutSubviews();preview?.frame = view.bounds }
    private func prepareCamera() {
        guard visible, !processing else { return }
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: settings.isHidden = true;startCamera()
        case .notDetermined:
            guard !requestingPermission else { return };requestingPermission = true
            AVCaptureDevice.requestAccess(for: .video) { [weak self] _ in DispatchQueue.main.async { self?.requestingPermission = false;self?.prepareCamera() } }
        default: showError("未获相机权限。请在系统设置中允许知识秘书使用相机。");settings.isHidden = false
        }
    }
    private func startCamera() {
        retry.isHidden = true;hint.text = "将相机对准 Mac 的手机配对二维码"
        queue.async { [weak self] in
            guard let self else { return }
            if !self.configured {
                guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
                      let input = try? AVCaptureDeviceInput(device: camera) else { DispatchQueue.main.async { self.showError("无法使用后置相机，请检查相机权限后重试") };return }
                self.capture.beginConfiguration();self.capture.sessionPreset = .high
                guard self.capture.canAddInput(input) else { self.capture.commitConfiguration();DispatchQueue.main.async { self.showError("相机当前不可用，请重试") };return }
                self.capture.addInput(input)
                let output = AVCaptureMetadataOutput()
                guard self.capture.canAddOutput(output) else { self.capture.removeInput(input);self.capture.commitConfiguration();DispatchQueue.main.async { self.showError("无法启动二维码识别，请重试") };return }
                self.capture.addOutput(output);output.setMetadataObjectsDelegate(self, queue: .main)
                guard output.availableMetadataObjectTypes.contains(.qr) else { self.capture.removeOutput(output);self.capture.removeInput(input);self.capture.commitConfiguration();DispatchQueue.main.async { self.showError("此相机无法识别二维码") };return }
                output.metadataObjectTypes = [.qr];self.capture.commitConfiguration();self.configured = true
            }
            if !self.capture.isRunning { self.capture.startRunning() }
        }
    }
    private func showError(_ message: String) { guard visible else { return };hint.text = message;retry.isHidden = false }
    @objc private func retryScan() { processing = false;prepareCamera() }
    @objc private func cancelScan() { cancelled?() }
    @objc private func openSettings() { if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) } }
    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard visible, !processing else { return }
        let values = metadataObjects.compactMap { ($0 as? AVMetadataMachineReadableCodeObject)?.stringValue }
        guard !values.isEmpty else { return }
        guard let value = values.first(where: { (try? PairInfo.pairingCode($0)) != nil }) else { hint.text = PairingCodeError.invalid.localizedDescription;return }
        processing = true;retry.isHidden = true;hint.text = "已识别配对码，正在检查局域网并连接 Mac…"
        queue.async { self.capture.stopRunning() }
        scanned?(value, { [weak self] message in
            guard let self, self.visible else { return };self.showError(message)
        })
    }
}
