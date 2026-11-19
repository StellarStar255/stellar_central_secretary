import XCTest
@testable import CompanionPairing

final class PairedComputersTests: XCTestCase {
    private func pair(_ server:String, pin:String="b") -> PairedMac {
        PairedMac(info:PairInfo(v:1,server_id:String(repeating:server,count:32),name:"Computer "+server,url:"https://192.0.2.20:8769",fingerprint:String(repeating:pin,count:64),secret:nil),credential:"credential-"+server)
    }
    func testLegacySinglePairMigratesWithoutLosingCredentials() throws {
        let original=pair("a")
        let saved=try PairedComputers.decode(JSONEncoder().encode(original))
        XCTAssertEqual(saved.selected?.id,original.id)
        XCTAssertEqual(saved.selected?.credential,original.credential)
        XCTAssertEqual(saved.computers.count,1)
    }
    func testAddingAndReconnectingNeverReplacesOtherComputersOrNickname() throws {
        var registry=PairedComputers(),work=pair("a"),home=pair("c")
        work.nickname="Company";registry.remember(work);registry.remember(home)
        home.credential="refreshed";registry.remember(home)
        work.nickname=nil;registry.remember(work)
        let restored=try PairedComputers.decode(JSONEncoder().encode(registry))
        XCTAssertEqual(restored.computers.count,2)
        XCTAssertEqual(restored.selected?.displayName,"Company")
        XCTAssertEqual(restored.computers.first(where:{$0.id==home.id})?.credential,"refreshed")
    }
    func testRemovingActiveComputerNeverSilentlySelectsAnother() {
        var registry=PairedComputers();let work=pair("a"),home=pair("c")
        registry.remember(work);registry.remember(home)
        registry.remove(work.id);XCTAssertEqual(registry.selected?.id,home.id)
        registry.remove(home.id);XCTAssertNil(registry.selected)
        registry.remember(work);registry.remember(home);registry.remove(home.id)
        XCTAssertNil(registry.selected);XCTAssertEqual(registry.computers.first?.id,work.id)
    }
    func testCertificateChangeNeverSharesIdentityOrCaches() {
        let old=pair("a"),changed=pair("a",pin:"d")
        XCTAssertNotEqual(old.id,changed.id)
        var registry=PairedComputers();registry.remember(old);registry.remember(changed)
        XCTAssertEqual(registry.computers.count,2)
    }
    func testManualOrderSurvivesReloadAndReconnectWithoutChangingSelection() throws {
        let work = pair("a"), home = pair("c"), other = pair("d")
        var registry = PairedComputers()
        registry.remember(work)
        registry.remember(home)
        registry.remember(other, select: false)
        registry.move(from: IndexSet(integer: 0), to: 3)

        var restored = try PairedComputers.decode(JSONEncoder().encode(registry))
        XCTAssertEqual(restored.computers.map(\.id), [home.id, other.id, work.id])
        XCTAssertEqual(restored.selected?.id, home.id)
        var reconnected = work
        reconnected.credential = "refreshed"
        restored.remember(reconnected, select: false)
        XCTAssertEqual(restored.computers.map(\.id), [home.id, other.id, work.id])
        XCTAssertEqual(restored.computers.last?.credential, "refreshed")
        XCTAssertEqual(restored.selected?.id, home.id)
    }
    func testRememberedInvitationsAreStrippedAndInvalidStorageIsRejected() throws {
        var registry=PairedComputers(),value=pair("a")
        value.info.secret="one-time-invitation";registry.remember(value)
        XCTAssertNil(registry.selected?.info.secret)
        XCTAssertThrowsError(try PairedComputers.decode(Data("{}".utf8)))
    }
}
