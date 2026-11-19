import Foundation
import CryptoKit
import Security
import SwiftUI

struct PairedMac: Codable, Identifiable {
    var info: PairInfo
    var credential: String
    var transport: String? = nil
    var nickname: String? = nil
    var id: String { Self.identity(serverID: info.server_id, fingerprint: info.fingerprint) }
    var displayName: String { nickname?.isEmpty == false ? nickname! : info.name }
    static func identity(serverID: String, fingerprint: String) -> String {
        SHA256.hash(data: Data((serverID+":"+fingerprint.lowercased()).utf8)).map { String(format:"%02x", $0) }.joined()
    }
}

// One atomic Keychain value keeps selection and credentials consistent. The
// previous single-computer value decodes here without changing its credential.
struct PairedComputers: Codable {
    var computers: [PairedMac] = []
    var selectedID: String?
    var selected: PairedMac? { computers.first { $0.id == selectedID } }
    static func decode(_ data: Data) throws -> Self {
        let decoder = JSONDecoder()
        if let saved = try? decoder.decode(Self.self, from: data) { return saved }
        let legacy = try decoder.decode(PairedMac.self, from: data)
        return Self(computers: [legacy], selectedID: legacy.id)
    }
    mutating func remember(_ pair: PairedMac, select: Bool = true) {
        var saved = pair; saved.info.secret = nil
        if let index = computers.firstIndex(where: { $0.id == pair.id }) {
            saved.nickname = computers[index].nickname
            computers[index] = saved
        } else { computers.append(saved) }
        if select { selectedID = saved.id }
    }
    mutating func remove(_ id: String) {
        computers.removeAll { $0.id == id }
        // Removing the current computer never silently selects another one.
        if selectedID == id { selectedID = nil }
    }
    mutating func move(from offsets: IndexSet, to destination: Int) {
        computers.move(fromOffsets: offsets, toOffset: destination)
    }
}

enum CredentialStore {
    static let service = "io.github.stellarstar255.secretary.companion"
    private static var query: [String:Any] {
        [kSecClass as String:kSecClassGenericPassword, kSecAttrService as String:service, kSecAttrAccount as String:"paired-mac"]
    }
    static func load() throws -> PairedComputers {
        var query = query;query[kSecReturnData as String] = true
        var value: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &value)
        if status == errSecItemNotFound { return PairedComputers() }
        guard status == errSecSuccess, let data = value as? Data else { throw NSError(domain:NSOSStatusErrorDomain,code:Int(status)) }
        return try PairedComputers.decode(data)
    }
    static func save(_ value: PairedComputers) throws {
        let attributes: [String:Any] = [kSecValueData as String:try JSONEncoder().encode(value), kSecAttrAccessible as String:kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        var status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound { status = SecItemAdd(query.merging(attributes) { _,new in new } as CFDictionary,nil) }
        guard status == errSecSuccess else { throw NSError(domain:NSOSStatusErrorDomain,code:Int(status)) }
    }
}

struct CaptureEditor {
    var text = ""
    var filename: String?
    var data: Data?
}
