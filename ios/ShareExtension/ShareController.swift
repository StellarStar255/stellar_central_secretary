import UIKit
import UniformTypeIdentifiers

final class ShareController: UIViewController {
    private let message = UILabel()
    private let done = UIButton(type: .system)

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        message.numberOfLines = 0
        message.textAlignment = .center
        message.text = "正在接收文件…"
        done.setTitle("完成", for: .normal)
        done.addTarget(self, action: #selector(close), for: .touchUpInside)
        done.isHidden = true
        let stack = UIStackView(arrangedSubviews: [message, done])
        stack.axis = .vertical
        stack.spacing = 16
        stack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            stack.leadingAnchor.constraint(equalTo: view.layoutMarginsGuide.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: view.layoutMarginsGuide.trailingAnchor)
        ])
        let attachments = (extensionContext?.inputItems as? [NSExtensionItem])?.flatMap { $0.attachments ?? [] } ?? []
        guard attachments.count == 1, let provider = attachments.first else {
            finish("无法读取这个文件。"); return
        }
        let receive: (URL?) -> Void = { url in
            let result: String
            do {
                guard let url, url.isFileURL else { throw CocoaError(.fileReadUnknown) }
                let scoped = url.startAccessingSecurityScopedResource()
                defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                var name = provider.suggestedName ?? url.lastPathComponent
                if (name as NSString).pathExtension.isEmpty, !url.pathExtension.isEmpty { name += "." + url.pathExtension }
                try SharedInbox.save(url, name: name)
                result = "已保存到手机。打开知识秘书，在「归档」中选择电脑并发送。"
            } catch {
                result = "未能保存文件。请选择一个非空且不超过 10 MB 的文件，并检查手机剩余空间。"
            }
            DispatchQueue.main.async { self.finish(result) }
        }
        if let type = provider.registeredTypeIdentifiers.first(where: {
            $0 != UTType.fileURL.identifier && UTType($0)?.conforms(to: .data) == true
        }) {
            provider.loadFileRepresentation(forTypeIdentifier: type) { url, _ in receive(url) }
        } else if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier) { item, _ in receive(item as? URL) }
        } else {
            finish("无法读取这个文件。")
        }
    }

    private func finish(_ text: String) { message.text = text; done.isHidden = false }
    @objc private func close() { extensionContext?.completeRequest(returningItems: nil) }
}
