# Stellar Secretary · iPhone companion (first trial)

Native SwiftUI companion for iOS 17 or later. The Mac keeps the library and performs retrieval/model work; the phone does not download a model.

## Try on an iPhone

1. Start the updated desktop source with your existing library. In **Models & settings → Phone connection**, enable the connection. Keep the Mac awake on the same LAN as the phone.
2. Open `StellarSecretary.xcodeproj` in Xcode. Select your own development team in the **StellarSecretary → Signing & Capabilities** settings. Connect the iPhone to the Mac, trust the computer, and enable Developer Mode when requested by iOS.
3. Select the phone as the run destination and run **StellarSecretary**. This is a development installation, not an App Store or TestFlight release.
4. Allow local network, Bluetooth (if requested) and camera access. Scan the Mac QR using the app, compare the six digits, and approve the request on the Mac.
5. Capture notes, links, screenshots or files (10 MB maximum), search the library, ask questions and open cited text. In a record detail, open original links and archived files from the top, edit its title, add individual tag chips or confirm removal of an existing tag, or append a photo/file to the same record. Edits detect concurrent changes, and attachment retries do not create duplicate batches. Images automatically show a small JPEG preview (at most 96 KB) inline in the detail page without requiring a separate view action; background preview loading does not block metadata editing. A separate original action preserves the complete file. Authenticated original downloads show byte progress and can be cancelled. Completed downloads and image previews are reused from a protected, bounded iPhone cache; they are invalidated when the archived file changes. Original files open in a native preview after the download. URL captures initially save the link; complete webpage reading on the desktop.

Credentials are saved in the phone Keychain; the QR contains a short-lived invitation and the server certificate fingerprint. Only the fingerprint-matching TLS server is trusted. Desktop APIs, settings, model credentials and arbitrary file downloads are not exposed by the companion listener. Pairing and revocation are available only through the desktop UI. The listener is off by default.

## Reconnection and offline behavior

- The Mac source needs its nearby carrier built once: `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer .venv/bin/python packaging/build_peer_bridge.py`. Packaged Mac builds include this component automatically.
- Ordinary LAN access races a Network-framework TCP carrier with Apple peer-to-peer Wi-Fi enabled. The client scopes connections to discovered Wi-Fi/AWDL interfaces, excluding USB Ethernet as a substitute. It stops browsing before connecting to avoid disrupting AWDL traffic. A CoreBluetooth GATT carrier provides an independent fallback without IP routing. The phone remembers the last verified carrier and prioritizes it on reopening; USB link-local addresses do not take priority. Bluetooth transfers are slower than Wi-Fi, so Wi-Fi remains useful for larger attachments. Keep Wi-Fi enabled on both devices; availability still depends on permissions and radio/network conditions. These paths do not require changing global VPN or proxy settings.
- Both carriers preserve end-to-end TLS certificate pinning and the same Mac-approved device credentials. Nearby peers do not gain access merely by being discovered. The relay only forwards to the mobile gateway, never desktop APIs.
- A short app switch reuses a working pinned TLS session. After at least 20 seconds in the background (the gateway HTTP idle deadline), the app rebuilds its TLS session, radio relays and service discovery using the saved pairing. It cancels the previous connection attempt and ignores late results from that attempt. A live upload or question is allowed to finish before the pending rebuild; queued captures remain on the phone.
- Reopening the app starts discovery and reconnects with the saved credentials. A working transport remains selected during uploads and questions. The mobile gateway reuses its port on restart when available, and refreshes discovery when interfaces change.
- Pending captures are stored on the phone with data protection, excluded from backup, scoped to the paired server ID and retried on connection. Stable request IDs prevent replayed requests from creating duplicates.
- Keep the Mac awake and the desktop service running. The first trial does not provide cloud sync, remote access, full offline search, background delivery while the app is closed, system share-sheet extensions, or reminder notifications.
- A locally saved file is not guaranteed to survive deleting the app. Do not uninstall with unsent captures.
- Removing a phone on the desktop immediately revokes new requests. Turning off phone connection stops discovery and new connections; already running requests may finish.

## Library list cache

The phone keeps the last successful list results (titles and summaries) for up to eight queries, scoped to the paired Mac ID and pinned certificate. Opening the library displays that snapshot immediately, including after restarting offline. Results less than a minute old are reused; older results refresh in the background. Pull to refresh or use Search to update immediately. A failed update keeps the previous list, and successful phone captures mark the cache for refresh. The cache is protected on the phone, excluded from backup, and cleared when unpairing; original documents and AI answers are not cached.

## Shared desktop chat

The **聊天** tab opens the desktop's existing conversations. Choose a thread from **会话**, continue it on either device, or create a new one. **问知识库** in Search opens this same shared chat. Retrieval, model requests, retained context and final transcript storage stay on the Mac. Source citations open the existing record details. The phone displays partial answers and can stop an active answer; closing the phone app leaves accepted questions running on the Mac.

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
