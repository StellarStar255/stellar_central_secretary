// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "CompanionPairing", products: [.library(name: "CompanionPairing", targets: ["CompanionPairing"])], targets: [
    .target(name: "CompanionPairing", path: "StellarSecretary", exclude: ["Companion.swift", "Views.swift", "Info.plist", "Assets.xcassets"], sources: ["PairingCode.swift"]),
    .testTarget(name: "PairingTests", dependencies: ["CompanionPairing"], path: "PairingTests")
])
