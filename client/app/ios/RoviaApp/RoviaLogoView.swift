import SwiftUI

#if canImport(UIKit)
    import UIKit
    private typealias BrandImage = UIImage
#elseif canImport(AppKit)
    import AppKit
    private typealias BrandImage = NSImage
#endif

/// The Rovia brand mark (`Assets/rovia-logo.png`, bundled as a resource).
///
/// A loose PNG is used instead of an asset catalog on purpose: the Xcode
/// project currently has no `.xcassets` bundle, and adding one by hand would
/// churn the project file. The view resolves the file from the main bundle at
/// runtime and falls back to an SF Symbol so every screen keeps working even
/// if the resource is missing (previews, tests).
struct RoviaLogoView: View {
    enum Size {
        case navigation
        case header
        case emptyState

        var side: CGFloat {
            switch self {
            case .navigation: 28
            case .header: 44
            case .emptyState: 88
            }
        }

        var cornerRadius: CGFloat {
            switch self {
            case .navigation: 7
            case .header: 11
            case .emptyState: 20
            }
        }
    }

    let size: Size

    init(_ size: Size = .header) {
        self.size = size
    }

    var body: some View {
        Group {
            if let image = Self.logoImage() {
                #if canImport(UIKit)
                    Image(uiImage: image)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                #elseif canImport(AppKit)
                    Image(nsImage: image)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                #endif
            } else {
                Image(systemName: "paperplane.circle.fill")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(width: size.side, height: size.side)
        .clipShape(RoundedRectangle(cornerRadius: size.cornerRadius))
        .accessibilityLabel("Rovia logo")
        .accessibilityAddTraits(.isImage)
    }

    private static func logoImage() -> BrandImage? {
        #if canImport(UIKit)
            if let url = Bundle.main.url(forResource: "rovia-logo", withExtension: "png"),
               let image = UIImage(contentsOfFile: url.path)
            {
                return image
            }
            return UIImage(named: "rovia-logo")
        #elseif canImport(AppKit)
            if let url = Bundle.main.url(forResource: "rovia-logo", withExtension: "png"),
               let image = NSImage(contentsOf: url)
            {
                return image
            }
            return nil
        #endif
    }
}
