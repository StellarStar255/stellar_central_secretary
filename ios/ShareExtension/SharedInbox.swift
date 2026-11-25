import Foundation

enum SharedInbox {
    static let maxBytes = 10 * 1024 * 1024

    private static func directory() throws -> URL {
        guard let root = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.io.github.stellarstar255.secretary.companion") else {
            throw CocoaError(.fileNoSuchFile)
        }
        let folder = root.appendingPathComponent("Incoming", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return folder
    }

    static func save(_ source: URL, name: String) throws -> URL {
        let values = try source.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
        guard values.isRegularFile == true, let size = values.fileSize, (1...maxBytes).contains(size) else {
            throw CocoaError(.fileReadTooLarge)
        }
        let handle = try FileHandle(forReadingFrom: source)
        defer { try? handle.close() }
        let data = try handle.read(upToCount: maxBytes + 1) ?? Data()
        guard data.count == size else { throw CocoaError(.fileReadCorruptFile) }
        let inbox = try directory()
        let id = UUID().uuidString
        let staging = inbox.appendingPathComponent("." + id, isDirectory: true)
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: staging) }
        let leaf = (name as NSString).lastPathComponent
        let file = leaf.isEmpty || leaf.hasPrefix(".") ? "Attachment" : leaf
        try data.write(to: staging.appendingPathComponent(file), options: .completeFileProtectionUntilFirstUserAuthentication)
        let folder = inbox.appendingPathComponent(id)
        try FileManager.default.moveItem(at: staging, to: folder)
        return folder.appendingPathComponent(file)
    }

    static func noteReference(for file: URL) throws -> String {
        guard let date = try file.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate else {
            throw CocoaError(.fileReadCorruptFile)
        }
        return ISO8601DateFormatter().string(from: date)
    }

    static func files() throws -> [URL] {
        let manager = FileManager.default
        let folders = try manager.contentsOfDirectory(at: directory(), includingPropertiesForKeys: nil, options: .skipsHiddenFiles)
        return try folders.filter { UUID(uuidString: $0.lastPathComponent) != nil }.flatMap {
            try manager.contentsOfDirectory(at: $0, includingPropertiesForKeys: nil)
        }.sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
    }
}
