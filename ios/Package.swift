// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "CompanionPairing", platforms: [.macOS(.v12), .iOS(.v17)], products: [.library(name: "CompanionPairing", targets: ["CompanionPairing"])], targets: [
    .target(name: "CompanionPairing", path: "StellarSecretary", exclude: ["Companion.swift", "Views.swift", "ReviewDemoView.swift", "en.lproj", "zh-Hans.lproj", "Info.plist", "Assets.xcassets"], sources: ["PairedComputers.swift", "ChatStore.swift", "LibraryCache.swift", "PairingCode.swift", "PairingNetwork.swift", "WiFiRelay.swift", "BluetoothRelay.swift"]),
    .testTarget(name: "PairingTests", dependencies: ["CompanionPairing"], path: "PairingTests")
])
