import SwiftUI
import PhotosUI
import AVFoundation
import QuickLook

enum PhoneLanguage {
    static let setting = "phoneInterfaceLanguage"
    static let chinese = "zh-Hans"
    private static let englishBundle = Bundle.main.url(forResource:"en",withExtension:"lproj")
        .flatMap { Bundle(url:$0) }

    static func text(_ message: String, in locale: Locale) -> String {
        guard locale.language.languageCode?.identifier == "en", let bundle = englishBundle else { return message }
        func translate(_ key: String) -> String { bundle.localizedString(forKey:key,value:key,table:nil) }
        let translated = translate(message)
        if translated != message {return translated}
        let patterns = [
            ("正在连接 ", "…", "正在连接 %@…"),
            ("已连接 · ", "", "已连接 · %@"),
            ("", " 离线 · 内容保留在手机", "%@ 离线 · 内容保留在手机"),
            ("待发送内容已保留：", "", "待发送内容已保留：%@"),
        ]
        for (prefix, suffix, key) in patterns where message.hasPrefix(prefix) && message.hasSuffix(suffix) {
            let value = String(message.dropFirst(prefix.count).dropLast(suffix.count))
            return String(format:translate(key),value)
        }
        if let suffix = message.range(of:"（错误 ",options:.backwards), message.hasSuffix("）") {
            let code = String(message[suffix.upperBound..<message.index(before:message.endIndex)])
            return translate(String(message[..<suffix.lowerBound]))+String(format:translate("（错误 %@）"),code)
        }
        return message
    }
}

private struct PhoneLanguagePicker: View {
    @AppStorage(PhoneLanguage.setting) private var language = PhoneLanguage.chinese

    var body: some View {
        Picker("显示语言",selection:$language) {
            Text(verbatim:"简体中文").tag(PhoneLanguage.chinese)
            Text(verbatim:"English").tag("en")
        }.pickerStyle(.menu).accessibilityIdentifier("phone-language-picker")
    }
}

@main struct StellarCompanionApp: App {
    @StateObject private var model = Companion()
    @Environment(\.scenePhase) private var scene
    @AppStorage(PhoneLanguage.setting) private var language = PhoneLanguage.chinese
    var body: some Scene {
        WindowGroup {
            ContentView().environmentObject(model)
                .environment(\.locale,Locale(identifier:language))
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
    @Environment(\.locale) private var interfaceLocale
    @State private var scan = false
    @State private var showDemo = false
    @State private var pairingTask: Task<Void, Never>?
    var body: some View {
        Group {
            if model.paired == nil && !model.computers.computers.isEmpty {
                DeviceView(addComputer: {scan=true})
            } else if model.paired == nil {
                NavigationStack {
                    VStack(spacing:24) {
                        Image(systemName:"sparkle").font(.system(size:64,weight:.light)).foregroundStyle(.orange)
                        Text("随手存，随时查").font(.largeTitle.bold())
                        Text("与 Mac 上的 Stellar Secretary 配对，\n共用你的知识库。").multilineTextAlignment(.center).foregroundStyle(.secondary)
                        if model.waiting { Text(model.code).font(.largeTitle.monospacedDigit()).tracking(8);Text(PhoneLanguage.text(model.status,in:interfaceLocale));ProgressView() }
                        else { Button { scan = true } label: { Label("扫描 Mac 配对码",systemImage:"qrcode.viewfinder").frame(maxWidth:.infinity) }.buttonStyle(.borderedProminent).controlSize(.large)
                            Text("电脑端：模型与设置 → 手机连接").font(.footnote).foregroundStyle(.secondary)
                            Button("演示模式 / Demo") { showDemo = true }.accessibilityIdentifier("open-review-demo")
                            Button("隐私与 AI / Privacy") { model.showPrivacy = true }
                        }
                        PhoneLanguagePicker()
                        if !model.error.isEmpty { Text(PhoneLanguage.text(model.error,in:interfaceLocale)).foregroundStyle(.orange).font(.callout) }
                    }.padding(30).navigationTitle("Stellar Secretary")
                }
            } else {
                TabView(selection:$model.selectedTab) {
                    CaptureView().id(model.workspaceID).tabItem { Label("归档",systemImage:"square.and.pencil") }.tag("archive")
                    ChatView().id(model.workspaceID).tabItem {Label("聊天",systemImage:"bubble.left.and.bubble.right")}.tag("chat")
                    LibraryView().id(model.workspaceID).tabItem { Label("检索",systemImage:"magnifyingglass") }.tag("library")
                    DeviceView(addComputer: {scan=true}).id(model.workspaceID).tabItem { Label("连接",systemImage:"laptopcomputer.and.iphone") }.tag("device")
                }.tint(.orange)
            }
        }.sheet(isPresented:$showDemo) {
            ReviewDemoView()
        }.sheet(isPresented:$model.showPrivacy) {
            PrivacyView().environmentObject(model)
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
    @Environment(\.locale) private var interfaceLocale
    var body: some View {
        VStack(alignment:.leading,spacing:4) {
            if let pair=model.paired {Text("当前电脑 · \(pair.displayName)").font(.caption).foregroundStyle(.secondary)}
            Label(PhoneLanguage.text(model.status,in:interfaceLocale),systemImage:model.online ? "checkmark.circle.fill":"wifi.slash").font(.footnote).foregroundStyle(model.online ? .green:.secondary)
        }.padding(.vertical,4)
    }
}
struct CaptureView: View {
    @Environment(\.locale) private var interfaceLocale
    @EnvironmentObject var model: Companion
    @Environment(\.scenePhase) private var scene
    private var text: String {model.captureEditor.text}
    @State private var photo: PhotosPickerItem?
    private var image: Data? {model.captureEditor.data}
    private var filename: String? {model.captureEditor.filename}
    @State private var importing = false
    @State private var saving = false
    @FocusState private var editing: Bool
    var body: some View {
        NavigationStack {
            Form {
                Section { ConnectionBanner() }
                Section("链接、笔记或安排") { TextEditor(text:$model.captureEditor.text).focused($editing).frame(minHeight:150).accessibilityLabel("归档内容") }
                Section {
                    PhotosPicker(selection:$photo,matching:.images) { Label("添加截图或照片",systemImage:"photo") }
                    Button { importing = true } label: { Label("添加文件",systemImage:"paperclip") }
                    if let filename { HStack { Text(filename);Spacer();Button("移除") { model.captureEditor.data = nil;model.captureEditor.filename = nil;photo = nil } } }
                    Button { editing = false;saving = true;let id=model.workspaceID,value=text,file=filename,data=image;Task { if await model.enqueue(text:value,filename:file,data:data,workspace:id),model.workspaceID==id { model.captureEditor=CaptureEditor();photo = nil };saving = false } } label: { Label(LocalizedStringKey(model.online ? "保存到知识库":"暂存，连接后发送"),systemImage:"tray.and.arrow.down").frame(maxWidth:.infinity) }.disabled(saving || (text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && image == nil))
                } footer: { Text("可在「连接 → 隐私与 AI」授权手机归档自动摘要。附件最多 10 MB。") }
                if !model.error.isEmpty { Section { Text(PhoneLanguage.text(model.error,in:interfaceLocale)).foregroundStyle(.orange) } }
                if !model.currentDrafts.isEmpty {
                    Section("待发送 · \(model.currentDrafts.count)") {
                        ForEach(model.currentDrafts) { draft in
                            VStack(alignment:.leading) {
                                Text(draft.filename ?? draft.text).lineLimit(2)
                                Text(LocalizedStringKey(model.sendingDraftID == draft.id ? "正在上传" : "待发送")).font(.caption).foregroundStyle(.secondary)
                            }.accessibilityIdentifier("capture-outbox-"+draft.id)
                            .swipeActions { if model.sendingDraftID != draft.id { Button("删除",role:.destructive) { model.removeDraft(draft.id) } } }
                        }
                        Button("重新发送") { Task { await model.connect() } }
                    }
                }
                if !model.captureReceipts.isEmpty {
                    Section {
                        ForEach(model.captureReceipts) { receipt in
                            NavigationLink { DetailView(record:receipt.record,workspace:model.workspaceID) } label: {
                                CaptureReceiptRow(receipt:receipt)
                            }.accessibilityIdentifier("capture-receipt-"+receipt.id)
                        }
                    } header: { Text("最近手机归档") } footer: {
                        if !model.online { Text("离线 · 显示上次确认的状态") }
                    }
                }
            }.navigationTitle(PhoneLanguage.text("随手归档",in:interfaceLocale)).scrollDismissesKeyboard(.interactively).toolbar { ToolbarItemGroup(placement:.keyboard) { Spacer();Button("完成") { editing = false } } }
            .task(id:"\(model.workspaceID)-\(model.selectedTab)-\(model.online)-\(model.captureStatusAvailable)-\(scene)") {
                guard model.selectedTab == "archive", model.online, model.captureStatusAvailable, scene == .active else {return}
                while !Task.isCancelled {
                    await model.refreshCaptureReceipts()
                    let processing = model.captureReceipts.contains {$0.stage == "processing"}
                    try? await Task.sleep(for:.seconds(processing ? 3 : 10))
                }
            }
            .onChange(of:photo) { _,value in Task {
                guard let value else { return }
                let id=model.workspaceID
                if let data = try? await value.loadTransferable(type:Data.self), data.count <= 10*1024*1024 {
                    guard id==model.workspaceID else {return}
                    model.captureEditor.data = data;let type = value.supportedContentTypes.first;model.captureEditor.filename = "Photo." + (type?.preferredFilenameExtension ?? "jpg")
                } else { model.error = "照片读取失败或超过 10 MB" }
            } }
            .fileImporter(isPresented:$importing,allowedContentTypes:[.item]) { result in
                do { let url = try result.get();let access = url.startAccessingSecurityScopedResource();defer { if access { url.stopAccessingSecurityScopedResource() } };let values = try url.resourceValues(forKeys:[.fileSizeKey]);guard (values.fileSize ?? Int.max) <= 10*1024*1024 else { model.error = "文件超过 10 MB";return };model.captureEditor.data = try Data(contentsOf:url);model.captureEditor.filename = url.lastPathComponent }
                catch { model.error = "无法读取文件" }
            }
        }
    }
}

private struct CaptureReceiptRow: View {
    @Environment(\.locale) private var interfaceLocale
    let receipt: CaptureReceipt
    var body: some View {
        VStack(alignment:.leading,spacing:4) {
            Text(receipt.record.title).lineLimit(2)
            switch receipt.stage {
            case "processing": Label("正在整理", systemImage:"clock")
            case "ready": Label("摘要已完成", systemImage:"checkmark.circle")
            case "error": Label("整理未完成", systemImage:"exclamationmark.circle").foregroundStyle(.orange)
            default: Label("已归档", systemImage:"tray.and.arrow.down")
            }
            if !receipt.message.isEmpty {Text(PhoneLanguage.text(receipt.message,in:interfaceLocale)).fixedSize(horizontal:false,vertical:true)}
        }.font(.subheadline)
    }
}
struct ChatView: View {
    private struct CameraTarget: Identifiable {
        let id = UUID()
        let workspace: String
        let chat: String

        @MainActor func matches(_ model: Companion) -> Bool {
            workspace == model.workspaceID && chat == model.selectedChatID
        }
    }

    @Environment(\.locale) private var interfaceLocale
    @EnvironmentObject var model:Companion
    private var input:String {model.chatInput}
    @State private var choosing=false
    @State private var removing:PendingChatMessage?
    @State private var confirmingRemoval=false
    @State private var composing=false
    @State private var dismissKeyboard=0
    @State private var composerRevision=0
    @State private var sending=false
    @State private var pickingPhoto=false
    @State private var pickingFile=false
    @State private var cameraTarget: CameraTarget?
    @State private var loadingAttachment=false
    @State private var pickedPhoto:PhotosPickerItem?
    @State private var attachmentError=""
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
                if !model.chatNotice.isEmpty {Text(PhoneLanguage.text(model.chatNotice,in:interfaceLocale)).font(.footnote).foregroundStyle(.orange).padding(.horizontal)}
                ScrollViewReader {reader in
                    ScrollView {
                        LazyVStack(alignment:.leading,spacing:16) {
                            if model.chatSnapshot?.hasMore==true {Button("加载更早的消息") {Task {await model.syncSelectedChat(older:true)}}.disabled(!model.online)}
                            if messages.isEmpty && queued.isEmpty {
                                Text(LocalizedStringKey(model.selectedChatID.isEmpty ? "发一条消息开始聊天":"继续这段对话，电脑会结合相同的上下文处理")).foregroundStyle(.secondary).padding(.vertical,24)
                            }
                            ForEach(messages) {message in
                                HStack(alignment:.top) {
                                    if message.role=="user" {Spacer(minLength:35)}
                                    VStack(alignment:.leading,spacing:8) {
                                        Text(LocalizedStringKey(message.role=="user" ? "我":"电脑")).font(.caption).foregroundStyle(.secondary)
                                        if !message.text.isEmpty {Text(message.text).textSelection(.enabled).foregroundStyle(message.error ? Color.orange:Color.primary)}
                                        ForEach(message.files,id:\.self) {Text($0).font(.caption).foregroundStyle(.secondary)}
                                        if message.pending || message.requestState=="running" {
                                            Text(LocalizedStringKey(stage(model.chatStage))).font(.footnote).foregroundStyle(.secondary)
                                            if !model.chatPartial.isEmpty {Text(model.chatPartial).textSelection(.enabled);Text("回答生成中").font(.caption).foregroundStyle(.secondary)}
                                            Button("停止回答") {Task {await model.stopChatAnswer(message)}}.disabled(!model.online)
                                        }
                                        ForEach(Array(message.sources.enumerated()),id:\.offset) {_,source in NavigationLink {DetailView(record:source,workspace:model.workspaceID)} label:{Label(source.title,systemImage:"doc.text").font(.footnote)}}
                                    }.padding(12).background(message.role=="user" ? Color.accentColor.opacity(0.12):Color.secondary.opacity(0.08),in:RoundedRectangle(cornerRadius:14)).id(message.id)
                                    if message.role != "user" {Spacer(minLength:20)}
                                }
                            }
                            ForEach(queued) {pending in
                                VStack(alignment:.leading,spacing:8) {
                                    if !pending.text.isEmpty {Text(pending.text).textSelection(.enabled)}
                                    if let file=pending.attachment {Label(file.name,systemImage:"paperclip")}
                                    Text(PhoneLanguage.text(pending.lastError.isEmpty ? "待发送 · 连接后由电脑处理":pending.lastError,in:interfaceLocale)).font(.footnote).foregroundStyle(.secondary)
                                    HStack {
                                        if !pending.lastError.isEmpty {Button("重新发送") {Task {await model.retryChatMessage(pending.id)}}.disabled(!model.online || model.chatSubmitting)}
                                        Button("移除待发消息",role:.destructive) {removing=pending;confirmingRemoval=true}.disabled(model.chatSubmitting)
                                    }
                                }.padding(12).frame(maxWidth:.infinity,alignment:.leading).background(Color.accentColor.opacity(0.08),in:RoundedRectangle(cornerRadius:14)).id(pending.id)
                            }
                            Color.clear.frame(height:1).id("chat-bottom")
                        }.padding()
                    }.scrollDismissesKeyboard(.interactively)
                    .onChange(of:messages.last?.id,initial:true) {_,_ in reader.scrollTo("chat-bottom",anchor:.bottom)}
                    .onChange(of:model.chatSnapshot?.running) {old,new in if old==true && new==false {reader.scrollTo("chat-bottom",anchor:.bottom)}}
                    .onChange(of:queued.count) {_,_ in withAnimation {reader.scrollTo("chat-bottom",anchor:.bottom)}}
                }
                VStack(alignment:.leading,spacing:8) {
                    if let file=model.chatAttachment {
                        HStack {
                            Label(file.name,systemImage:"paperclip").lineLimit(1)
                            Spacer()
                            Button {model.chatAttachment=nil} label:{Image(systemName:"xmark.circle.fill")}
                                .accessibilityLabel("移除聊天附件").disabled(sending)
                        }.font(.subheadline)
                    }
                    if loadingAttachment {ProgressView("正在读取附件…").font(.caption)}
                    if !attachmentError.isEmpty {Text(PhoneLanguage.text(attachmentError,in:interfaceLocale)).font(.footnote).foregroundStyle(.orange)}
                    HStack(alignment:.bottom) {
                    Menu {
                        Button("拍照",systemImage:"camera") { openCamera() }
                        Button("截图或照片",systemImage:"photo") {pickingPhoto=true}
                        Button("文件",systemImage:"doc") {pickingFile=true}
                    } label: {
                        Image(systemName:"plus.circle").font(.title2).frame(width:44,height:48)
                    }.tint(.accentColor)
                    .accessibilityLabel("添加聊天附件")
                    .accessibilityIdentifier("chat-add-attachment")
                    .disabled(sending || loadingAttachment)
                    ChatComposer(text:$model.chatInput,composing:$composing,dismissKeyboard:dismissKeyboard)
                        .id(composerRevision)
                        .overlay(alignment:.topLeading) {
                            if input.isEmpty && !composing {
                                Text(LocalizedStringKey(model.selectedChatID.isEmpty ? "输入消息开始聊天…" : "发消息，继续这段对话…"))
                                    .foregroundStyle(.secondary).padding(.horizontal,12).padding(.vertical,10)
                                    .allowsHitTesting(false).accessibilityHidden(true)
                            }
                        }
                    Button("发送") {
                        guard !composing else {return}
                        let value=input,id=model.workspaceID,chat=model.selectedChatID,file=model.chatAttachment
                        dismissKeyboard+=1;sending=true
                        Task {
                            defer {sending=false}
                            if await model.enqueueChat(value,workspace:id,chatID:chat,attachment:file),
                               model.workspaceID==id,(chat.isEmpty || model.selectedChatID==chat) {
                                if input==value,!composing {model.chatInput=""}
                                if model.chatAttachment==file {model.chatAttachment=nil}
                            }
                        }
                    }.buttonStyle(.borderedProminent).controlSize(.large).accessibilityIdentifier("chat-send")
                        .disabled(composing || sending || loadingAttachment || (input.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && model.chatAttachment==nil) || model.chatSubmitting)
                    }
                }.padding()
            }.navigationTitle(model.chatSnapshot?.title ?? PhoneLanguage.text("聊天",in:interfaceLocale)).navigationBarTitleDisplayMode(.inline)
            .fullScreenCover(item:$cameraTarget) { target in
                ChatCamera { result in
                    cameraTarget = nil
                    guard case .captured(let photo) = result, target.matches(model) else { return }
                    guard let data = photo?.jpegData(compressionQuality: 0.8) else {
                        attachmentError = "无法读取照片。"
                        return
                    }
                    setAttachment(name:"Photo.jpg",data:data)
                }
                .ignoresSafeArea()
            }
            .photosPicker(isPresented:$pickingPhoto,selection:$pickedPhoto,matching:.images)
            .onChange(of:pickedPhoto) {_,photo in
                guard let photo else {return}
                let workspace=model.workspaceID,chat=model.selectedChatID
                loadingAttachment=true;attachmentError=""
                Task {
                    defer {loadingAttachment=false;pickedPhoto=nil}
                    let data = try? await photo.loadTransferable(type:Data.self)
                    guard workspace==model.workspaceID,chat.isEmpty || chat==model.selectedChatID else {return}
                    guard let data else {attachmentError="无法读取照片。";return}
                    let ext=photo.supportedContentTypes.first?.preferredFilenameExtension ?? "jpg"
                    setAttachment(name:"Photo."+ext,data:data)
                }
            }
            .fileImporter(isPresented:$pickingFile,allowedContentTypes:[.item]) { result in
                do {
                    let url=try result.get(),access=url.startAccessingSecurityScopedResource()
                    defer {if access {url.stopAccessingSecurityScopedResource()}}
                    guard let size=try url.resourceValues(forKeys:[.fileSizeKey]).fileSize,(1...10*1024*1024).contains(size) else {
                        attachmentError="聊天附件须为非空文件，最多 10 MB。";return
                    }
                    setAttachment(name:url.lastPathComponent,data:try Data(contentsOf:url))
                } catch {attachmentError="无法读取文件。"}
            }
            .onChange(of:model.selectedChatID) {old,_ in
                if !old.isEmpty {composing=false;composerRevision+=1}
            }
            .toolbar {
                ToolbarItem(placement:.topBarLeading) {Button("会话") {choosing=true}.disabled(sending)}
                ToolbarItem(placement:.topBarTrailing) {Button {Task {await model.createChat()}} label:{Image(systemName:"square.and.pencil")}.accessibilityLabel("新建聊天").disabled(!model.online || model.chatSubmitting || sending)}
            }
            .sheet(isPresented:$choosing) {
                NavigationStack {
                    List {
                        ForEach(model.chatThreads) {chat in Button {model.selectChat(chat.id);choosing=false} label:{HStack {Text(chat.title);Spacer();if chat.running {ProgressView()};if chat.id==model.selectedChatID {Image(systemName:"checkmark")}}}}
                        if !model.currentChatQueue.isEmpty {
                            Section("手机待发送") {ForEach(model.currentChatQueue) {pending in VStack(alignment:.leading) {Text(pending.text).lineLimit(3);if !pending.lastError.isEmpty {Text(PhoneLanguage.text(pending.lastError,in:interfaceLocale)).font(.caption).foregroundStyle(.orange)}}}}
                        }
                    }.navigationTitle(PhoneLanguage.text("电脑上的会话",in:interfaceLocale)).toolbar {Button("关闭") {choosing=false}}.refreshable {await model.syncChatList()}
                }
            }
            .alert("移除待发消息？",isPresented:$confirmingRemoval) {Button("移除",role:.destructive) {if let pending=removing {model.removeQueuedChatMessage(pending.id)}};Button("取消",role:.cancel) {}} message:{Text("这条尚未发送的内容将从手机移除。")}
            .task(id:model.workspaceID+model.selectedChatID+String(model.online)+model.deviceGeneration.uuidString) {
                guard model.online else {return};var tick=0
                while !Task.isCancelled && model.online {
                    if tick%5==0 {await model.syncChatList()}
                    await model.flushChatMessages();await model.syncSelectedChat()
                    tick+=1;try? await Task.sleep(nanoseconds:model.chatSnapshot?.running==true ? 1_500_000_000:3_000_000_000)
                }
            }
        }
    }
    private func openCamera() {
        guard UIImagePickerController.isSourceTypeAvailable(.camera) else {
            attachmentError = "此设备无法使用相机。"
            return
        }
        let target = CameraTarget(workspace:model.workspaceID,chat:model.selectedChatID)
        attachmentError = ""
        dismissKeyboard += 1
        loadingAttachment = true
        Task {
            defer { loadingAttachment = false }
            let granted = await AVCaptureDevice.requestAccess(for: .video)
            guard target.matches(model) else { return }
            if granted {
                cameraTarget = target
            } else {
                attachmentError = "未获相机权限。请在系统设置中允许知识秘书使用相机。"
            }
        }
    }

    private func setAttachment(name:String,data:Data) {
        guard (1...10*1024*1024).contains(data.count) else {attachmentError="聊天附件须为非空文件，最多 10 MB。";return}
        attachmentError="";model.chatAttachment=ChatAttachment(name:name,data:data)
    }
}

private struct ChatCamera: UIViewControllerRepresentable {
    enum Result {
        case cancelled
        case captured(UIImage?)
    }

    let onFinish: (Result) -> Void

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.cameraCaptureMode = .photo
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ picker: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(onFinish: onFinish) }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onFinish: (Result) -> Void

        init(onFinish: @escaping (Result) -> Void) { self.onFinish = onFinish }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            onFinish(.cancelled)
        }

        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            onFinish(.captured(info[.originalImage] as? UIImage))
        }
    }
}

private struct ChatComposer: UIViewRepresentable {
    @Environment(\.locale) private var interfaceLocale
    @Binding var text: String
    @Binding var composing: Bool
    let dismissKeyboard: Int
    private let placeholder = "发消息，继续这段对话…"

    // UIKit owns the marked range until the keyboard commits its candidate.
    final class Editor: UITextView {
        var onInput: (() -> Void)?
        lazy var keyboardDone = UIBarButtonItem(
            title: nil, style: .done, target: self, action: #selector(hideKeyboard)
        )
        private var changingMark = 0
        var isComposing: Bool { changingMark > 0 || markedTextRange != nil }

        @objc func hideKeyboard() {
            guard isFirstResponder else { return }
            if markedTextRange != nil { unmarkText() }
            resignFirstResponder()
        }

        override func setMarkedText(_ markedText: String?, selectedRange: NSRange) {
            changingMark += 1
            super.setMarkedText(markedText, selectedRange: selectedRange)
            changingMark -= 1
            onInput?()
        }

        override func unmarkText() {
            changingMark += 1
            super.unmarkText()
            changingMark -= 1
            onInput?()
        }
    }

    final class Coordinator: NSObject, UITextViewDelegate {
        var parent: ChatComposer
        init(_ parent: ChatComposer) { self.parent = parent }

        func publish(_ editor: Editor) {
            let marked = editor.isComposing
            if parent.composing != marked { parent.composing = marked }
            if !marked, parent.text != editor.text { parent.text = editor.text }
        }

        func textViewDidChange(_ textView: UITextView) {
            if let editor = textView as? Editor { publish(editor) }
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> Editor {
        let editor = Editor()
        editor.font = .preferredFont(forTextStyle:.body)
        editor.adjustsFontForContentSizeCategory = true
        editor.textContainerInset = UIEdgeInsets(top:10,left:12,bottom:10,right:12)
        editor.textContainer.lineFragmentPadding = 0
        editor.backgroundColor = .secondarySystemBackground
        editor.layer.borderWidth = 1
        editor.layer.cornerRadius = 8
        editor.accessibilityIdentifier = "chat-input"
        editor.accessibilityLabel = placeholder
        editor.keyboardDone.accessibilityIdentifier = "chat-dismiss-keyboard"
        let keyboardToolbar = UIToolbar()
        keyboardToolbar.tintColor = UIColor(Color.accentColor)
        keyboardToolbar.items = [UIBarButtonItem(systemItem:.flexibleSpace), editor.keyboardDone]
        keyboardToolbar.sizeToFit()
        editor.inputAccessoryView = keyboardToolbar
        editor.delegate = context.coordinator
        editor.onInput = { [weak editor, weak coordinator = context.coordinator] in
            if let editor { coordinator?.publish(editor) }
        }
        return editor
    }

    func updateUIView(_ editor: Editor, context: Context) {
        let shouldDismiss = context.coordinator.parent.dismissKeyboard != dismissKeyboard
        context.coordinator.parent = self
        editor.layer.borderColor = UIColor.separator.resolvedColor(with:editor.traitCollection).cgColor
        editor.keyboardDone.title = PhoneLanguage.text("完成",in:interfaceLocale)
        if !editor.isComposing, editor.text != text { editor.text = text }
        if shouldDismiss {
            // Ending editing can publish a committed IME draft through the delegate.
            Task { @MainActor [weak editor] in editor?.hideKeyboard() }
        }
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView editor: Editor, context: Context) -> CGSize? {
        guard let width=proposal.width, width>0 else {return nil}
        let lineHeight=editor.font?.lineHeight ?? 22
        let inset=editor.textContainerInset.top+editor.textContainerInset.bottom
        let full=editor.sizeThatFits(CGSize(width:width,height:.greatestFiniteMagnitude)).height
        return CGSize(width:width,height:ceil(min(max(full,lineHeight*2+inset),lineHeight*5+inset)))
    }
}
struct LibraryView: View {
    @Environment(\.locale) private var interfaceLocale
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
                    Section { HStack { ProgressView();Text(LocalizedStringKey(model.libraryUpdatedAt == nil ? "正在加载资料…":"正在后台更新资料…")) }.font(.footnote).foregroundStyle(.secondary) }
                }
                if !model.libraryMessage.isEmpty { Section { Text(PhoneLanguage.text(model.libraryMessage,in:interfaceLocale)).font(.footnote).foregroundStyle(.secondary) } }
                if !model.error.isEmpty { Section { Text(PhoneLanguage.text(model.error,in:interfaceLocale)).foregroundStyle(.orange) } }
                if !model.answer.isEmpty { Section("回答") { Text(model.answer).textSelection(.enabled);ForEach(model.sources) { item in NavigationLink(item.title) { DetailView(record:item,workspace:model.workspaceID) } } } }
                Section("资料") { ForEach(model.records) { item in NavigationLink { DetailView(record:item,workspace:model.workspaceID) } label: { VStack(alignment:.leading,spacing:5) { Text(item.title);if !item.summary.isEmpty { Text(item.summary).font(.caption).foregroundStyle(.secondary).lineLimit(2) } } } } }
            }.navigationTitle(PhoneLanguage.text("知识库",in:interfaceLocale))
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
    let workspace:String
    @State private var image:UIImage?
    @State private var failed=false
    @State private var retry=0
    var body:some View {
        VStack(alignment:.leading,spacing:8) {
            if let image {
                Image(uiImage:image).resizable().scaledToFit().frame(maxWidth:.infinity,maxHeight:280)
                    .clipShape(RoundedRectangle(cornerRadius:10)).accessibilityLabel("图片预览 · \(file.name)")
            } else if failed {
                HStack {Text("图片预览暂未加载").font(.footnote).foregroundStyle(.secondary);Button("重试") {retry+=1}}
            } else {
                HStack {ProgressView();Text("正在加载图片预览…").font(.footnote).foregroundStyle(.secondary)}.frame(maxWidth:.infinity,minHeight:100)
            }
        }.task(id:file.version+String(model.online)+String(retry)) {
            guard image == nil else {return};failed=false
            do {
                let url=try await model.downloadAttachment(file.previewPath,name:file.name+".preview.jpg",version:file.version,workspace:workspace) {_,_ in}
                guard !Task.isCancelled else {return}
                guard let value=UIImage(contentsOfFile:url.path) else {failed=true;return};image=value
            } catch {if !Task.isCancelled {failed=true}}
        }
    }
}
struct DetailView: View {
    @Environment(\.locale) private var interfaceLocale
    @EnvironmentObject var model: Companion
    let record:Record
    let workspace:String
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
                                    InlineAttachmentImage(file:file,workspace:workspace)
                                }
                                Button {fileTask=Task {await open(file)}} label:{Label("打开原件 · \(file.name)",systemImage:"doc")}.disabled(working || !model.online)
                                if file.size>0 {Text(ByteCountFormatter.string(fromByteCount:file.size,countStyle:.file)+(!file.previewPath.isEmpty ? PhoneLanguage.text(" · 图片预览更快，原件保持完整",in:interfaceLocale):"")).font(.caption).foregroundStyle(.secondary)}
                            }
                        }
                    }.frame(maxWidth:.infinity,alignment:.leading).padding().background(.quaternary,in:RoundedRectangle(cornerRadius:14))
                }
                if fileTask != nil {
                    VStack(alignment:.leading,spacing:8) {
                        Text(PhoneLanguage.text(operationLabel,in:interfaceLocale)).font(.subheadline)
                        if downloadTotal>0 {
                            ProgressView(value:Double(downloadDone),total:Double(max(downloadTotal,1)))
                            Text(ByteCountFormatter.string(fromByteCount:downloadDone,countStyle:.file)+" / "+ByteCountFormatter.string(fromByteCount:downloadTotal,countStyle:.file)).font(.caption).foregroundStyle(.secondary)
                        } else {ProgressView()}
                        Button("取消下载") {fileTask?.cancel()}
                    }
                }
                if !loaded {Text(record.title).font(.title2.bold());Text(record.summary).textSelection(.enabled);if working {ProgressView("正在加载资料详情…")}}
                if !error.isEmpty {Text(PhoneLanguage.text(error,in:interfaceLocale)).foregroundStyle(.orange)}
                if !notice.isEmpty {Text(PhoneLanguage.text(notice,in:interfaceLocale)).foregroundStyle(.secondary)}
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
                                        .buttonStyle(.plain).accessibilityLabel("删除标签 \(tag)").accessibilityIdentifier("tag-remove-"+tag)
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
        }.navigationTitle(PhoneLanguage.text("资料详情",in:interfaceLocale)).navigationBarTitleDisplayMode(.inline)
        .toolbar {Button("重新加载") {Task {await load()}}.disabled(working)}
        .task {await load()}
        .sheet(item:$preview,onDismiss:{clearPreview()}) {value in
            NavigationStack {
                OriginalPreview(url:value.url).navigationTitle(PhoneLanguage.text(value.lightweight ? "图片预览（非原件）":"完整原件",in:interfaceLocale)).navigationBarTitleDisplayMode(.inline)
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
        } message: {Text("确定删除标签“\(deletingTag ?? "")”？")}
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
        do {apply(try await model.detail(record.id,workspace:workspace));error=""}
        catch {self.error=error.localizedDescription}
    }
    private func save() async {
        working=true;defer {working=false};notice=""
        do {apply(try await model.saveMetadata(record.id,title:title,tags:tags,updated:updated,workspace:workspace));error="";notice="标题已保存"}
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
            apply(try await model.saveMetadata(record.id,title:savedTitle,tags:values,updated:updated,workspace:workspace))
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
            apply(try await model.addAttachment(record.id,name:pendingName,data:data,updated:updated,requestID:attachmentRequestID,workspace:workspace))
            if titleChanged {title=draftTitle};if tagsChanged {tags=draftTags}
            pendingData=nil;photo=nil;error="";notice="附件已添加"
        } catch {self.error=error.localizedDescription}
    }
    private func open(_ file:PhoneAttachment,lightweight:Bool=false) async {
        working=true;downloadDone=0;downloadTotal=0
        operationLabel=lightweight ? "正在加载图片预览（非原件）…":"正在下载完整原件…"
        defer {working=false;fileTask=nil}
        do {
            let url=try await model.downloadAttachment(lightweight ? file.previewPath:file.path,name:lightweight ? file.name+".preview.jpg":file.name,version:file.version,workspace:workspace) {done,total in
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
    @Environment(\.locale) private var interfaceLocale
    @EnvironmentObject var model: Companion
    var addComputer: () -> Void
    @State private var removing:PairedMac?
    @State private var renaming:PairedMac?
    @State private var nickname=""
    @State private var showRemove=false
    @State private var showRename=false
    @State private var computerEditMode: EditMode = .inactive
    var body: some View {
        NavigationStack {
            Form {
                if model.paired != nil {
                    Section("当前电脑") {ConnectionBanner();Button("重新连接") {Task {await model.connect()}}.disabled(model.pairingInFlight)}
                }
                if model.pairingInFlight {Section("添加电脑") {if model.waiting {Text(model.code).font(.largeTitle.monospacedDigit()).tracking(8);Text(PhoneLanguage.text(model.status,in:interfaceLocale))};ProgressView();Button("取消添加电脑") {model.cancelPairing()}}}
                Section {
                    ForEach(model.computers.computers) {pair in
                        VStack(alignment:.leading,spacing:8) {
                            HStack {Text(pair.displayName).font(.headline);Spacer();if pair.id==model.paired?.id {Label("当前",systemImage:"checkmark.circle.fill").font(.caption).foregroundStyle(.green)}}
                            if pair.displayName != pair.info.name {Text(pair.info.name).font(.caption).foregroundStyle(.secondary)}
                            if model.pendingCount(pair)>0 {Text("此电脑有 \(model.pendingCount(pair)) 条待发送内容").font(.caption).foregroundStyle(.secondary)}
                            if !computerEditMode.isEditing {
                                HStack {
                                    if pair.id != model.paired?.id {Button("使用这台电脑") {Task {await model.selectComputer(pair.id)}}.accessibilityIdentifier("computer-select-"+pair.info.server_id)}
                                    Button("备注名") {renaming=pair;nickname=pair.nickname ?? "";showRename=true}.accessibilityIdentifier("computer-rename-"+pair.info.server_id)
                                    Spacer()
                                    Button("移除",role:.destructive) {removing=pair;showRemove=true}.accessibilityIdentifier("computer-remove-"+pair.info.server_id)
                                }.buttonStyle(.borderless).disabled(!model.canChangeComputer)
                            }
                        }.padding(.vertical,4)
                    }.onMove(perform: model.moveComputers)
                    if !computerEditMode.isEditing {
                        Button {addComputer()} label:{Label("添加电脑",systemImage:"qrcode.viewfinder")}.disabled(!model.canChangeComputer)
                    }
                } header:{
                    HStack {
                        Text("我的电脑 · \(model.computers.computers.count)")
                        Spacer()
                        if model.computers.computers.count > 1 {
                            Button(LocalizedStringKey(computerEditMode.isEditing ? "完成" : "排序")) {
                                withAnimation {computerEditMode = computerEditMode.isEditing ? .inactive : .active}
                            }.accessibilityIdentifier("computer-order")
                        }
                    }
                } footer:{
                    if computerEditMode.isEditing {
                        Text("拖动右侧的手柄调整顺序。")
                    } else {
                        Text("分别扫码授权后即可切换，无需重新绑定。每台电脑最多绑定 10 部手机，手机最多保存 10 台电脑。")
                    }
                }
                if !model.canChangeComputer {Section {Text(LocalizedStringKey(model.pairingInFlight ? "正在配对，请先完成或取消配对":"正在提交内容，完成后即可切换电脑")).font(.footnote).foregroundStyle(.secondary)}}
                if !model.error.isEmpty {Section {Text(PhoneLanguage.text(model.error,in:interfaceLocale)).foregroundStyle(.orange)}}
                Section("语言") { PhoneLanguagePicker() }
                Section { Button("隐私与 AI") { model.showPrivacy = true } }
                Section {
                    Text("每台电脑的知识库、聊天记录和手机待发送内容分别保存。切换不会同步或合并电脑资料。连接需要电脑开机运行，且网络或附近连接可达。").font(.callout).foregroundStyle(.secondary)
                }
                if model.paired != nil && !computerEditMode.isEditing {
                    Section {Button("解除手机上的配对",role:.destructive) {removing=model.paired;showRemove=true}.disabled(!model.canChangeComputer)}
                }
            }.navigationTitle(PhoneLanguage.text("连接",in:interfaceLocale))
            .environment(\.editMode, $computerEditMode)
            .onChange(of: model.computers.computers.count) {_, count in
                if count < 2 {computerEditMode = .inactive}
            }
            .alert("电脑备注名",isPresented:$showRename) {
                TextField("例如：公司电脑、家里电脑",text:$nickname)
                Button("保存") {if let pair=renaming {model.renameComputer(pair.id,name:nickname)}}
                Button("取消",role:.cancel) {}
            } message:{Text("只修改这部手机上的显示名称。")}
            .confirmationDialog("移除 \(removing?.displayName ?? PhoneLanguage.text("这台电脑",in:interfaceLocale)) 的配对？",isPresented:$showRemove,titleVisibility:.visible) {
                Button("解除配对",role:.destructive) {if let pair=removing {model.removeComputer(pair.id)}}
            } message:{Text("仅移除这台电脑的手机凭据。待发送内容和缓存保留，重新配对原电脑后可继续使用；电脑端可另外撤销此手机的访问权限。")}
        }
    }
}
struct PrivacyView: View {
    @Environment(\.locale) private var interfaceLocale
    @EnvironmentObject private var companion: Companion
    @Environment(\.dismiss) private var dismiss
    @State private var permission: ModelPrivacy?
    @State private var message = ""
    @State private var saving = false

    var body: some View {
        NavigationStack {
            Form {
                if let pair = companion.paired {
                    Section {
                        if let permission {
                            LabeledContent("模型服务", value: permission.destination)
                            if !permission.model.isEmpty { LabeledContent("模型", value: permission.model) }
                            if !permission.fingerprint.isEmpty {
                                if permission.approved {
                                    Button("撤回授权", role: .destructive) { update(false, permission) }.disabled(saving)
                                } else {
                                    Button("同意并允许向此服务发送") { update(true, permission) }.disabled(saving)
                                }
                            }
                        } else if !companion.privacySupported {
                            Text("连接并更新电脑端后，可以查看及管理模型授权。")
                        } else if message.isEmpty {
                            ProgressView()
                        }
                        if !message.isEmpty { Text(PhoneLanguage.text(message,in:interfaceLocale)).foregroundStyle(.secondary) }
                    } header: {
                        Text("AI 问答 · \(pair.displayName)")
                    } footer: {
                        Text("授权后，电脑可能向所示服务发送问题、聊天附件、相关聊天记录、知识库摘录或图片，包括手机待发送的问答。授权只适用于这台电脑和当前模型服务。撤回后，尚未发出的模型请求将被拦截，已发出的内容无法收回。")
                    }
                    if let permission, let approved = permission.summaryApproved, !permission.fingerprint.isEmpty {
                        Section("手机归档自动摘要") {
                            LabeledContent("模型服务", value: permission.destination)
                            if !permission.model.isEmpty { LabeledContent("模型", value: permission.model) }
                            Text("开启后，电脑可把新上传的文字、文件摘录或图片发送给这个服务生成摘要。这项授权与问答分开，可以随时关闭。")
                            if !permission.desktopAutoSummary { Text("电脑端的自动总结目前已关闭。").foregroundStyle(.secondary) }
                            Button(LocalizedStringKey(approved ? "关闭手机自动摘要" : "同意并开启自动摘要")) {
                                update(!approved, permission, summary:true)
                            }.disabled(saving)
                        }
                    }
                }
                Section("数据和权限") {
                    Text("相机用于扫描电脑的配对码，局域网和蓝牙用于发现并连接附近的电脑。手机将你提交的资料和问题发给所选电脑。配对凭据保存在钥匙串，待发送内容和近期缓存保存在手机。")
                    Text("手机归档默认只存入电脑知识库。可单独授权自动摘要；如果启用了本机语义索引，电脑会使用配置的本机嵌入服务。演示模式退出时清除演示改动。")
                    Text("你可以在 iOS 设置管理权限，在电脑端移除此手机的访问权限，或在这里撤回模型授权。")
                }
            }
            .navigationTitle(PhoneLanguage.text("隐私与 AI",in:interfaceLocale))
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("关闭") { dismiss() } } }
            .task(id: "\(companion.deviceGeneration)-\(companion.privacySupported)-\(companion.online)") { await load() }
        }
    }

    private func load() async {
        permission = nil
        message = ""
        guard companion.privacySupported, companion.online else {
            if companion.privacySupported { message = "先连接电脑，再管理模型授权。" }
            return
        }
        do { permission = try await companion.modelPrivacy() }
        catch is CancellationError {}
        catch { message = error.localizedDescription }
    }

    private func update(_ approved: Bool, _ reviewed: ModelPrivacy, summary: Bool = false) {
        let workspace = companion.workspaceID
        saving = true
        message = ""
        Task {
            defer { saving = false }
            do {
                permission = try await companion.setModelPrivacy(approved, fingerprint: reviewed.fingerprint, workspace: workspace, summary:summary)
                if !summary { message = approved ? "已授权。返回后可继续发送问答。" : "已撤回授权。" }
            } catch is CancellationError {
            } catch {
                await load()
                message = error.localizedDescription
            }
        }
    }
}
struct ScannerView: UIViewControllerRepresentable {
    @Environment(\.locale) private var interfaceLocale
    var scanned: (String, @escaping (String) -> Void) -> Void
    var cancelled: () -> Void
    func makeUIViewController(context: Context) -> ScannerController {
        let controller = ScannerController();controller.interfaceLocale = interfaceLocale;controller.scanned = scanned;controller.cancelled = cancelled;return controller
    }
    func updateUIViewController(_ controller: ScannerController, context: Context) {}
}
final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var interfaceLocale = Locale(identifier:PhoneLanguage.chinese)
    private func localized(_ message: String) -> String {PhoneLanguage.text(message,in:interfaceLocale)}
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
        let cancel = UIButton(type: .system);cancel.setTitle(localized("取消扫码"), for: .normal);cancel.tintColor = .white
        cancel.accessibilityIdentifier = "scanner-cancel";cancel.addTarget(self, action: #selector(cancelScan), for: .touchUpInside)
        cancel.translatesAutoresizingMaskIntoConstraints = false;view.addSubview(cancel)
        hint.text = localized("将相机对准 Mac 的手机配对二维码");hint.textColor = .white;hint.numberOfLines = 0
        hint.textAlignment = .center;hint.accessibilityIdentifier = "scanner-status"
        retry.setTitle(localized("重试扫码"), for: .normal);retry.addTarget(self, action: #selector(retryScan), for: .touchUpInside);retry.isHidden = true
        settings.setTitle(localized("打开系统设置"), for: .normal);settings.addTarget(self, action: #selector(openSettings), for: .touchUpInside);settings.isHidden = true
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
        retry.isHidden = true;hint.text = localized("将相机对准 Mac 的手机配对二维码")
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
    private func showError(_ message: String) { guard visible else { return };hint.text = localized(message);retry.isHidden = false }
    @objc private func retryScan() { processing = false;prepareCamera() }
    @objc private func cancelScan() { cancelled?() }
    @objc private func openSettings() { if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) } }
    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard visible, !processing else { return }
        let values = metadataObjects.compactMap { ($0 as? AVMetadataMachineReadableCodeObject)?.stringValue }
        guard !values.isEmpty else { return }
        guard let value = values.first(where: { (try? PairInfo.pairingCode($0)) != nil }) else { hint.text = localized(PairingCodeError.invalid.localizedDescription);return }
        processing = true;retry.isHidden = true;hint.text = localized("已识别配对码，正在检查局域网并连接 Mac…")
        queue.async { self.capture.stopRunning() }
        scanned?(value, { [weak self] message in
            guard let self, self.visible else { return };self.showError(message)
        })
    }
}
