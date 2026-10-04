import Foundation
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
            switch model.snapshot.contentSource {
            case .unavailable:
                unavailableState
            case .none:
                emptyState
            case .live, .allRejected, .sample:
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

    // MARK: - Unavailable store

    private var unavailableState: some View {
        ContentUnavailableView {
            Label("Subscriptions unavailable", systemImage: "exclamationmark.triangle")
        } description: {
            Text("The stored subscriptions could not be read. Nothing was deleted or overwritten.")
        } actions: {
            Button("Try again") {
                Task { await model.bootstrap() }
            }
            .buttonStyle(.borderedProminent)
            .accessibilityIdentifier(AppAccessibilityIdentifier.subscriptionScreen + ".retry")
        }
        .modifier(ConditionalAccessibilityIdentifier(
            identifier: AppAccessibilityIdentifier.subscriptionScreen + ".unavailable"
        ))
    }

    // MARK: - List

    private var subscriptionList: some View {
        List {
            if model.snapshot.contentSource == .allRejected {
                Section {
                    Text("Subscriptions are stored, but every entry was rejected. Check a row's reasons, fix the source, and refresh.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .modifier(ConditionalAccessibilityIdentifier(
                    identifier: AppAccessibilityIdentifier.subscriptionAllRejected
                ))
            }
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
                guard !Task.isCancelled else { break }
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
            if let info = subscription.userInfo, let line = userInfoLine(info) {
                Text(line)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
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

    private func userInfoLine(_ info: SubscriptionUserInfo) -> String? {
        var parts: [String] = []
        if let total = info.totalBytes {
            let used = (info.uploadBytes ?? 0) + (info.downloadBytes ?? 0)
            parts.append("\(formatBytes(used)) of \(formatBytes(total)) used")
        }
        if let expire = info.expireDate {
            parts.append("expires \(expire.formatted(date: .abbreviated, time: .omitted))")
        }
        guard !parts.isEmpty else { return nil }
        return parts.joined(separator: " · ")
    }

    private func formatBytes(_ value: Int64) -> String {
        let formatter = ByteCountFormatter()
        formatter.countStyle = .binary
        return formatter.string(fromByteCount: value)
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

/// Confirms an inbound deep link before anything happens: no silent add,
/// no network request from opening a URL. Shows what the link holds (URL
/// host redacted, single-link scheme, or container line count) and lets
/// the user name it, add it, or dismiss it.
struct ImportPreviewSheet: View {
    let model: AppModel
    let pending: PendingImport

    @State private var nameText: String = ""
    @Environment(\.dismiss) private var dismiss

    private enum Preview {
        case url(host: String)
        case single(scheme: String)
        case container(lines: Int, base64: Bool)
        case invalid
    }

    private var preview: Preview {
        switch SubscriptionInputClassifier.classify(pending.text) {
        case .subscriptionURL(let url):
            return .url(host: url.host ?? "unknown host")
        case .singleShareLink(let scheme):
            return .single(scheme: scheme.rawValue)
        case .pastedText:
            guard let data = pending.text.data(using: .utf8),
                  let document = try? SubscriptionDocumentDecoder.decode(data)
            else {
                return .invalid
            }
            return .container(lines: document.lines.count, base64: document.wasBase64)
        case .none:
            return .invalid
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Link") {
                    switch preview {
                    case .url(let host):
                        Text("Subscription URL at \(host)")
                    case .single(let scheme):
                        Text("Single \(scheme) server")
                    case .container(let lines, let base64):
                        Text(base64 ? "Subscription list (\(lines) servers)" : "\(lines) pasted lines")
                    case .invalid:
                        Text("This link holds nothing importable.")
                            .foregroundStyle(.secondary)
                    }
                }
                Section("Name") {
                    TextField("Subscription name", text: $nameText)
                }
                Section {
                    Button("Add subscription") {
                        let name = nameText.trimmingCharacters(in: .whitespacesAndNewlines)
                        Task {
                            let succeeded = await model.addSubscriptionText(
                                pending.text,
                                name: name.isEmpty ? (pending.name ?? "Imported subscription") : name
                            )
                            // Only then discard the pending link — a failed
                            // add must not throw the link away with the tap.
                            if succeeded {
                                model.discardPendingImport()
                            }
                            dismiss()
                        }
                    }
                    .disabled(!canAdd)
                }
            }
            .navigationTitle("Import subscription")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        model.discardPendingImport()
                        dismiss()
                    }
                }
            }
            .onAppear {
                nameText = pending.name ?? ""
            }
            // A second deep link replaces the item: reset the editable name
            // so it never carries the previous link's suggestion.
            .onChange(of: pending.id) { _, _ in
                nameText = pending.name ?? ""
            }
        }
    }

    private var canAdd: Bool {
        if case .invalid = preview { return false }
        return true
    }
}
