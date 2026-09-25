"""Deterministic shared-radio events; model assumptions in EVENT_RADIO_CHANNEL.md."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
import heapq
import itertools
import math
import random
from typing import Callable

from seian_sim.config import LoraConfig, RadioConfig
from seian_sim.lora_airtime import calculate_airtime, receiver_sensitivity_dbm
from seian_sim.lora_channel import LinkObservation, calculate_link_quality


@dataclass
class Transmission:
    id: int
    sender: str
    receivers: tuple[str, ...]
    frame_bytes: int
    profile: LoraConfig
    priority: int
    on_start: Callable
    on_result: Callable
    retry: bool = True
    attempt: int = 0
    backoffs: int = 0


@dataclass
class Flight:
    request: Transmission
    start: float
    end: float
    observations: dict[str, LinkObservation] = field(default_factory=dict)
    powers: dict[str, float] = field(default_factory=dict)


class EventRadio:
    """One heap of start/end/completion events for every simulated transmitter.

    Call step() at next_time, then process application queues. Same-time starts
    sense the same prior channel state; submitting first gives no CCA advantage.
    """

    def __init__(self, settings: RadioConfig, rng: random.Random,
                 position: Callable, available: Callable):
        settings.validate()
        self.settings = settings
        self.rng = rng
        self.position = position
        self.available = available
        self.now = 0.0
        self._events = []
        self._serial = itertools.count()
        self._ids = itertools.count(1)
        self._active: dict[int, Flight] = {}
        self._next_tx: dict[str, float] = {}
        self.records: list[dict] = []
        self.stats = Counter()

    @property
    def pending(self) -> bool:
        return bool(self._events)

    @property
    def next_time(self) -> float:
        return self._events[0][0]

    def _push(self, time, phase, kind, item):
        heapq.heappush(self._events, (time, phase, next(self._serial), kind, item))

    def schedule(self, sender, receivers, frame_bytes, profile, *, at, priority=1,
                 on_start=lambda request: None, on_result=lambda request, results: None,
                 retry=True):
        calculate_airtime(frame_bytes, profile)  # validates one physical frame
        if not math.isfinite(at) or at < self.now:
            raise ValueError("Radio events cannot be scheduled in the past.")
        receivers = tuple(sorted(set(receivers)))
        if not receivers or sender in receivers:
            raise ValueError("Transmission needs distinct remote receivers.")
        request = Transmission(next(self._ids), sender, receivers, frame_bytes,
                               deepcopy(profile), priority, on_start, on_result, retry)
        self._push(at, 2, "start", request)
        return request.id

    def _record(self, kind, request, **details):
        self.records.append(dict(timestamp=self.now, event=kind, transmission_id=request.id,
                                 sender=request.sender, attempt=request.attempt + 1, **details))

    @staticmethod
    def _overlaps(a, b):
        return abs(a.frequency_hz - b.frequency_hz) < (a.bandwidth_hz + b.bandwidth_hz) / 2

    def _power(self, flight, receiver):
        if receiver not in flight.powers:
            profile = flight.request.profile
            distance = max(1.0, math.dist(self.position(flight.request.sender), self.position(receiver)))
            flight.powers[receiver] = (profile.reference_rssi_dbm
                - 10 * profile.path_loss_exponent * math.log10(distance / profile.reference_distance_m)
                + self.rng.gauss(0, profile.shadow_fading_std_db))
        return flight.powers[receiver]

    def _backoff(self, request):
        slots = self.rng.randint(1, 2 ** min(10, request.backoffs + request.attempt + 1))
        return slots * self.settings.backoff_slot_s

    def _cancel(self, request, reason):
        self.stats[reason] += 1
        self._record(reason, request)
        request.on_result(request, {receiver: LinkObservation(False, 0, 0, 0, 0, reason)
                                    for receiver in request.receivers})

    def _start(self, request, prior):
        if not self.available(request.sender):
            self._cancel(request, "sender_inactive")
            return
        ready = self._next_tx.get(request.sender, self.now)
        if ready > self.now:
            self.stats["transmitter_deferrals"] += 1
            self._push(ready, 2, "start", request)
            return
        busy = self.settings.carrier_sense and any(
            self.available(f.request.sender) and self._overlaps(f.request.profile, request.profile)
            and self._power(f, request.sender) >= self.settings.carrier_sense_threshold_dbm
            for f in prior if f.request.sender != request.sender
        )
        if busy:
            self.stats["carrier_sense_busy"] += 1
            if request.backoffs >= self.settings.max_backoffs:
                self._cancel(request, "backoff_exhausted")
                return
            request.backoffs += 1
            delay = self._backoff(request)
            self._record("backoff", request, delay_s=delay)
            self._push(self.now + delay, 2, "start", request)
            return
        duration = calculate_airtime(request.frame_bytes, request.profile).total_s
        flight = Flight(request, self.now, self.now + duration)
        # One transceiver cannot transmit twice simultaneously; duty-cycle off-time
        # conservatively applies to this transmitter across every frequency.
        self._next_tx[request.sender] = self.now + duration / self.settings.duty_cycle
        for receiver in request.receivers:
            if not self.available(receiver):
                flight.observations[receiver] = LinkObservation(False, 0, 0, 0, duration, "receiver_inactive", duration)
                continue
            power = self._power(flight, receiver)
            cfg = request.profile
            noise = -174 + 10 * math.log10(cfg.bandwidth_hz) + cfg.receiver_noise_figure_db
            distance = math.dist(self.position(request.sender), self.position(receiver))
            reason = None
            if distance > cfg.max_range_m:
                reason = "outside_range"
            elif power < receiver_sensitivity_dbm(cfg):
                reason = "rssi_below_sensitivity"
            elif self.rng.random() < cfg.packet_loss_probability:
                reason = "packet_loss"
            elif self.rng.random() < cfg.interference_probability:
                reason = "interference"
            flight.observations[receiver] = LinkObservation(
                reason is None, power, power - noise,
                calculate_link_quality(power, power-noise, cfg.packet_loss_probability),
                duration + cfg.transmission_delay_s, reason, duration)
        self._active[request.id] = flight
        self.stats["physical_transmissions"] += 1
        self.stats["airtime_s"] += duration
        self._record("tx_start", request, end_s=flight.end, frame_bytes=request.frame_bytes,
                     frequency_hz=request.profile.frequency_hz, bandwidth_hz=request.profile.bandwidth_hz,
                     spreading_factor=request.profile.spreading_factor)
        request.on_start(request)
        self._push(flight.end, 0, "end", flight)

    def _interference(self):
        active = list(self._active.values())
        for flight in active:
            for receiver, obs in flight.observations.items():
                if not obs.delivered:
                    continue  # a damaged packet never recovers later in its airtime
                if any(other.request.sender == receiver for other in active):
                    obs.delivered, obs.drop_reason = False, "half_duplex"
                    continue
                interference = [other for other in active if other is not flight
                    and self._overlaps(flight.request.profile, other.request.profile)
                    and (self.settings.cross_sf_interference
                         or flight.request.profile.spreading_factor == other.request.profile.spreading_factor)]
                powers = [self._power(other, receiver) for other in interference
                          if self.available(receiver) and self.available(other.request.sender)]
                if powers:
                    maximum = max(powers)
                    total_dbm = maximum + 10 * math.log10(sum(10 ** ((p - maximum) / 10) for p in powers))
                    if obs.rssi - total_dbm < self.settings.capture_threshold_db:
                        obs.delivered, obs.drop_reason = False, "collision"
                    else:
                        self.stats["capture_checks_passed"] += 1

    def _end(self, flight):
        self._active.pop(flight.request.id, None)
        for receiver, obs in flight.observations.items():
            if not self.available(flight.request.sender):
                obs.delivered, obs.drop_reason = False, "sender_inactive"
            elif not self.available(receiver):
                obs.delivered, obs.drop_reason = False, "receiver_inactive"
        self._record("tx_end", flight.request)
        self._push(self.now + flight.request.profile.transmission_delay_s, 1, "complete", flight)

    def _complete(self, flight):
        request = flight.request
        for receiver, obs in flight.observations.items():
            if obs.delivered and not self.available(receiver):
                obs.delivered, obs.drop_reason = False, "receiver_inactive"
            self.stats["receptions" if obs.delivered else obs.drop_reason] += 1
            self._record("rx_success" if obs.delivered else "rx_drop", request,
                         receiver=receiver, reason=obs.drop_reason, rssi_dbm=obs.rssi)
        # Ideal outcome feedback, not an on-air ACK protocol. Broadcast is never retried.
        retryable = (request.retry and len(request.receivers) == 1
                     and not any(obs.delivered for obs in flight.observations.values()))
        request.on_result(request, flight.observations)
        if retryable and self.available(request.sender):
            if request.attempt < self.settings.max_retries:
                request.attempt += 1
                request.backoffs = 0
                self.stats["retries"] += 1
                delay = self.settings.retry_delay_s + self._backoff(request)
                self._record("retry", request, delay_s=delay)
                self._push(self.now + delay, 2, "start", request)
            else:
                self.stats["retry_exhausted"] += 1
                self._record("retry_exhausted", request)

    def step(self):
        if not self._events:
            return
        self.now = self.next_time
        starts = []
        while self._events and self._events[0][0] == self.now:
            _, _, _, kind, item = heapq.heappop(self._events)
            if kind == "end":
                self._end(item)
            elif kind == "complete":
                self._complete(item)
            else:
                starts.append(item)
        prior = list(self._active.values())
        # Same-source queue priority applies to contenders ready at this instant.
        for request in sorted(starts, key=lambda req: (-req.priority, req.sender, req.id)):
            self._start(request, prior)
        self._interference()

    def drain(self, max_events=100000):
        count = 0
        while self.pending:
            count += 1
            if count > max_events:
                raise RuntimeError("Radio event limit exceeded; pending events preserved.")
            self.step()
