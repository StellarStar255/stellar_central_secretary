import Foundation

struct Record: Codable, Identifiable, Equatable {
    var id: String
    var title: String
    var summary: String
    init(_ value: [String: Any]) {
        id = value["id"] as? String ?? value["item_id"] as? String ?? ""
        title = value["title"] as? String ?? "资料"
        summary = value["summary"] as? String ?? ""
    }
}

struct CaptureReceipt: Codable, Identifiable, Equatable {
    let record: Record
    let stage: String
    let message: String
    var id: String { record.id }

    init(_ value: [String: Any]) {
        record = Record(value)
        if let stage = value["stage"] as? String { self.stage = stage }
        else { stage = record.summary.isEmpty ? "archived" : "ready" }
        message = value["message"] as? String ?? ""
    }
}

// A bounded snapshot of list metadata, scoped to one pinned Mac. No originals,
// credentials, or model answers are stored here.
struct LibraryCache: Codable {
    struct Snapshot: Codable {
        var records: [Record]
        var updatedAt: Date
        var requiresRefresh = false
        func isFresh(at now: Date = Date()) -> Bool {
            let age = now.timeIntervalSince(updatedAt)
            return !requiresRefresh && age >= 0 && age < 60
        }
    }
    var serverID: String
    var fingerprint: String
    private(set) var snapshots: [String: Snapshot] = [:]

    func belongsTo(serverID: String, fingerprint: String) -> Bool {
        self.serverID == serverID && self.fingerprint == fingerprint
    }
    mutating func update(_ records: [Record], query: String, at date: Date = Date()) {
        snapshots[query] = Snapshot(records: Array(records.prefix(50)), updatedAt: date)
        while snapshots.count > 8 {
            guard let oldest = snapshots.min(by: { $0.value.updatedAt < $1.value.updatedAt })?.key else { break }
            snapshots.removeValue(forKey: oldest)
        }
    }
    mutating func replace(_ record: Record) {
        for query in Array(snapshots.keys) {
            if let index=snapshots[query]?.records.firstIndex(where:{$0.id==record.id}) {snapshots[query]?.records[index]=record}
        }
        invalidate()
    }
    mutating func invalidate() {
        for query in Array(snapshots.keys) { snapshots[query]?.requiresRefresh = true }
    }
    static func load(from url: URL, serverID: String, fingerprint: String) -> LibraryCache {
        if let data = try? Data(contentsOf: url), data.count <= 4_000_000,
           let value = try? JSONDecoder().decode(Self.self, from: data),
           value.belongsTo(serverID: serverID, fingerprint: fingerprint) { return value }
        return LibraryCache(serverID: serverID, fingerprint: fingerprint)
    }
    func save(to url: URL) throws {
        let data = try JSONEncoder().encode(self)
        guard data.count <= 4_000_000 else { return }
        #if os(iOS)
        try data.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        #else
        try data.write(to: url, options: .atomic)
        #endif
        var target = url
        var resources = URLResourceValues();resources.isExcludedFromBackup = true
        try target.setResourceValues(resources)
    }
}
