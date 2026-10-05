import SwiftUI

/// The scope: a sonar range-instrument that is the tunnel's state. Rings and
/// ticks are the etched face; the sweep rotates only while the engine is
/// working or running; contacts are the fleet's fastest servers, the selected
/// one burning brightest. Nothing here is synthesized — the sweep stops when
/// the engine stops, and a contact exists only for a server the content holds.
///
/// VoiceOver reads the center button and the status text below; the etched
/// face and blips are decorative duplicates of the Servers list and hidden.
struct ScopeView: View {
    let engine: TunnelState
    let contacts: [ServerSummary]
    let selectedServer: ServerID?
    let actionEnabled: Bool
    let action: () -> Void
    let identifier: String
    let actionLabel: String
    let actionHint: String

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// The instrument is a control: it scales with the user's text size, like
    /// the hero ring it replaces.
    @ScaledMetric(relativeTo: .largeTitle) private var scopeSide: CGFloat = 252

    /// The center control marks affordance, not state: phosphor while the
    /// action can be taken, quiet when it cannot.
    private var controlTint: Color {
        actionEnabled ? ScopeTheme.phosphor : ScopeTheme.inkSecondary
    }

    private var sweeping: Bool {
        switch engine {
        case .starting, .connected:
            true
        case .unknown, .unavailable, .idle, .stopping, .failed:
            false
        }
    }
    var body: some View {
        ZStack {
            face
            if sweeping, !reduceMotion {
                TimelineView(.animation) { context in
                    sweepLayer(angle: sweepAngle(at: context.date))
                }
            } else if sweeping {
                // Reduce Motion: the sweep holds as a soft lit sector instead
                // of rotating — the state reads without movement.
                sweepLayer(angle: .degrees(-90))
            }
            contactsLayer
            centerControl
        }
        .frame(width: scopeSide, height: scopeSide)
        .accessibilityElement(children: .contain)
    }

    // MARK: - Etched face

    private var face: some View {
        Canvas { context, size in
            let side = min(size.width, size.height)
            let center = CGPoint(x: size.width / 2, y: size.height / 2)
            let radius = side / 2
            let etched = ScopeTheme.etched

            // Housing.
            let housing = Path(ellipseIn: CGRect(
                x: center.x - radius, y: center.y - radius,
                width: side, height: side
            ))
            context.fill(housing, with: .color(ScopeTheme.housing))
            context.stroke(
                housing,
                with: .color(etched.opacity(0.9)),
                style: StrokeStyle(lineWidth: 1)
            )

            // Range rings at 1/3 and 2/3 of the radius.
            for fraction in [1.0 / 3.0, 2.0 / 3.0] {
                let ringRadius = radius * fraction
                let ring = Path(ellipseIn: CGRect(
                    x: center.x - ringRadius, y: center.y - ringRadius,
                    width: ringRadius * 2, height: ringRadius * 2
                ))
                context.stroke(
                    ring,
                    with: .color(etched.opacity(0.75)),
                    style: StrokeStyle(lineWidth: 1)
                )
            }

            // Tick marks: major every 45°, minor every 15°.
            for tick in 0 ..< 24 {
                let major = tick % 3 == 0
                let angle = Angle.degrees(Double(tick) * 15 - 90)
                let inner = radius * (major ? 0.90 : 0.94)
                var path = Path()
                path.move(to: CGPoint(
                    x: center.x + inner * cos(angle.radians),
                    y: center.y + inner * sin(angle.radians)
                ))
                path.addLine(to: CGPoint(
                    x: center.x + (radius - 1) * cos(angle.radians),
                    y: center.y + (radius - 1) * sin(angle.radians)
                ))
                context.stroke(
                    path,
                    with: .color(etched.opacity(major ? 0.95 : 0.55)),
                    style: StrokeStyle(lineWidth: major ? 1.5 : 1, lineCap: .round)
                )
            }

            // Crosshair.
            for angle in [Angle.zero, .degrees(90)] {
                var path = Path()
                path.move(to: CGPoint(
                    x: center.x + radius * 0.14 * cos(angle.radians),
                    y: center.y + radius * 0.14 * sin(angle.radians)
                ))
                path.addLine(to: CGPoint(
                    x: center.x + radius * 0.86 * cos(angle.radians),
                    y: center.y + radius * 0.86 * sin(angle.radians)
                ))
                context.stroke(
                    path,
                    with: .color(etched.opacity(0.35)),
                    style: StrokeStyle(lineWidth: 1, dash: [2, 4])
                )
            }
        }
        .accessibilityHidden(true)
    }

    // MARK: - Sweep

    private func sweepAngle(at date: Date) -> Angle {
        // One revolution per 2.4s while working, slower once locked.
        let locked: Bool = if case .connected = engine { true } else { false }
        let period: Double = locked ? 6.0 : 2.4
        let phase = date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: period) / period
        return .degrees(phase * 360 - 90)
    }

    private func sweepLayer(angle: Angle) -> some View {
        Circle()
            .fill(
                AngularGradient(
                    stops: [
                        .init(color: ScopeTheme.sweep.opacity(0.30), location: 0),
                        .init(color: ScopeTheme.sweep.opacity(0.10), location: 0.18),
                        .init(color: .clear, location: 0.42),
                    ],
                    center: .center,
                    startAngle: .degrees(0),
                    endAngle: .degrees(151.2) // 0.42 of a turn: the trail dies out
                )
            )
            .rotationEffect(angle)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }

    // MARK: - Contacts

    /// Latency maps to range: a fast server sits close, a slow one far, an
    /// unmeasured one at the dim outer band. Angle is the server's index —
    /// stable across redraws so a rerank reads as motion, not a shuffle.
    private func contactPosition(
        for server: ServerSummary,
        at index: Int,
        in size: CGSize
    ) -> CGPoint {
        let count = max(contacts.count, 1)
        let angle = Angle.degrees(Double(index) * (360.0 / Double(count)) - 90)
        let fraction: Double = switch server.latency.quality {
        case .good: 0.42
        case .fair: 0.58
        case .poor: 0.72
        case .unavailable: 0.86
        }
        let radius = min(size.width, size.height) / 2 * fraction
        return CGPoint(
            x: size.width / 2 + radius * cos(angle.radians),
            y: size.height / 2 + radius * sin(angle.radians)
        )
    }

    private var contactsLayer: some View {
        GeometryReader { geometry in
            ForEach(Array(contacts.enumerated()), id: \.element.id) { index, server in
                let selected = server.id == selectedServer
                let position = contactPosition(for: server, at: index, in: geometry.size)
                ZStack {
                    if selected {
                        // The locked contact: a steady ring, the one thing on
                        // the face allowed to burn.
                        Circle()
                            .stroke(ScopeTheme.phosphor, lineWidth: 1.5)
                            .frame(width: 18, height: 18)
                    }
                    Circle()
                        .fill(selected ? ScopeTheme.phosphor : ScopeTheme.qualityTint(server.latency.quality).opacity(0.55))
                        .frame(width: selected ? 7 : 5, height: selected ? 7 : 5)
                }
                .position(position)
                .animation(reduceMotion ? nil : ScopeTheme.stateChange, value: server.latency)
                .animation(reduceMotion ? nil : ScopeTheme.stateChange, value: selectedServer)
                .accessibilityHidden(true)
            }
        }
        .allowsHitTesting(false)
    }

    // MARK: - Center control

    private var centerControl: some View {
        Button(action: action) {
            ZStack {
                Circle()
                    .fill(ScopeTheme.ground)
                    .overlay(
                        Circle().stroke(
                            controlTint,
                            lineWidth: 2
                        )
                    )
                Image(systemName: "power")
                    .font(.system(.title, weight: .semibold))
                    .foregroundStyle(controlTint)
            }
            .contentShape(Circle())
        }
        .buttonStyle(ScopePressStyle(enabled: actionEnabled))
        .frame(width: scopeSide * 0.34, height: scopeSide * 0.34)
        .disabled(!actionEnabled)
        .accessibilityLabel(actionLabel)
        .accessibilityHint(actionHint)
        .accessibilityIdentifier(identifier)
    }
}

/// A press is felt, not seen leaving: a short scale under the finger and the
/// ring brightens. No bounce on entry — the instrument is already there.
private struct ScopePressStyle: ButtonStyle {
    let enabled: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed && enabled ? 0.94 : 1)
            .opacity(configuration.isPressed && enabled ? 0.92 : 1)
            .animation(ScopeTheme.press, value: configuration.isPressed)
    }
}
