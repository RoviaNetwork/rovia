import RoviaSubscription
import SwiftUI

#if canImport(UIKit)
    import UIKit
#endif

struct SubscriptionInspectorView: View {
    let model: AppModel

    @State private var addShown = false
    @State private var urlText = ""
    @State private var nameText = ""
    @State private var pasteText = ""
    @State private var allowInsecure = false
    @State private var renameTarget: UUID?
    @State private var renameText = ""

    var body: some View {
        Group {
            if model.storedSubscriptions.isEmpty {
                emptyState
            } else {
                subscriptionList
            }
        }
        .navigationTitle(AppRoute.subscription.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    addShown = true
                } label: {
                    Label("Add subscription", systemImage: "plus")
                }
                .accessibilityIdentifier(AppAccessibilityIdentifier.subscriptionScreen + ".add")
            }
        }
        .sheet(isPresented: $addShown) {
            addSheet
        }
        .alert("Rename subscription", isPresented: renameBinding) {
            TextField("Name", text: $renameText)
            Button("Rename") {
                if let id = renameTarget {
                    Task { await model.renameSubscription(id, name: renameText) }
                }
            }
            Button("Cancel", role: .cancel) {}
        }
    }

    // MARK: - Empty

    private var emptyState: some View {
        ContentUnavailableView {
            Label {
                Text("No subscriptions yet")
            } icon: {
                RoviaLogoView(.emptyState)
            }
        } description: {
            Text("Add a subscription URL or paste subscription text. Servers appear here and in the Servers list.")
        } actions: {
            Button("Add subscription") {
                addShown = true
            }
            .buttonStyle(.borderedProminent)
            .accessibilityIdentifier(AppAccessibilityIdentifier.subscriptionScreen + ".addEmpty")
        }
        .modifier(ConditionalAccessibilityIdentifier(
            identifier: AppAccessibilityIdentifier.subscriptionEmpty
        ))
    }

    // MARK: - List

    private var subscriptionList: some View {
        List {
            if let result = model.snapshot.lastSubscriptionResult {
                Section {
                    resultBanner(result)
                }
            }
            if let error = model.snapshot.lastError {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(error.userMessage)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        Button("Dismiss") {
                            model.clearError()
                        }
                        .font(.footnote)
                        .accessibilityIdentifier(AppAccessibilityIdentifier.subscriptionScreen + ".dismissError")
                    }
                    .accessibilityElement(children: .combine)
                }
            }
            Section {
                ForEach(model.storedSubscriptions) { subscription in
                    subscriptionRow(subscription)
                }
                .onDelete { offsets in
                    for index in offsets {
                        let id = model.storedSubscriptions[index].id
                        Task { await model.removeSubscription(id) }
                    }
                }
            } header: {
                Text("Subscriptions")
            }
            .accessibilityIdentifier(AppAccessibilityIdentifier.subscriptionEntries)
            Section {
                Label(
                    "Credentials are never shown. Server addresses are replaced with a redacted placeholder, and secrets stay in the Keychain.",
                    systemImage: "eye.slash"
                )
                .font(.footnote)
                .foregroundStyle(.secondary)
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier(AppAccessibilityIdentifier.subscriptionRedaction)
            }
        }
        .listStyle(.insetGrouped)
        .refreshable {
            for subscription in model.storedSubscriptions {
                await model.refreshSubscription(subscription.id)
            }
        }
    }

    private func subscriptionRow(_ subscription: StoredSubscription) -> some View {
        let groupID = "sub/\(subscription.id.uuidString.lowercased())"
        let memberCount = model.snapshot.content.group(id: groupID)?.memberIDs.count
            ?? subscription.servers.count
        let isRefreshing = model.refreshingSubscriptions.contains(subscription.id)
        return VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(subscription.name)
                    .font(.headline)
                Spacer(minLength: 12)
                if isRefreshing {
                    ProgressView()
                        .accessibilityLabel("Refreshing \(subscription.name)")
                } else {
                    Button {
                        Task { await model.refreshSubscription(subscription.id) }
                    } label: {
                        Label("Refresh", systemImage: "arrow.clockwise")
                            .labelStyle(.iconOnly)
                    }
                    .accessibilityLabel("Refresh \(subscription.name)")
                    .accessibilityIdentifier(AppAccessibilityIdentifier.subscriptionEntryPrefix + subscription.id.uuidString)
                }
            }
            Text("\(memberCount) servers · updated \(subscription.updatedAt.formatted(date: .abbreviated, time: .shortened))")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            if subscription.rejectedCount > 0 {
                Text("\(subscription.acceptedCount) accepted · \(subscription.rejectedCount) rejected")
                    .font(.footnote)
                    .foregroundStyle(.orange)
            }
        }
        .padding(.vertical, 4)
        .contextMenu {
            Button("Rename") {
                renameTarget = subscription.id
                renameText = subscription.name
            }
            Button("Refresh") {
                Task { await model.refreshSubscription(subscription.id) }
            }
            Button("Delete", role: .destructive) {
                Task { await model.removeSubscription(subscription.id) }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(subscription.name), \(memberCount) servers")
    }

    private func resultBanner(_ result: SubscriptionImportSummary) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: result.rejected.isEmpty ? "checkmark.circle" : "exclamationmark.triangle")
                    .foregroundStyle(result.rejected.isEmpty ? Color.green : Color.orange)
                Text("\(result.accepted) accepted · \(result.rejected.count) rejected")
                    .font(.subheadline.weight(.semibold))
            }
            ForEach(result.rejected.prefix(5), id: \.index) { line in
                Text("Line \(line.index): \(reasonText(line.reason))")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            if result.rejected.count > 5 {
                Text("…and \(result.rejected.count - 5) more")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(AppAccessibilityIdentifier.subscriptionSummary)
    }

    private func reasonText(_ reason: ShareLinkParseError) -> String {
        switch reason {
        case .unsupportedScheme: "unsupported link type"
        case .malformedURL: "malformed link"
        case .invalidUUID: "bad identifier"
        case .invalidHost: "bad host"
        case .invalidPort: "bad port"
        case .invalidCredential: "bad credential"
        case .invalidQuery, .unsupportedQueryKey, .unsupportedQueryValue, .duplicateQueryKey, .queryTooComplex:
            "unsupported setting"
        case .inputTooLarge: "link too large"
        case .invalidUTF8, .emptyInput: "empty or unreadable"
        case .invalidPercentEncoding, .invalidPath: "bad encoding"
        case .invalidSecretReference, .credentialSinkFailed: "could not save credentials"
        }
    }

    // MARK: - Add sheet

    private var addSheet: some View {
        NavigationStack {
            Form {
                Section("From URL") {
                    TextField("https://provider.example/sub", text: $urlText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("Name", text: $nameText)
                    Toggle("Allow plain HTTP (insecure)", isOn: $allowInsecure)
                    Button("Add subscription") {
                        addShown = false
                        let urlString = urlText.trimmingCharacters(in: .whitespacesAndNewlines)
                        let name = nameText.trimmingCharacters(in: .whitespacesAndNewlines)
                        if let url = URL(string: urlString) {
                            Task { await model.addSubscription(url: url, name: name.isEmpty ? urlString : name, allowInsecure: allowInsecure) }
                        }
                        urlText = ""
                        nameText = ""
                        allowInsecure = false
                    }
                    .disabled(urlText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                Section("Paste") {
                    #if canImport(UIKit)
                        Button("Paste from clipboard") {
                            pasteText = UIPasteboard.general.string ?? ""
                        }
                    #endif
                    TextEditor(text: $pasteText)
                        .frame(minHeight: 120)
                    Button("Import pasted text") {
                        addShown = false
                        let name = nameText.trimmingCharacters(in: .whitespacesAndNewlines)
                        Task {
                            await model.addSubscriptionText(
                                pasteText,
                                name: name.isEmpty ? "Pasted subscription" : name
                            )
                        }
                        pasteText = ""
                        nameText = ""
                    }
                    .disabled(pasteText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .navigationTitle("Add subscription")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { addShown = false }
                }
            }
        }
    }

    private var renameBinding: Binding<Bool> {
        Binding(
            get: { renameTarget != nil },
            set: { if !$0 { renameTarget = nil } }
        )
    }
}
