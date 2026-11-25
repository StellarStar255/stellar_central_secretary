# Stellar Secretary · iPhone companion (first trial)

Native SwiftUI companion for iOS 17 or later. The Mac keeps the library and performs retrieval/model work; the phone does not download a model.

## Try on an iPhone

1. Start the updated desktop source with your existing library. In **Models & settings → Phone connection**, enable the connection. Keep the Mac awake on the same LAN as the phone.
2. Open `StellarSecretary.xcodeproj` in Xcode. Select your own development team in the **StellarSecretary → Signing & Capabilities** settings. Connect the iPhone to the Mac, trust the computer, and enable Developer Mode when requested by iOS.
3. Select the phone as the run destination and run **StellarSecretary**. This is a development installation, not an App Store or TestFlight release.
4. Allow local network, Bluetooth (if requested) and camera access. Scan the Mac QR using the app, compare the six digits, and approve the request on the Mac.
5. Capture notes, links, screenshots or files (10 MB maximum), search the library, ask questions and open cited text. In a record detail, open original links and archived files from the top, edit its title, add individual tag chips or confirm removal of an existing tag, or append a photo/file to the same record. Edits detect concurrent changes, and attachment retries do not create duplicate batches. Images automatically show a small JPEG preview (at most 96 KB) inline in the detail page without requiring a separate view action; background preview loading does not block metadata editing. A separate original action preserves the complete file. Authenticated original downloads show byte progress and can be cancelled. Completed downloads and image previews are reused from a protected, bounded iPhone cache; they are invalidated when the archived file changes. Original files open in a native preview after the download. URL captures initially save the link; complete webpage reading on the desktop.

Credentials are saved in the phone Keychain; the QR contains a short-lived invitation and the server certificate fingerprint. Only the fingerprint-matching TLS server is trusted. Desktop APIs, settings, model credentials and arbitrary file downloads are not exposed by the companion listener. Pairing and revocation are available only through the desktop UI. The listener is off by default.

From the iOS share sheet, choose Stellar Secretary to send a file to the selected paired Mac or keep it on the phone. If delivery fails, retry from the extension or open Archive later.

## App Review demo

On the unpaired welcome screen, tap **演示模式 / Demo**. Reviewers can search the sample library, open a record, and save a note or link under **Archive**. Under **Chat**, tap **Ask** to see a quoted answer and open its source. Demo changes are discarded when the demo closes. It does not connect to a computer or call an AI service.

The demo covers those sample workflows. For the connected workflows, including pairing, attachment transfer, and shared chat, prepare a recording of the iPhone and Mac using a synthetic library and provide pairing instructions in App Review Information.

### App Store privacy copy (draft)

Stellar Secretary for iPhone connects to a desktop library you pair and approve. It uses the camera to scan a pairing code and uses local network access and Bluetooth to discover and connect to nearby computers. The app sends the notes, links, attachments, and questions you choose to submit to your selected computer. Your pairing credential is stored in the iPhone Keychain. The phone keeps local copies of recent results and downloaded files for quicker access, and keeps unsent submissions until they can be sent or you remove them.

The desktop computer stores the library. Phone uploads and appended files are saved without an automatic AI summary by default. You can summarize them on the desktop or separately approve automatic summaries under **连接 → 隐私与 AI**. With that approval and desktop automatic summaries enabled, new uploads can send text, file excerpts or images to the displayed model service. Changing the model destination requires approval for that destination. If local semantic indexing is enabled, the desktop uses its configured local embedding service.

To send questions from the phone, first approve the displayed model service under **连接 → 隐私与 AI**. The desktop may send your question, relevant conversation history, and relevant excerpts or images to that service. The provider’s data handling terms apply. Approval is scoped to the phone, computer and model destination. You can withdraw approval in the same screen. Withdrawal blocks later calls and does not recall data already sent. Update the desktop companion before using mobile writes so these rules can be enforced.

The **Archive** tab shows the outbox and up to eight recent upload receipts for the paired phone. It shows when originals are saved, a summary is running or complete, and any processing failure. The phone keeps the last checked receipt titles and statuses locally for offline display. The sample demo works locally with synthetic records and discards its changes when closed.

Before publication, confirm the publisher and privacy contact, publish the policy at a public URL and link to it in the app and App Store Connect.

### App Store listing (draft)

**名称**　Stellar Secretary 知识秘书

**副标题**　随手归档，检索电脑知识库

**描述**　用 iPhone 把网页链接、笔记、照片和文件存入自己的 Stellar Secretary 知识库。扫码连接已运行知识秘书的电脑，搜索归档、查看原件，或继续电脑上的对话。发送 AI 问答前，你可以查看并确认电脑当前使用的模型服务。连接暂时中断时，手机会保留待发送内容，恢复连接后继续提交。

正式使用需配对运行 Stellar Secretary v0.1.123 或以上版本的电脑，电脑需开机且手机能通过局域网或附近连接访问它。首次打开可进入演示模式，用样例资料试用归档、检索和带来源的回答。

**App Review notes**　On a fresh install, choose **演示模式 / Demo** from the welcome screen. In **Library**, open “Rain garden checklist.” In **Archive**, save a sample note and find it in the library. In **Chat**, select **Ask** and open the cited record. The sample workspace is cleared when closed. For the live features, use the desktop companion and the pairing and file transfer recording that accompanies the submission.

## Interface language

In the iPhone app, open **Connection → Display Language** (「连接 → 显示语言」) and choose **English** or **简体中文**. The welcome screen also offers this setting before pairing. The choice is saved on this iPhone and applies immediately. Your library content and computer names keep their original wording.

## Multiple computers and phones

Each desktop can approve up to ten phones independently. The phone's **连接 → 添加电脑** saves up to ten computers without replacing an existing pairing. Approve each computer once, optionally give it a local name such as 公司电脑 or 家里电脑, then use **使用这台电脑** to switch. The current computer appears on capture, chat and library screens. Reopening the app reconnects to the last selected computer; it never silently switches to another reachable computer.

Each computer keeps its own library and chats. Phone list/chat caches, attachment identities and offline queues are separated by computer ID and pinned certificate. Switching computers preserves queued content for its original destination and the in-memory editor contents. Submissions and downloads must finish or be cancelled before switching; an answer already accepted by a desktop continues there. Removing a computer affects only its phone credential and does not automatically select another computer. Its queued content and caches remain on the phone and become available after pairing the same computer and certificate again; revoke phone access separately on that desktop. This feature does not synchronize desktop libraries or add internet remote access. Existing single-computer credentials and caches migrate automatically when upgrading the phone app in place.

## Reconnection and offline behavior

- The Mac source needs its nearby carrier built once: `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer .venv/bin/python packaging/build_peer_bridge.py`. Packaged Mac builds include this component automatically.
- Ordinary LAN access races a Network-framework TCP carrier with Apple peer-to-peer Wi-Fi enabled. The client scopes connections to discovered Wi-Fi/AWDL interfaces, excluding USB Ethernet as a substitute. It stops browsing before connecting to avoid disrupting AWDL traffic. A CoreBluetooth GATT carrier provides an independent fallback without IP routing. The phone remembers the last verified carrier and prioritizes it on reopening; USB link-local addresses do not take priority. Bluetooth transfers are slower than Wi-Fi, so Wi-Fi remains useful for larger attachments. Keep Wi-Fi enabled on both devices; availability still depends on permissions and radio/network conditions. These paths do not require changing global VPN or proxy settings.
- Both carriers preserve end-to-end TLS certificate pinning and the same Mac-approved device credentials. Nearby peers do not gain access merely by being discovered. The relay only forwards to the mobile gateway, never desktop APIs.
- A short app switch reuses a working pinned TLS session. After at least 20 seconds in the background (the gateway HTTP idle deadline), the app rebuilds its TLS session, radio relays and service discovery using the saved pairing. It cancels the previous connection attempt and ignores late results from that attempt. A live upload or question is allowed to finish before the pending rebuild; queued captures remain on the phone.
- Reopening the app starts discovery and reconnects with the saved credentials. A working transport remains selected during uploads and questions. The mobile gateway reuses its port on restart when available, and refreshes discovery when interfaces change.
- Pending captures are stored on the phone with data protection, excluded from backup, scoped to the paired server ID and retried on connection. Stable request IDs prevent replayed requests from creating duplicates.
- Keep the Mac awake and the desktop service running. The first trial does not provide cloud sync, remote access, full offline search, background delivery while the app is closed, or reminder notifications.
- A locally saved file is not guaranteed to survive deleting the app. Do not uninstall with unsent captures.
- Removing a phone on the desktop immediately revokes new requests. Turning off phone connection stops discovery and new connections; already running requests may finish.

## Library list cache

The phone keeps the last successful list results (titles and summaries) for up to eight queries per computer, scoped to the Mac ID and pinned certificate. Opening the library displays that snapshot immediately, including after restarting offline. Results less than a minute old are reused; older results refresh in the background. Pull to refresh or use Search to update immediately. A failed update keeps the previous list, and successful phone captures mark the cache for refresh. The cache is protected on the phone and excluded from backup; original documents and AI answers are not stored in the list cache.

## Shared desktop chat

The **聊天** tab opens the desktop's existing conversations. Choose a thread from **会话**, continue it on either device, or create a new one. Use **+** in the composer to attach one screenshot, photo, or file up to 10 MB. The desktop saves the original and answers about the attachment and accompanying message using the chat model authorization. **问知识库** in Search opens the same shared chat. Retrieval, model requests, retained context and final transcript storage stay on the Mac. Source citations open the existing record details. The phone displays partial text answers and can stop an active answer; closing the phone app leaves accepted questions running on the Mac.

Cached transcripts appear immediately, including offline. The phone protects and excludes from backup the latest 100 messages in up to five cached threads, scoped to the paired Mac and certificate. Older messages load on demand. Offline messages for an existing thread are durably queued and retried on reconnect with a stable request ID, so a lost acknowledgement does not run the question twice. New conversations require a connection. Keep the Mac awake and its service running; this does not provide internet remote access.

## Validation

```sh
.venv/bin/python -m unittest tests.test_mobile -v
.venv/bin/python scripts/check_mobile_ui.py
# Create/boot a dedicated simulator named "Stellar Secretary Trial"; synthetic data only.
.venv/bin/python scripts/check_mobile_ios.py SIMULATOR_UDID
```

The simulator test runs a loopback control fixture on port 18769 and an authenticated TLS listener with a temporary synthetic knowledge base. It never opens the user's library. Keep screenshots, pairing payloads and generated result bundles outside Git.

The native transport fixture additionally checks BLE framing across GATT MTUs and repeated authenticated requests over one pinned TLS connection: `.venv/bin/python scripts/check_wifi_tls.py`.

Apple references: [Local-network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy), [Server trust authentication](https://developer.apple.com/documentation/foundation/performing-manual-server-trust-authentication).
