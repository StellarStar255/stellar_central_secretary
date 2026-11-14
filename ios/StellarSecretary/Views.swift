import SwiftUI
import PhotosUI
import AVFoundation

@main struct StellarCompanionApp: App {
    @StateObject private var model = Companion()
    @Environment(\.scenePhase) private var scene
    var body: some Scene {
        WindowGroup {
            ContentView().environmentObject(model)
                .onOpenURL { url in
                    guard url.scheme == "stellar-secretary", url.host == "pair", let value = URLComponents(url:url,resolvingAgainstBaseURL:false)?.queryItems?.first(where:{$0.name == "data"})?.value,
                          let data = Data(base64Encoded:value), let raw = String(data:data,encoding:.utf8) else { return }
                    Task { await model.pair(raw) }
                }
                .task(id:scene) { while scene == .active && !Task.isCancelled { await model.connect();try? await Task.sleep(for:.seconds(10)) } }
        }
    }
}
struct ContentView: View {
    @EnvironmentObject var model: Companion
    @State private var scan = false
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
        }.sheet(isPresented:$scan) { ScannerView { raw in scan = false;Task { await model.pair(raw) } }.ignoresSafeArea() }
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
    @State private var query = ""
    @FocusState private var searching: Bool
    var body: some View {
        NavigationStack {
            List {
                Section { ConnectionBanner();TextField("搜索资料或输入问题",text:$query).focused($searching).submitLabel(.search).onSubmit { searching = false;Task { await model.search(query) } }
                    HStack { Button("搜索资料") { searching = false;Task { await model.search(query) } };Spacer();Button("问知识库") { searching = false;Task { await model.ask(query) } }.disabled(query.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty) }.disabled(model.busy || !model.online)
                }
                if model.busy { Section { HStack { ProgressView();Text("正在查询 Mac 上的知识库…") } } }
                if !model.error.isEmpty { Section { Text(model.error).foregroundStyle(.orange) } }
                if !model.answer.isEmpty { Section("回答") { Text(model.answer).textSelection(.enabled);ForEach(model.sources) { item in NavigationLink(item.title) { DetailView(record:item) } } } }
                Section("资料") { ForEach(model.records) { item in NavigationLink { DetailView(record:item) } label: { VStack(alignment:.leading,spacing:5) { Text(item.title);if !item.summary.isEmpty { Text(item.summary).font(.caption).foregroundStyle(.secondary).lineLimit(2) } } } } }
            }.navigationTitle("知识库").task { if model.online { await model.search("") } }
        }
    }
}
struct DetailView: View {
    @EnvironmentObject var model: Companion
    let record: Record
    @State private var content = ""
    @State private var original: URL?
    @State private var error = ""
    var body: some View { ScrollView { VStack(alignment:.leading,spacing:20) { Text(record.title).font(.title2.bold());if !error.isEmpty { Text(error).foregroundStyle(.orange) };Text(content).textSelection(.enabled);if let original { Link("打开原网页 ↗",destination:original) } }.padding() }.navigationTitle("资料详情").navigationBarTitleDisplayMode(.inline).task {
        do { let value = try await model.detail(record.id);content = (value["summary"] as? String ?? "") + "\n\n" + (value["text"] as? String ?? "");if let raw = value["url"] as? String, let url = URL(string:raw), ["http","https"].contains(url.scheme ?? "") { original = url } }
        catch { self.error = error.localizedDescription }
    } }
}
struct DeviceView: View {
    @EnvironmentObject var model: Companion
    @State private var confirm = false
    var body: some View { NavigationStack { Form { Section("已配对的 Mac") { Text(model.paired?.info.name ?? "");ConnectionBanner();Button("重新连接") { Task { await model.connect() } } };Section { Text("连接同一局域网时，App 打开后会自动寻找已配对的 Mac。电脑休眠或网络隔离时可能无法连接。手机不下载 AI 模型，检索和问答由电脑完成。").font(.callout).foregroundStyle(.secondary) };Section { Button("解除手机上的配对",role:.destructive) { confirm = true } } }.navigationTitle("连接").confirmationDialog("解除配对？待发送内容仍保留在手机，Mac 端可移除此设备。",isPresented:$confirm,titleVisibility:.visible) { Button("解除配对",role:.destructive) { model.disconnect() } } } }
}
struct ScannerView: UIViewControllerRepresentable {
    var scanned: (String)->Void
    func makeUIViewController(context:Context)->ScannerController { let controller = ScannerController();controller.scanned = scanned;return controller }
    func updateUIViewController(_ controller:ScannerController,context:Context) {}
}
final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var scanned: ((String)->Void)?
    private let capture = AVCaptureSession()
    private let queue = DispatchQueue(label:"companion.camera")
    private var preview: AVCaptureVideoPreviewLayer?
    private var completed = false
    override func viewDidLoad() { super.viewDidLoad();view.backgroundColor = .black;AVCaptureDevice.requestAccess(for:.video) { granted in DispatchQueue.main.async { if granted { self.setup() } else { self.showError("请在系统设置中允许相机访问，然后重新扫码") } } } }
    private func showError(_ text:String) { let label = UILabel();label.text = text;label.textColor = .white;label.numberOfLines = 0;label.textAlignment = .center;label.frame = view.bounds.insetBy(dx:25,dy:100);label.autoresizingMask = [.flexibleWidth,.flexibleHeight];view.addSubview(label) }
    private func setup() {
        guard let camera = AVCaptureDevice.default(for:.video), let input = try? AVCaptureDeviceInput(device:camera), capture.canAddInput(input) else { showError("无法使用相机；模拟器请通过配对测试链接连接");return }
        capture.addInput(input);let output = AVCaptureMetadataOutput();guard capture.canAddOutput(output) else { return };capture.addOutput(output);output.setMetadataObjectsDelegate(self,queue:.main);output.metadataObjectTypes = [.qr]
        let preview = AVCaptureVideoPreviewLayer(session:capture);preview.videoGravity = .resizeAspectFill;view.layer.insertSublayer(preview,at:0);self.preview = preview;queue.async { self.capture.startRunning() }
    }
    override func viewDidLayoutSubviews() { super.viewDidLayoutSubviews();preview?.frame = view.bounds }
    override func viewWillDisappear(_ animated:Bool) { super.viewWillDisappear(animated);queue.async { self.capture.stopRunning() } }
    func metadataOutput(_ output:AVCaptureMetadataOutput,didOutput metadataObjects:[AVMetadataObject],from connection:AVCaptureConnection) { guard !completed, let value = (metadataObjects.first as? AVMetadataMachineReadableCodeObject)?.stringValue else { return };completed = true;queue.async { self.capture.stopRunning() };scanned?(value) }
}
