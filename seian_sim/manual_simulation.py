"""Manual, Packet Tracer-style packet forwarding for SEIAN-AMRP.

The batch simulator intentionally processes many queued packets in one call.  This
module provides an isolated event queue where exactly one physical transmission is
attempted per ``forward_one`` call.  It is designed for teaching and protocol
inspection rather than real-time radio control.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Deque

from seian_sim.enums import PacketType, TrustStatus
from seian_sim.packets import Packet, PRIORITY_CONTROL
from seian_sim.simulator import SeianMeshSimulator


FLOODED_PACKET_TYPES = {
    PacketType.FAULT_ALERT,
    PacketType.CONTROL_COORDINATION,
    PacketType.GATEWAY_ANNOUNCE,
    PacketType.ROUTE_ADVERTISEMENT,
    PacketType.ROUTE_ERROR,
}


@dataclass(slots=True)
class PendingTransmission:
    """One physical link transmission waiting for the Forward button."""

    sender_id: str
    receiver_id: str
    packet: Packet
    reason: str = "route"


@dataclass(slots=True)
class ManualStepRecord:
    """Result of one manually advanced physical transmission."""

    step: int
    timestamp: float
    status: str
    action: str
    sender_id: str
    receiver_id: str
    origin_id: str
    destination_id: str | None
    packet_type: str
    sequence_number: int
    priority: int
    hop_count: int
    ttl: int
    rssi: float | None
    snr: float | None
    link_quality: float | None
    message: str
    path: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a dataframe-friendly representation."""

        row = asdict(self)
        row["path"] = " → ".join(self.path)
        return row


@dataclass
class ManualPacketSession:
    """State for one Packet Tracer-style manual packet trace."""

    source_id: str
    destination_id: str | None
    packet_type: PacketType
    packet: Packet
    generate_fault_acks: bool = True
    pending: Deque[PendingTransmission] = field(default_factory=deque)
    history: list[ManualStepRecord] = field(default_factory=list)
    seen_by_node: set[tuple[str, str, int]] = field(default_factory=set)
    delivered_nodes: set[str] = field(default_factory=set)
    dropped_events: int = 0
    complete: bool = False
    completion_message: str = "Packet created. Press Forward to begin."

    @classmethod
    def create(
        cls,
        sim: SeianMeshSimulator,
        *,
        source_id: str,
        destination_id: str | None,
        packet_type: PacketType,
        priority: int,
        ttl: int,
        payload: dict[str, Any] | None = None,
        generate_fault_acks: bool = True,
    ) -> "ManualPacketSession":
        """Create a trace and schedule its first link transmission(s)."""

        if source_id not in sim.nodes:
            raise ValueError(f"Unknown source node: {source_id}")
        if destination_id is not None and destination_id not in sim.nodes:
            raise ValueError(f"Unknown destination node: {destination_id}")
        if ttl < 1:
            raise ValueError("TTL must be at least 1.")
        if not sim.nodes[source_id].active:
            raise ValueError("The source node is inactive.")
        if len(sim.nodes) > 1 and not any(node.neighbor_table for node in sim.nodes.values()):
            sim.discover_neighbors()

        source = sim.nodes[source_id]
        packet = sim.create_packet(
            source,
            packet_type,
            destination_id=destination_id,
            priority=priority,
            ttl=ttl,
            payload=payload or {},
        )
        session = cls(
            source_id=source_id,
            destination_id=destination_id,
            packet_type=packet_type,
            packet=packet,
            generate_fault_acks=generate_fault_acks,
        )
        session.seen_by_node.add((source_id, packet.origin_id, packet.sequence_number))
        session._schedule_from(sim, source_id, packet, previous_hop=None, reason="origin")
        session._refresh_completion()
        return session

    @property
    def last_step(self) -> ManualStepRecord | None:
        return self.history[-1] if self.history else None

    @property
    def pending_count(self) -> int:
        return len(self.pending)

    def pending_rows(self) -> list[dict[str, Any]]:
        """Return the waiting event queue for dashboard display."""

        return [
            {
                "queue_position": index,
                "sender": item.sender_id,
                "receiver": item.receiver_id,
                "packet_type": item.packet.packet_type.value,
                "origin": item.packet.origin_id,
                "destination": item.packet.destination_id or "BROADCAST",
                "priority": item.packet.priority,
                "hop_count": item.packet.hop_count,
                "ttl": item.packet.ttl,
                "reason": item.reason,
                "path": " → ".join(item.packet.path),
            }
            for index, item in enumerate(self.pending, start=1)
        ]

    def history_rows(self) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self.history]

    def forward_one(self, sim: SeianMeshSimulator) -> ManualStepRecord | None:
        """Attempt exactly one pending physical transmission."""

        if not self.pending:
            self._refresh_completion()
            return None

        item = self.pending.popleft()
        sender = sim.nodes.get(item.sender_id)
        receiver = sim.nodes.get(item.receiver_id)
        packet = item.packet
        step_number = len(self.history) + 1

        if sender is None or receiver is None:
            return self._record_drop(
                sim,
                item,
                step_number,
                "missing_node",
                "The sender or receiver no longer exists in the topology.",
            )
        if not sender.active:
            return self._record_drop(sim, item, step_number, "sender_inactive", f"{sender.node_id} is inactive.")
        if not receiver.active:
            return self._record_drop(sim, item, step_number, "receiver_inactive", f"{receiver.node_id} is inactive.")
        if receiver.node_id not in sender.neighbor_table:
            return self._record_drop(
                sim,
                item,
                step_number,
                "not_neighbors",
                f"{receiver.node_id} is not a current one-hop neighbor of {sender.node_id}.",
            )

        observation = sim.channel.observe(sender.position, receiver.position, packet.payload_length)
        sim.env.run(until=sim.now + max(0.001, observation.delay_s))

        validation_error = self._validation_error(sim, receiver.node_id, packet)
        if validation_error:
            reason, message = validation_error
            return self._record_drop(
                sim,
                item,
                step_number,
                reason,
                message,
                rssi=observation.rssi,
                snr=observation.snr,
                link_quality=observation.link_quality,
            )
        if not observation.delivered:
            return self._record_drop(
                sim,
                item,
                step_number,
                observation.drop_reason or "radio_drop",
                f"LoRa delivery failed: {observation.drop_reason or 'radio drop'}.",
                rssi=observation.rssi,
                snr=observation.snr,
                link_quality=observation.link_quality,
            )

        duplicate_key = (receiver.node_id, packet.origin_id, packet.sequence_number)
        if duplicate_key in self.seen_by_node:
            sim.metrics.duplicate_drops += 1
            record = ManualStepRecord(
                step=step_number,
                timestamp=sim.now,
                status="DUPLICATE",
                action="Receive and suppress",
                sender_id=sender.node_id,
                receiver_id=receiver.node_id,
                origin_id=packet.origin_id,
                destination_id=packet.destination_id,
                packet_type=packet.packet_type.value,
                sequence_number=packet.sequence_number,
                priority=packet.priority,
                hop_count=packet.hop_count,
                ttl=packet.ttl,
                rssi=observation.rssi,
                snr=observation.snr,
                link_quality=observation.link_quality,
                message=f"{receiver.node_id} already saw origin/sequence {packet.origin_id}/{packet.sequence_number}.",
                path=[*packet.path, receiver.node_id],
            )
            self.history.append(record)
            self._append_packet_event(sim, record, delivered=False, drop_reason="duplicate")
            self._refresh_completion()
            return record

        self.seen_by_node.add(duplicate_key)
        self.delivered_nodes.add(receiver.node_id)
        sim.metrics.packets_transmitted += 1
        sim.metrics.packets_delivered += 1
        sim.metrics.throughput_by_time[int(sim.now)] += 1
        sim.metrics.record_latency(packet.priority, max(0.0, sim.now - packet.timestamp))
        receiver.recent_received_packets.append(
            {
                "timestamp": sim.now,
                "from": sender.node_id,
                "type": packet.packet_type.value,
                "priority": packet.priority,
                "manual": True,
            }
        )

        destination_reached = packet.destination_id == receiver.node_id
        path = [*packet.path, receiver.node_id]
        if destination_reached:
            status = "DELIVERED"
            action = "Transmit and deliver"
            message = f"{receiver.node_id} is the final destination. Packet delivery completed."
        elif packet.destination_id is None:
            status = "RECEIVED"
            action = "Broadcast receive"
            message = f"{receiver.node_id} accepted the broadcast packet."
        else:
            status = "FORWARDED"
            action = "Transmit, receive, and route"
            message = f"{receiver.node_id} accepted the packet and evaluated the next hop."

        record = ManualStepRecord(
            step=step_number,
            timestamp=sim.now,
            status=status,
            action=action,
            sender_id=sender.node_id,
            receiver_id=receiver.node_id,
            origin_id=packet.origin_id,
            destination_id=packet.destination_id,
            packet_type=packet.packet_type.value,
            sequence_number=packet.sequence_number,
            priority=packet.priority,
            hop_count=packet.hop_count,
            ttl=packet.ttl,
            rssi=observation.rssi,
            snr=observation.snr,
            link_quality=observation.link_quality,
            message=message,
            path=path,
        )
        self.history.append(record)
        self._append_packet_event(sim, record, delivered=True, drop_reason=None)

        if packet.packet_type == PacketType.FAULT_ALERT and self.generate_fault_acks:
            self._schedule_fault_ack(sim, receiver.node_id, packet)

        if not destination_reached:
            if packet.ttl <= 1:
                self.history.append(
                    ManualStepRecord(
                        step=len(self.history) + 1,
                        timestamp=sim.now,
                        status="TTL_EXPIRED",
                        action="Forwarding decision",
                        sender_id=receiver.node_id,
                        receiver_id=receiver.node_id,
                        origin_id=packet.origin_id,
                        destination_id=packet.destination_id,
                        packet_type=packet.packet_type.value,
                        sequence_number=packet.sequence_number,
                        priority=packet.priority,
                        hop_count=packet.hop_count,
                        ttl=packet.ttl,
                        rssi=None,
                        snr=None,
                        link_quality=None,
                        message="The packet was received, but TTL prevents another hop.",
                        path=path,
                    )
                )
            else:
                forwarded = packet.forwarded(receiver.node_id, sim.now)
                scheduled = self._schedule_from(
                    sim,
                    receiver.node_id,
                    forwarded,
                    previous_hop=sender.node_id,
                    reason="forward",
                )
                if scheduled:
                    sim.metrics.packets_forwarded += 1

        self._refresh_completion()
        return record

    def _schedule_from(
        self,
        sim: SeianMeshSimulator,
        sender_id: str,
        packet: Packet,
        *,
        previous_hop: str | None,
        reason: str,
    ) -> int:
        """Schedule the next physical transmission(s), without executing them."""

        sender = sim.nodes.get(sender_id)
        if sender is None or not sender.active:
            return 0

        if packet.destination_id == sender_id:
            self.delivered_nodes.add(sender_id)
            return 0

        if packet.destination_id is not None:
            entry = sender.routing_table.get(packet.destination_id)
            if entry is None:
                self._append_decision_record(
                    sim,
                    sender_id,
                    packet,
                    "NO_ROUTE",
                    f"No routing-table entry exists for {packet.destination_id}.",
                )
                return 0
            next_hop = entry.next_hop_id
            if next_hop not in sender.neighbor_table and entry.backup_next_hop:
                next_hop = entry.backup_next_hop
            if next_hop not in sender.neighbor_table:
                self._append_decision_record(
                    sim,
                    sender_id,
                    packet,
                    "NO_NEXT_HOP",
                    f"Neither the primary nor backup next hop is a current neighbor of {sender_id}.",
                )
                return 0
            if next_hop in packet.path:
                self._append_decision_record(
                    sim,
                    sender_id,
                    packet,
                    "ROUTE_LOOP",
                    f"Next hop {next_hop} already appears in the packet path.",
                )
                return 0
            self.pending.append(PendingTransmission(sender_id, next_hop, packet, reason))
            return 1

        neighbors = sorted(sender.neighbor_table)
        if previous_hop is not None:
            neighbors = [node_id for node_id in neighbors if node_id != previous_hop]

        # HELLO, HEARTBEAT, and ordinary one-hop state updates terminate at
        # direct neighbors.  The listed control/routing packets use controlled
        # flooding when TTL permits.
        if reason == "forward" and packet.packet_type not in FLOODED_PACKET_TYPES:
            return 0

        scheduled = 0
        for neighbor_id in neighbors:
            self.pending.append(PendingTransmission(sender_id, neighbor_id, packet, reason))
            scheduled += 1
        if scheduled == 0 and not self.history:
            self._append_decision_record(
                sim,
                sender_id,
                packet,
                "NO_NEIGHBORS",
                f"{sender_id} has no active one-hop neighbors for this transmission.",
            )
        return scheduled

    def _schedule_fault_ack(self, sim: SeianMeshSimulator, receiver_id: str, alert: Packet) -> None:
        if receiver_id == alert.origin_id:
            return
        receiver = sim.nodes[receiver_id]
        ack = sim.create_packet(
            receiver,
            PacketType.FAULT_ACK,
            destination_id=alert.origin_id,
            priority=PRIORITY_CONTROL,
            ttl=sim.config.max_hops,
            payload={"fault_id": alert.payload.get("fault_id", "manual-fault")},
        )
        self._schedule_from(sim, receiver_id, ack, previous_hop=None, reason="fault_ack")

    def _validation_error(
        self,
        sim: SeianMeshSimulator,
        receiver_id: str,
        packet: Packet,
    ) -> tuple[str, str] | None:
        receiver = sim.nodes[receiver_id]
        if packet.network_id != receiver.network_id:
            return "wrong_network_id", "The receiver rejected a different Network ID."
        if receiver.trust_status == TrustStatus.BLOCKED:
            return "blocked_node", "The receiver is blocked by the trust policy."
        if not packet.crc_valid:
            return "invalid_crc", "CRC validation failed."
        if not packet.authentication_valid:
            receiver.trust_status = TrustStatus.SUSPICIOUS
            return "invalid_authentication", "Message authentication failed."
        if not isinstance(packet.payload, dict):
            return "invalid_payload", "The payload format is invalid."
        return None

    def _record_drop(
        self,
        sim: SeianMeshSimulator,
        item: PendingTransmission,
        step_number: int,
        reason: str,
        message: str,
        *,
        rssi: float | None = None,
        snr: float | None = None,
        link_quality: float | None = None,
    ) -> ManualStepRecord:
        self.dropped_events += 1
        sender = sim.nodes.get(item.sender_id)
        if sender is not None:
            sender.remember_drop(reason)
        sim.metrics.record_drop(reason)
        if reason == "collision":
            sim.metrics.collisions += 1
        if reason == "channel_busy":
            sim.metrics.channel_busy_events += 1
        packet = item.packet
        record = ManualStepRecord(
            step=step_number,
            timestamp=sim.now,
            status="DROPPED",
            action="Transmission attempt",
            sender_id=item.sender_id,
            receiver_id=item.receiver_id,
            origin_id=packet.origin_id,
            destination_id=packet.destination_id,
            packet_type=packet.packet_type.value,
            sequence_number=packet.sequence_number,
            priority=packet.priority,
            hop_count=packet.hop_count,
            ttl=packet.ttl,
            rssi=rssi,
            snr=snr,
            link_quality=link_quality,
            message=message,
            path=[*packet.path, item.receiver_id],
        )
        self.history.append(record)
        self._append_packet_event(sim, record, delivered=False, drop_reason=reason)
        self._refresh_completion()
        return record

    def _append_decision_record(
        self,
        sim: SeianMeshSimulator,
        node_id: str,
        packet: Packet,
        status: str,
        message: str,
    ) -> None:
        self.history.append(
            ManualStepRecord(
                step=len(self.history) + 1,
                timestamp=sim.now,
                status=status,
                action="Routing decision",
                sender_id=node_id,
                receiver_id=node_id,
                origin_id=packet.origin_id,
                destination_id=packet.destination_id,
                packet_type=packet.packet_type.value,
                sequence_number=packet.sequence_number,
                priority=packet.priority,
                hop_count=packet.hop_count,
                ttl=packet.ttl,
                rssi=None,
                snr=None,
                link_quality=None,
                message=message,
                path=list(packet.path),
            )
        )

    def _append_packet_event(
        self,
        sim: SeianMeshSimulator,
        record: ManualStepRecord,
        *,
        delivered: bool,
        drop_reason: str | None,
    ) -> None:
        sender = sim.nodes.get(record.sender_id)
        receiver = sim.nodes.get(record.receiver_id)
        sim.packet_events.append(
            {
                "timestamp": record.timestamp,
                "source_id": record.sender_id,
                "receiver_id": record.receiver_id,
                "origin_id": record.origin_id,
                "packet_type": record.packet_type,
                "priority": record.priority,
                "ttl": record.ttl,
                "hop_count": record.hop_count,
                "source_x": sender.position_x if sender else None,
                "source_y": sender.position_y if sender else None,
                "receiver_x": receiver.position_x if receiver else None,
                "receiver_y": receiver.position_y if receiver else None,
                "delivered": delivered,
                "drop_reason": drop_reason,
                "path": "->".join(record.path),
                "manual": True,
                "manual_step": record.step,
            }
        )

    def _refresh_completion(self) -> None:
        if self.pending:
            self.complete = False
            self.completion_message = f"{len(self.pending)} event(s) waiting. Press Forward for the next transmission."
            return
        self.complete = True
        if self.destination_id is not None:
            if self.destination_id in self.delivered_nodes:
                self.completion_message = f"Packet reached {self.destination_id}."
            elif self.history:
                self.completion_message = "No more events remain; the destination was not reached."
            else:
                self.completion_message = "No transmission could be scheduled."
        else:
            self.completion_message = (
                f"Broadcast trace complete. {len(self.delivered_nodes)} node(s) received the packet; "
                f"{self.dropped_events} transmission(s) dropped."
            )
