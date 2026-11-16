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
                TabView(selection:$model.selectedTab) {
                    CaptureView().tabItem { Label("归档",systemImage:"square.and.pencil") }.tag("archive")
                    ChatView().tabItem {Label("聊天",systemImage:"bubble.left.and.bubble.right")}.tag("chat")
                    LibraryView().tabItem { Label("检索",systemImage:"magnifyingglass") }.tag("library")
                    DeviceView().tabItem { Label("连接",systemImage:"laptopcomputer.and.iphone") }.tag("device")
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
struct ChatView: View {
    @EnvironmentObject var model:Companion
    @State private var input=""
    @State private var inputDrafts:[String:String]=[:]
    @State private var choosing=false
    @State private var removing:PendingChatMessage?
    @State private var confirmingRemoval=false
    @FocusState private var typing:Bool
    private var messages:[ChatMessage] {model.chatSnapshot?.messages ?? []}
    private var queued:[PendingChatMessage] {
        let known=Set(messages.map(\.clientID))
        return model.currentChatQueue.filter {($0.chatID==model.selectedChatID || model.selectedChatID.isEmpty) && !known.contains($0.id)}
    }
    private func stage(_ value:String) -> String {
        switch value {
        case "queued":return "等待电脑处理…"
        case "planning":return "电脑正在理解问题…"
        case "retrieving":return "电脑正在检索资料…"
        case "answering","partial":return "电脑正在回答…"
        case "images","expanding":return "电脑正在核对资料…"
        case "approval":return "请在电脑上确认模型使用后继续"
        default:return "电脑正在处理…"
        }
    }
    var body:some View {
        NavigationStack {
            VStack(spacing:0) {
                ConnectionBanner().padding(.horizontal).frame(maxWidth:.infinity,alignment:.leading)
                if !model.online {Text("离线时显示已同步记录，新消息会暂存在手机").font(.caption).foregroundStyle(.secondary).padding(.horizontal)}
                if !model.chatNotice.isEmpty {Text(model.chatNotice).font(.footnote).foregroundStyle(.orange).padding(.horizontal)}
                ScrollViewReader {reader in
                    ScrollView {
                        LazyVStack(alignment:.leading,spacing:16) {
                            if model.chatSnapshot?.hasMore==true {Button("加载更早的消息") {Task {await model.syncSelectedChat(older:true)}}.disabled(!model.online)}
                            if messages.isEmpty && queued.isEmpty {
                                Text(model.selectedChatID.isEmpty ? "选择电脑上的会话，或新建对话":"继续这段对话，电脑会结合相同的上下文处理").foregroundStyle(.secondary).padding(.vertical,24)
                            }
                            ForEach(messages) {message in
                                HStack(alignment:.top) {
                                    if message.role=="user" {Spacer(minLength:35)}
                                    VStack(alignment:.leading,spacing:8) {
                                        Text(message.role=="user" ? "我":"电脑").font(.caption).foregroundStyle(.secondary)
                                        if !message.text.isEmpty {Text(message.text).textSelection(.enabled).foregroundStyle(message.error ? Color.orange:Color.primary)}
                                        ForEach(message.files,id:\.self) {Text($0).font(.caption).foregroundStyle(.secondary)}
                                        if message.pending || message.requestState=="running" {
                                            Text(stage(model.chatStage)).font(.footnote).foregroundStyle(.secondary)
                                            if !model.chatPartial.isEmpty {Text(model.chatPartial).textSelection(.enabled);Text("回答生成中").font(.caption).foregroundStyle(.secondary)}
                                            Button("停止回答") {Task {await model.stopChatAnswer(message)}}.disabled(!model.online)
                                        }
                                        ForEach(Array(message.sources.enumerated()),id:\.offset) {_,source in NavigationLink {DetailView(record:source)} label:{Label(source.title,systemImage:"doc.text").font(.footnote)}}
                                    }.padding(12).background(message.role=="user" ? Color.accentColor.opacity(0.12):Color.secondary.opacity(0.08),in:RoundedRectangle(cornerRadius:14)).id(message.id)
                                    if message.role != "user" {Spacer(minLength:20)}
                                }
                            }
                            ForEach(queued) {pending in
                                VStack(alignment:.leading,spacing:8) {
                                    Text(pending.text).textSelection(.enabled)
                                    Text(pending.lastError.isEmpty ? "待发送 · 连接后由电脑处理":pending.lastError).font(.footnote).foregroundStyle(.secondary)
                                    HStack {
                                        if !pending.lastError.isEmpty {Button("重新发送") {Task {await model.retryChatMessage(pending.id)}}.disabled(!model.online || model.chatSubmitting)}
                                        Button("移除待发消息",role:.destructive) {removing=pending;confirmingRemoval=true}.disabled(model.chatSubmitting)
                                    }
                                }.padding(12).frame(maxWidth:.infinity,alignment:.leading).background(Color.accentColor.opacity(0.08),in:RoundedRectangle(cornerRadius:14)).id(pending.id)
                            }
                            Color.clear.frame(height:1).id("chat-bottom")
                        }.padding()
                    }.scrollDismissesKeyboard(.interactively)
                    .onChange(of:messages.last?.id) {_,_ in withAnimation {reader.scrollTo("chat-bottom",anchor:.bottom)}}
                    .onChange(of:queued.count) {_,_ in withAnimation {reader.scrollTo("chat-bottom",anchor:.bottom)}}
                }
                HStack(alignment:.bottom) {
                    TextField("发消息，继续这段对话…",text:$input,axis:.vertical).lineLimit(1...5).textFieldStyle(.roundedBorder).focused($typing).accessibilityIdentifier("chat-input").disabled(model.selectedChatID.isEmpty)
                    Button("发送") {
                        let value=input;typing=false
                        Task {if await model.enqueueChat(value),input==value {input=""}}
                    }.buttonStyle(.borderedProminent).accessibilityIdentifier("chat-send").disabled(model.selectedChatID.isEmpty || input.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || model.chatSubmitting)
                }.padding()
            }.navigationTitle(model.chatSnapshot?.title ?? "聊天").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement:.topBarLeading) {Button("会话") {choosing=true}}
                ToolbarItem(placement:.topBarTrailing) {Button {Task {await model.createChat()}} label:{Image(systemName:"square.and.pencil")}.accessibilityLabel("新建聊天").disabled(!model.online || model.chatSubmitting)}
            }
            .sheet(isPresented:$choosing) {
                NavigationStack {
                    List {
                        ForEach(model.chatThreads) {chat in Button {model.selectChat(chat.id);choosing=false} label:{HStack {Text(chat.title);Spacer();if chat.running {ProgressView()};if chat.id==model.selectedChatID {Image(systemName:"checkmark")}}}}
                        if !model.currentChatQueue.isEmpty {
                            Section("手机待发送") {ForEach(model.currentChatQueue) {pending in VStack(alignment:.leading) {Text(pending.text).lineLimit(3);if !pending.lastError.isEmpty {Text(pending.lastError).font(.caption).foregroundStyle(.orange)}}}}
                        }
                    }.navigationTitle("电脑上的会话").toolbar {Button("关闭") {choosing=false}}.refreshable {await model.syncChatList()}
                }
            }
            .alert("移除待发消息？",isPresented:$confirmingRemoval) {Button("移除",role:.destructive) {if let pending=removing {model.removeQueuedChatMessage(pending.id)}};Button("取消",role:.cancel) {}} message:{Text("这条尚未发送的内容将从手机移除。")}
            .onChange(of:model.selectedChatID) {old,new in inputDrafts[old]=input;input=inputDrafts[new] ?? ""}
            .task(id:model.selectedChatID+String(model.online)) {
                guard model.online else {return};var tick=0
                while !Task.isCancelled && model.online {
                    if tick%5==0 {await model.syncChatList()}
                    await model.flushChatMessages();await model.syncSelectedChat()
                    tick+=1;try? await Task.sleep(nanoseconds:model.chatSnapshot?.running==true ? 1_500_000_000:3_000_000_000)
                }
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
    let id:String;let name:String;let path:String;let previewPath:String;let version:String;let size:Int64
    init(_ value:[String:Any]) {
        id=value["path"] as? String ?? "";name=value["name"] as? String ?? "附件";path=id
        previewPath=value["preview_path"] as? String ?? "";version=value["version"] as? String ?? "";size=(value["size"] as? NSNumber)?.int64Value ?? 0
    }
}
private struct PhoneLink: Identifiable {
    let id:String;let title:String;let url:URL
    init?(_ value:[String:Any]) {
        guard let raw=value["url"] as? String,let url=URL(string:raw),["https","http"].contains(url.scheme?.lowercased() ?? "") else {return nil}
        self.url=url;id=raw;title=value["title"] as? String ?? raw
    }
}
private struct PhonePreview: Identifiable {let id=UUID();let url:URL;let lightweight:Bool}
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
private struct TagFlowLayout: Layout {
    var spacing:CGFloat=8
    private func arrange(_ subviews:Subviews,width:CGFloat) -> (CGSize,[CGPoint],[CGSize]) {
        var points:[CGPoint]=[],sizes:[CGSize]=[];var x:CGFloat=0,y:CGFloat=0,row:CGFloat=0
        for view in subviews {
            let ideal=view.sizeThatFits(.unspecified)
            let size=view.sizeThatFits(ProposedViewSize(width:min(ideal.width,width),height:nil))
            if x>0 && x+size.width>width {x=0;y+=row+spacing;row=0}
            points.append(CGPoint(x:x,y:y));sizes.append(size);x+=size.width+spacing;row=max(row,size.height)
        }
        return (CGSize(width:width,height:y+row),points,sizes)
    }
    func sizeThatFits(proposal:ProposedViewSize,subviews:Subviews,cache:inout ()) -> CGSize {
        arrange(subviews,width:max(1,proposal.width ?? 320)).0
    }
    func placeSubviews(in bounds:CGRect,proposal:ProposedViewSize,subviews:Subviews,cache:inout ()) {
        let (_,points,sizes)=arrange(subviews,width:max(1,bounds.width))
        for index in subviews.indices {subviews[index].place(at:CGPoint(x:bounds.minX+points[index].x,y:bounds.minY+points[index].y),proposal:ProposedViewSize(sizes[index]))}
    }
}
private struct InlineAttachmentImage: View {
    @EnvironmentObject var model:Companion
    let file:PhoneAttachment
    @State private var image:UIImage?
    @State private var failed=false
    @State private var retry=0
    var body:some View {
        VStack(alignment:.leading,spacing:8) {
            if let image {
                Image(uiImage:image).resizable().scaledToFit().frame(maxWidth:.infinity,maxHeight:280)
                    .clipShape(RoundedRectangle(cornerRadius:10)).accessibilityLabel("图片预览 · "+file.name)
            } else if failed {
                HStack {Text("图片预览暂未加载").font(.footnote).foregroundStyle(.secondary);Button("重试") {retry+=1}}
            } else {
                HStack {ProgressView();Text("正在加载图片预览…").font(.footnote).foregroundStyle(.secondary)}.frame(maxWidth:.infinity,minHeight:100)
            }
        }.task(id:file.version+String(model.online)+String(retry)) {
            guard image == nil else {return};failed=false
            do {
                let url=try await model.downloadAttachment(file.previewPath,name:file.name+".preview.jpg",version:file.version) {_,_ in}
                guard !Task.isCancelled else {return}
                guard let value=UIImage(contentsOfFile:url.path) else {failed=true;return};image=value
            } catch {if !Task.isCancelled {failed=true}}
        }
    }
}
struct DetailView: View {
    @EnvironmentObject var model: Companion
    let record:Record
    @State private var title=""
    @State private var tags:[String]=[]
    @State private var newTag=""
    @State private var addingTag=false
    @State private var deletingTag:String?
    @State private var confirmTagDeletion=false
    @State private var updated=""
    @State private var savedTitle=""
    @State private var savedTags:[String]=[]
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
    @State private var fileTask:Task<Void,Never>?
    @State private var downloadDone:Int64=0
    @State private var downloadTotal:Int64=0
    @State private var operationLabel=""
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:20) {
                if !originals.isEmpty || !attachments.isEmpty {
                    VStack(alignment:.leading,spacing:12) {
                        Text("原链接与原件").font(.headline)
                        ForEach(originals) {link in Link(destination:link.url) {Label(link.title,systemImage:"arrow.up.right.square").lineLimit(2)}}
                        ForEach(attachments) {file in
                            VStack(alignment:.leading,spacing:8) {
                                if !file.previewPath.isEmpty {
                                    InlineAttachmentImage(file:file)
                                }
                                Button {fileTask=Task {await open(file)}} label:{Label("打开原件 · "+file.name,systemImage:"doc")}.disabled(working || !model.online)
                                if file.size>0 {Text(ByteCountFormatter.string(fromByteCount:file.size,countStyle:.file)+(!file.previewPath.isEmpty ? " · 图片预览更快，原件保持完整":"")).font(.caption).foregroundStyle(.secondary)}
                            }
                        }
                    }.frame(maxWidth:.infinity,alignment:.leading).padding().background(.quaternary,in:RoundedRectangle(cornerRadius:14))
                }
                if fileTask != nil {
                    VStack(alignment:.leading,spacing:8) {
                        Text(operationLabel).font(.subheadline)
                        if downloadTotal>0 {
                            ProgressView(value:Double(downloadDone),total:Double(max(downloadTotal,1)))
                            Text(ByteCountFormatter.string(fromByteCount:downloadDone,countStyle:.file)+" / "+ByteCountFormatter.string(fromByteCount:downloadTotal,countStyle:.file)).font(.caption).foregroundStyle(.secondary)
                        } else {ProgressView()}
                        Button("取消下载") {fileTask?.cancel()}
                    }
                }
                if !loaded {Text(record.title).font(.title2.bold());Text(record.summary).textSelection(.enabled);if working {ProgressView("正在加载资料详情…")}}
                if !error.isEmpty {Text(error).foregroundStyle(.orange)}
                if !notice.isEmpty {Text(notice).foregroundStyle(.secondary)}
                if loaded {
                    VStack(alignment:.leading,spacing:12) {
                        Text("标题").font(.headline)
                        TextField("资料标题",text:$title,axis:.vertical).textFieldStyle(.roundedBorder).accessibilityIdentifier("detail-title")
                        Button("保存标题") {Task {await save()}}.buttonStyle(.borderedProminent)
                        Text("标签").font(.headline)
                        TagFlowLayout {
                            ForEach(tags,id:\.self) {tag in
                                HStack(spacing:4) {
                                    Text(tag).font(.subheadline).fixedSize(horizontal:false,vertical:true).accessibilityIdentifier("tag-chip-"+tag)
                                    Button {deletingTag=tag;confirmTagDeletion=true} label:{Image(systemName:"xmark.circle.fill").foregroundStyle(.secondary).frame(width:32,height:36)}
                                        .buttonStyle(.plain).accessibilityLabel("删除标签 "+tag).accessibilityIdentifier("tag-remove-"+tag)
                                }.padding(.leading,12).padding(.trailing,4).padding(.vertical,4).background(Color.accentColor.opacity(0.12),in:RoundedRectangle(cornerRadius:16))
                            }
                            Button {newTag="";addingTag=true} label:{Label("添加标签",systemImage:"plus")}.buttonStyle(.bordered)
                        }
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
                    if working && fileTask == nil {ProgressView("正在处理…")}
                    if !summary.isEmpty {Text("摘要").font(.headline);Text(summary).textSelection(.enabled)}
                    if !text.isEmpty {DisclosureGroup("正文与归档说明") {Text(text).frame(maxWidth:.infinity,alignment:.leading).textSelection(.enabled)}}
                }
            }.padding().frame(maxWidth:.infinity,alignment:.leading)
        }.navigationTitle("资料详情").navigationBarTitleDisplayMode(.inline)
        .toolbar {Button("重新加载") {Task {await load()}}.disabled(working)}
        .task {await load()}
        .sheet(item:$preview,onDismiss:{clearPreview()}) {value in
            NavigationStack {
                OriginalPreview(url:value.url).navigationTitle(value.lightweight ? "图片预览（非原件）":"完整原件").navigationBarTitleDisplayMode(.inline)
                    .toolbar {ToolbarItem(placement:.topBarTrailing) {Button("关闭") {preview=nil}}}
            }
        }
        .alert("添加标签",isPresented:$addingTag) {
            TextField("标签名称",text:$newTag)
            Button("添加") {Task {await addTag()}}
            Button("取消",role:.cancel) {}
        }
        .alert("删除标签？",isPresented:$confirmTagDeletion) {
            Button("删除标签",role:.destructive) {if let tag=deletingTag {Task {await saveTags(tags.filter {$0 != tag},notice:"标签已删除")}}}
            Button("取消",role:.cancel) {deletingTag=nil}
        } message: {Text("确定删除标签“"+(deletingTag ?? "")+"”？")}
        .onDisappear {fileTask?.cancel();if preview == nil {clearPreview()}}
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
        title=value["title"] as? String ?? record.title;tags=value["tags"] as? [String] ?? []
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
        do {apply(try await model.saveMetadata(record.id,title:title,tags:tags,updated:updated));error="";notice="标题已保存"}
        catch {self.error=error.localizedDescription}
    }
    private func addTag() async {
        let tag=newTag.trimmingCharacters(in:.whitespacesAndNewlines)
        guard !tag.isEmpty,tag.count<=60,tags.count<50 else {error="标签需为 1–60 个字符，最多 50 个标签";return}
        guard !tags.contains(where:{$0.caseInsensitiveCompare(tag) == .orderedSame}) else {error="这个标签已存在";return}
        await saveTags(tags+[tag],notice:"标签已添加")
    }
    private func saveTags(_ values:[String],notice message:String) async {
        guard !working else {return};working=true;defer {working=false}
        let draftTitle=title,titleChanged=title != savedTitle
        do {
            apply(try await model.saveMetadata(record.id,title:savedTitle,tags:values,updated:updated))
            if titleChanged {title=draftTitle}
            error="";notice=message
        } catch {self.error=error.localizedDescription}
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
    private func open(_ file:PhoneAttachment,lightweight:Bool=false) async {
        working=true;downloadDone=0;downloadTotal=0
        operationLabel=lightweight ? "正在加载图片预览（非原件）…":"正在下载完整原件…"
        defer {working=false;fileTask=nil}
        do {
            let url=try await model.downloadAttachment(lightweight ? file.previewPath:file.path,name:lightweight ? file.name+".preview.jpg":file.name,version:file.version) {done,total in
                Task {@MainActor in downloadDone=done;downloadTotal=total}
            }
            guard !Task.isCancelled else {return}
            clearPreview();previewFolder=url.deletingLastPathComponent();preview=PhonePreview(url:url,lightweight:lightweight);error=""
        } catch {
            if Task.isCancelled {return}
            self.error=error.localizedDescription
        }
    }
    private func clearPreview() {previewFolder=nil}

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
