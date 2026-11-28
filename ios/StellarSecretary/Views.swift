import SwiftUI
import PhotosUI
import AVFoundation
import Vision
import QuickLook
import UniformTypeIdentifiers
import CryptoKit

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
                    if url.isFileURL {
                        model.selectedTab = "archive"
                        guard model.paired != nil else { model.error = "请先配对电脑"; return }
                        importCaptureFile(url, into: model, external: true)
                        return
                    }
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
private let attachmentLimit = "附件最多 8 个，合计最多 10 MB。"

private func appendAttachment(_ file: ChatAttachment,to files:inout [ChatAttachment]) -> Bool {
    if files.contains(where: { $0.data == file.data }) { return true }
    guard ChatAttachment.fits(files+[file]) else { return false }
    files.append(file)
    return true
}

@MainActor
private func importCaptureFile(_ url: URL, into model: Companion, external: Bool = false) {
    let access = url.startAccessingSecurityScopedResource()
    defer { if access { url.stopAccessingSecurityScopedResource() } }
    let inbox = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("Inbox").resolvingSymlinksInPath().standardizedFileURL.path
    let inboxCopy = url.resolvingSymlinksInPath().standardizedFileURL.deletingLastPathComponent().path == inbox
    do {
        guard !external || access || inboxCopy else { model.error = "无法读取文件"; return }
        let values = try url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey, .isSymbolicLinkKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true else { model.error = "无法读取文件"; return }
        defer { if external && inboxCopy { try? FileManager.default.removeItem(at: url) } }
        guard let size = values.fileSize, (1...ChatAttachment.maxBytes).contains(size) else {
            model.error = attachmentLimit
            return
        }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let data = try handle.read(upToCount: ChatAttachment.maxBytes + 1) ?? Data()
        guard data.count == size else { model.error = "无法读取文件"; return }
        let attachment = ChatAttachment(name: url.lastPathComponent, data: data)
        let added = appendAttachment(attachment, to: &model.captureEditor.files)
        model.error = added ? "" : attachmentLimit
        if external && added { pairingDiagnostic("open-document-staged") }
    } catch {
        model.error = "无法读取文件"
    }
}

private func loadPhotos(_ photos:[PhotosPickerItem],addingTo existing:[ChatAttachment]) async -> ([ChatAttachment],String) {
    var files = existing
    var error = ""
    for photo in photos {
        if Task.isCancelled { break }
        guard let data = try? await photo.loadTransferable(type:Data.self), !data.isEmpty else {
            error = "无法读取照片。"
            continue
        }
        let ext = photo.supportedContentTypes.first?.preferredFilenameExtension ?? "jpg"
        let names = Set(files.map(\.name))
        var name = "Photo."+ext
        var suffix = 2
        while names.contains(name) { name = "Photo-\(suffix)."+ext;suffix+=1 }
        if !appendAttachment(ChatAttachment(name:name,data:data),to:&files) { error = attachmentLimit }
    }
    return (files,error)
}

private func cameraPhotoSubject(_ data: Data, locale: Locale) -> String {
    let handler = VNImageRequestHandler(data:data)
    let animals = VNRecognizeAnimalsRequest()
    let people = VNDetectHumanRectanglesRequest()
    try? handler.perform([animals,people])

    // Prefer a substantial visible subject over a background texture.
    let chinese = locale.language.languageCode?.identifier == "zh"
    var subjects: [(area:CGFloat, name:String)] = []
    for animal in animals.results ?? [] {
        guard let label = animal.labels.first, label.confidence >= 0.5 else { continue }
        let names = ["Dog":chinese ? "狗" : "Dog", "Cat":chinese ? "猫" : "Cat"]
        if let name = names[label.identifier] {
            subjects.append((animal.boundingBox.width * animal.boundingBox.height,name))
        }
    }
    for person in people.results ?? [] where person.confidence >= 0.5 {
        subjects.append((person.boundingBox.width * person.boundingBox.height,chinese ? "人物" : "Person"))
    }
    if let subject = subjects.max(by:{ $0.area < $1.area }), subject.area >= 0.04 { return subject.name }

    let classifier = VNClassifyImageRequest()
    try? handler.perform([classifier])
    let generic: Set<String> = ["material","structure","object","textile","tool","equipment","furniture","organism"]
    for result in classifier.results ?? [] where result.confidence >= 0.65 {
        let label = String(result.identifier.split(separator:",").first ?? "")
        if !label.isEmpty && !generic.contains(label) { return label.replacingOccurrences(of:"_",with:" ") }
    }
    return ""
}

private func namedCameraFiles(_ files: [ChatAttachment], note: String, locale: Locale) -> [ChatAttachment] {
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier:"en_US_POSIX")
    formatter.dateFormat = "yyyy-MM-dd_HHmmss"
    let separators = CharacterSet(charactersIn:"/\\:*?\"<>|").union(.controlCharacters)
    func stem(_ text: String) -> String {
        let clean = text.components(separatedBy:separators).joined(separator:" ")
            .split(whereSeparator: { $0.isWhitespace }).joined(separator:" ")
            .trimmingCharacters(in:CharacterSet(charactersIn:" ."))
        return String(clean.unicodeScalars.prefix(40))
    }
    let subject = stem(String(note.split(whereSeparator: { $0.isNewline }).first ?? ""))
    var used = Set(files.filter { $0.capturedAt == nil }.map { $0.name.lowercased() })
    var sequence = 0
    return files.map { file in
        guard let date = file.capturedAt else { return file }
        var title = subject
        if title.isEmpty {
            title = stem(cameraPhotoSubject(file.data,locale:locale))
        }
        if title.isEmpty { title = "Photo-" + formatter.string(from:date) }
        var name: String
        repeat {
            sequence += 1
            name = title + String(format:"-%02d.jpg",sequence)
        } while !used.insert(name.lowercased()).inserted
        return ChatAttachment(name:name,data:file.data)
    }
}

struct CaptureView: View {
    @Environment(\.locale) private var interfaceLocale
    @EnvironmentObject var model: Companion
    @Environment(\.scenePhase) private var scene
    private var text: String {model.captureEditor.text}
    @State private var photos: [PhotosPickerItem] = []
    @State private var loadingPhotos = false
    @State private var importing = false
    @State private var sharedFiles: [URL] = []
    @State private var showingSummarySettings = false
    @State private var cameraOpen = false
    @State private var saving = false
    @FocusState private var editing: Bool
    var body: some View {
        NavigationStack {
            Form {
                Section { ConnectionBanner() }
                if !sharedFiles.isEmpty {
                    Section("选择文件，合为一份归档") {
                        ForEach(sharedFiles, id: \.self) { url in
                            VStack(alignment: .leading) {
                                Button {
                                    if model.captureEditor.inboxSelection.contains(url) {
                                        model.captureEditor.inboxSelection.removeAll { $0 == url }
                                    } else {
                                        model.captureEditor.inboxSelection.append(url)
                                    }
                                } label: {
                                    Label(url.lastPathComponent, systemImage: model.captureEditor.inboxSelection.contains(url) ? "checkmark.circle.fill" : "circle")
                                }.disabled(saving)
                            }.swipeActions {
                                Button("删除", role: .destructive) {
                                    do {
                                        try FileManager.default.removeItem(at: url.deletingLastPathComponent())
                                        sharedFiles.removeAll { $0 == url }
                                        model.captureEditor.inboxSelection.removeAll { $0 == url }
                                    } catch { model.error = "无法移除待发送内容" }
                                }.disabled(saving)
                            }
                        }
                    }
                }
                Section("链接、笔记或安排") { TextEditor(text:$model.captureEditor.text).focused($editing).frame(minHeight:150).accessibilityLabel("归档内容") }
                Section {
                    Button {
                        editing = false
                        model.prepareAttachmentTransfer()
                        cameraOpen = true
                    } label: { Label("拍照",systemImage:"camera") }
                    .accessibilityIdentifier("capture-camera")
                    .disabled(loadingPhotos || saving || remainingCameraSlots <= 0 || remainingCameraBytes <= 0)
                    PhotosPicker(selection:$photos,maxSelectionCount:ChatAttachment.maxCount,selectionBehavior:.ordered,matching:.images,preferredItemEncoding:.current) {
                        Label("添加截图或照片",systemImage:"photo")
                    }.disabled(loadingPhotos || saving)
                    Button { importing = true } label: { Label("添加文件",systemImage:"paperclip") }.disabled(loadingPhotos || saving)
                    ForEach(Array(model.captureEditor.files.enumerated()),id:\.offset) { index,file in
                        HStack {
                            Text(file.name);Spacer()
                            Button("移除") { model.captureEditor.files.remove(at:index) }.disabled(loadingPhotos || saving)
                        }
                    }
                    if model.captureEditor.files.contains(where: { $0.capturedAt != nil }) {
                        Toggle("自动重命名拍摄的照片",isOn:$model.captureEditor.renameCameraPhotos)
                            .disabled(saving).accessibilityIdentifier("capture-rename-photos")
                    }
                    if loadingPhotos { ProgressView("正在读取附件…") }
                    Button {
                        editing = false;saving = true
                        let workspace = model.workspaceID, note = text
                        let selected = model.captureEditor.inboxSelection
                        let attachments = model.captureEditor.files
                        let renamePhotos = model.captureEditor.renameCameraPhotos
                        Task {
                            defer { saving = false }
                            do {
                                var files = attachments
                                for url in selected {
                                    let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                                    guard files.count < ChatAttachment.maxCount, size > 0,
                                          files.reduce(0, { $0 + $1.data.count }) + size <= SharedInbox.maxBytes else {
                                        model.error = "附件最多 8 个，合计最多 10 MB。"
                                        return
                                    }
                                    files.append(ChatAttachment(name: url.lastPathComponent, data: try Data(contentsOf: url)))
                                }
                                let single = selected.count == 1 && attachments.isEmpty && note.isEmpty ? selected.first : nil
                                let requestID = single?.deletingLastPathComponent().lastPathComponent ?? UUID().uuidString
                                if renamePhotos && files.contains(where: { $0.capturedAt != nil }) {
                                    let originals = files, locale = interfaceLocale
                                    files = await Task.detached(priority:.userInitiated) {
                                        namedCameraFiles(originals,note:note,locale:locale)
                                    }.value
                                }
                                let reference = try single.map { try SharedInbox.noteReference(for: $0) }
                                guard await model.enqueue(text: note, files: files, workspace: workspace, id: requestID, noteReference: reference) else { return }
                                if workspace == model.workspaceID { model.captureEditor = CaptureEditor() }
                                for url in selected {
                                    try FileManager.default.removeItem(at: url.deletingLastPathComponent())
                                    sharedFiles.removeAll { $0 == url }
                                }
                            } catch { model.error = "无法读取或移除分享的文件" }
                        }
                    } label: {
                        Label(LocalizedStringKey(model.online ? "保存到知识库":"暂存，连接后发送"),systemImage:"tray.and.arrow.down").frame(maxWidth:.infinity)
                    }.disabled(saving || loadingPhotos || (text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && model.captureEditor.files.isEmpty && model.captureEditor.inboxSelection.isEmpty))
                } footer: { Text("只添加图片或文件也可归档。附件最多 8 个，合计最多 10 MB。") }
                Section {
                    Button("手机归档自动摘要") { showingSummarySettings = true }
                }
                if !model.error.isEmpty { Section { Text(PhoneLanguage.text(model.error,in:interfaceLocale)).foregroundStyle(.orange) } }
                if !model.currentDrafts.isEmpty {
                    Section("待发送 · \(model.currentDrafts.count)") {
                        ForEach(model.currentDrafts) { draft in
                            VStack(alignment:.leading) {
                                Text(draft.attachmentBatch?.map(\.name).joined(separator:", ") ?? draft.filename ?? draft.text).lineLimit(2)
                                    .accessibilityIdentifier("capture-outbox-"+draft.id)
                                if model.sendingDraftID==draft.id, let route=model.captureUploadTransport {
                                    Text(LocalizedStringKey(route=="direct" ? "网络直连" : route=="bluetooth" ? "蓝牙中继" : "附近 Wi-Fi 中继"))
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                if let progress=model.uploadProgress[draft.id] {
                                    AttachmentUploadProgress(progress:progress)
                                } else {
                                    let status = draft.lastError ?? (model.sendingDraftID==draft.id ? "正在上传" : model.captureRetryAfter[draft.id] != nil ? "发送中断，将自动重试。" : "待发送")
                                    Text(PhoneLanguage.text(status,in:interfaceLocale)).font(.caption).foregroundStyle(.secondary)
                                }
                                if draft.lastError != nil || model.captureRetryAfter[draft.id] != nil {
                                    Button("重新发送") { Task { await model.retryDraft(draft.id) } }
                                        .buttonStyle(.borderless).disabled(!model.online || model.sendingDraftID != nil)
                                        .accessibilityIdentifier("capture-retry-"+draft.id)
                                }
                            }
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
            }.disabled(saving).navigationTitle(PhoneLanguage.text("随手归档",in:interfaceLocale)).scrollDismissesKeyboard(.interactively).toolbar { ToolbarItemGroup(placement:.keyboard) { Spacer();Button("完成") { editing = false } } }
            .fullScreenCover(isPresented: $cameraOpen) {
                CaptureCameraBatch(slots:remainingCameraSlots, bytes:remainingCameraBytes) { batch in
                    guard batch.count <= remainingCameraSlots,
                          batch.reduce(0, { $0 + $1.data.count }) <= remainingCameraBytes else { return false }
                    model.prepareAttachmentTransfer()
                    model.captureEditor.files.append(contentsOf:batch)
                    model.error = ""
                    return true
                }
            }
            .sheet(isPresented: $showingSummarySettings) { PrivacyView() }
            .task(id:"\(scene)-\(model.selectedTab)") {
                guard scene == .active, model.selectedTab == "archive" else { return }
                do { sharedFiles = try SharedInbox.files() } catch { model.error = "无法读取文件" }
            }
            .task(id:"\(model.workspaceID)-\(model.selectedTab)-\(model.online)-\(model.captureStatusAvailable)-\(scene)") {
                guard model.selectedTab == "archive", model.online, model.captureStatusAvailable, scene == .active else {return}
                while !Task.isCancelled {
                    await model.refreshCaptureReceipts()
                    let processing = model.captureReceipts.contains {$0.stage == "processing"}
                    try? await Task.sleep(for:.seconds(processing ? 3 : 10))
                }
            }
            .onChange(of:photos) { _,selection in
                guard !selection.isEmpty else { return }
                model.prepareAttachmentTransfer()
                let id=model.workspaceID,existing=model.captureEditor.files
                loadingPhotos=true
                Task {
                    defer { loadingPhotos=false;photos=[] }
                    let (files,error) = await loadPhotos(selection,addingTo:existing)
                    guard id==model.workspaceID else {return}
                    model.captureEditor.files=files;model.error=error
                }
            }
            .fileImporter(isPresented:$importing,allowedContentTypes:[.item]) { result in
                do {
                    importCaptureFile(try result.get(), into: model)
                }
                catch { model.error = "无法读取文件" }
            }
        }
    }
    private var remainingCameraSlots: Int {
        ChatAttachment.maxCount - model.captureEditor.files.count - model.captureEditor.inboxSelection.count
    }
    private var remainingCameraBytes: Int {
        var used = model.captureEditor.files.reduce(0) { $0 + $1.data.count }
        for url in model.captureEditor.inboxSelection {
            guard let size = try? url.resourceValues(forKeys:[.fileSizeKey]).fileSize else { return 0 }
            used += size
        }
        return ChatAttachment.maxBytes - used
    }

}

private struct AttachmentUploadProgress: View {
    let progress: UploadProgress
    var body: some View {
        VStack(alignment:.leading,spacing:4) {
            ProgressView(value:Double(progress.received),total:Double(progress.total))
            if progress.received==progress.total {
                Text("电脑已收齐，正在处理…")
            } else {
                let received=ByteCountFormatter.string(fromByteCount:progress.received,countStyle:.file)
                let total=ByteCountFormatter.string(fromByteCount:progress.total,countStyle:.file)
                Text(verbatim:received+" / "+total)
            }
        }.font(.caption).foregroundStyle(.secondary)
    }
}

private struct AnswerEvidenceView: View {
    let evidence: AnswerEvidence
    var body: some View {
        DisclosureGroup("本次使用的资料") {
            VStack(alignment:.leading,spacing:8) {
                switch evidence.kind {
                case "local": Text("本地回复，未检索知识库。")
                case "general": Text("通用对话，未检索知识库。")
                case "archive": Text("直接读取已归档资料。")
                case "no_match": Text("没有找到相关正文。")
                case "catalog": Text("检索了资料目录。")
                case "material": Text("依据本次提交的资料。")
                default: EmptyView()
                }
                if evidence.passage_count>0 { Text("提供的资料片段 · \(evidence.passage_count)") }
                if evidence.history_turns>0 { Text("参考的对话轮次 · \(evidence.history_turns)") }
                if !evidence.conditions.isEmpty {
                    Text("本次采用的对话条件").bold()
                    ForEach(Array(evidence.conditions.enumerated()),id:\.offset) { _,value in Text(value) }
                }
                if !evidence.pdf_pages.isEmpty {
                    Text("本次提供的 PDF 页码").bold()
                    ForEach(Array(evidence.pdf_pages.enumerated()),id:\.offset) { _,pdf in Text(pdf.name+" · "+pdf.pages) }
                }
                if !evidence.excerpts.isEmpty {
                    Text("回答引用的片段").bold()
                    ForEach(Array(evidence.excerpts.enumerated()),id:\.offset) { _,excerpt in
                        Text(excerpt.title).bold();Text(excerpt.text).textSelection(.enabled)
                    }
                }
            }.frame(maxWidth:.infinity,alignment:.leading).padding(.top,6)
        }.font(.footnote)
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
    @State private var pickedPhotos:[PhotosPickerItem]=[]
    @State private var attachmentError=""
    private var messages:[ChatMessage] {model.chatSnapshot?.messages ?? []}
    private var queued:[PendingChatMessage] {
        let known=Set(messages.map(\.clientID))
        return model.currentChatQueue.filter {($0.chatID==model.selectedChatID || model.selectedChatID.isEmpty) && !known.contains($0.id)}
    }
    private func queueStatus(_ pending: PendingChatMessage) -> String {
        if !pending.lastError.isEmpty { return pending.lastError }
        if model.sendingChatID == pending.id {
            if pending.files.isEmpty { return "正在发送消息…" }
            if model.chatUploadTransport == "bluetooth" { return "正在通过蓝牙上传附件…" }
            if model.chatUploadTransport != nil { return "正在上传附件…" }
            return "正在准备上传附件…"
        }
        if !model.online { return "待发送 · 连接后由电脑处理" }
        if pending.files.count>1, !model.multiAttachmentsAvailable { return "请更新电脑端以发送多个附件。" }
        if model.chatSnapshot?.id == pending.chatID, model.chatSnapshot?.running == true {
            return "等待上一条回答完成…"
        }
        if model.chatRetryAfter[pending.id] != nil { return "发送中断，将自动重试。" }
        return "待发送…"
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
                                        ForEach(Array(message.files.enumerated()),id:\.offset) {_,name in Text(name).font(.caption).foregroundStyle(.secondary)}
                                        if message.pending || message.requestState=="running" {
                                            Text(LocalizedStringKey(stage(model.chatStage))).font(.footnote).foregroundStyle(.secondary)
                                            if !model.chatPartial.isEmpty {Text(model.chatPartial).textSelection(.enabled);Text("回答生成中").font(.caption).foregroundStyle(.secondary)}
                                            Button("停止回答") {Task {await model.stopChatAnswer(message)}}.disabled(!model.online)
                                        }
                                        ForEach(Array(message.sources.enumerated()),id:\.offset) {_,source in NavigationLink {DetailView(record:source,workspace:model.workspaceID)} label:{Label(source.title,systemImage:"doc.text").font(.footnote)}}
                                        if let evidence=message.evidence, !message.pending { AnswerEvidenceView(evidence:evidence) }
                                    }.padding(12).background(message.role=="user" ? Color.accentColor.opacity(0.12):Color.secondary.opacity(0.08),in:RoundedRectangle(cornerRadius:14)).id(message.id)
                                    if message.role != "user" {Spacer(minLength:20)}
                                }
                            }
                            ForEach(queued) {pending in
                                VStack(alignment:.leading,spacing:8) {
                                    if !pending.text.isEmpty {Text(pending.text).textSelection(.enabled)}
                                    ForEach(Array(pending.files.enumerated()),id:\.offset) {_,file in Label(file.name,systemImage:"paperclip")}
                                    Text(PhoneLanguage.text(queueStatus(pending),in:interfaceLocale)).font(.footnote).foregroundStyle(.secondary)
                                    if let progress=model.uploadProgress[pending.id] { AttachmentUploadProgress(progress:progress) }
                                    HStack {
                                        if !pending.lastError.isEmpty || model.chatRetryAfter[pending.id] != nil {
                                            Button("重新发送") {Task {await model.retryChatMessage(pending.id)}}.disabled(!model.online || model.chatSubmitting)
                                        }
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
                    if !model.chatFiles.isEmpty {
                        ScrollView {
                            VStack(spacing:8) {
                                ForEach(Array(model.chatFiles.enumerated()),id:\.offset) {index,file in
                                    HStack {
                                        Label(file.name,systemImage:"paperclip").lineLimit(1)
                                        Spacer()
                                        Button { model.chatFiles.remove(at:index) } label:{Image(systemName:"xmark.circle.fill")}
                                            .accessibilityLabel("移除聊天附件").disabled(sending || loadingAttachment)
                                    }.font(.subheadline).accessibilityIdentifier("chat-file-\(index)")
                                }
                            }
                        }.frame(maxHeight:min(CGFloat(model.chatFiles.count)*34,120))
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
                        let value=input,id=model.workspaceID,chat=model.selectedChatID,files=model.chatFiles
                        dismissKeyboard+=1;sending=true
                        Task {
                            defer {sending=false}
                            if await model.enqueueChat(value,workspace:id,chatID:chat,files:files),
                               model.workspaceID==id,(chat.isEmpty || model.selectedChatID==chat) {
                                if input==value,!composing {model.chatInput=""}
                                if model.chatFiles==files {model.chatFiles=[]}
                            }
                        }
                    }.buttonStyle(.borderedProminent).controlSize(.large).accessibilityIdentifier("chat-send")
                        .disabled(composing || sending || loadingAttachment || (input.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && model.chatFiles.isEmpty) || model.chatSubmitting)
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
            .photosPicker(isPresented:$pickingPhoto,selection:$pickedPhotos,maxSelectionCount:ChatAttachment.maxCount,selectionBehavior:.ordered,matching:.images,preferredItemEncoding:.current)
            .onChange(of:pickedPhotos) {_,selection in
                guard !selection.isEmpty else {return}
                model.prepareAttachmentTransfer()
                let workspace=model.workspaceID,chat=model.selectedChatID,existing=model.chatFiles
                loadingAttachment=true;attachmentError=""
                Task {
                    defer {loadingAttachment=false;pickedPhotos=[]}
                    let (files,error) = await loadPhotos(selection,addingTo:existing)
                    guard workspace==model.workspaceID,chat.isEmpty || chat==model.selectedChatID else {return}
                    model.chatFiles=files;attachmentError=error
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
        let file=ChatAttachment(name:name,data:data)
        attachmentError=appendAttachment(file,to:&model.chatFiles) ? "" : attachmentLimit
    }
}

private struct CaptureCameraBatch: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.locale) private var locale
    let slots: Int
    let bytes: Int
    let add: ([ChatAttachment]) -> Bool
    private struct Shot: Identifiable {
        let attachment: ChatAttachment
        let thumbnail: UIImage
        var id: String { attachment.name }
    }
    @State private var photos: [Shot] = []
    @State private var preview: Shot?
    @State private var shooting = false
    @State private var error = ""

    @State private var shutterRequest = 0
    @State private var capturing = false
    @State private var frontCamera = false

    private var availableBytes: Int { bytes - photos.reduce(0) { $0 + $1.attachment.data.count } }

    var body: some View {
        ZStack {
            if shooting {
                ZStack {
                    Color.black.ignoresSafeArea()
                    if !fixtureCamera {
                        ContinuousCamera(request:shutterRequest,front:frontCamera,onPhoto:receive)
                            .ignoresSafeArea()
                    }
                    VStack {
                        HStack {
                            if photos.isEmpty {
                                Button("取消") { dismiss() }
                            } else {
                                Label("\(photos.count)",systemImage:"photo.stack")
                                    .accessibilityIdentifier("camera-count")
                            }
                            Spacer()
                            Button("完成") { shooting = false }
                                .disabled(photos.isEmpty || capturing)
                                .accessibilityIdentifier("camera-done")
                        }.padding().background(.black.opacity(0.75))
                        Spacer()
                        if !error.isEmpty {
                            Text(PhoneLanguage.text(error,in:locale)).padding(8).background(.black.opacity(0.8))
                        }
                        if photos.count > 1 {
                            Text("长按并拖动照片调整顺序").font(.caption)
                        }
                        if !photos.isEmpty {
                            ScrollViewReader { scroll in
                                ScrollView(.horizontal) {
                                    HStack(spacing:8) {
                                        ForEach(Array(photos.enumerated()), id:\.element.id) { index,shot in
                                            Button { preview = shot } label: {
                                                Image(uiImage:shot.thumbnail)
                                                    .resizable().scaledToFit()
                                                    .frame(width:72,height:72)
                                                    .overlay(alignment:.bottomLeading) {
                                                        Text(verbatim:String(index + 1)).font(.caption2.bold())
                                                            .padding(4).background(.black.opacity(0.75),in:.capsule)
                                                    }
                                                    .contentShape(Rectangle())
                                            }
                                            .buttonStyle(.plain)
                                            .disabled(capturing)
                                            .accessibilityLabel(Text("照片") + Text(verbatim:" \(index + 1)"))
                                            .accessibilityIdentifier("camera-thumbnail-\(index + 1)")
                                            .draggable(shot.id)
                                            .dropDestination(for:String.self) { ids,_ in
                                                guard !capturing, ids.count == 1,
                                                      let from = photos.firstIndex(where:{ $0.id == ids[0] }),
                                                      let to = photos.firstIndex(where:{ $0.id == shot.id }),
                                                      from != to else { return false }
                                                withAnimation {
                                                    photos.move(fromOffsets:IndexSet(integer:from),toOffset:from < to ? to + 1 : to)
                                                }
                                                return true
                                            }
                                            .id(shot.id)
                                        }
                                    }.padding(.horizontal,12)
                                }.scrollIndicators(.hidden)
                                .onAppear { if let latest = photos.last { scroll.scrollTo(latest.id,anchor:.trailing) } }
                                .onChange(of:photos.count) { old,new in
                                    if new > old, let latest = photos.last { scroll.scrollTo(latest.id,anchor:.trailing) }
                                }
                            }.frame(height:76)
                        }
                        ZStack {
                            Button(action:takePhoto) {
                                Circle().fill(.white).padding(5)
                                    .overlay(Circle().stroke(.white,lineWidth:3)).frame(width:68,height:68)
                            }
                            .accessibilityLabel("拍照").accessibilityIdentifier("camera-shutter")
                            .disabled(capturing || photos.count >= slots || availableBytes <= 0)
                            .opacity(capturing || photos.count >= slots || availableBytes <= 0 ? 0.45 : 1)
                            if !fixtureCamera && UIImagePickerController.isCameraDeviceAvailable(.front) {
                                HStack {
                                    Spacer()
                                    Button { frontCamera.toggle() } label: { Image(systemName:"camera.rotate") }
                                        .accessibilityLabel("切换摄像头").disabled(capturing)
                                }.padding(.trailing,24)
                            }
                        }.padding(.vertical,12).frame(maxWidth:.infinity).background(.black.opacity(0.75))
                    }.foregroundStyle(.white)
                }
            } else {
                NavigationStack {
                    List {
                        ForEach(Array(photos.enumerated()),id:\.element.id) { index,photo in
                            HStack {
                                Button { preview = photo } label: {
                                    Image(uiImage:photo.thumbnail).resizable().scaledToFit().frame(width:80,height:68)
                                }.buttonStyle(.borderless)
                                .accessibilityLabel(Text("照片") + Text(verbatim:" \(index + 1)"))
                                Text(verbatim:String(index + 1))
                                Spacer()
                                Button("移除") { photos.removeAll { $0.id == photo.id } }
                                    .buttonStyle(.borderless)
                            }
                        }
                        if !error.isEmpty { Text(PhoneLanguage.text(error,in:locale)).foregroundStyle(.secondary) }
                        Button { Task { await openCamera() } } label: { Label("继续拍摄",systemImage:"camera") }
                            .disabled(photos.count >= slots || availableBytes <= 0)
                        Button("加入草稿") {
                            if add(photos.map(\.attachment)) { dismiss() } else { error = attachmentLimit }
                        }.disabled(photos.isEmpty)
                    }.navigationTitle("拍照")
                    .toolbar { ToolbarItem(placement:.cancellationAction) { Button("取消") { dismiss() } } }
                }
            }
        }.task { await openCamera() }
        .fullScreenCover(item:$preview) { shot in
            NavigationStack {
                ZStack {
                    Color.black.ignoresSafeArea()
                    if let image = UIImage(data:shot.attachment.data) {
                        Image(uiImage:image).resizable().scaledToFit()
                    }
                }
                .navigationTitle(Text(verbatim:"\((photos.firstIndex { $0.id == shot.id } ?? 0) + 1) / \(photos.count)"))
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement:.cancellationAction) {
                        Button("关闭") { preview = nil }.accessibilityIdentifier("camera-preview-close")
                    }
                    ToolbarItem(placement:.primaryAction) {
                        Button("移除",role:.destructive) {
                            photos.removeAll { $0.id == shot.id }
                            preview = nil
                        }.accessibilityIdentifier("camera-preview-remove")
                    }
                }
            }.preferredColorScheme(.dark)
        }
    }

    private var fixtureCamera: Bool {
        #if DEBUG && targetEnvironment(simulator)
        return ProcessInfo.processInfo.arguments.contains("-fixture-camera")
        #else
        return false
        #endif
    }

    private func takePhoto() {
        guard !capturing, photos.count < slots, availableBytes > 0 else { return }
        capturing = true
        shutterRequest += 1
        if fixtureCamera {
            let image = UIGraphicsImageRenderer(size:CGSize(width:80,height:80)).image { context in
                UIColor(hue:CGFloat(shutterRequest % 16) / 16,saturation:0.9,brightness:0.95,alpha:1).setFill()
                context.fill(CGRect(x:0,y:0,width:80,height:80))
            }
            receive(image)
        }
    }

    @MainActor private func openCamera() async {
        if fixtureCamera { shooting = true; return }
        guard UIImagePickerController.isSourceTypeAvailable(.camera) else { error = "此设备无法使用相机。"; return }
        let granted = await AVCaptureDevice.requestAccess(for:.video)
        guard !Task.isCancelled else { return }
        if granted { shooting = true; error = "" }
        else { error = "未获相机权限。请在系统设置中允许知识秘书使用相机。" }
    }

    private func receive(_ image:UIImage?) {
        capturing = false
        guard let image, image.size.width > 0, image.size.height > 0 else { error = "无法读取照片。"; shooting = false; return }
        let scale = min(1, 2560 / max(image.size.width,image.size.height))
        let size = CGSize(width:image.size.width * scale,height:image.size.height * scale)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        let data = UIGraphicsImageRenderer(size:size,format:format).jpegData(withCompressionQuality:0.82) { _ in
            image.draw(in:CGRect(origin:.zero,size:size))
        }
        guard !data.isEmpty, photos.count < slots, data.count <= availableBytes else { error = attachmentLimit; shooting = false; return }
        let thumbScale = min(1,240 / max(size.width,size.height))
        let thumbSize = CGSize(width:size.width * thumbScale,height:size.height * thumbScale)
        let thumbnail = UIGraphicsImageRenderer(size:thumbSize,format:format).image { _ in
            image.draw(in:CGRect(origin:.zero,size:thumbSize))
        }
        let attachment = ChatAttachment(name:"Camera-" + UUID().uuidString.prefix(8) + ".jpg",data:data,capturedAt:Date())
        photos.append(Shot(attachment:attachment,thumbnail:thumbnail))
        error = ""
    }
}

private struct ContinuousCamera: UIViewControllerRepresentable {
    let request: Int
    let front: Bool
    let onPhoto: (UIImage?) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(request:request,onPhoto:onPhoto) }

    func makeUIViewController(context:Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.cameraCaptureMode = .photo
        picker.showsCameraControls = false
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ picker:UIImagePickerController, context:Context) {
        context.coordinator.onPhoto = onPhoto
        let device: UIImagePickerController.CameraDevice = front ? .front : .rear
        if picker.cameraDevice != device { picker.cameraDevice = device }
        if request != context.coordinator.request {
            context.coordinator.request = request
            picker.takePicture()
        }
    }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        var request: Int
        var onPhoto: (UIImage?) -> Void

        init(request:Int,onPhoto:@escaping (UIImage?) -> Void) {
            self.request = request
            self.onPhoto = onPhoto
        }

        func imagePickerController(_ picker:UIImagePickerController, didFinishPickingMediaWithInfo info:[UIImagePickerController.InfoKey:Any]) {
            onPhoto(info[.originalImage] as? UIImage)
        }
        func imagePickerControllerDidCancel(_ picker:UIImagePickerController) { onPhoto(nil) }
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
private final class PhonePreview: Identifiable {
    let url: URL
    private let folder: URL

    init(original: URL) throws {
        let files = FileManager.default
        let folder = files.temporaryDirectory.appendingPathComponent(UUID().uuidString,isDirectory:true)
        let url = folder.appendingPathComponent(original.lastPathComponent)
        try files.createDirectory(at:folder,withIntermediateDirectories:false)
        do {
            // Keep the original available even if the download cache is pruned.
            do { try files.linkItem(at:original,to:url) }
            catch { try files.copyItem(at:original,to:url) }
        } catch {
            try? files.removeItem(at:folder)
            throw error
        }
        self.folder = folder
        self.url = url
    }

    deinit { try? FileManager.default.removeItem(at:folder) }

    var isImage: Bool {
        UTType(filenameExtension:url.pathExtension)?.conforms(to:.image) == true
    }

    static func photoSaveKey(for url: URL) async throws -> String {
        try await Task.detached(priority:.userInitiated) {
            let file = try FileHandle(forReadingFrom:url)
            defer { try? file.close() }
            var hash = SHA256()
            while let chunk = try file.read(upToCount:256 * 1024), !chunk.isEmpty { hash.update(data:chunk) }
            return "savedOriginalPhoto." + hash.finalize().map { String(format:"%02x",$0) }.joined()
        }.value
    }
}

private struct OriginalFileSheet: View {
    @Environment(\.locale) private var interfaceLocale
    @Environment(\.dismiss) private var dismiss
    let file: PhonePreview
    @State private var exporting = false
    @State private var savingPhoto = false
    @State private var confirmDuplicate = false
    @State private var result = ""

    var body: some View {
        NavigationStack {
            OriginalPreview(url:file.url)
                .safeAreaInset(edge:.bottom) {
                    VStack(spacing:8) {
                        ViewThatFits {
                            HStack { saveButtons }
                            VStack { saveButtons }
                        }
                        if !result.isEmpty {
                            Text(LocalizedStringKey(result)).font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    .buttonStyle(.bordered)
                    .frame(maxWidth:.infinity)
                    .padding()
                    .background(.bar)
                }
                .navigationTitle(PhoneLanguage.text("完整原件",in:interfaceLocale))
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement:.topBarTrailing) {
                        Button("关闭") { dismiss() }.disabled(savingPhoto)
                    }
                }
        }
        .interactiveDismissDisabled(savingPhoto)
        .sheet(isPresented:$exporting) {
            OriginalFileExporter(file:file) { didSave in
                if didSave { result = "原件已存储到文件。" }
                exporting = false
            }
            .ignoresSafeArea()
        }
        .alert("这张原图已保存过",isPresented:$confirmDuplicate) {
            Button("取消",role:.cancel) {}
            Button("仍然保存") { Task { await savePhoto(allowDuplicate:true) } }
        } message: {
            Text("如果你已从照片中删除原图，可以再次保存。")
        }
    }

    @ViewBuilder private var saveButtons: some View {
        Button { result = "";exporting = true } label: { Label("存储到文件",systemImage:"folder") }
            .accessibilityIdentifier("original-save-files")
            .disabled(savingPhoto)
        if file.isImage {
            Button { Task { await savePhoto() } } label: {
                if savingPhoto { ProgressView().accessibilityLabel("正在保存照片…") }
                else { Label("保存到照片",systemImage:"photo") }
            }
            .accessibilityIdentifier("original-save-photo")
            .disabled(savingPhoto)
        }
    }

    private func savePhoto(allowDuplicate: Bool = false) async {
        guard !savingPhoto else { return }
        result = ""
        savingPhoto = true
        defer { savingPhoto = false }
        let originalURL = file.url
        do {
            let key = try await PhonePreview.photoSaveKey(for:originalURL)
            if !allowDuplicate, UserDefaults.standard.bool(forKey:key) {
                confirmDuplicate = true
                return
            }
            let authorization = await PHPhotoLibrary.requestAuthorization(for:.addOnly)
            guard authorization == .authorized || authorization == .limited else {
                result = "请在 iPhone 设置中允许添加照片，或选择存储到文件。"
                return
            }
            try await PHPhotoLibrary.shared().performChanges {
                let asset = PHAssetCreationRequest.forAsset()
                asset.addResource(with:.photo,fileURL:originalURL,options:nil)
            }
            UserDefaults.standard.set(true,forKey:key)
            result = "原图已保存到照片。"
        } catch {
            result = "无法将原图保存到照片。你可以存储到文件。"
        }
    }
}

private struct OriginalFileExporter: UIViewControllerRepresentable {
    let file: PhonePreview
    let onFinish: (Bool) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onFinish:onFinish) }

    func makeUIViewController(context:Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forExporting:[file.url],asCopy:true)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ picker:UIDocumentPickerViewController,context:Context) {}

    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onFinish: (Bool) -> Void
        init(onFinish:@escaping (Bool) -> Void) { self.onFinish = onFinish }

        func documentPicker(_ controller:UIDocumentPickerViewController,didPickDocumentsAt urls:[URL]) {
            onFinish(!urls.isEmpty)
        }

        func documentPickerWasCancelled(_ controller:UIDocumentPickerViewController) { onFinish(false) }
    }
}

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
    private var appendKey: RecordAppendKey { RecordAppendKey(workspace:workspace,record:record.id) }
    private var draft: RecordAppend? { model.recordAppends[appendKey] }
    private var appending: Bool { draft?.attempt != nil }
    @State private var latestAppendID: String?
    @State private var preview:PhonePreview?
    @State private var fileTask:Task<Void,Never>?
    @State private var downloadDone:Int64=0
    @State private var downloadTotal:Int64=0
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
                                Button {fileTask=Task {await open(file)}} label:{Label("打开原件 · \(file.name)",systemImage:"doc")}.disabled(working || appending || !model.online)
                                if file.size>0 {Text(ByteCountFormatter.string(fromByteCount:file.size,countStyle:.file)+(!file.previewPath.isEmpty ? PhoneLanguage.text(" · 图片预览更快，原件保持完整",in:interfaceLocale):"")).font(.caption).foregroundStyle(.secondary)}
                            }
                        }
                    }.frame(maxWidth:.infinity,alignment:.leading).padding().background(.quaternary,in:RoundedRectangle(cornerRadius:14))
                }
                if fileTask != nil {
                    VStack(alignment:.leading,spacing:8) {
                        Text("正在下载完整原件…").font(.subheadline)
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
                if let draft, appending {
                    Text(draft.name).lineLimit(1)
                    if draft.total > 0 && draft.sent >= draft.total {
                        ProgressView("附件已发出，等待电脑保存…")
                    } else if draft.total > 0 {
                        ProgressView(value:Double(draft.sent),total:Double(draft.total)) {
                            Text("正在上传附件…")
                        } currentValueLabel: {
                            Text(verbatim:ByteCountFormatter.string(fromByteCount:draft.sent,countStyle:.file) + " / " +
                                 ByteCountFormatter.string(fromByteCount:draft.total,countStyle:.file))
                        }
                    } else { ProgressView("正在准备上传附件…") }
                }
                if let failure = draft?.failure, !failure.isEmpty { Text(failure).foregroundStyle(.orange) }
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
                    }.disabled(working || appending || !model.online)
                    VStack(alignment:.leading,spacing:12) {
                        Text("添加附件").font(.headline)
                        HStack {
                            PhotosPicker(selection:$photo,matching:.images) {Label("照片",systemImage:"photo")}
                            Button {importing=true} label:{Label("文件",systemImage:"paperclip")}
                        }.disabled(working || appending || !model.online)
                        Text("追加到当前资料，保留已有原件。每个附件最多 10 MB。").font(.footnote).foregroundStyle(.secondary)
                        if let draft, draft.data != nil && !appending {
                            Text(draft.name).lineLimit(2)
                            HStack {
                                Button("添加到这份资料") {notice="";error="";model.submitAppend(appendKey,updated:updated)}.buttonStyle(.borderedProminent)
                                Button("取消") {model.clearAppend(appendKey);photo=nil}
                            }.disabled(working || appending || !model.online)
                        }
                    }
                    if working && fileTask == nil && !appending {ProgressView("正在处理…")}
                    if !summary.isEmpty {Text("摘要").font(.headline);Text(summary).textSelection(.enabled)}
                    if !text.isEmpty {DisclosureGroup("正文与归档说明") {Text(text).frame(maxWidth:.infinity,alignment:.leading).textSelection(.enabled)}}
                }
            }.padding().frame(maxWidth:.infinity,alignment:.leading)
        }.navigationTitle(PhoneLanguage.text("资料详情",in:interfaceLocale)).navigationBarTitleDisplayMode(.inline)
        .toolbar {Button("重新加载") {Task {await load()}}.disabled(working)}
        .task {await load()}
        .onChange(of:draft?.result != nil,initial:true) { _,ready in
            guard ready, let draft, let value=draft.result else {return}
            let oldTitle=title,oldTags=tags,titleChanged=title != savedTitle,tagsChanged=tags != savedTags
            latestAppendID=draft.requestID
            apply(value)
            if titleChanged {title=oldTitle};if tagsChanged {tags=oldTags}
            photo=nil;error="";notice="附件已添加";model.clearAppend(appendKey)
        }
        .sheet(item:$preview) { OriginalFileSheet(file:$0) }
        .alert("添加标签",isPresented:$addingTag) {
            TextField("标签名称",text:$newTag)
            Button("添加") {Task {await addTag()}}
            Button("取消",role:.cancel) {}
        }
        .alert("删除标签？",isPresented:$confirmTagDeletion) {
            Button("删除标签",role:.destructive) {if let tag=deletingTag {Task {await saveTags(tags.filter {$0 != tag},notice:"标签已删除")}}}
            Button("取消",role:.cancel) {deletingTag=nil}
        } message: {Text("确定删除标签“\(deletingTag ?? "")”？")}
        .onDisappear {fileTask?.cancel()}
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
        let previous=latestAppendID
        do {
            let value=try await model.detail(record.id,workspace:workspace)
            guard previous==latestAppendID, !Task.isCancelled else {return}
            apply(value);error=""
        }
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
        model.stageAppend(appendKey,name:name,data:data);error="";notice=""
    }
    private func open(_ file:PhoneAttachment) async {
        working=true;downloadDone=0;downloadTotal=0
        defer {working=false;fileTask=nil}
        do {
            let url=try await model.downloadAttachment(file.path,name:file.name,version:file.version,workspace:workspace) {done,total in
                Task {@MainActor in downloadDone=done;downloadTotal=total}
            }
            guard !Task.isCancelled else {return}
            preview=try PhonePreview(original:url);error=""
        } catch {
            if Task.isCancelled {return}
            self.error=error.localizedDescription
        }
    }
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
                    Section("当前电脑") {
                        ConnectionBanner()
                        if let route=model.paired?.transport, ["direct","bluetooth","wifi"].contains(route) {
                            LabeledContent {
                                Text(LocalizedStringKey(route=="direct" ? "网络直连" : route=="bluetooth" ? "蓝牙中继" : "附近 Wi-Fi 中继"))
                            } label: {
                                Text(LocalizedStringKey(model.online ? "连接方式" : "上次连接方式"))
                            }
                        }
                        Button("重新连接") {Task {await model.connect()}}.disabled(model.pairingInFlight)}
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
