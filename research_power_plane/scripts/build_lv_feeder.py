"""Build the sibling SEIAN_LV_Timed_Switching PSCAD LV EMT feeder model.

Builds, on the existing case's Main canvas: a Thevenin source at G01, buses at
every node, a breaker3 on every logical line, lumped R/L branches for line
impedance, Y-connected loads at N02..N06, and multimeter instrumentation
(bus RMS voltage, per-line RMS current and active power).

Two PSCAD mechanics drive the whole design, both of which are easy to get
wrong (see AI_CONTEXT.md for the dead ends):

* **Switching.** breaker3's ``NAME`` is a *control signal reference*, not a
  label: the breaker reads a real signal of that name every timestep, 0 =
  closed, 1 = open. Each line therefore gets PSCAD's native ``tbreakn``
  (Timed Breaker Logic) feeding ``datalabel(Name=<line_id>)``. The dashboard
  writes ``INIT``/``NUMS``/``TO1``/``TO2`` so controller timestamps become
  physical breaker operations inside one continuous EMT run. breaker3's own
  ``BOpen1/2/3`` parameters are GUI animation state and switch nothing.
* **Recording.** A channel lands in the ``.psout`` only via a ``pgb``
  ("Output Channel") fed by a real signal. Each multimeter names its
  measurements (``Crms``/``P``/``Vrms``) and ``_build_recorders`` wires
  ``datalabel -> pgb`` for each, giving full-sample-rate traces. Components'
  ``animate="true"`` fields do appear in the .psout but only as ~3-sample GUI
  snapshots that don't track switching, so they are not used for results.

Uses the ``mhi.pscad`` automation API directly (like bootstrap_pscad_workspace.py)
because the PSCAD MCP server can operate an existing project but cannot create
new components/wires on the canvas.

Electrical parameters (LV voltage base, frequency, per-km cable impedance
scaling, and per-node demand) are not specified anywhere in the topology
JSON (which only carries line capacity_kw) or in AI_CONTEXT.md, so they are
research-illustrative assumptions -- see AI_CONTEXT.md for the exact values
and the reasoning, and replace them with real cable/load data as it becomes
available.
"""

from __future__ import annotations

import json
import math
import traceback
from pathlib import Path
from typing import Any

import mhi.pscad

import sys


ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research_power_plane"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))

from seian_power_pipeline.project_config import (
    TIMED_BUILD_ERROR_FILE,
    TIMED_BUILD_REPORT_FILE,
    TIMED_CASE_FILE,
    TIMED_CASE_NAME,
    TIMED_MAP_FILE,
    WORKSPACE_DIR,
    WORKSPACE_FILE,
)

CASE_NAME = TIMED_CASE_NAME
CASE_FILE = TIMED_CASE_FILE
TOPOLOGY_FILE = RESEARCH / "examples" / "lv_power_plane_microgrid.json"
MAP_FILE = TIMED_MAP_FILE
REPORT_FILE = TIMED_BUILD_REPORT_FILE
ERROR_FILE = TIMED_BUILD_ERROR_FILE

# --- Illustrative LV feeder assumptions (topology JSON has no V/Hz/impedance/demand data) ---
VLL_KV = 0.4            # LV secondary line-line RMS voltage base
FREQ_HZ = 50.0           # grid frequency
SOURCE_R_OHM = 0.02      # stiff Thevenin source series resistance
R_OHM_PER_KW = 3.0       # illustrative: line resistance ~ inverse of rated capacity
XR_RATIO = 0.3           # typical LV cable X/R ratio
LOAD_KW = {"N02": 8.0, "N03": 8.0, "N04": 10.0, "N05": 8.0, "N06": 6.0}
LOAD_PF = 0.98           # near-unity resistive load approximation

# breaker3 control-signal convention: the breaker reads the signal named by its
# NAME parameter every timestep; 0 holds it closed, 1 opens it.
BREAKER_CLOSED = 0
BREAKER_OPEN = 1
IDLE_OPERATION_TIME_S = 1_000_000.0

# Bus layout (PSCAD grid units) -- graph shape mirrors the JSON topology.
# New PSCAD cases clamp negative and very large coordinates when reopened, so
# every generated item deliberately stays within the initial positive canvas.
# Every bus has a distinct X coordinate so a wire leaving a bus along its own
# column cannot pass through an unrelated bus and create an implicit splice.
BUS_XY = {
    "G01": (50, 80),
    "N02": (110, 80),
    "N03": (170, 80),
    "N04": (230, 80),
    "N05": (140, 170),
    "N06": (290, 170),
}
GND_XY = (10, 125)

# (line_id, from_node, to_node, chain_row_y, chain_x_start, entry_corridor_y,
# exit_corridor_y). A chain row may equal both endpoint rows (straight, no
# bend needed). The corridor_y values are
# dedicated rows (never a bus or chain row) used only to route the
# entry/exit bend *around* the chain's own components instead of through
# them -- see ``_connect``.
LINES = [
    ("SW_G01_N02", "G01", "N02", 80, 65, None, None),
    ("SW_N02_N03", "N02", "N03", 80, 125, None, None),
    ("SW_N03_N04", "N03", "N04", 80, 185, None, None),
    ("SW_N05_N06", "N05", "N06", 170, 170, None, None),
    ("SW_N03_N05", "N03", "N05", 125, 80, 121, 129),
    ("SW_N02_N05_TIE", "N02", "N05", 145, 220, 141, 149),
    ("SW_N04_N06_TIE", "N04", "N06", 210, 240, 206, 214),
]


def main() -> int:
    try:
        report = build_feeder()
    except Exception:
        ERROR_FILE.write_text(traceback.format_exc(), encoding="utf-8")
        print(f"Feeder build failed. See {ERROR_FILE}")
        return 1

    REPORT_FILE.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "case_file": report["case_file"],
                "mapping_file": report["mapping_file"],
                "line_count": len(report["lines"]),
                "load_count": len(report["loads"]),
                "voltmeter_count": len(report["voltmeters"]),
                "recorded_channel_count": len(report["recorders"]),
            },
            indent=2,
        )
    )
    return 0


def build_feeder() -> dict[str, Any]:
    topo = json.loads(TOPOLOGY_FILE.read_text(encoding="utf-8"))
    closed_by_line = {row["line_id"]: bool(row["closed"]) for row in topo["power_lines"]}
    capacity_by_line = {row["line_id"]: float(row["capacity_kw"]) for row in topo["power_lines"]}

    pscad = mhi.pscad.application()
    try:
        project = pscad.project(CASE_NAME)
    except ValueError:
        pscad.load(str(WORKSPACE_FILE))
        try:
            project = pscad.project(CASE_NAME)
        except ValueError:
            project = pscad.create_case(str(CASE_FILE))
            # A brand-new case must be persisted once before placing a large
            # schematic. Otherwise PSCAD 5.0.1 can clamp outlying coordinates
            # to the default page bounds when the project is next reopened.
            project.save()
            pscad.save_workspace(str(WORKSPACE_FILE))
    project.focus()
    main = project.canvas("Main")

    main.delete(*main.components())

    main.create_sticky_note(10, 245, text="SEIAN LV EMT feeder (generated by build_lv_feeder.py)")
    main.create_sticky_note(
        10,
        250,
        text=(
            f"Assumptions: {VLL_KV} kV LL, {FREQ_HZ} Hz, line R={R_OHM_PER_KW} ohm*kW / capacity, "
            f"X/R={XR_RATIO}. Loads (kW): {LOAD_KW}. Replace with real cable/load data when available."
        ),
    )

    ground = main.create_component("master:ground", GND_XY[0], GND_XY[1] - 6)
    gnd_bus = main.create_bus((GND_XY[0] - 2, GND_XY[1]), (GND_XY[0] + 2, GND_XY[1]))
    gnd_bus.parameters(Name="BUS_GND")
    main.create_wire(ground.port("A"), (GND_XY[0], GND_XY[1]))

    source = main.create_component(
        "master:source3",
        BUS_XY["G01"][0] - 20,
        BUS_XY["G01"][1],
        View=1,
        Ctrl=0,
        Type=1,
        R1s=SOURCE_R_OHM,
        MVA=1.0,
        Vm=VLL_KV,
        F=FREQ_HZ,
        Es=VLL_KV,
        F0=FREQ_HZ,
        Ph=0,
    )
    main.create_wire(source.port("N"), (GND_XY[0], GND_XY[1]))

    buses = {}
    for node, (x, y) in BUS_XY.items():
        bus = main.create_bus((x - 2, y), (x + 2, y))
        bus.parameters(Name=f"BUS_{node}")
        buses[node] = bus

    main.create_wire(source.port("N3"), BUS_XY["G01"])

    line_report = []
    for line_id, from_node, to_node, row_y, x_start, entry_corr_y, exit_corr_y in LINES:
        chain = _build_line_chain(
            main,
            line_id=line_id,
            from_point=BUS_XY[from_node],
            to_point=BUS_XY[to_node],
            row_y=row_y,
            x_start=x_start,
            entry_corridor_y=entry_corr_y,
            exit_corridor_y=exit_corr_y,
            closed=closed_by_line[line_id],
            capacity_kw=capacity_by_line[line_id],
        )
        line_report.append(chain)

    load_report = []
    for node, kw in LOAD_KW.items():
        load_report.append(_build_load(main, node, BUS_XY[node], kw))

    voltmeter_report = []
    for node, (x, y) in BUS_XY.items():
        voltmeter_report.append(_build_bus_voltmeter(main, node, (x, y)))

    # Turn every named measurement signal into a recorded PSOUT channel.
    signals: list[tuple[str, str, str]] = []
    for row in voltmeter_report:
        signals.extend((name, name, "kV") for name in row["signals"])
    for row in line_report:
        for name in row["signals"]:
            signals.append((name, name, "kA" if name.startswith("Irms_") else "MW"))
        signals.append((row["control_signal"], f"State_{row['line_id']}", "binary"))
    recorder_report = _build_recorders(main, signals)

    project.parameters(time_duration=1.0, time_step=25.0, sample_step=50.0, PlotType="PSOUT")
    project.save()
    pscad.save_workspace(str(WORKSPACE_FILE))

    mapping = {
        "schema_version": 2,
        "project_name": CASE_NAME,
        "control_model": "master:tbreakn",
        "line_bindings": [
            {
                "line_id": row["line_id"],
                # The tbreakn component feeding this line's datalabel.
                "component_id": row["switch_id"],
                "closed_parameter": "INIT",
                "closed_value": BREAKER_CLOSED,
                "open_value": BREAKER_OPEN,
                "closed_parameters": {
                    "INIT": BREAKER_CLOSED,
                    "NUMS": 1,
                    "TO1": IDLE_OPERATION_TIME_S,
                    "TO2": IDLE_OPERATION_TIME_S + 1.0,
                },
                "open_parameters": {
                    "INIT": BREAKER_OPEN,
                    "NUMS": 1,
                    "TO1": IDLE_OPERATION_TIME_S,
                    "TO2": IDLE_OPERATION_TIME_S + 1.0,
                },
                "timed_control": {
                    "initial_state_parameter": "INIT",
                    "operation_count_parameter": "NUMS",
                    "operation_time_parameters": ["TO1", "TO2"],
                    "closed_value": BREAKER_CLOSED,
                    "open_value": BREAKER_OPEN,
                },
            }
            for row in line_report
        ],
    }
    MAP_FILE.write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    return {
        "case_file": str(CASE_FILE),
        "mapping_file": str(MAP_FILE),
        "source_id": _iid(source),
        "ground_id": _iid(ground),
        "lines": line_report,
        "loads": load_report,
        "voltmeters": voltmeter_report,
        "recorders": recorder_report,
    }


def _build_line_chain(
    main: Any,
    *,
    line_id: str,
    from_point: tuple[int, int],
    to_point: tuple[int, int],
    row_y: int,
    x_start: int,
    entry_corridor_y: int | None,
    exit_corridor_y: int | None,
    closed: bool,
    capacity_kw: float,
) -> dict[str, Any]:
    r_ohm = R_OHM_PER_KW / max(capacity_kw, 1.0)
    x_ohm = r_ohm * XR_RATIO
    l_henry = x_ohm / (2 * math.pi * FREQ_HZ)

    # Measurement -> recorded channel works via multimeter's "Signal Names"
    # fields (Crms/CurI/P/Q/Vrms): each one declares a *named* EMTDC signal,
    # which a datalabel + pgb ("Output Channel") pair then records at the full
    # sample rate (see _build_recorders). A component's animate="true" fields
    # (Pd/Qd/Vd) also show up in the .psout but only as sparse GUI-animation
    # snapshots (~3 samples), so they are not used for results here.
    ammeter = main.create_component(
        "master:multimeter",
        x_start,
        row_y,
        Name=f"PQ_{line_id}",
        MeasP=1,
        MeasQ=1,
        MeasI=1,
        IRMS=1,
        Crms=f"Irms_{line_id}",
        P=f"P_{line_id}",
        Q=f"Q_{line_id}",
    )
    breaker = main.create_component(
        "master:breaker3",
        x_start + 9,
        row_y,
        NAME=line_id,
        IBRA=f"IA_{line_id}",
        IBRB=f"IB_{line_id}",
        IBRC=f"IC_{line_id}",
    )
    resistor = main.create_component("master:resistor", x_start + 18, row_y, R=r_ohm)
    inductor = main.create_component("master:inductor", x_start + 27, row_y, L=l_henry)
    # breaker3's NAME is a *control signal reference*: the breaker reads a real
    # signal of that name each timestep, 0 = closed, 1 = open. (Its BOpen1/2/3
    # parameters are only the GUI animation state -- setting them does not
    # switch anything, which is why the build fails with "expected signal
    # source 'NAME' is undefined" until a matching signal actually exists.)
    # Native Timed Breaker Logic publishes the state signal. Its initial state
    # and one/two operation times are written from the controller timeline.
    # A no-event run schedules TO1 far beyond the simulation duration.
    switch = main.create_component(
        "master:tbreakn",
        x_start,
        row_y - 6,
        Name=f"CTRL_{line_id}",
        INIT=BREAKER_CLOSED if closed else BREAKER_OPEN,
        NUMS=1,
        TO1=IDLE_OPERATION_TIME_S,
        TO2=IDLE_OPERATION_TIME_S + 1.0,
    )
    switch_label = main.create_component(
        "master:datalabel", x_start + 12, row_y - 6, Name=line_id
    )
    main.create_wire(switch.port("Sig"), switch_label.ports()["A"])

    # breaker3 (View=1) has N1 on its *right* (+36) and N2 on its *left* (-36).
    # multimeter's A is on the left, B on the right -- same left/right sense.
    _connect(main, ammeter.port("A"), from_point, row_y, entry_corridor_y)
    main.create_wire(ammeter.port("B"), breaker.port("N2"))
    main.create_wire(breaker.port("N1"), resistor.port("A"))
    main.create_wire(resistor.port("B"), inductor.port("A"))
    _connect(main, inductor.port("B"), to_point, row_y, exit_corridor_y)

    return {
        "line_id": line_id,
        "ammeter_id": _iid(ammeter),
        "breaker_id": _iid(breaker),
        "switch_id": _iid(switch),
        "resistor_id": _iid(resistor),
        "inductor_id": _iid(inductor),
        "signals": [f"Irms_{line_id}", f"P_{line_id}"],
        "control_signal": line_id,
        "r_ohm": r_ohm,
        "l_henry": l_henry,
        "initial_closed": closed,
    }


def _build_load(main: Any, node: str, bus_point: tuple[int, int], kw: float) -> dict[str, Any]:
    x, y = bus_point
    v_ln = (VLL_KV * 1000.0) / math.sqrt(3.0)
    p_per_phase_w = (kw * 1000.0 / 3.0) * LOAD_PF
    r_phase = (v_ln * v_ln) / max(p_per_phase_w, 1.0)

    # A chain's exit corridor makes its final approach vertically along the
    # bus's own column, so a load sitting on that same column would have its
    # port sit right on that wire. Offset clear of it and jog in at the end.
    load_x = x + 8
    load = main.create_component(
        "master:Yload",
        load_x,
        y - 15,
        Name=f"LOAD_{node}",
        A=1,
        B=1,
        C=1,
        N=8,
        Ra=r_phase,
        Rb=r_phase,
        Rc=r_phase,
    )
    main.create_wire(load.port("ABC"), (load_x, y), (x, y))

    return {
        "node": node,
        "load_id": _iid(load),
        "kw": kw,
        "r_phase_ohm": r_phase,
    }


def _build_bus_voltmeter(main: Any, node: str, bus_point: tuple[int, int]) -> dict[str, Any]:
    # master:voltmetergnd only carries a cosmetic "Name" label (no recorded
    # channel -- see the line-meter comment above), so this uses multimeter
    # (RMS=1) instead: its Vd is animate="true" and actually lands in PSOUT.
    # With no current measurement enabled, multimeter auto-shorts A to B
    # internally, so wiring both to the same bus point is a harmless
    # zero-impedance tap rather than a real loop.
    x, y = bus_point
    meter_x = x - 15
    meter = main.create_component(
        "master:multimeter",
        meter_x,
        y - 30,
        Name=f"V_{node}",
        RMS=1,
        Vrms=f"Vrms_{node}",
    )
    main.create_wire(meter.port("A"), (meter_x, y), (x, y))
    main.create_wire(meter.port("B"), (meter_x, y - 3), (x, y - 3), (x, y))
    return {"node": node, "voltmeter_id": _iid(meter), "signals": [f"Vrms_{node}"]}


def _build_recorders(main: Any, signals: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """Record each named measurement signal as a real PSOUT output channel.

    A multimeter's "Signal Names" field declares a named EMTDC signal but does
    not by itself record anything. ``master:datalabel`` puts that named signal
    onto a wire and ``master:pgb`` ("Output Channel") records it -- that pair
    is what produces a full-sample-rate trace (~20k samples for a 1 s run at
    the configured sample_step) instead of the ~3-sample animation snapshots.

    These are pure signal components with no electrical ports, so they are
    parked in a shallow bank above the feeder. Positive coordinates are
    essential: PSCAD clamps negative positions in a newly created case when
    it is reopened, which can otherwise merge unrelated signal components.
    """

    report: list[dict[str, Any]] = []
    for index, (source_signal, channel_name, unit) in enumerate(signals):
        x = 10 + (index % 9) * 35
        y = 15 + (index // 9) * 10
        label = main.create_component("master:datalabel", x, y, Name=source_signal)
        channel = main.create_component(
            "master:pgb",
            x + 15,
            y,
            Name=channel_name,
            Group="SEIAN",
            Units=unit,
            UseSignalName=0,
        )
        main.create_wire(label.ports()["A"], channel.ports()["Signl"])
        report.append(
            {
                "source_signal": source_signal,
                "signal": channel_name,
                "unit": unit,
                "pgb_id": _iid(channel),
            }
        )
    return report


def _connect(main: Any, port: Any, bus_point: tuple[int, int], row_y: int, corridor_y: int | None) -> None:
    """Wire a chain port (already at ``row_y``) to a bus.

    When the bus is on the same row this is a straight wire. Otherwise the
    naive route -- bend at (bus_x, row_y) then run along row_y into the port
    -- can sweep straight through the *other* components in the same chain
    whenever the bus sits on their far side. Routing the horizontal leg on a
    dedicated ``corridor_y`` (a row no component ever sits on) instead of
    ``row_y`` avoids that: it only ever touches a real port at its two ends.
    """
    bx, by = bus_point
    if by == row_y:
        main.create_wire(port, bus_point)
    else:
        main.create_wire(port, (port.x, corridor_y), (bx, corridor_y), bus_point)


def _iid(component: Any) -> int:
    return int(getattr(component, "iid"))


if __name__ == "__main__":
    raise SystemExit(main())
