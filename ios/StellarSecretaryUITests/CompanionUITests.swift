import XCTest

final class CompanionUITests: XCTestCase {
    func fixture(_ path:String) throws -> [String:Any] {
        let done = expectation(description:path);var result: [String:Any] = [:];var failure: Error?
        URLSession.shared.dataTask(with:URL(string:"http://127.0.0.1:18769"+path)!) { data,_,error in
            failure = error;if let data { result = (try? JSONSerialization.jsonObject(with:data)) as? [String:Any] ?? [:] };done.fulfill()
        }.resume();wait(for:[done],timeout:15);if let failure { throw failure };return result
    }
    @MainActor func testPairCaptureSearchAndOfflineOutbox() throws {
        continueAfterFailure = false
        let app = XCUIApplication();app.launch()
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
        let editor = app.textViews["归档内容"];editor.tap();editor.typeText("Mobile fixture unique note")
        app.buttons["保存到知识库"].tap()
        let empty = NSPredicate(format:"value == ''");expectation(for:empty,evaluatedWith:editor);waitForExpectations(timeout:20)
        app.tabBars.buttons["检索"].tap()
        XCTAssertEqual(try fixture("/count")["count"] as? Int,2)
        let row = app.buttons.containing(NSPredicate(format:"label CONTAINS 'Mobile fixture unique note'")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout:20),app.debugDescription)
        row.tap()
        XCTAssertTrue(app.navigationBars["资料详情"].waitForExistence(timeout:10));app.navigationBars.buttons.firstMatch.tap()
        let search = app.textFields["搜索资料或输入问题"];search.tap();search.typeText("fixture")
        app.buttons["问知识库"].tap();XCTAssertTrue(app.staticTexts["Synthetic fixture answer [1]"].waitForExistence(timeout:20))
        _ = try fixture("/offline")
        app.tabBars.buttons["归档"].tap()
        XCTAssertTrue(app.buttons["暂存，连接后发送"].waitForExistence(timeout:20))
        editor.tap();editor.typeText("Offline fixture note");app.buttons["暂存，连接后发送"].tap()
        app.terminate();app.launch();XCTAssertTrue(app.staticTexts["Offline fixture note"].waitForExistence(timeout:20))
        _ = try fixture("/online")
        app.tabBars.buttons["连接"].tap();app.buttons["重新连接"].tap()
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format:"label BEGINSWITH '已连接'")).firstMatch.waitForExistence(timeout:20))
        app.tabBars.buttons["归档"].tap()
        let sent = NSPredicate(format:"exists == false");expectation(for:sent,evaluatedWith:app.staticTexts["Offline fixture note"]);waitForExpectations(timeout:20)
        XCTAssertEqual(try fixture("/count")["count"] as? Int,3)
        let screenshot = XCTAttachment(screenshot:app.screenshot());screenshot.name = "Paired iPhone capture";screenshot.lifetime = .keepAlways;add(screenshot)
    }
}
