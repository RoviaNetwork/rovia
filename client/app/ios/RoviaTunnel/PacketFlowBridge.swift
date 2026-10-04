import Foundation
import NetworkExtension
import RoviaEngineAPI

/// `NEPacketTunnelFlow` as the engine API's `PacketBridge`.
///
/// Reads are the flow's own batched reads: one readPackets completion becomes
/// one `read()`. A read parked without traffic cannot be cancelled from the
/// outside — the flow's completion fires when packets arrive or the tunnel
/// dies — so the pump's stop is signalled through `XrayTunPump.stop()`, and a
/// parked read that eventually fires sees the pump already stopped and drops
/// its batch. No queue grows here: the flow itself is the buffer.
final class PacketFlowBridge: PacketBridge, @unchecked Sendable {
    private let flow: NEPacketTunnelFlow

    init(flow: NEPacketTunnelFlow) {
        self.flow = flow
    }

    func read() async throws -> [EnginePacket] {
        try Task.checkCancellation()
        return await withCheckedContinuation { continuation in
            flow.readPackets { datagrams, protocols in
                let packets = zip(datagrams, protocols).map { datagram, proto in
                    EnginePacket(data: datagram, protocolNumber: proto.int32Value)
                }
                continuation.resume(returning: packets)
            }
        }
    }

    func write(_ packets: [EnginePacket]) async throws {
        try Task.checkCancellation()
        guard !packets.isEmpty else { return }
        flow.writePackets(
            packets.map(\.data),
            withProtocols: packets.map { NSNumber(value: $0.protocolNumber) }
        )
    }
}
