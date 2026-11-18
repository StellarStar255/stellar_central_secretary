import XCTest

final class CompanionUITests: XCTestCase {
    @MainActor func clearSavedComputers(_ app:XCUIApplication) {
        if app.tabBars.buttons["连接"].exists {app.tabBars.buttons["连接"].tap()}
        // Keychain pairings can survive a simulator uninstall. Remove only the
        // test app's saved computers through its real UI before each scenario.
        for _ in 0..<12 {
            let remove=app.buttons.matching(NSPredicate(format:"identifier BEGINSWITH 'computer-remove-'")).firstMatch
            guard remove.exists else {break}
            let id=remove.identifier
            app.buttons[id].tap();app.buttons["解除配对"].tap()
            let removed=expectation(for:NSPredicate(format:"exists == false"),evaluatedWith:app.buttons[id])
            wait(for:[removed],timeout:5)
        }
    }
    func fixture(_ path:String) throws -> [String:Any] {
        let done = expectation(description:path);var result: [String:Any] = [:];var failure: Error?
        URLSession.shared.dataTask(with:URL(string:"http://127.0.0.1:18769"+path)!) { data,_,error in
            failure = error;if let data { result = (try? JSONSerialization.jsonObject(with:data)) as? [String:Any] ?? [:] };done.fulfill()
        }.resume();wait(for:[done],timeout:15);if let failure { throw failure };return result
    }
    @MainActor func testReviewDemoWithoutPairing() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        clearSavedComputers(app)
        let openDemo = app.buttons["open-review-demo"]
        XCTAssertTrue(openDemo.waitForExistence(timeout: 10))
        openDemo.tap()
        let garden = app.buttons["Rain garden checklist"]
        XCTAssertTrue(garden.waitForExistence(timeout: 5))
        let search = app.textFields["Search sample records"]
        search.tap()
        search.typeText("workshop")
        XCTAssertTrue(app.buttons["Community workshop"].exists)
        XCTAssertFalse(garden.exists)

        app.buttons["Archive"].tap()
        let note = app.textViews["Demo note"]
        note.tap()
        note.typeText("Test bench checklist")
        app.buttons["Save to demo library"].tap()
        let archived = app.buttons["Test bench checklist"]
        XCTAssertTrue(archived.waitForExistence(timeout: 5))
        archived.tap()
        XCTAssertTrue(app.staticTexts["Test bench checklist"].exists)
        app.navigationBars.buttons.firstMatch.tap()

        app.buttons["Chat"].tap()
        app.buttons["Ask"].tap()
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "check drainage after rain")).firstMatch.waitForExistence(timeout: 5))
        XCTAssertTrue(garden.exists)
        app.buttons["Close"].tap()
        XCTAssertTrue(app.buttons["扫描 Mac 配对码"].waitForExistence(timeout: 5))
        openDemo.tap()
        XCTAssertTrue(garden.waitForExistence(timeout: 5))
        XCTAssertFalse(archived.exists)
    }
    @MainActor func testScannerStaysVisibleUntilCancel() throws {
        let app = XCUIApplication();app.launch();clearSavedComputers(app)
        if app.tabBars.buttons["连接"].exists {
            app.tabBars.buttons["连接"].tap();app.buttons["解除手机上的配对"].tap();app.buttons["解除配对"].tap()
        }
        addUIInterruptionMonitor(withDescription: "Camera permission") { alert in
            for name in ["Allow", "允许", "OK", "好"] { if alert.buttons[name].exists { alert.buttons[name].tap();return true } };return false
        }
        app.buttons["扫描 Mac 配对码"].tap()
        let cancel = app.buttons["scanner-cancel"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 10))
        // Permission failure or unavailable simulator camera must keep the scanner visible.
        let closed = expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: cancel)
        closed.isInverted = true;wait(for: [closed], timeout: 3)
        cancel.tap();XCTAssertTrue(app.buttons["扫描 Mac 配对码"].waitForExistence(timeout: 10))
    }
    @MainActor func testPairCaptureSearchAndOfflineOutbox() throws {
        continueAfterFailure = false
        let app = XCUIApplication();app.launch();clearSavedComputers(app)
        if app.tabBars.buttons["连接"].exists {
            app.tabBars.buttons["连接"].tap();app.buttons["解除手机上的配对"].tap();app.buttons["解除配对"].tap()
        }
        addUIInterruptionMonitor(withDescription:"Local network") { alert in
            for name in ["Allow","允许","OK","好"] { if alert.buttons[name].exists { alert.buttons[name].tap();return true } };return false
        }
        let pair = try fixture("/pair.json")
        app.open(URL(string:pair["url"] as! String)!)
        XCTAssertTrue(app.staticTexts["请在 Mac 上核对数字并允许配对"].waitForExistence(timeout:20))
        _ = try fixture("/approve")
        XCTAssertTrue(app.navigationBars["随手归档"].waitForExistence(timeout:20),app.debugDescription)
        app.terminate();app.launch()
        XCTAssertTrue(app.navigationBars["随手归档"].waitForExistence(timeout:20))
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format:"label BEGINSWITH '已连接'")).firstMatch.waitForExistence(timeout:20),app.debugDescription)
        // A short app switch must validate the existing connection rather
        // than paying for another TLS handshake and device discovery.
        let before=try fixture("/connections")
        XCUIDevice.shared.press(.home);app.activate()
        let after=try fixture("/wait-status?after=\(before["status"] as! Int)")
        XCTAssertGreaterThan(after["status"] as! Int,before["status"] as! Int)
        XCTAssertEqual(after["tls"] as? Int,before["tls"] as? Int,"Short foreground resume must reuse the pinned TLS connection")
        // Reproduce a long suspension with the old gateway going away. The
        // foreground path must rebuild immediately, without terminating the app.
        let beforeLong=try fixture("/connections")
        XCUIDevice.shared.press(.home)
        _ = try fixture("/offline")
        let backgroundElapsed=expectation(description:"Gateway idle deadline elapsed")
        DispatchQueue.global().asyncAfter(deadline:.now()+21) {backgroundElapsed.fulfill()}
        wait(for:[backgroundElapsed],timeout:25)
        _ = try fixture("/online")
        let resumed=Date();app.activate()
        let afterLong=try fixture("/wait-status?after=\(beforeLong["status"] as! Int)")
        XCTAssertGreaterThan(afterLong["status"] as! Int,beforeLong["status"] as! Int)
        XCTAssertLessThan(Date().timeIntervalSince(resumed),8,"Long background resume must not wait for the old transport")
        XCTAssertGreaterThan(afterLong["tls"] as! Int,beforeLong["tls"] as! Int)
        let editor = app.textViews["归档内容"];editor.tap();editor.typeText("Mobile fixture unique note")
        app.buttons["保存到知识库"].tap()
        let empty = NSPredicate(format:"value == ''");expectation(for:empty,evaluatedWith:editor);waitForExpectations(timeout:20)
        app.tabBars.buttons["检索"].tap()
        XCTAssertEqual(try fixture("/count")["count"] as? Int,2)
        let row = app.buttons.containing(NSPredicate(format:"label CONTAINS 'Mobile fixture unique note'")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout:20),app.debugDescription)
        let listsBefore=try fixture("/connections")["items"] as! Int
        app.tabBars.buttons["归档"].tap();app.tabBars.buttons["检索"].tap()
        XCTAssertTrue(row.exists)
        XCTAssertEqual(try fixture("/connections")["items"] as? Int,listsBefore,"A fresh cached list must not refetch on every tab switch")
        _ = try fixture("/hold-items")
        app.buttons["搜索资料"].tap()
        XCTAssertTrue(app.staticTexts["正在后台更新资料…"].waitForExistence(timeout:5))
        XCTAssertTrue(row.exists,"Refreshing must keep the cached results visible")
        XCTAssertTrue(app.buttons["搜索资料"].isEnabled,"List refresh must not lock the whole screen")
        _ = try fixture("/offline");_ = try fixture("/release-items")
        XCTAssertTrue(app.staticTexts["更新未完成，继续显示上次的资料"].waitForExistence(timeout:20))
        XCTAssertTrue(row.exists)
        app.terminate();app.launch();app.tabBars.buttons["检索"].tap()
        XCTAssertTrue(row.waitForExistence(timeout:3),"The list cache must survive a process restart while offline")
        _ = try fixture("/online")
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format:"label BEGINSWITH '已连接'")).firstMatch.waitForExistence(timeout:20))
        _ = try fixture("/prepare-detail")
        row.tap()
        XCTAssertTrue(app.navigationBars["资料详情"].waitForExistence(timeout:10))
        let original=app.buttons["打开原件 · fixture.txt"]
        XCTAssertTrue(original.waitForExistence(timeout:10));XCTAssertTrue(original.isHittable,"Original file access must appear before the long summary")
        XCTAssertTrue(app.buttons["打开原链接"].isHittable || app.links["打开原链接"].isHittable)
        XCTAssertFalse(app.buttons.containing(NSPredicate(format:"label BEGINSWITH '查看图片'")).firstMatch.exists)
        XCTAssertTrue(app.images["图片预览 · fixture.png"].waitForExistence(timeout:10),"Image previews must appear without a tap")
        let filesBefore=try fixture("/connections")["files"] as! Int
        original.tap()
        XCTAssertTrue(app.buttons["关闭"].waitForExistence(timeout:10))
        XCTAssertTrue(app.navigationBars["完整原件"].exists)
        app.buttons["关闭"].tap()
        let filesAfter=try fixture("/connections")["files"] as! Int
        XCTAssertEqual(filesAfter,filesBefore+1)
        original.tap()
        XCTAssertTrue(app.buttons["关闭"].waitForExistence(timeout:3))
        app.buttons["关闭"].tap()
        XCTAssertEqual(try fixture("/connections")["files"] as? Int,filesAfter,"Reopening a completed original must use the protected phone cache")
        _ = try fixture("/hold-files")
        app.buttons["打开原件 · slow.txt"].tap()
        XCTAssertTrue(app.buttons["取消下载"].waitForExistence(timeout:5))
        app.buttons["取消下载"].tap()
        let cancelled=NSPredicate(format:"enabled == true")
        expectation(for:cancelled,evaluatedWith:app.buttons["保存标题"]);waitForExpectations(timeout:5)
        _ = try fixture("/release-files")
        let details=XCTAttachment(screenshot:app.screenshot());details.name="Phone details top actions";details.lifetime = .keepAlways;add(details)
        let title=app.textFields["detail-title"].exists ? app.textFields["detail-title"] : app.textViews["detail-title"]
        title.coordinate(withNormalizedOffset:CGVector(dx:0.95,dy:0.5)).tap();title.typeText(String(repeating:XCUIKeyboardKey.delete.rawValue,count:40))
        title.typeText("Edited mobile fixture title")
        app.buttons["保存标题"].tap()
        XCTAssertTrue(app.staticTexts["标题已保存"].waitForExistence(timeout:15))
        for tag in ["Phone","Review"] {
            app.buttons["添加标签"].tap()
            let alert=app.alerts["添加标签"];XCTAssertTrue(alert.waitForExistence(timeout:3))
            alert.textFields.firstMatch.tap();alert.textFields.firstMatch.typeText(tag);alert.buttons["添加"].tap()
            XCTAssertTrue(app.staticTexts["tag-chip-"+tag].waitForExistence(timeout:10))
        }
        app.buttons["tag-remove-Phone"].tap()
        XCTAssertTrue(app.alerts["删除标签？"].waitForExistence(timeout:3))
        app.alerts["删除标签？"].buttons["取消"].tap()
        XCTAssertTrue(app.staticTexts["tag-chip-Phone"].exists,"Cancel must keep the tag")
        XCTAssertEqual(try fixture("/metadata")["tags"] as? [String],["Phone","Review"])
        app.buttons["tag-remove-Phone"].tap()
        app.alerts["删除标签？"].buttons["删除标签"].tap()
        XCTAssertTrue(app.staticTexts["标签已删除"].waitForExistence(timeout:10))
        XCTAssertFalse(app.staticTexts["tag-chip-Phone"].exists)
        XCTAssertEqual(try fixture("/metadata")["tags"] as? [String],["Review"])
        app.navigationBars.buttons.firstMatch.tap()
        let search = app.textFields["搜索资料或输入问题"];search.tap();search.typeText("fixture")
        app.buttons["问知识库"].tap()
        let allow = app.buttons["同意并允许向此服务发送"]
        XCTAssertTrue(allow.waitForExistence(timeout:10))
        XCTAssertFalse(app.staticTexts["Synthetic fixture answer [1]"].exists)
        allow.tap()
        XCTAssertTrue(app.buttons["撤回授权"].waitForExistence(timeout:10))
        app.buttons["关闭"].tap()
        app.buttons["问知识库"].tap()
        XCTAssertTrue(app.staticTexts["Synthetic fixture answer [1]"].waitForExistence(timeout:20))
        _ = try fixture("/offline")
        app.tabBars.buttons["归档"].tap()
        XCTAssertTrue(app.buttons["暂存，连接后发送"].waitForExistence(timeout:20))
        editor.tap();editor.typeText("Offline fixture note");app.buttons["暂存，连接后发送"].tap()
        app.terminate();app.launch();XCTAssertTrue(app.staticTexts["Offline fixture note"].waitForExistence(timeout:20))
        // Leave an offline connection attempt in flight, then suspend. Its
        // late completion must not block or overwrite the foreground attempt.
        XCUIDevice.shared.press(.home)
        let attemptExpired=expectation(description:"Offline attempt suspended")
        DispatchQueue.global().asyncAfter(deadline:.now()+21) {attemptExpired.fulfill()}
        wait(for:[attemptExpired],timeout:25)
        _ = try fixture("/online")
        let offlineResume=Date();app.activate()
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format:"label BEGINSWITH '已连接'")).firstMatch.waitForExistence(timeout:8),app.debugDescription)
        XCTAssertLessThan(Date().timeIntervalSince(offlineResume),10)
        app.tabBars.buttons["连接"].tap();app.buttons["重新连接"].tap()
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format:"label BEGINSWITH '已连接'")).firstMatch.waitForExistence(timeout:20))
        app.tabBars.buttons["归档"].tap()
        let sent = NSPredicate(format:"exists == false");expectation(for:sent,evaluatedWith:app.staticTexts["Offline fixture note"]);waitForExpectations(timeout:20)
        XCTAssertEqual(try fixture("/count")["count"] as? Int,3)
        let screenshot = XCTAttachment(screenshot:app.screenshot());screenshot.name = "Paired iPhone capture";screenshot.lifetime = .keepAlways;add(screenshot)
    }
    @MainActor func testSharedDesktopChatAndOfflineRecovery() throws {
        continueAfterFailure=false
        let app=XCUIApplication();app.launch();clearSavedComputers(app)
        if app.buttons["扫描 Mac 配对码"].exists {
            let pair=try fixture("/pair.json");app.open(URL(string:pair["url"] as! String)!)
            XCTAssertTrue(app.staticTexts["请在 Mac 上核对数字并允许配对"].waitForExistence(timeout:20))
            _ = try fixture("/approve")
            XCTAssertTrue(app.tabBars.buttons["聊天"].waitForExistence(timeout:20))
        }
        app.tabBars.buttons["聊天"].tap()
        XCTAssertTrue(app.staticTexts["Desktop context fixture"].waitForExistence(timeout:15))
        let input=app.textFields["chat-input"].exists ? app.textFields["chat-input"]:app.textViews["chat-input"]
        input.tap();input.typeText("Mobile shared question");app.buttons["chat-send"].tap()
        let allow = app.buttons["同意并允许向此服务发送"]
        XCTAssertTrue(allow.waitForExistence(timeout:10))
        XCTAssertEqual(try fixture("/chat-inspect")["phone_count"] as? Int,0)
        allow.tap()
        XCTAssertTrue(app.buttons["撤回授权"].waitForExistence(timeout:10))
        app.buttons["关闭"].tap()
        app.buttons["chat-send"].tap()
        XCTAssertTrue(app.staticTexts["Shared phone reply"].waitForExistence(timeout:15),app.debugDescription)
        XCTAssertEqual(try fixture("/chat-inspect")["phone_count"] as? Int,1)
        _ = try fixture("/desktop-chat-append")
        XCTAssertTrue(app.staticTexts["Desktop updated reply"].waitForExistence(timeout:15))
        _ = try fixture("/offline")
        app.terminate();app.launch();app.tabBars.buttons["聊天"].tap()
        XCTAssertTrue(app.staticTexts["Desktop updated reply"].waitForExistence(timeout:3),"Offline history must be available without connecting")
        let offlineInput=app.textFields["chat-input"].exists ? app.textFields["chat-input"]:app.textViews["chat-input"]
        offlineInput.tap();offlineInput.typeText("Offline shared follow-up");app.buttons["chat-send"].tap()
        XCTAssertTrue(app.staticTexts["待发送 · 连接后由电脑处理"].waitForExistence(timeout:5))
        app.terminate();app.launch();app.tabBars.buttons["聊天"].tap()
        XCTAssertTrue(app.staticTexts["Offline shared follow-up"].waitForExistence(timeout:3))
        _ = try fixture("/online")
        XCTAssertTrue(app.staticTexts["Offline shared answer"].waitForExistence(timeout:30),app.debugDescription)
        XCTAssertEqual(try fixture("/chat-inspect")["offline_count"] as? Int,1)
        let backgroundInput=app.textFields["chat-input"].exists ? app.textFields["chat-input"]:app.textViews["chat-input"]
        backgroundInput.tap();backgroundInput.typeText("Background shared question")
        let sendReady=expectation(for:NSPredicate(format:"enabled == true"),evaluatedWith:app.buttons["chat-send"])
        wait(for:[sendReady],timeout:10);app.buttons["chat-send"].tap()
        XCTAssertTrue(try fixture("/wait-background")["started"] as? Bool == true)
        app.terminate();_ = try fixture("/finish-background")
        app.launch();app.tabBars.buttons["聊天"].tap()
        XCTAssertTrue(app.staticTexts["Background shared answer"].waitForExistence(timeout:20),app.debugDescription)
        XCTAssertEqual(try fixture("/chat-inspect")["background_calls"] as? Int,1)
        let shot=XCTAttachment(screenshot:app.screenshot());shot.name="Shared desktop chat on iPhone";shot.lifetime = .keepAlways;add(shot)
        app.buttons["新建聊天"].tap()
        XCTAssertTrue(app.staticTexts["继续这段对话，电脑会结合相同的上下文处理"].waitForExistence(timeout:10))
        app.buttons["会话"].tap();app.buttons["Shared fixture chat"].tap()
        XCTAssertTrue(app.staticTexts["Background shared answer"].waitForExistence(timeout:10))
    }

    @MainActor func testZZMultipleComputersKeepCachesAndOutboxesSeparate() throws {
        continueAfterFailure=false
        let app=XCUIApplication();app.launch();clearSavedComputers(app)
        let ids=try fixture("/computers"),work=ids["first"] as! String,home=ids["second"] as! String
        if app.tabBars.buttons["连接"].exists {app.tabBars.buttons["连接"].tap()}
        // Start with a fresh approved work computer, then add the home computer.
        let first=try fixture("/pair.json");app.open(URL(string:first["url"] as! String)!)
        if app.staticTexts["请在 Mac 上核对数字并允许配对"].waitForExistence(timeout:20) {_ = try fixture("/approve")}
        XCTAssertTrue(app.tabBars.buttons["连接"].waitForExistence(timeout:20))
        app.tabBars.buttons["连接"].tap()
        app.buttons["computer-rename-"+work].tap()
        app.alerts.textFields.firstMatch.tap();app.alerts.textFields.firstMatch.typeText("公司电脑")
        app.alerts.buttons["保存"].tap()
        XCTAssertTrue(app.staticTexts["当前电脑 · 公司电脑"].waitForExistence(timeout:5))
        app.tabBars.buttons["检索"].tap()
        XCTAssertTrue(app.buttons.containing(NSPredicate(format:"label CONTAINS 'Reference fixture'")).firstMatch.waitForExistence(timeout:10))
        app.tabBars.buttons["聊天"].tap();app.buttons["会话"].tap();app.buttons["Shared fixture chat"].tap()
        XCTAssertTrue(app.navigationBars["Shared fixture chat"].waitForExistence(timeout:10))
        // Start a list refresh on A; its delayed completion must never appear on B.
        app.tabBars.buttons["检索"].tap();_ = try fixture("/hold-items");app.buttons["搜索资料"].tap()
        let second=try fixture("/second/pair.json");app.open(URL(string:second["url"] as! String)!)
        XCTAssertTrue(app.staticTexts["请在 Mac 上核对数字并允许配对"].waitForExistence(timeout:20))
        _ = try fixture("/second/approve");_ = try fixture("/release-items")
        XCTAssertTrue(app.staticTexts["当前电脑 · Home Mac"].waitForExistence(timeout:20),app.debugDescription)
        app.tabBars.buttons["检索"].tap()
        XCTAssertTrue(app.buttons.containing(NSPredicate(format:"label CONTAINS 'Home-only reference'")).firstMatch.waitForExistence(timeout:15))
        XCTAssertFalse(app.buttons.containing(NSPredicate(format:"label CONTAINS 'Reference fixture'")).firstMatch.exists)
        app.tabBars.buttons["聊天"].tap()
        XCTAssertTrue(app.staticTexts["Home private reply"].waitForExistence(timeout:10))
        XCTAssertFalse(app.staticTexts["Desktop context fixture"].exists,"Same chat/message IDs on two Macs must remain isolated")
        app.tabBars.buttons["连接"].tap()
        XCTAssertTrue(app.buttons["computer-select-"+work].exists)
        app.buttons["computer-select-"+work].tap()
        XCTAssertTrue(app.staticTexts["当前电脑 · 公司电脑"].waitForExistence(timeout:10))
        _ = try fixture("/offline")
        app.terminate();app.launch();app.tabBars.buttons["归档"].tap()
        let editor=app.textViews["归档内容"];editor.tap();editor.typeText("Company queued note")
        app.buttons["暂存，连接后发送"].tap()
        XCTAssertTrue(app.staticTexts["Company queued note"].waitForExistence(timeout:5))
        app.tabBars.buttons["聊天"].tap()
        XCTAssertTrue(app.navigationBars["Shared fixture chat"].waitForExistence(timeout:3),"Company chat cache survives switching and restart")
        let input=app.textFields["chat-input"].exists ? app.textFields["chat-input"]:app.textViews["chat-input"]
        input.tap();input.typeText("Company unsent input");app.buttons["完成"].tap()
        app.tabBars.buttons["连接"].tap();app.buttons["computer-select-"+home].tap()
        XCTAssertTrue(app.staticTexts["当前电脑 · Home Mac"].waitForExistence(timeout:10))
        app.tabBars.buttons["归档"].tap();XCTAssertFalse(app.staticTexts["Company queued note"].exists)
        app.tabBars.buttons["聊天"].tap();XCTAssertTrue(app.staticTexts["Home private reply"].waitForExistence(timeout:10))
        let homeInput=app.textFields["chat-input"].exists ? app.textFields["chat-input"]:app.textViews["chat-input"]
        XCTAssertTrue((homeInput.value as? String ?? "").isEmpty || homeInput.value as? String=="发消息，继续这段对话…")
        app.tabBars.buttons["连接"].tap();app.buttons["computer-select-"+work].tap();app.tabBars.buttons["聊天"].tap()
        let restoredInput=app.textFields["chat-input"].exists ? app.textFields["chat-input"]:app.textViews["chat-input"]
        XCTAssertEqual(restoredInput.value as? String,"Company unsent input")
        app.tabBars.buttons["连接"].tap();app.buttons["computer-select-"+home].tap()
        app.terminate();_ = try fixture("/second/offline");app.launch();app.tabBars.buttons["聊天"].tap()
        XCTAssertTrue(app.staticTexts["Home private reply"].waitForExistence(timeout:3),"Home chat cache survives restart while offline")
        app.tabBars.buttons["连接"].tap();app.buttons["computer-select-"+work].tap()
        app.tabBars.buttons["归档"].tap();XCTAssertTrue(app.staticTexts["Company queued note"].waitForExistence(timeout:3))
        _ = try fixture("/online")
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format:"label BEGINSWITH '已连接'")).firstMatch.waitForExistence(timeout:20))
        let gone=NSPredicate(format:"exists == false");expectation(for:gone,evaluatedWith:app.staticTexts["Company queued note"]);waitForExpectations(timeout:15)
        XCTAssertTrue((try fixture("/first/inspect")["titles"] as! [String]).contains("Company queued note"))
        XCTAssertFalse((try fixture("/second/inspect")["titles"] as! [String]).contains("Company queued note"))
        _ = try fixture("/second/online")
        // Cancelling a new approval leaves the active computer and saved list intact.
        app.tabBars.buttons["连接"].tap()
        let repair=try fixture("/second/pair.json");app.open(URL(string:repair["url"] as! String)!)
        XCTAssertTrue(app.staticTexts["当前电脑 · Home Mac"].waitForExistence(timeout:15))
        app.tabBars.buttons["连接"].tap()
        XCTAssertTrue(app.buttons["computer-select-"+work].exists)
        let unapproved=try fixture("/third/pair.json");app.open(URL(string:unapproved["url"] as! String)!)
        XCTAssertTrue(app.buttons["取消添加电脑"].waitForExistence(timeout:20))
        app.buttons["取消添加电脑"].tap()
        XCTAssertTrue(app.staticTexts["当前电脑 · Home Mac"].waitForExistence(timeout:10))
        XCTAssertFalse(app.staticTexts["Unapproved Mac"].exists)
        let canRemove=NSPredicate(format:"enabled == true");expectation(for:canRemove,evaluatedWith:app.buttons["computer-remove-"+home]);waitForExpectations(timeout:10)
        let shot=XCTAttachment(screenshot:app.screenshot());shot.name="Multiple paired computers";shot.lifetime = .keepAlways;add(shot)
        app.buttons["computer-remove-"+home].tap();app.buttons["解除配对"].tap()
        XCTAssertTrue(app.buttons["computer-select-"+work].waitForExistence(timeout:5),"Removing active computer must not remove the other pairing")
        XCTAssertFalse(app.staticTexts["当前电脑 · 公司电脑"].exists,"Removing active computer must not silently send to another Mac")
        app.buttons["computer-select-"+work].tap()
        XCTAssertTrue(app.staticTexts["当前电脑 · 公司电脑"].waitForExistence(timeout:10))
    }
}
