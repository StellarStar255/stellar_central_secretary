import UIKit
import UniformTypeIdentifiers

final class ShareController: UIViewController {
    private let message = UILabel()
    private let done = UIButton(type: .system)

    private let sendButton = UIButton(type: .system)
    private var pendingFile: URL?
    private var destination: PairedMac?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        message.numberOfLines = 0
        message.textAlignment = .center
        message.text = "正在接收文件…"
        done.setTitle("完成", for: .normal)
        done.addTarget(self, action: #selector(close), for: .touchUpInside)
        done.isHidden = true
        sendButton.isHidden = true
        sendButton.setTitle("发送到这台 Mac", for: .normal)
        sendButton.addTarget(self, action: #selector(sendFile), for: .touchUpInside)
        let stack = UIStackView(arrangedSubviews: [message, sendButton, done])
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
            let result: Result<URL, Error>
            do {
                guard let url, url.isFileURL else { throw CocoaError(.fileReadUnknown) }
                let scoped = url.startAccessingSecurityScopedResource()
                defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                var name = provider.suggestedName ?? url.lastPathComponent
                if (name as NSString).pathExtension.isEmpty, !url.pathExtension.isEmpty { name += "." + url.pathExtension }
                result = .success(try SharedInbox.save(url, name: name))
            } catch {
                result = .failure(error)
            }
            DispatchQueue.main.async {
                switch result {
                case .success(let file):
                    self.pendingFile = file
                    self.destination = try? CredentialStore.load().selected
                    if let pair = self.destination {
                        self.finish("\(file.lastPathComponent)\n\n当前电脑：\(pair.displayName)")
                        self.sendButton.isHidden = false
                        self.done.setTitle("留在手机，稍后合并归档", for: .normal)
                    } else {
                        self.finish("已保存到手机。请在知识秘书中选择已配对的电脑。")
                    }
                case .failure:
                    self.finish("未能保存文件。请选择一个非空且不超过 10 MB 的文件，并检查手机剩余空间。")
                }
            }
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

    @objc private func sendFile() {
        guard let file = pendingFile, let pair = destination, sendButton.isEnabled else { return }
        sendButton.isEnabled = false
        done.isHidden = true
        message.text = "正在发送到 " + pair.displayName + "…"
        Task {
            do {
                try await Self.upload(file, to: pair)
                try FileManager.default.removeItem(at: file.deletingLastPathComponent())
                close()
            } catch {
                message.text = "未确认送达 " + pair.displayName + "。文件已保留在手机，可重试或稍后在「归档」中发送。"
                sendButton.setTitle("重试", for: .normal)
                sendButton.isEnabled = true
                done.isHidden = false
            }
        }
    }

    private nonisolated static func upload(_ file: URL, to pair: PairedMac) async throws {
        let wifi = try? WiFiRelay(serverID: pair.info.server_id)
        let bluetooth = try? BluetoothRelay(serverID: pair.info.server_id)
        defer { wifi?.stop(); bluetooth?.stop() }
        let pin = pair.info.fingerprint
        let endpoint = try await withThrowingTaskGroup(of: String.self) { group in
            group.addTask {
                guard let url = await PairingTLSProbe.firstVerifiedDirect(pair.info.connectionURLs, fingerprint: pin, timeout: 4) else { throw URLError(.cannotConnectToHost) }
                return url
            }
            if let wifi {
                group.addTask {
                    wifi.start()
                    return try await wifi.verifiedEndpoint(fingerprint:pin)
                }
            }
            if let bluetooth {
                group.addTask {
                    try await Task.sleep(for: .seconds(2))
                    bluetooth.start()
                    return try await PairingTLSProbe.verified(bluetooth.endpoint(), fingerprint: pin, timeout: 5)
                }
            }
            while !group.isEmpty {
                if let url = try? await group.next() { group.cancelAll(); return url }
            }
            throw URLError(.cannotConnectToHost)
        }
        guard URLComponents(string: endpoint)?.scheme == "https", let base = URL(string: endpoint) else { throw URLError(.badURL) }
        let config = URLSessionConfiguration.ephemeral
        config.connectionProxyDictionary = [:]
        config.timeoutIntervalForResource = 180
        let session = URLSession(configuration: config, delegate: PairingTLSProbe(fingerprint: pin), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        func request(_ path: String) -> URLRequest {
            var request = URLRequest(url: base.appendingPathComponent(path))
            request.setValue("Bearer " + pair.credential, forHTTPHeaderField: "Authorization")
            return request
        }
        let (status, http) = try await session.data(for: request("status"))
        guard (http as? HTTPURLResponse)?.statusCode == 200,
              let info = try JSONSerialization.jsonObject(with: status) as? [String: Any],
              info["server_id"] as? String == pair.info.server_id, info["privacy_version"] as? Int == 1,
              try CredentialStore.load().selected?.id == pair.id else { throw URLError(.userAuthenticationRequired) }

        let id = file.deletingLastPathComponent().lastPathComponent
        let content = ["filename": file.lastPathComponent, "text": "", "data": try Data(contentsOf: file).base64EncodedString(), "note_reference": try SharedInbox.noteReference(for: file)]
        var post = request("privacy-v1/ingest")
        post.httpMethod = "POST"
        post.setValue("application/json", forHTTPHeaderField: "Content-Type")
        post.httpBody = try JSONSerialization.data(withJSONObject: ["request_id": id, "content": content])
        let (body, response) = try await session.data(for: post)
        guard (response as? HTTPURLResponse)?.statusCode == 200,
              let receipt = try JSONSerialization.jsonObject(with: body) as? [String: Any],
              let item = receipt["item"] as? [String: Any], let record = item["id"] as? String, !record.isEmpty else { throw URLError(.badServerResponse) }
    }

    private func finish(_ text: String) { message.text = text; done.isHidden = false }
    @objc private func close() { extensionContext?.completeRequest(returningItems: nil) }
}
