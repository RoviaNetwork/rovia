import SwiftUI

#if canImport(UIKit)
    import UIKit
#endif

/// The Scope world's tokens. One instrument grammar for the whole app:
/// etched range rings, phosphor mint reserved for what is actionable or
/// locked, tabular figures for real measurements, amber for transition and
/// red for failure — never decoration.
///
/// No asset catalog exists in this project on purpose (see RoviaLogoView),
/// so every color here is a dynamic-provider color: Dark Mode and Increase
/// Contrast adapt without a single asset file.
enum ScopeTheme {
    // MARK: - Palette

    /// Deep ink. The dark scene: a scope in a dim room, read at arm's length.
    static let ground = Color(dynamicLight: 0xF2F6F3, dark: 0x060D0B)
    /// The instrument housing: a half-step off the ground.
    static let housing = Color(dynamicLight: 0xFFFFFF, dark: 0x0B1714)
    /// Etched lines: range rings, ticks, separators.
    static let etched = Color(dynamicLight: 0xB9CFC6, dark: 0x1E3A32)
    /// Phosphor mint. The accent — only where something can be done, or on
    /// the locked (selected) contact.
    static let phosphor = Color(dynamicLight: 0x097B5C, dark: 0x3DF0A8)
    /// The sweep: cool cyan, always used at low alpha.
    static let sweep = Color(dynamicLight: 0x0B9E77, dark: 0x5EEAD4)
    /// Primary reading on the ground.
    static let ink = Color(dynamicLight: 0x0C1A16, dark: 0xE6F4EE)
    /// Secondary reading: tinted from the phosphor, never plain gray.
    static let inkSecondary = Color(dynamicLight: 0x41635A, dark: 0x8FB8AC)
    /// Transition: starting, stopping, reasserting.
    static let warn = Color(dynamicLight: 0xB26A00, dark: 0xFFB454)
    /// Failure.
    static let alarm = Color(dynamicLight: 0xC43D3D, dark: 0xFF6B6B)

    // MARK: - Roles

    /// The tint a state wears. Unknown/idle stay quiet; only a live or
    /// failing engine earns color.
    static func stateTint(_ engine: TunnelState) -> Color {
        switch engine {
        case .connected:
            phosphor
        case .starting, .stopping:
            warn
        case .failed, .unavailable:
            alarm
        case .unknown, .idle:
            inkSecondary
        }
    }

    static func qualityTint(_ quality: LatencyState.Quality) -> Color {
        switch quality {
        case .good:
            phosphor
        case .fair:
            warn
        case .poor:
            alarm
        case .unavailable:
            inkSecondary
        }
    }

    // MARK: - Type

    /// Measurements (milliseconds, counters) set tabular: figures that
    /// rerank without the line jumping.
    static func measurement(_ style: Font.TextStyle = .body, weight: Font.Weight = .regular) -> Font {
        .system(style, design: .monospaced, weight: weight)
    }

    // MARK: - Motion

    /// One authored spring for presses; entries never bounce.
    static let press = Animation.spring(response: 0.32, dampingFraction: 0.72)
    /// State changes crossfade — no sliding chrome.
    static let stateChange = Animation.easeOut(duration: 0.22)
}

private extension Color {
    /// A dynamic color from two sRGB hex values. Increase Contrast deepens
    /// the dark ground and brightens the phosphor so etched lines stay
    /// legible under the accessibility setting.
    init(dynamicLight light: UInt32, dark: UInt32) {
        #if canImport(UIKit)
            self.init(uiColor: UIColor { traits in
                let hex: UInt32
                switch (traits.userInterfaceStyle, traits.accessibilityContrast) {
                case (.dark, .high):
                    hex = ScopeThemeHex.highContrast(dark)
                case (_, .high):
                    hex = ScopeThemeHex.highContrast(light)
                case (.dark, _):
                    hex = dark
                default:
                    hex = light
                }
                return UIColor(
                    red: CGFloat((hex >> 16) & 0xFF) / 255,
                    green: CGFloat((hex >> 8) & 0xFF) / 255,
                    blue: CGFloat(hex & 0xFF) / 255,
                    alpha: 1
                )
            })
        #else
            self.init(
                red: Double((light >> 16) & 0xFF) / 255,
                green: Double((light >> 8) & 0xFF) / 255,
                blue: Double(light & 0xFF) / 255
            )
        #endif
    }
}

private enum ScopeThemeHex {
    /// Nudges a color away from its ground under Increase Contrast: dark
    /// colors go darker, light colors go lighter, and the saturated phosphor
    /// family keeps its hue but gains separation.
    static func highContrast(_ hex: UInt32) -> UInt32 {
        func clamp(_ v: Int) -> UInt32 { UInt32(max(0, min(255, v))) }
        let r = Int((hex >> 16) & 0xFF)
        let g = Int((hex >> 8) & 0xFF)
        let b = Int(hex & 0xFF)
        let luminance = (r * 299 + g * 587 + b * 114) / 1000
        let delta = luminance < 128 ? -28 : 28
        let packed = (clamp(r + delta) << 16) | (clamp(g + delta) << 8) | clamp(b + delta)
        return packed
    }
}
