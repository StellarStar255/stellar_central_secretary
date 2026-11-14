# Stellar Secretary · iPhone companion (first trial)

Native SwiftUI companion for iOS 17 or later. The Mac keeps the library and performs retrieval/model work; the phone does not download a model.

## Try on an iPhone

1. Start the updated desktop source with your existing library. In **Models & settings → Phone connection**, enable the connection. Keep the Mac awake on the same LAN as the phone.
2. Open `StellarSecretary.xcodeproj` in Xcode. Select your own development team in the **StellarSecretary → Signing & Capabilities** settings. Connect the iPhone to the Mac, trust the computer, and enable Developer Mode when requested by iOS.
3. Select the phone as the run destination and run **StellarSecretary**. This is a development installation, not an App Store or TestFlight release.
4. Allow local network and camera access. Scan the Mac QR using the app, compare the six digits, and approve the request on the Mac.
5. Capture notes, links, screenshots or files (10 MB maximum), search the library, ask questions and open cited text. URL captures initially save the link; complete webpage reading on the desktop.

Credentials are saved in the phone Keychain; the QR contains a short-lived invitation and the server certificate fingerprint. Only the fingerprint-matching TLS server is trusted. Desktop APIs, settings, model credentials and arbitrary file downloads are not exposed by the companion listener. Pairing and revocation are available only through the desktop UI. The listener is off by default.

## Reconnection and offline behavior

- Bonjour discovers the paired server while the app is open. The server refreshes advertised addresses when network interfaces change. Networks that isolate clients may prevent connection.
- Pending captures are stored on the phone with data protection, excluded from backup, scoped to the paired server ID and retried on connection. Stable request IDs prevent replayed requests from creating duplicates.
- Keep the Mac awake and the desktop service running. The first trial does not provide cloud sync, remote access, full offline search, background delivery while the app is closed, system share-sheet extensions, or reminder notifications.
- A locally saved file is not guaranteed to survive deleting the app. Do not uninstall with unsent captures.
- Removing a phone on the desktop immediately revokes new requests. Turning off phone connection stops discovery and new connections; already running requests may finish.

## Validation

```sh
.venv/bin/python -m unittest tests.test_mobile -v
.venv/bin/python scripts/check_mobile_ui.py
# Create/boot a dedicated iPhone simulator first; this test uses synthetic data only.
.venv/bin/python scripts/check_mobile_ios.py SIMULATOR_UDID
```

The simulator test runs a loopback control fixture on port 18769 and an authenticated TLS listener with a temporary synthetic knowledge base. It never opens the user's library. Keep screenshots, pairing payloads and generated result bundles outside Git.

Apple references: [Local-network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy), [Server trust authentication](https://developer.apple.com/documentation/foundation/performing-manual-server-trust-authentication).
