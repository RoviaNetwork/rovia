// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "RoviaApplePlatform",
    platforms: [
        .iOS(.v17),
        .macOS(.v14)
    ],
    products: [
        .library(name: "RoviaApplePlatform", targets: ["RoviaApplePlatform"]),
        .library(name: "RoviaTunnelRuntime", targets: ["RoviaTunnelRuntime"])
    ],
    targets: [
        .target(name: "RoviaApplePlatform"),
        .target(name: "RoviaTunnelRuntime"),
        .testTarget(name: "RoviaApplePlatformTests", dependencies: ["RoviaApplePlatform"]),
        .testTarget(name: "RoviaTunnelRuntimeTests", dependencies: ["RoviaTunnelRuntime"])
    ]
)
