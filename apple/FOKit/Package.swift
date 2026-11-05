// swift-tools-version: 6.0
// FOKit: the code the Mac and iOS apps share. It talks to `fo serve` over HTTP only and
// never reads office files.
import PackageDescription

let package = Package(
    name: "FOKit",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [
        .library(name: "FOKit", targets: ["FOKit"])
    ],
    targets: [
        .target(name: "FOKit"),
        .testTarget(
            name: "FOKitTests",
            dependencies: ["FOKit"],
            resources: [.copy("Fixtures")]
        ),
    ],
    swiftLanguageModes: [.v6]
)
