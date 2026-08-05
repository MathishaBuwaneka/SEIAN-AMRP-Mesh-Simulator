"""Main deterministic SEIAN-AMRP simulation engine."""

from __future__ import annotations

import json
import logging
import random
from dataclasses import asdict, is_dataclass
from typing import Any

import pandas as pd

from seian_sim.config import SimulationConfig
from seian_sim.enums import EventCategory, FaultStatus, FaultType, NodeRole, PacketType, TrustStatus
from seian_sim.fault_model import SEVERITY_TTL, apply_fault_to_nodes, classify_fault_boundary, create_fault
from seian_sim.grid_model import GridModel
from seian_sim.lora_channel import LoraChannel
from seian_sim.metrics import Metrics
from seian_sim.models import EventRecord, FaultEvent, NeighborEntry, NodeSnapshot
from seian_sim.node import SeianNode
from seian_sim.packets import Packet, PRIORITY_CONTROL, PRIORITY_EMERGENCY, PRIORITY_FAULT, PRIORITY_TELEMETRY
from seian_sim.routing import RoutingEngine

logger = logging.getLogger(__name__)

class SimulationClock:
    """Minimal deterministic simulation clock used by the batch engine."""

    def __init__(self) -> None:
        self.now = 0.0

    def run(self, *, until: float) -> None:
        target = float(until)
        if target < self.now:
            raise ValueError("Simulation time cannot move backwards.")
        self.now = target


class SeianMeshSimulator:
    """Coordinates nodes, LoRa channel, routing, grid state, faults, and metrics."""

    def __init__(self, config: SimulationConfig | None = None) -> None:
        self.config = config or SimulationConfig()
        self.config.validate()
        self.rng = random.Random(self.config.random_seed)
        self.env = SimulationClock()
        self.channel = LoraChannel(self.config.lora, self.rng)
        self.grid = GridModel(self.config.grid, self.rng)
        self.routing = RoutingEngine(
            self.config.routing_weights, self.config.route_lifetime_s, self.config.max_hops
        )
        self.nodes: dict[str, SeianNode] = {}
        self.metrics = Metrics()
        self.events: list[EventRecord] = []
        self.measurements: list[NodeSnapshot] = []
        self.packet_events: list[dict[str, Any]] = []
        self.route_history: list[dict[str, Any]] = []
        self.fault_events: list[FaultEvent] = []
        self.whitelist: set[str] = set()

    @property
    def now(self) -> float:
        """Return current simulation time."""

        return float(self.env.now)

    def add_node(
        self,
        node_id: str,
        x: float,
        y: float,
        *,
        network_id: str | None = None,
        gateway_capable: bool = False,
        gateway_online: bool = False,
        role: NodeRole | None = None,
        load_percent: float | None = None,
        health_score: float = 1.0,
    ) -> SeianNode:
        """Add one inverter node to the simulation."""

        local_address = len(self.nodes) + 1
        node = SeianNode(
            node_id=node_id,
            local_address=local_address,
            network_id=network_id or self.config.network_id,
            position_x=x,
            position_y=y,
            role=role or (NodeRole.GATEWAY if gateway_capable else NodeRole.STANDARD),
            gateway_capable=gateway_capable,
            gateway_online=gateway_online,
            load_percent=load_percent if load_percent is not None else self.rng.uniform(25.0, 70.0),
            health_score=health_score,
        )
        self.nodes[node_id] = node
        self.whitelist.add(node_id)
        return node

    def move_node(self, node_id: str, x: float, y: float) -> None:
        node = self.nodes[node_id]
        node.position_x = x
        node.position_y = y

        for node in self.nodes.values():
            node.neighbor_table.clear()
            node.routing_table.clear()

        self.discover_neighbors()

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        self.whitelist.discard(node_id)

        for node in self.nodes.values():
            node.neighbor_table.pop(node_id, None)
            node.routing_table.pop(node_id, None)

        self.recalculate_routes("node removed")

    def clear_network(self) -> None:
        self.nodes.clear()
        self.whitelist.clear()
        self.events.clear()
        self.measurements.clear()
        self.packet_events.clear()
        self.route_history.clear()
        self.fault_events.clear()
        self.metrics = Metrics()

    

    def log(
        self,
        category: EventCategory,
        message: str,
        *,
        node_id: str | None = None,
        packet_type: PacketType | str | None = None,
        priority: int | None = None,
        fault_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append a timestamped event-log row."""

        self.events.append(
            EventRecord(
                timestamp=self.now,
                category=category,
                message=message,
                node_id=node_id,
                packet_type=packet_type.value if isinstance(packet_type, PacketType) else packet_type,
                priority=priority,
                fault_id=fault_id,
                details=details or {},
            )
        )

    def create_packet(
        self,
        source: SeianNode,
        packet_type: PacketType,
        *,
        destination_id: str | None = None,
        priority: int = PRIORITY_TELEMETRY,
        ttl: int = 6,
        payload: dict[str, Any] | None = None,
        crc_valid: bool = True,
        authentication_valid: bool = True,
        network_id: str | None = None,
        sequence_number: int | None = None,
    ) -> Packet:
        """Create a protocol packet from node state."""

        data = payload or {}
        return Packet(
            version=1,
            packet_type=packet_type,
            source_id=source.node_id,
            origin_id=source.node_id,
            destination_id=destination_id,
            sequence_number=sequence_number if sequence_number is not None else source.next_sequence(),
            priority=priority,
            hop_count=0,
            ttl=ttl,
            timestamp=self.now,
            payload_length=len(json.dumps(data, sort_keys=True)),
            payload=data,
            crc_valid=crc_valid,
            authentication_valid=authentication_valid,
            network_id=network_id or source.network_id,
            key_id=self.config.key_id,
            path=[source.node_id],
        )

    def discover_neighbors(self) -> None:
        """Perform startup discovery and route-advertisement behavior."""

        for node in self.nodes.values():
            node.neighbor_table.clear()
            node.routing_table.clear()
            self.log(EventCategory.DISCOVERY, "Initialized radio, neighbor table, and routing table.", node_id=node.node_id)
        for sender in self.nodes.values():
            if not sender.active:
                continue
            self.log(EventCategory.DISCOVERY, "Broadcast HELLO.", node_id=sender.node_id, packet_type=PacketType.HELLO)
            for receiver in self.nodes.values():
                if sender.node_id == receiver.node_id:
                    continue
                obs = self.channel.observe(sender.position, receiver.position)
                if not receiver.active:
                    self._drop(receiver, "receiver_inactive", PacketType.HELLO)
                    continue
                if sender.network_id != receiver.network_id:
                    self.log(EventCategory.SECURITY, "Ignored HELLO from different Network ID.", node_id=receiver.node_id)
                    continue
                if not obs.delivered:
                    self._drop(receiver, obs.drop_reason or "radio_drop", PacketType.HELLO)
                    continue
                self._add_neighbor(receiver, sender, obs.rssi, obs.snr, obs.link_quality)
                self._add_neighbor(sender, receiver, obs.rssi, obs.snr, obs.link_quality)
                self.log(
                    EventCategory.DISCOVERY,
                    f"HELLO_REPLY accepted from {receiver.node_id}.",
                    node_id=sender.node_id,
                    packet_type=PacketType.HELLO_REPLY,
                )
        self.recalculate_routes("initial discovery")
        for node in self.nodes.values():
            self.log(EventCategory.ROUTING, "Broadcast ROUTE_ADVERTISEMENT.", node_id=node.node_id, packet_type=PacketType.ROUTE_ADVERTISEMENT)

    def _add_neighbor(self, node: SeianNode, neighbor: SeianNode, rssi: float, snr: float, quality: float) -> None:
        entry = NeighborEntry(
            neighbor_id=neighbor.node_id,
            rssi=rssi,
            snr=snr,
            last_seen=self.now,
            hop_count=1,
            link_quality=quality,
            neighbor_health_score=neighbor.health_score,
            neighbor_fault_status=neighbor.fault_status,
            neighbor_voltage=neighbor.voltage_rms,
            neighbor_frequency=neighbor.frequency_hz,
            neighbor_phase_angle=neighbor.phase_angle_deg,
            neighbor_load_percent=neighbor.load_percent,
            gateway_distance=neighbor.gateway_distance,
            route_cost=0.0,
            trust_status=neighbor.trust_status,
        )
        is_new = neighbor.node_id not in node.neighbor_table
        node.neighbor_table[neighbor.node_id] = entry
        if is_new:
            self.log(EventCategory.DISCOVERY, f"Neighbor {neighbor.node_id} added.", node_id=node.node_id)

    def expire_neighbors(self) -> None:
        """Expire neighbor and route entries based on configured lifetimes."""

        for node in self.nodes.values():
            expired = [
                nid for nid, entry in node.neighbor_table.items()
                if self.now - entry.last_seen > self.config.neighbor_timeout_s
            ]
            for nid in expired:
                del node.neighbor_table[nid]
                self.log(EventCategory.DISCOVERY, f"Neighbor {nid} expired.", node_id=node.node_id)
            expired_routes = [
                dest for dest, entry in node.routing_table.items() if self.now > entry.route_lifetime
            ]
            for dest in expired_routes:
                del node.routing_table[dest]
                self.log(EventCategory.ROUTING, f"Route to {dest} expired.", node_id=node.node_id)
        self.recalculate_routes("expiration")

    def recalculate_routes(self, reason: str) -> None:
        """Rebuild routes and log transitions."""

        changed = self.routing.recalculate(self.nodes, self.now)
        self.metrics.route_changes += changed
        if changed:
            self.log(EventCategory.ROUTING, f"Routes recalculated after {reason}.", details={"changed_nodes": changed})
        for node in self.nodes.values():
            for entry in node.routing_table.values():
                self.route_history.append({
                    "timestamp": self.now,
                    "node_id": node.node_id,
                    "destination_id": entry.destination_id,
                    "next_hop_id": entry.next_hop_id,
                    "hop_count": entry.hop_count,
                    "route_cost": round(entry.route_cost, 4),
                    "backup_next_hop": entry.backup_next_hop,
                })

    def run(self, duration_s: float | None = None, step_s: float = 10.0) -> None:
        """Run a deterministic batch simulation in fixed steps."""

        target = self.now + (duration_s if duration_s is not None else self.config.duration_s)
        if not any(node.neighbor_table for node in self.nodes.values()):
            self.discover_neighbors()
        while self.now < target:
            self.env.run(until=min(target, self.now + step_s))
            self._step()

    def _step(self) -> None:
        for node in self.nodes.values():
            if not node.active:
                continue
            self.grid.update_node(node, self.now)
            self.measurements.append(NodeSnapshot(self.now, node.node_id, node.voltage_rms, node.frequency_hz, node.phase_angle_deg, node.current_a, node.active_power_kw, node.reactive_power_kvar, node.load_percent, node.power_factor, node.thd_percent, node.temperature_c, node.fault_status))
            self._send_heartbeat(node)
            self._send_telemetry(node)
        self.expire_neighbors()
        self.recalculate_routes("grid-state update")
        self.process_queues()
        self._sample_gateway_reachability()

    def _send_heartbeat(self, node: SeianNode) -> None:
        packet = self.create_packet(node, PacketType.HEARTBEAT, priority=PRIORITY_TELEMETRY, ttl=2, payload=self._measurement_payload(node))
        self.broadcast(node.node_id, packet)

    def _send_telemetry(self, node: SeianNode) -> None:
        gateways = [n.node_id for n in self.nodes.values() if n.gateway_capable and n.gateway_online and n.active]
        payload = self._measurement_payload(node)
        if not gateways:
            node.cached_gateway_telemetry.append({"timestamp": self.now, **payload})
            return
        gateway_id = gateways[0]
        packet = self.create_packet(node, PacketType.GRID_STATE_UPDATE, destination_id=gateway_id, priority=PRIORITY_TELEMETRY, ttl=self.config.max_hops, payload=payload)
        if not self.route_packet(node.node_id, packet):
            node.cached_gateway_telemetry.append({"timestamp": self.now, **payload})

    def _measurement_payload(self, node: SeianNode) -> dict[str, Any]:
        return {
            "voltage": round(node.voltage_rms, 2),
            "frequency": round(node.frequency_hz, 3),
            "phase": round(node.phase_angle_deg, 2),
            "load": round(node.load_percent, 2),
            "temperature": round(node.temperature_c, 2),
            "fault_status": node.fault_status.value,
        }

    def broadcast(self, source_id: str, packet: Packet, exclude: set[str] | None = None) -> bool:
        """Deliver a packet to all current neighbors."""

        source = self.nodes[source_id]
        delivered_any = False
        for neighbor_id in list(source.neighbor_table):
            if exclude and neighbor_id in exclude:
                continue
            delivered_any = self._deliver(source_id, neighbor_id, packet) or delivered_any
        return delivered_any

    def route_packet(self, source_id: str, packet: Packet) -> bool:
        """Route a unicast packet, falling back to local broadcast for alerts."""

        source = self.nodes[source_id]
        if packet.destination_id is None:
            return self.broadcast(source_id, packet)
        if packet.destination_id == source_id:
            return self.receive_packet(source_id, packet)
        entry = source.routing_table.get(packet.destination_id)
        if not entry:
            self.log(EventCategory.ROUTING, f"No route to {packet.destination_id}.", node_id=source_id, packet_type=packet.packet_type)
            return False
        next_hop = entry.next_hop_id
        if next_hop not in source.neighbor_table and entry.backup_next_hop:
            next_hop = entry.backup_next_hop
            self.log(EventCategory.ROUTING, f"Backup route selected via {next_hop}.", node_id=source_id)
        if next_hop in packet.path:
            self._drop(source, "route_loop", packet.packet_type)
            return False
        return self._deliver(source_id, next_hop, packet)

    def _deliver(self, source_id: str, receiver_id: str, packet: Packet) -> bool:
        source = self.nodes[source_id]
        receiver = self.nodes.get(receiver_id)
        if receiver is None or not receiver.active:
            self._drop(source, "receiver_inactive", packet.packet_type)
            return False
        obs = self.channel.observe(source.position, receiver.position, packet.payload_length)
        if packet.network_id != receiver.network_id:
            self._drop(receiver, "wrong_network_id", packet.packet_type)
            return False
        if receiver.trust_status == TrustStatus.BLOCKED:
            self._drop(receiver, "blocked_node", packet.packet_type)
            return False
        if not packet.crc_valid:
            self._drop(receiver, "invalid_crc", packet.packet_type)
            return False
        if not packet.authentication_valid:
            receiver.trust_status = TrustStatus.SUSPICIOUS
            self._drop(receiver, "invalid_authentication", packet.packet_type)
            return False
        if not isinstance(packet.payload, dict):
            self._drop(receiver, "invalid_payload", packet.packet_type)
            return False
        if not obs.delivered:
            if obs.drop_reason == "collision":
                self.metrics.collisions += 1
            if obs.drop_reason == "channel_busy":
                self.metrics.channel_busy_events += 1
            self._drop(receiver, obs.drop_reason or "radio_drop", packet.packet_type)
            return False
        self.metrics.packets_transmitted += 1
        
        self.metrics.throughput_by_time[int(self.now)] += 1

        event_row = {
            "timestamp": self.now,
            "source_id": source_id,
            "receiver_id": receiver_id,
            "origin_id": packet.origin_id,
            "packet_type": packet.packet_type.value,
            "priority": packet.priority,
            "ttl": packet.ttl,
            "hop_count": packet.hop_count,
            "source_x": source.position_x,
            "source_y": source.position_y,
            "receiver_x": receiver.position_x,
            "receiver_y": receiver.position_y,
            "delivered": True,
            "drop_reason": None,
            "path": "->".join(packet.path),
        }

        self.packet_events.append(event_row)
        source.recent_transmitted_packets.append(event_row)

        self._add_neighbor(receiver, source, obs.rssi, obs.snr, obs.link_quality)
        queued = receiver.enqueue_packet(packet, self.now, self.config.queue_limit)
        if not queued:
            self.metrics.queue_drops_by_priority[packet.priority] += 1
            self._drop(receiver, "queue_overflow", packet.packet_type)
            return False
        return True

    def process_queues(self) -> None:
        """Process queued packets in priority order."""

        for node in self.nodes.values():
            processed = 0
            while processed < 8:
                item = node.dequeue_packet()
                if item is None:
                    break
                delay = self.now - item.enqueued_at
                self.metrics.queue_delay_sum += delay
                self.metrics.queue_delay_max = max(self.metrics.queue_delay_max, delay)
                self.receive_packet(node.node_id, item.packet)
                processed += 1

    def receive_packet(self, receiver_id: str, packet: Packet) -> bool:
        """Receive, validate, suppress duplicates, deliver, and possibly forward."""

        receiver = self.nodes[receiver_id]
        if packet.packet_type not in {PacketType.HELLO, PacketType.HELLO_REPLY}:
            if receiver.recent_packet_cache.seen(packet, self.now):
                self.metrics.duplicate_drops += 1
                self.log(EventCategory.PACKET, "Duplicate packet suppressed.", node_id=receiver_id, packet_type=packet.packet_type, priority=packet.priority)
                return False
        receiver.recent_received_packets.append({"timestamp": self.now, "from": packet.source_id, "type": packet.packet_type.value, "priority": packet.priority})
        self.metrics.packets_delivered += 1
        self.metrics.record_latency(packet.priority, max(0.0, self.now - packet.timestamp))
        if packet.priority >= PRIORITY_FAULT:
            self.metrics.emergency_delivered += 1
        # Physical delivery attempts are recorded once in _deliver().  The
        # receiver keeps its own recent_received_packets list, so adding a
        # second packet_events row here would double-count each transmission.

        if packet.destination_id == receiver_id:
            return True
        if packet.packet_type == PacketType.FAULT_ALERT:
            self._handle_fault_alert(receiver, packet)
            if packet.ttl > 1 and packet.hop_count < self.config.max_hops:
                forwarded = packet.forwarded(receiver_id, self.now)
                self.metrics.packets_forwarded += 1
                self.broadcast(receiver_id, forwarded, exclude={packet.source_id})
            return True
        if packet.destination_id and packet.ttl > 1 and packet.hop_count < self.config.max_hops:
            forwarded = packet.forwarded(receiver_id, self.now)
            self.metrics.packets_forwarded += 1
            return self.route_packet(receiver_id, forwarded)
        if packet.ttl <= 1:
            self._drop(receiver, "ttl_expired", packet.packet_type)
        return True

    def _handle_fault_alert(self, receiver: SeianNode, packet: Packet) -> None:
        fault_id = str(packet.payload.get("fault_id", "unknown"))
        self.log(EventCategory.FAULT, "Fault alert received and acknowledged.", node_id=receiver.node_id, packet_type=packet.packet_type, priority=packet.priority, fault_id=fault_id)
        ack = self.create_packet(receiver, PacketType.FAULT_ACK, destination_id=packet.origin_id, priority=PRIORITY_CONTROL, ttl=self.config.max_hops, payload={"fault_id": fault_id})
        self.log(EventCategory.FAULT, "Fault acknowledgement generated.", node_id=receiver.node_id, packet_type=PacketType.FAULT_ACK, priority=PRIORITY_CONTROL, fault_id=fault_id)
        self.route_packet(receiver.node_id, ack)

    def inject_fault(
        self,
        origin_node_id: str,
        fault_type: FaultType = FaultType.VOLTAGE_SAG,
        *,
        severity: str = "severe",
        duration: float = 90.0,
        radius_m: float = 160.0,
    ) -> FaultEvent:
        """Inject a fault and begin controlled high-priority flooding."""

        origin = self.nodes[origin_node_id]
        fault = create_fault(origin, fault_type, severity, self.now, duration, radius_m)
        apply_fault_to_nodes(fault, self.nodes)
        classifications = classify_fault_boundary(fault, self.nodes)
        self.fault_events.append(fault)
        self.log(EventCategory.FAULT, f"Fault detected: {fault_type.value}.", node_id=origin.node_id, fault_id=fault.fault_id)
        for node_id, label in classifications.items():
            if label == "BOUNDARY_NODE":
                self.log(EventCategory.FAULT, "Boundary node identified.", node_id=node_id, fault_id=fault.fault_id)
        ttl = SEVERITY_TTL.get(severity, 4)
        priority = PRIORITY_EMERGENCY if severity == "emergency" else PRIORITY_FAULT
        self.metrics.emergency_sent += 1
        packet = self.create_packet(origin, PacketType.FAULT_ALERT, priority=priority, ttl=ttl, payload={
            "fault_id": fault.fault_id,
            "fault_type": fault.fault_type.value,
            "severity": severity,
            "recommended_action": fault.recommended_action,
        })
        self.broadcast(origin.node_id, packet)
        coord = self.create_packet(origin, PacketType.CONTROL_COORDINATION, priority=PRIORITY_CONTROL, ttl=ttl, payload={
            "fault_id": fault.fault_id,
            "recommendation": fault.recommended_action,
            "safety_note": "Simulated recommendation only; local protection overrides network coordination.",
        })
        self.broadcast(origin.node_id, coord)
        self.recalculate_routes("fault state change")
        return fault

    def fail_node(self, node_id: str) -> None:
        """Deactivate a node and trigger rerouting."""

        node = self.nodes[node_id]
        node.active = False
        node.health_score = 0.0
        node.fault_status = FaultStatus.FAULT
        for other in self.nodes.values():
            other.neighbor_table.pop(node_id, None)
        self.log(EventCategory.ROUTING, "Node failed; ROUTE_ERROR generated where needed.", node_id=node_id, packet_type=PacketType.ROUTE_ERROR)
        self.recalculate_routes("node failure")

    def recover_node(self, node_id: str) -> None:
        """Reactivate a node and rediscover links."""

        node = self.nodes[node_id]
        node.active = True
        node.health_score = max(0.75, node.health_score)
        node.fault_status = FaultStatus.NORMAL
        self.log(EventCategory.ROUTING, "Node recovered.", node_id=node_id)
        self.discover_neighbors()

    def set_gateway(self, node_id: str, online: bool = True) -> None:
        """Change gateway state for a node."""

        node = self.nodes[node_id]
        node.gateway_capable = True
        node.role = NodeRole.GATEWAY
        was_online = node.gateway_online
        node.gateway_online = online
        self.log(EventCategory.GATEWAY, "Gateway restored." if online and not was_online else "Gateway lost.", node_id=node_id)
        if online:
            self._flush_cached_gateway_telemetry(node_id)
        self.recalculate_routes("gateway state change")

    def _flush_cached_gateway_telemetry(self, gateway_id: str) -> None:
        for node in self.nodes.values():
            if node.node_id == gateway_id:
                continue
            for row in list(node.cached_gateway_telemetry):
                packet = self.create_packet(node, PacketType.GRID_STATE_UPDATE, destination_id=gateway_id, priority=PRIORITY_TELEMETRY, ttl=self.config.max_hops, payload=row)
                if self.route_packet(node.node_id, packet):
                    node.cached_gateway_telemetry.remove(row)

    def simulate_attack(self, source_id: str, attack: str) -> None:
        """Inject benign research packets that should be rejected."""

        source = self.nodes[source_id]
        kwargs: dict[str, Any] = {}
        if attack == "replay":
            kwargs["sequence_number"] = 1
        if attack == "invalid_authentication":
            kwargs["authentication_valid"] = False
        if attack == "wrong_network_id":
            kwargs["network_id"] = "OTHER-NET"
        if attack == "malformed_payload":
            packet = self.create_packet(source, PacketType.GRID_STATE_UPDATE, payload={})
            packet.payload = "bad"  # type: ignore[assignment]
        else:
            packet = self.create_packet(source, PacketType.GRID_STATE_UPDATE, payload={"attack": attack}, **kwargs)
        self.broadcast(source_id, packet)
        self.process_queues()

    def _drop(self, node: SeianNode, reason: str, packet_type: PacketType | str) -> None:
        node.remember_drop(reason)
        self.metrics.record_drop(reason)
        packet_type_value = packet_type.value if isinstance(packet_type, PacketType) else str(packet_type)
        self.packet_events.append({
            "timestamp": self.now,
            "source_id": None,
            "receiver_id": node.node_id,
            "origin_id": None,
            "packet_type": packet_type_value,
            "priority": None,
            "ttl": None,
            "hop_count": None,
            "source_x": None,
            "source_y": None,
            "receiver_x": node.position_x,
            "receiver_y": node.position_y,
            "delivered": False,
            "drop_reason": reason,
            "path": "",
        })
        self.log(EventCategory.PACKET, f"Packet dropped: {reason}.", node_id=node.node_id, packet_type=packet_type)

    def _sample_gateway_reachability(self) -> None:
        gateways = [n.node_id for n in self.nodes.values() if n.gateway_capable and n.gateway_online and n.active]
        for node in self.nodes.values():
            if not node.active:
                continue
            self.metrics.gateway_total_samples += 1
            if node.node_id in gateways or any(gid in node.routing_table for gid in gateways):
                self.metrics.gateway_reachable_samples += 1

    def export_dataframes(self) -> dict[str, pd.DataFrame]:
        """Return standard CSV-ready dataframes."""

        return {
            "measurements": pd.DataFrame([_jsonable(m) for m in self.measurements]),
            "packet_events": pd.DataFrame(self.packet_events),
            "route_history": pd.DataFrame(self.route_history),
            "fault_events": pd.DataFrame([
                {**_jsonable(f), "fault_type": f.fault_type.value, "affected_nodes": ",".join(sorted(f.affected_nodes))}
                for f in self.fault_events
            ]),
            "events": pd.DataFrame([_jsonable(e) for e in self.events]),
        }

    def export_tables_json(self) -> dict[str, Any]:
        """Return JSON-serializable neighbor, route, config, and summary tables."""

        return {
            "neighbor_tables": {
                nid: {k: _jsonable(v) for k, v in node.neighbor_table.items()} for nid, node in self.nodes.items()
            },
            "routing_tables": {
                nid: {k: _jsonable(v) for k, v in node.routing_table.items()} for nid, node in self.nodes.items()
            },
            "configuration": _jsonable(self.config),
            "summary_report": self.metrics.summary(),
        }
    
    def clear_network(self) -> None:
        """Remove all nodes, events, routes, packets, and metrics."""
        self.nodes.clear()
        self.whitelist.clear()
        self.events.clear()
        self.measurements.clear()
        self.packet_events.clear()
        self.route_history.clear()
        self.fault_events.clear()
        self.metrics = Metrics()

    def move_node(self, node_id: str, x: float, y: float) -> None:
        """Move a node and rebuild discovery/routing from the new geometry."""
        node = self.nodes[node_id]
        node.position_x = x
        node.position_y = y
        for n in self.nodes.values():
            n.neighbor_table.clear()
            n.routing_table.clear()
        self.discover_neighbors()

    def remove_node(self, node_id: str) -> None:
        """Remove a node from the simulated network."""
        self.nodes.pop(node_id, None)
        self.whitelist.discard(node_id)
        for node in self.nodes.values():
            node.neighbor_table.pop(node_id, None)
            node.routing_table.pop(node_id, None)
        self.recalculate_routes("node removed")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "value"):
        return value.value
    return value
