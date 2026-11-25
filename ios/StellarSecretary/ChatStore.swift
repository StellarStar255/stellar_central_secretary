import Foundation

struct UploadProgress: Decodable {
    let received: Int64
    let total: Int64
}

struct AnswerEvidence: Codable {
    struct PDFPages: Codable { let name:String;let pages:String }
    struct Excerpt: Codable { let title:String;let text:String }
    let kind:String
    let passage_count:Int
    let history_turns:Int
    let conditions:[String]
    let pdf_pages:[PDFPages]
    let excerpts:[Excerpt]
}

struct ChatThread: Codable, Identifiable {
    var id:String;var title:String;var updated:Double;var running:Bool
    init(_ value:[String:Any]) {id=value["id"] as? String ?? "";title=value["title"] as? String ?? "新对话";updated=(value["updated"] as? NSNumber)?.doubleValue ?? 0;running=value["running"] as? Bool ?? false}
}
struct ChatMessage: Codable, Identifiable {
    var id:String;var role:String;var text:String;var pending:Bool;var error:Bool
    var requestID:String;var requestState:String;var clientID:String;var sources:[Record];var files:[String]
    var evidence: AnswerEvidence?
    init(_ value:[String:Any]) {
        id=value["id"] as? String ?? "";role=value["role"] as? String ?? "assistant";text=value["text"] as? String ?? ""
        pending=value["pending"] as? Bool ?? false;error=value["error"] as? Bool ?? false
        requestID=value["requestId"] as? String ?? "";requestState=value["requestState"] as? String ?? "";clientID=value["mobileRequestId"] as? String ?? ""
        sources=(value["sources"] as? [[String:Any]] ?? []).map(Record.init);files=value["files"] as? [String] ?? []
        if let object=value["answerEvidence"] as? [String:Any],let data=try? JSONSerialization.data(withJSONObject:object) {
            evidence=try? JSONDecoder().decode(AnswerEvidence.self,from:data)
        }
    }
}
struct ChatSnapshot: Codable {
    var id:String;var title:String;var revision:String;var messages:[ChatMessage];var hasMore:Bool
    var running:Bool {messages.contains {$0.pending || $0.requestState=="running"}}
}
struct PendingChatMessage: Codable, Identifiable {
    var id=UUID().uuidString
    var serverID:String;var fingerprint:String;var chatID:String;var text:String
    var lastError=""
    var attachment: ChatAttachment? = nil
    var attachmentBatch: [ChatAttachment]? = nil
    var files: [ChatAttachment] { attachmentBatch ?? attachment.map { [$0] } ?? [] }
}
struct ChatAttachment: Codable, Equatable {
    let name: String
    let data: Data

    static let maxCount = 8
    static let maxBytes = 10 * 1024 * 1024
    static func fits(_ files: [Self]) -> Bool {
        files.count <= maxCount && files.allSatisfy { !$0.data.isEmpty }
            && files.reduce(0) { $0 + $1.data.count } <= maxBytes
    }
    var payload: [String:String] { ["name":name,"data":data.base64EncodedString()] }
}
struct ChatCache: Codable {
    var serverID:String;var fingerprint:String
    var threads:[ChatThread]=[];var selectedID="";var listRevision=""
    var snapshots:[String:ChatSnapshot]=[:]
    mutating func trim() {
        let keep=Set(([selectedID]+threads.map(\.id)).filter {!$0.isEmpty}.prefix(5))
        snapshots=snapshots.filter {keep.contains($0.key)}
        for key in Array(snapshots.keys) {
            if var snapshot=snapshots[key],snapshot.messages.count>100 {snapshot.messages=Array(snapshot.messages.suffix(100));snapshot.hasMore=true;snapshots[key]=snapshot}
        }
    }
    static func load(_ url:URL,serverID:String,fingerprint:String) -> ChatCache {
        if let data=try? Data(contentsOf:url),data.count<=8_000_000,let cache=try? JSONDecoder().decode(Self.self,from:data),cache.serverID==serverID,cache.fingerprint==fingerprint {return cache}
        return ChatCache(serverID:serverID,fingerprint:fingerprint)
    }
    func save(_ url:URL) throws {
        var cache=self;cache.trim();let data=try JSONEncoder().encode(cache)
        guard data.count<=8_000_000 else {return}
        try Self.protectedWrite(data,to:url)
    }
    static func protectedWrite(_ data:Data,to url:URL) throws {
        #if os(iOS)
        try data.write(to:url,options:[.atomic,.completeFileProtectionUntilFirstUserAuthentication])
        #else
        try data.write(to:url,options:.atomic)
        #endif
        var target=url;var values=URLResourceValues();values.isExcludedFromBackup=true;try target.setResourceValues(values)
    }
}

struct CaptureEditor {
    var text = ""
    var files: [ChatAttachment] = []
}
