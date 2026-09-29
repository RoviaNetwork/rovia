import SwiftUI

struct ServersView: View {
    let model: AppModel

    @State private var searchText = ""
    @State private var favoritesOnly = false

    var body: some View {
        Group {
            if model.snapshot.content.servers.isEmpty {
                ContentUnavailableView(
                    "No servers in this configuration",
                    systemImage: "server.rack",
                    description: Text("Add servers to a local configuration to compare latency and health confidence offline.")
                )
                .modifier(ConditionalAccessibilityIdentifier(
                    identifier: AppAccessibilityIdentifier.serversEmpty
                ))
            } else {
                RoviaScreen {
                    RoviaScreenHeader(
                        title: "Servers",
                        subtitle: "Pick a group, then a member server. Selection never reaches the tunnel engine in this build.",
                        identifier: AppAccessibilityIdentifier.serversScreen
                    )
                    groupCard
                    profileCard
                    serverList
                    latencyButton
                    SampleDataNotice(identifier: AppAccessibilityIdentifier.serversScreen + ".notice")
                }
                .searchable(text: $searchText, prompt: "Search servers")
                .toolbar {
                    ToolbarItem(placement: .primaryAction) {
                        Button {
                            favoritesOnly.toggle()
                        } label: {
                            Label("Favorites only", systemImage: favoritesOnly ? "star.fill" : "star")
                        }
                        .accessibilityIdentifier(AppAccessibilityIdentifier.serversScreen + ".favoritesOnly")
                    }
                }
            }
        }
        .navigationTitle(AppRoute.servers.title)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var filteredServers: [ServerSummary] {
        var servers = model.snapshot.visibleServers
        if favoritesOnly {
            servers = servers.filter { model.isFavorite($0.id) }
        }
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !query.isEmpty else { return servers }
        return servers.filter {
            $0.name.lowercased().contains(query) || $0.protocolLabel.lowercased().contains(query)
        }
    }

    private var profileCard: some View {
        SectionCard(title: "Profile", systemImage: "person.crop.rectangle") {
            VStack(alignment: .leading, spacing: 12) {
                Menu {
                    ForEach(model.snapshot.content.profiles) { profile in
                        Button {
                            Task { await model.selectProfile(profile.id) }
                        } label: {
                            Text("\(profile.name) · \(profile.serverIDs.count) servers")
                        }
                    }
                } label: {
                    Label(selectedProfileLabel, systemImage: "chevron.up.chevron.down")
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.bordered)
                .accessibilityLabel("Profile")
                .accessibilityValue(selectedProfileLabel)
                .accessibilityHint("Changes which servers are listed. A selected server that the new profile does not contain is cleared.")
                .accessibilityIdentifier(AppAccessibilityIdentifier.serversProfileMenu)

                InfoRow(
                    label: "Source",
                    value: model.snapshot.content.profiles
                        .first { $0.id == model.snapshot.selection.profile }?
                        .sourceKindLabel ?? "Unknown",
                    identifier: AppAccessibilityIdentifier.serversScreen + ".profileSource"
                )
            }
        }
    }

    private var groupCard: some View {
        SectionCard(title: "Server group", systemImage: "square.stack.3d.up") {
            VStack(alignment: .leading, spacing: 12) {
                Menu {
                    ForEach(model.snapshot.content.groups) { group in
                        Button {
                            Task { await model.selectGroup(group.id) }
                        } label: {
                            Text("\(group.name) · \(group.memberIDs.count) members")
                        }
                    }
                } label: {
                    Label(selectedGroupLabel, systemImage: "chevron.up.chevron.down")
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.bordered)
                .accessibilityLabel("Server group")
                .accessibilityValue(selectedGroupLabel)
                .accessibilityHint("Changes which servers are listed and which servers can be selected.")
                .accessibilityIdentifier(AppAccessibilityIdentifier.serversGroupMenu)

                InfoRow(
                    label: "Selection policy",
                    value: model.snapshot.content.group(id: model.snapshot.selection.group ?? "")?.policyLabel ?? "No group",
                    identifier: AppAccessibilityIdentifier.serversScreen + ".policy"
                )
                InfoRow(
                    label: "Group mode",
                    value: model.snapshot.content.group(id: model.snapshot.selection.group ?? "")?.modeLabel ?? "No group",
                    identifier: AppAccessibilityIdentifier.serversScreen + ".mode"
                )
            }
        }
    }

    private var serverList: some View {
        SectionCard(
            title: "Members",
            systemImage: "list.bullet.rectangle",
            identifier: AppAccessibilityIdentifier.serversList
        ) {
            // LazyVStack: rows are built on scroll, not all upfront. With
            // thousands of servers an eager VStack stalls the first frame.
            LazyVStack(alignment: .leading, spacing: 12) {
                if filteredServers.isEmpty {
                    Text("No server matches \(model.snapshot.serverFilterDescription). Choose a different profile or group to see members.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                ForEach(filteredServers) { server in
                    serverRow(server)
                }
            }
        }
    }

    private var latencyButton: some View {
        let isProbing = model.inFlightActions.contains(.probeServers)
        return Button {
            Task { await model.probeVisibleServers() }
        } label: {
            if isProbing {
                Label("Measuring…", systemImage: "speedometer")
            } else {
                Label("Check latency", systemImage: "speedometer")
            }
        }
        .buttonStyle(.bordered)
        .disabled(isProbing || model.snapshot.visibleServers.isEmpty)
        .accessibilityHint("Opens a TCP connection to each listed server and shows the handshake time. Bounded and cancellable by leaving the screen.")
        .accessibilityIdentifier(AppAccessibilityIdentifier.serversScreen + ".checkLatency")
    }

    private func serverRow(_ server: ServerSummary) -> some View {
        let isSelected = model.snapshot.selection.server == server.id
        return Button {
            Task { await model.selectServer(server.id) }
        } label: {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(server.name)
                        .font(.headline)
                    Text("\(server.protocolLabel) · \(server.locationLabel)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 8) {
                        QualityBadge(latency: server.latency)
                    }
                    HStack(spacing: 8) {
                        ConfidenceBadge(confidence: server.healthConfidence, evidence: server.health)
                    }
                }
                Spacer(minLength: 8)
                Button {
                    Task { await model.toggleFavorite(server.id) }
                } label: {
                    Image(systemName: model.isFavorite(server.id) ? "star.fill" : "star")
                        .foregroundStyle(model.isFavorite(server.id) ? Color.yellow : Color.secondary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(model.isFavorite(server.id) ? "Unfavorite \(server.name)" : "Favorite \(server.name)")
                .accessibilityIdentifier(AppAccessibilityIdentifier.serversScreen + ".favorite." + server.id)
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(isSelected ? Color.accentColor : Color.secondary)
                    .accessibilityHidden(true)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.quaternary.opacity(isSelected ? 0.5 : 0.25), in: RoundedRectangle(cornerRadius: 14))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(server.name)
        .accessibilityValue(accessibilityValue(for: server, isSelected: isSelected))
        .accessibilityHint("Selects this server for the selected group.")
        .accessibilityAddTraits(isSelected ? .isSelected : [])
        .accessibilityIdentifier(AppAccessibilityIdentifier.serversRowPrefix + server.id)
    }

    private func accessibilityValue(for server: ServerSummary, isSelected: Bool) -> String {
        let parts = [
            server.protocolLabel,
            server.locationLabel,
            "latency \(server.latency.displayText)",
            "health confidence \(server.healthConfidence.summary)",
            server.health.displayText
        ]
        return parts.joined(separator: ", ") + (isSelected ? ", selected" : "")
    }

    private var selectedGroupLabel: String {
        guard let groupID = model.snapshot.selection.group,
              let group = model.snapshot.content.group(id: groupID) else {
            return "All servers"
        }
        return group.name
    }

    private var selectedProfileLabel: String {
        model.snapshot.selectedProfileName ?? "No profile"
    }
}
