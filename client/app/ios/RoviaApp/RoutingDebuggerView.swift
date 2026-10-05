import SwiftUI

struct RoutingDebuggerView: View {
    let model: AppModel

    var body: some View {
        Group {
            if model.snapshot.content.debugSamples.isEmpty {
                ContentUnavailableView(
                    "No debug samples",
                    systemImage: "ladybug",
                    description: Text("Routing samples appear once a local configuration with rules and sample inputs is loaded.")
                )
                .modifier(ConditionalAccessibilityIdentifier(
                    identifier: AppAccessibilityIdentifier.routingDebuggerEmpty
                ))
            } else {
                RoviaScreen {
                    RoviaScreenHeader(
                        title: "Routing Debugger",
                        subtitle: "Explain which rule decides a built-in sample. Nothing is typed, stored, or sent anywhere.",
                        identifier: AppAccessibilityIdentifier.routingDebuggerScreen
                    )
                    sampleCard
                    if let evaluation = model.snapshot.evaluation {
                        resultCard(evaluation)
                        stepsCard(evaluation)
                    }
                    redactionNotice
                    SampleDataNotice(identifier: AppAccessibilityIdentifier.routingDebuggerScreen + ".notice")
                }
            }
        }
        .navigationTitle(ToolRoute.routingDebugger.title)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var sampleCard: some View {
        SectionCard(title: "Sample", systemImage: "target") {
            VStack(alignment: .leading, spacing: 12) {
                Menu {
                    ForEach(model.snapshot.content.debugSamples) { sample in
                        Button {
                            Task { await model.selectDebugSample(sample.id) }
                        } label: {
                            Text(sample.label)
                        }
                    }
                } label: {
                    Label(selectedSampleLabel, systemImage: "chevron.up.chevron.down")
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.bordered)
                .accessibilityLabel("Debug sample")
                .accessibilityValue(selectedSampleLabel)
                .accessibilityHint("Chooses which built-in sample the explanation evaluates.")
                .accessibilityIdentifier(AppAccessibilityIdentifier.routingDebuggerSampleMenu)

                if let sample = selectedSample {
                    Text(sample.detail)
                        .font(.subheadline)
                        .foregroundStyle(ScopeTheme.inkSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Button {
                    Task { await model.runDebugEvaluation() }
                } label: {
                    Label("Explain sample", systemImage: "play.circle")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(!model.snapshot.canExplainDebugSample)
                .accessibilityHint("Evaluates the sample against the loaded rules in order.")
                .accessibilityIdentifier(AppAccessibilityIdentifier.routingDebuggerExplain)

                if model.snapshot.evaluation == nil {
                    Text("Choose a sample and explain it to see the rule-by-rule outcome.")
                        .font(.footnote)
                        .foregroundStyle(ScopeTheme.inkSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func resultCard(_ evaluation: DebugEvaluation) -> some View {
        SectionCard(title: "Decision", systemImage: evaluation.decision.systemImage) {
            VStack(alignment: .leading, spacing: 12) {
                Label {
                    Text(evaluation.decision.label(using: model.snapshot.content))
                        .font(.title3.weight(.semibold))
                } icon: {
                    Image(systemName: evaluation.decision.systemImage)
                }
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier(AppAccessibilityIdentifier.routingDebuggerDecision)

                InfoRow(
                    label: "Sample",
                    value: evaluation.sampleLabel,
                    identifier: AppAccessibilityIdentifier.routingDebuggerDecision + ".sample"
                )
                InfoRow(
                    label: "Deciding rule",
                    value: evaluation.appliedRuleIndex.map { "Rule \($0 + 1)" } ?? "No rule matched, default action applied",
                    identifier: AppAccessibilityIdentifier.routingDebuggerDecision + ".rule"
                )
                InfoRow(
                    label: "Selected group",
                    value: evaluation.selectedGroupID.flatMap { model.snapshot.content.group(id: $0)?.name } ?? "None",
                    identifier: AppAccessibilityIdentifier.routingDebuggerDecision + ".group"
                )
                InfoRow(
                    label: "Input fields seen",
                    value: evaluation.inputPresence,
                    identifier: AppAccessibilityIdentifier.routingDebuggerDecision + ".input"
                )
            }
        }
    }

    private func stepsCard(_ evaluation: DebugEvaluation) -> some View {
        SectionCard(
            title: "Rule outcomes",
            systemImage: "list.bullet.rectangle",
            identifier: AppAccessibilityIdentifier.routingDebuggerSteps
        ) {
            VStack(alignment: .leading, spacing: 12) {
                ForEach(evaluation.steps) { step in
                    stepRow(step)
                }
            }
        }
    }

    private func stepRow(_ step: DebugStep) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text("Rule \(step.ruleIndex + 1)")
                        .font(.subheadline.weight(.semibold))
                    Text(step.reason.summary)
                        .font(.subheadline)
                        .foregroundStyle(ScopeTheme.inkSecondary)
                    Spacer(minLength: 12)
                    stepBadge(step)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text("Rule \(step.ruleIndex + 1)")
                        .font(.subheadline.weight(.semibold))
                    Text(step.reason.summary)
                        .font(.subheadline)
                        .foregroundStyle(ScopeTheme.inkSecondary)
                    stepBadge(step)
                }
            }
            Text(stepDetail(step))
                .font(.footnote)
                .foregroundStyle(ScopeTheme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(ScopeTheme.housing, in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Rule \(step.ruleIndex + 1), \(step.reason.summary)")
        .accessibilityValue(stepDetail(step))
        .accessibilityIdentifier(AppAccessibilityIdentifier.routingDebuggerStepPrefix + String(step.ruleIndex))
    }

    private func stepBadge(_ step: DebugStep) -> some View {
        StatusBadge(
            text: "\(step.evaluatedMatcherCount) matcher\(step.evaluatedMatcherCount == 1 ? "" : "s")",
            systemImage: step.matched ? "checkmark.circle" : "circle",
            tint: step.matched ? .green : .secondary
        )
    }

    private func stepDetail(_ step: DebugStep) -> String {
        guard let matcherIndex = step.appliedMatcherIndex,
              let rule = model.snapshot.content.routeRules.first(where: { $0.index == step.ruleIndex }),
              rule.matchers.indices.contains(matcherIndex) else {
            return step.isEnabled
                ? "None of the \(step.evaluatedMatcherCount) matchers matched this sample."
                : "Skipped because the rule is disabled."
        }
        return "First matching matcher: \(rule.matchers[matcherIndex].summaryText)."
    }

    private var redactionNotice: some View {
        Label(
            "The explanation stores rule outcomes only. Sample host names, addresses, ports, and networks are not written into the result.",
            systemImage: "eye.slash"
        )
        .font(.footnote)
        .foregroundStyle(ScopeTheme.inkSecondary)
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(AppAccessibilityIdentifier.routingDebuggerRedaction)
    }

    private var selectedSample: DebugSampleSummary? {
        guard let sampleID = model.snapshot.selection.debugSample else { return nil }
        return model.snapshot.content.debugSample(id: sampleID)
    }

    private var selectedSampleLabel: String {
        selectedSample?.label ?? "Choose a sample"
    }
}
