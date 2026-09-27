import Foundation
import RoviaConfig
import RoviaRouting

/// Why the app could not hand its display models to the canonical route model.
///
/// The canonical model identifies groups and rules by `UUID` and refuses input it
/// cannot evaluate. The app must not paper over either: a fabricated identifier
/// or a swallowed evaluation error would put a second, quieter answer on screen.
enum CanonicalRouteBridgeError: Error, Equatable, CustomStringConvertible {
    case notACanonicalIdentifier(String)
    case notACanonicalMatcher(String)
    case notACanonicalOutcome(String)
    case ruleOrderMismatch(rule: String, declaredIndex: Int, canonicalIndex: Int)
    case evaluationRefused(String)
    /// The bridge and the canonical model disagree about the shape of an answer.
    ///
    /// This is not a content problem and not a user-visible failure. It is the
    /// typed form of a branch that no content can reach: `explain` returns one
    /// rule diagnostic per rule of the route set it was given, in order, each
    /// carrying that rule's identifier. If it ever does not, the bridge's
    /// rendering is wrong rather than the content's, and saying so by name beats
    /// an index-out-of-range or a silently wrong screen.
    case unreachableInvariant(String)

    var description: String {
        switch self {
        case let .notACanonicalIdentifier(identifier):
            "identifier is not a canonical UUID: \(identifier)"
        case let .notACanonicalMatcher(description):
            "matcher cannot be represented canonically: \(description)"
        case let .notACanonicalOutcome(description):
            "route outcome cannot be represented canonically: \(description)"
        case let .ruleOrderMismatch(rule, declaredIndex, canonicalIndex):
            "rule \(rule) declares index \(declaredIndex) but the canonical model returned it at \(canonicalIndex)"
        case let .evaluationRefused(reason):
            "the canonical route evaluator refused the input: \(reason)"
        case let .unreachableInvariant(detail):
            "the bridge and the canonical route model disagree: \(detail)"
        }
    }
}

/// The app's only route evaluator.
///
/// The app used to carry its own matcher comparison, host normalization, and
/// IPv4 CIDR containment. That was a second implementation of
/// `RoviaRouting.RouteEvaluator` and it could disagree with the canonical one
/// without any gate noticing. It is gone: this bridge converts the display
/// models into the canonical input types, asks the canonical evaluator, and
/// converts the canonical `RoutingDiagnostic` back into the display models the
/// debugger renders.
///
/// Two properties are deliberate:
///
/// * the bridge never decides anything. Every match, every "first match", and
///   every reason code on screen comes from `RoutingDiagnostic`, so the
///   debugger and the configuration loader cannot tell different stories; and
/// * the bridge never falls back. Content whose identifiers or matchers the
///   canonical model cannot represent is refused, because the alternative is a
///   second implementation creeping back in behind a guard.
enum CanonicalRouteBridge {
    private static let evaluator = RouteEvaluator()

    /// The canonical route set for the content the app is showing.
    static func routeSet(for content: AppContent) throws -> RouteSet {
        var rules: [RouteRule] = []
        rules.reserveCapacity(content.routeRules.count)
        for rule in content.routeRules {
            rules.append(
                RouteRule(
                    id: try canonicalIdentifier(rule.id),
                    enabled: rule.isEnabled,
                    matchers: try rule.matchers.map(canonicalMatcher),
                    action: try canonicalAction(rule.action),
                    note: rule.note
                )
            )
        }
        return RouteSet(rules: rules, defaultAction: try canonicalAction(content.defaultRoute))
    }

    /// The canonical evaluation context for the content the app is showing.
    ///
    /// `selectedServers` is empty on purpose: the sample content carries no
    /// canonical server identifiers, and the debugger explains a route rather
    /// than a server choice. The group set is complete, because the canonical
    /// evaluator refuses an action that names a group it does not know.
    static func context(for content: AppContent) throws -> RouteEvaluationContext {
        RouteEvaluationContext(
            knownGroupIDs: Set(try content.groups.map { try canonicalIdentifier($0.id) }),
            selectedServers: [:]
        )
    }

    /// The canonical input for one of the content's built-in samples.
    ///
    /// The user types nothing: the debugger has no text field, and the only
    /// input it evaluates is a sample compiled into the app. That is why
    /// `PRIVACY.md` has no redaction limit to state for the debugger today.
    static func canonicalInput(for input: DebugInput) -> RouteInput {
        RouteInput(host: input.host, ip: input.ip, port: input.port, network: input.network)
    }

    /// Explains one debugger sample with the canonical evaluator and renders the
    /// answer as the display model the debugger shows.
    static func evaluation(sample: DebugSampleSummary, content: AppContent) throws -> DebugEvaluation {
        // Three typed invariants stand between the display models and the
        // canonical model. They are stated, not assumed:
        //
        // 1. every group and rule identifier in the content is a canonical UUID,
        //    so nothing here has to invent one;
        // 2. the canonical model returns exactly one rule diagnostic per rule the
        //    route set was built from, in the same order; and
        // 3. each rule diagnostic carries the rule's UUID, so the diagnostic can
        //    be read back against the content it came from.
        //
        // Invariant 2 and 3 are consequences of how `explain` is written, so a
        // violation is not a runtime condition to handle — it is a contradiction
        // between this file and the package. Throwing `unreachableInvariant` says
        // exactly that, and it is deliberately a distinct case from the refusals
        // above: a refusal means the content is not representable, and this means
        // the bridge and the package disagree.
        let diagnostic = try explain(sample: sample, content: content)
        try require(
            diagnostic.rules.count == content.routeRules.count,
            .unreachableInvariant(
                "the canonical evaluator returned \(diagnostic.rules.count) rules for a route set of \(content.routeRules.count)"
            )
        )
        for (offset, rule) in diagnostic.rules.enumerated() {
            let displayRule = content.routeRules[offset]
            try require(
                displayRule.id == rule.ruleID.uuidString,
                .unreachableInvariant("the canonical evaluator returned a rule the content does not contain")
            )
            try require(
                displayRule.index == offset,
                .ruleOrderMismatch(
                    rule: displayRule.id,
                    declaredIndex: displayRule.index,
                    canonicalIndex: offset
                )
            )
        }

        let steps: [DebugStep] = diagnostic.rules.enumerated().map { offset, rule in
            DebugStep(
                ruleIndex: offset,
                ruleID: content.routeRules[offset].id,
                isEnabled: rule.enabled,
                matched: rule.matched,
                appliedMatcherIndex: rule.matchers.firstIndex { $0.applied },
                evaluatedMatcherCount: rule.matchers.count,
                reason: displayReason(rule.reasonCode)
            )
        }

        return DebugEvaluation(
            sampleID: sample.id,
            sampleLabel: sample.label,
            inputPresence: presenceSummary(diagnostic.inputSummary),
            decision: displayOutcome(diagnostic.finalDecision),
            selectedGroupID: diagnostic.selectedGroup?.uuidString,
            appliedRuleIndex: diagnostic.rules.firstIndex { $0.selected },
            steps: steps,
            isSampleData: content.isSampleData
        )
    }

    /// The canonical diagnostic for one sample, or the refusal that replaced it.
    private static func explain(
        sample: DebugSampleSummary,
        content: AppContent
    ) throws -> RoutingDiagnostic {
        do {
            return try evaluator.explain(
                canonicalInput(for: sample.input),
                using: routeSet(for: content),
                context: context(for: content)
            )
        } catch {
            throw CanonicalRouteBridgeError.evaluationRefused(String(describing: error))
        }
    }

    /// Throws `reason` unless `condition` holds.
    ///
    /// One place, so every check below is written the same way and the invariants
    /// read as invariants rather than as control flow.
    private static func require(
        _ condition: Bool,
        _ reason: CanonicalRouteBridgeError
    ) throws {
        guard condition else { throw reason }
    }

    // MARK: - Display mappings

    /// The redacted presence summary, taken from the canonical diagnostic.
    ///
    /// The canonical `RoutingInputSummary` holds four booleans and no values, so
    /// this cannot leak the host, the address, the port, or the network even by
    /// accident: there is nothing to leak.
    static func presenceSummary(_ summary: RoutingInputSummary) -> String {
        var fields: [String] = []
        if summary.hasHost { fields.append("host present") }
        if summary.hasIP { fields.append("address present") }
        if summary.hasPort { fields.append("port present") }
        if summary.hasNetwork { fields.append("network present") }
        return fields.isEmpty ? "no input fields" : fields.joined(separator: ", ")
    }

    /// The display reason, derived from the canonical rule reason code.
    static func displayReason(_ reasonCode: String) -> DebugReason {
        guard let code = RoutingRuleReasonCode(rawValue: reasonCode) else { return .noMatcherMatched }
        switch code {
        case .ruleDisabled: return .ruleDisabled
        case .noMatchers, .noMatchingMatcher: return .noMatcherMatched
        case .firstMatchingRule: return .applied
        case .shadowedByEarlierMatch: return .shadowed
        }
    }

    /// The display outcome, derived from the canonical route action.
    static func displayOutcome(_ action: RouteAction) -> RouteOutcome {
        switch action {
        case .direct: return .direct
        case .block: return .block
        case let .group(id): return .group(id.uuidString)
        }
    }

    // MARK: - Canonical conversions

    static func canonicalIdentifier(_ identifier: String) throws -> UUID {
        guard let uuid = UUID(uuidString: identifier) else {
            throw CanonicalRouteBridgeError.notACanonicalIdentifier(identifier)
        }
        return uuid
    }

    static func canonicalAction(_ outcome: RouteOutcome) throws -> RouteAction {
        switch outcome {
        case .direct: return .direct
        case .block: return .block
        case let .group(identifier):
            return .group(try canonicalIdentifier(identifier))
        case .unavailable:
            throw CanonicalRouteBridgeError.notACanonicalOutcome(
                "unavailable is a display state for an engine that is not built; it is not a route action"
            )
        }
    }

    static func canonicalMatcher(_ summary: RouteMatcherSummary) throws -> RouteMatcher {
        switch summary.kind {
        case .domain:
            return .domain(summary.value)
        case .domainSuffix:
            return .domainSuffix(summary.value)
        case .ipCIDR:
            return .ipCIDR(summary.value)
        case .network:
            return .network(summary.value)
        case .port:
            guard let port = Int(summary.value) else {
                throw CanonicalRouteBridgeError.notACanonicalMatcher("port \(summary.value)")
            }
            return .port(port)
        case .portRange:
            guard let lower = Int(summary.value),
                  let upper = Int(summary.upperValue ?? summary.value) else {
                throw CanonicalRouteBridgeError.notACanonicalMatcher(
                    "port range \(summary.value)–\(summary.upperValue ?? summary.value)"
                )
            }
            return .portRange(lower: lower, upper: upper)
        }
    }
}
