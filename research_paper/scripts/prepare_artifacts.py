"""Generate paper assets from a frozen snapshot; never run or modify PSCAD."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

PAPER = Path(__file__).resolve().parents[1]
REPO = PAPER.parent
os.environ.setdefault("MPLCONFIGDIR", str(PAPER / ".mplconfig"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, Rectangle
import numpy as np

DATA = PAPER / "data"
FIGURES = PAPER / "figures"
TABLES = PAPER / "tables"
BUS_ORDER = ["G01", "N02", "N03", "N04", "N05", "N06"]
SHORT_NAMES = ["Baseline", "Isolation only", "Tie restoration", "Loop rejection",
               "Delayed restoration", "Physical fault"]
COLORS = {"G01": "#222222", "N02": "#0072B2", "N03": "#D55E00",
          "N04": "#009E73", "N05": "#CC79A7", "N06": "#6E5B00"}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def snapshot() -> None:
    workspace = REPO / "research_power_plane" / "pscad_workspace"
    sources = [workspace / "transient_scenario_results.json",
               workspace / "timed_feeder_build_report.json",
               workspace / "validation" / "graphical_gui_validation.json",
               workspace / "validation" / "graphical_command_edit.json"]
    scenario_files = sorted((REPO / "research_power_plane" / "examples" / "scenarios").glob("0[1-6]_*.json"))
    code_files = [REPO / "research_power_plane" / "AI_CONTEXT.md",
                  REPO / "research_power_plane" / "scripts" / "build_lv_feeder.py",
                  REPO / "research_power_plane" / "scripts" / "run_scenarios.py",
                  REPO / "research_power_plane" / "dashboard.py"]
    code_files.extend(sorted((REPO / "research_power_plane" / "seian_power_pipeline").glob("*.py")))
    code_files.extend([workspace / "SEIAN_LV_Timed_Switching.pscx",
                       workspace / "seian_pscad_timed_component_map.generated.json"])
    hashes = [{"path": p.relative_to(REPO).as_posix(), "bytes": p.stat().st_size,
               "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
              for p in sources + scenario_files + code_files]
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                              capture_output=True, text=True).stdout.strip()
    provenance = {"snapshot_utc": datetime.now(timezone.utc).isoformat(),
                  "repository_revision": revision, "inputs": hashes,
                  "method": "Read-only snapshot of existing saved experiments; no new PSCAD runs.",
                  "raw_psout_included": False,
                  "trace_previews_are_decimated": True}
    report = json.loads(sources[1].read_text(encoding="utf-8"))
    # Retain electrical evidence without embedding this computer's absolute paths.
    feeder = {key: report[key] for key in ["lines", "loads", "faults", "recorders"]}
    command_edit = json.loads(sources[3].read_text(encoding="utf-8"))
    evidence = {"provenance": provenance,
                "scenarios": json.loads(sources[0].read_text(encoding="utf-8")),
                "feeder": feeder,
                "gui_validation": json.loads(sources[2].read_text(encoding="utf-8")),
                "gui_command_edit": {key: command_edit[key] for key in
                                     ["plans", "physical_faults", "switching_timeline"]},
                "scenario_inputs": {p.stem: json.loads(p.read_text(encoding="utf-8"))
                                    for p in scenario_files}}
    write_json(DATA / "evidence_snapshot.json", evidence)
    write_json(DATA / "provenance.json", provenance)


def interval(scenario: dict, bus: str) -> dict | None:
    rows = scenario["measured_metrics"]["voltage_interruptions"].get(bus, [])
    if len(rows) > 1:
        raise ValueError(f"More than one interruption for {bus}; revise paper table semantics.")
    return rows[0] if rows else None


def validate(evidence: dict) -> None:
    scenarios = evidence["scenarios"]
    assert len(scenarios) == 6
    expected_counts = [0, 3, 5, 0, 5, 5]
    for (key, item), expected_events in zip(sorted(scenarios.items()), expected_counts):
        assert len(item["channels"]) == 31, key
        assert not item["build_messages"]["errors"], key
        assert not item["build_messages"]["warnings"], key
        assert item["timeline"]["event_count"] == expected_events, key
        duration = item["timeline"]["duration_s"]
        for name, channel in item["channels"].items():
            assert channel["samples"] == round(duration / 0.00005) + 1, (key, name)
            preview = channel["preview"]
            assert len(preview["time"]) == len(preview["values"]) == 501
            assert np.all(np.diff(preview["time"]) > 0)
            assert np.isfinite(preview["values"]).all()
            assert abs(preview["time"][-1] - duration) < 1e-8
            assert abs(preview["values"][-1] - channel["final"]) < 1e-8
        for bus in BUS_ORDER:
            row = interval(item, bus)
            if row:
                assert abs(row["duration_s"] - (row["end_s"] - row["start_s"])) < 1e-9
                assert row["threshold"] == 0.2
    assert scenarios["04_loop_rejection"]["accepted_commands"] == 0
    assert interval(scenarios["06_physical_fault_restoration"], "N03")["ongoing_at_end"]


def write_rows(name: str, rows: list[str]) -> None:
    # End the final row in the parent tabular, after LaTeX's input-file hooks.
    rows[-1] = rows[-1].removesuffix(r"\\").rstrip()
    (TABLES / name).write_text("\n".join(rows) + "\n", encoding="ascii")


def tables(evidence: dict) -> None:
    rows = []
    tex = []
    for index, (key, item) in enumerate(sorted(evidence["scenarios"].items()), 1):
        n04 = interval(item, "N04")
        duration = n04["duration_s"] if n04 else 0.0
        censored = bool(n04 and n04["ongoing_at_end"])
        samples = item["channels"]["Vrms_N04"]["samples"]
        row = {"scenario_id": f"S{index}", "artifact_key": key,
               "description": SHORT_NAMES[index - 1], "duration_s": item["timeline"]["duration_s"],
               "commands": item["commands"], "accepted_commands": item["accepted_commands"],
               "switch_events": item["timeline"]["event_count"], "samples_per_channel": samples,
               "N04_below_threshold_s": duration, "N04_ongoing_at_end": censored,
               "N04_final_V": 1000 * item["channels"]["Vrms_N04"]["final"],
               "maximum_phase_fault_peak_kA": max(item["measured_metrics"]["fault_current_peak_abs_ka"].values())}
        rows.append(row)
        value = rf"$\geq {duration:.4f}$" if censored else f"{duration:.4f}"
        tex.append(f"S{index} & {SHORT_NAMES[index - 1]} & {row['duration_s']:g} & "
                   f"{item['accepted_commands']}/{item['commands']} & {row['switch_events']} & "
                   f"{samples:,} & {value} " + r"\\")
    with (DATA / "scenario_summary.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    write_rows("scenario_rows.tex", tex)

    tex = []
    for line in evidence["feeder"]["lines"]:
        ends = line["line_id"].removeprefix("SW_").removesuffix("_TIE").replace("_", "--")
        state = "Closed" if line["initial_closed"] else "Open (tie)"
        tex.append(f"{ends} & {line['r_ohm']:.5f} & {line['l_henry'] * 1e6:.2f} & {state} " + r"\\")
    write_rows("line_rows.tex", tex)

    tex = []
    for load in evidence["feeder"]["loads"]:
        tex.append(f"{load['node']} & {load['kw']:g} & {load['kw'] * 0.98:.2f} & {load['r_phase_ohm']:.5f} " + r"\\")
    write_rows("load_rows.tex", tex)

    tex = []
    scenarios = evidence["scenarios"]
    for bus in ["N03", "N04", "N05", "N06"]:
        vals = [scenarios[k]["channels"][f"Vrms_{bus}"]["final"] * 1000 for k in
                ["01_no_fault_baseline", "03_tie_switch_restoration", "06_physical_fault_restoration"]]
        tex.append(bus + " & " + " & ".join(f"{v:.2f}" for v in vals) + r" \\")
    write_rows("voltage_rows.tex", tex)

    tex = []
    for bus in ["N04", "N05", "N06"]:
        vals = [interval(scenarios[k], bus)["duration_s"] for k in
                ["03_tie_switch_restoration", "05_degraded_control_plane", "06_physical_fault_restoration"]]
        tex.append(bus + " & " + " & ".join(f"{v:.5f}" for v in vals) + r" \\")
    write_rows("interruption_rows.tex", tex)


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(FIGURES / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(FIGURES / f"{name}.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def architecture() -> None:
    fig, ax = plt.subplots(figsize=(9.5, 3.6))
    ax.set(xlim=(0, 10), ylim=(0, 4.15))
    ax.axis("off")
    boxes = [(0.15, 2.6, "Network-team output\nJSON command batch"),
             (3.8, 2.6, "Power-plane adapter\nChecks + timeline"),
             (7.45, 2.6, "PSCAD execution\nTimed EMT experiment"),
             (0.15, 0.5, "Streamlit dashboard\nGraphical JSON editor"),
             (3.8, 0.5, "Saved evidence\nMetrics + provenance"),
             (7.45, 0.5, "PSOUT extraction\n31 research channels")]
    for x, y, label in boxes:
        ax.add_patch(Rectangle((x, y), 2.4, 0.95, facecolor="#F3F6F7", edgecolor="#424242", lw=1))
        ax.text(x + 1.2, y + 0.475, label, ha="center", va="center", fontsize=10)
    for a, b in [((2.55, 3.08), (3.8, 3.08)), ((6.2, 3.08), (7.45, 3.08)),
                 ((8.65, 2.6), (8.65, 1.45)), ((7.45, 0.975), (6.2, 0.975)),
                 ((3.8, 0.975), (2.55, 0.975)), ((1.35, 1.45), (3.8, 2.6))]:
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=13, lw=1.3, color="#0072B2"))
    ax.text(6.83, 3.42, "MCP + API", ha="center", fontsize=8.5)
    ax.text(3.0, 1.85, "Apply", ha="center", fontsize=8.5)
    ax.text(5, 0.07, "Each submitted change starts a new batch run; no live solver feedback to the network controller.",
            ha="center", fontsize=9)
    save(fig, "architecture")


def feeder(evidence: dict) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.25))
    pos = {"G01": (0, 1.4), "N02": (1.4, 1.4), "N03": (3.0, 1.4),
           "N04": (4.6, 1.4), "N05": (3, 0), "N06": (4.6, 0)}
    for index, ax in enumerate(axes):
        for line in evidence["feeder"]["lines"]:
            a, b = line["line_id"].removeprefix("SW_").removesuffix("_TIE").split("_")
            closed = line["initial_closed"] if index == 0 else ("N03" not in [a, b])
            xy = np.array([pos[a], pos[b]])
            ax.plot(xy[:, 0], xy[:, 1], color="#0072B2" if closed else "#999999",
                    lw=2.3 if closed else 1.4, ls="-" if closed else "--", zorder=1)
        for bus, (x, y) in pos.items():
            color = "#D55E00" if index == 1 and bus == "N03" else "#222222"
            ax.scatter(x, y, s=115 if bus == "G01" else 65, color=color,
                       marker="s" if bus == "G01" else "o", zorder=2)
            label_y = y - 0.24 if bus in {"N05", "N06"} else y + 0.23
            ax.text(x, label_y, bus, ha="center", fontsize=10)
        ax.text(0, 0.99, "400 V\n50 Hz", ha="center", fontsize=8.5)
        if index == 1:
            ax.text(3.15, 1.05, "isolated", ha="left", color="#D55E00", fontsize=8.5)
        ax.set_title(["(a) Initial radial feeder", "(b) Restored topology, N03 isolated"][index], fontsize=11)
        ax.set(xlim=(-0.4, 5.0), ylim=(-0.45, 2.1))
        ax.axis("off")
    fig.legend(handles=[Line2D([0], [0], color="#0072B2", lw=2.3, label="Closed branch"),
                        Line2D([0], [0], color="#999999", lw=1.4, ls="--", label="Open branch")],
               loc="lower center", ncol=2, frameon=False, fontsize=9)
    fig.subplots_adjust(bottom=0.18, wspace=0.2)
    save(fig, "feeder")


def transients(evidence: dict) -> None:
    item = evidence["scenarios"]["06_physical_fault_restoration"]
    fig, axes = plt.subplots(3, 1, figsize=(8.6, 6.5), sharex=True,
                             gridspec_kw={"height_ratios": [1.7, 1, 1]})
    for bus in ["N02", "N03", "N04", "N05", "N06"]:
        p = item["channels"][f"Vrms_{bus}"]["preview"]
        axes[0].plot(p["time"], np.array(p["values"]) * 1000, label=bus, color=COLORS[bus], lw=1.3)
    axes[0].axhline(200, color="#555555", lw=0.9, ls="--")
    axes[0].set(ylabel="Bus RMS voltage (V)", ylim=(-15, 450))
    axes[0].legend(ncol=5, loc="upper right", fontsize=8, frameon=False)
    for name, label, color in [("Irms_SW_N02_N05_TIE", "N02-N05 tie", "#0072B2"),
                               ("Irms_SW_N04_N06_TIE", "N04-N06 tie", "#009E73")]:
        p = item["channels"][name]["preview"]
        axes[1].plot(p["time"], np.array(p["values"]) * 1000, label=label, color=color, lw=1.3)
    axes[1].set(ylabel="Tie RMS current (A)", ylim=(-3, 45))
    axes[1].legend(ncol=2, loc="upper left", fontsize=8, frameon=False)
    # This panel shows exact INPUT schedules, not interpolated contact feedback.
    axes[2].step([4.5, 4.8, 5.2, 6.8], [0, 1, 0, 0], where="post",
                 color="#D55E00", label="Fault input (1 = active)", lw=1.3)
    axes[2].step([4.5, 5, 6.8], [0, 1, 1], where="post",
                 color="#222222", label="N03 breakers (1 = open)", lw=1.3)
    axes[2].step([4.5, 6, 6.8], [1, 0, 0], where="post",
                 color="#0072B2", label="Ties (0 = closed)", lw=1.3, ls="--")
    axes[2].set(xlabel="Simulation time (s)", ylabel="Scheduled inputs", ylim=(-0.1, 1.35), yticks=[0, 1])
    axes[2].legend(ncol=1, loc="center right", fontsize=7.8, frameon=True)
    for ax in axes:
        for t in [4.8, 5, 5.2, 6]:
            ax.axvline(t, color="#AAAAAA", ls=":", lw=0.8, zorder=0)
        ax.set_xlim(4.5, 6.8)
        ax.grid(axis="y", color="#DDDDDD", lw=0.6)
    fig.align_ylabels()
    fig.tight_layout()
    save(fig, "physical_fault")


def comparison(evidence: dict) -> None:
    scenarios = evidence["scenarios"]
    keys = ["03_tie_switch_restoration", "05_degraded_control_plane", "06_physical_fault_restoration"]
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.25), gridspec_kw={"width_ratios": [1.45, 1]})
    x = np.arange(3)
    for offset, bus in enumerate(["N04", "N05", "N06"]):
        values = [interval(scenarios[k], bus)["duration_s"] for k in keys]
        axes[0].bar(x + (offset - 1) * 0.24, values, width=0.22, color=COLORS[bus], label=bus)
    axes[0].set(yscale="log", ylim=(0.5, 80), ylabel="Time below 200 V (s)",
                xticks=x, xticklabels=["S3\nRestoration", "S5\nDelayed", "S6\nPhysical fault"])
    axes[0].legend(ncol=3, fontsize=8, frameon=False, loc="upper left")
    axes[0].set_title("(a) Saved full-rate interval metrics", fontsize=10)
    peaks = scenarios[keys[2]]["measured_metrics"]["fault_current_peak_abs_ka"]
    values = [peaks[f"Ifault{p}_FAULT_N03"] for p in "ABC"]
    bars = axes[1].bar(list("ABC"), values, color=["#0072B2", "#D55E00", "#009E73"], width=0.55)
    for bar, value in zip(bars, values):
        axes[1].text(bar.get_x() + bar.get_width() / 2, value + 0.05, f"{value:.3f}", ha="center", fontsize=9)
    axes[1].set(ylabel="Peak absolute fault current (kA)", ylim=(0, 1.95), xlabel="Phase")
    axes[1].set_title("(b) S6 full-rate peaks", fontsize=10)
    for ax in axes:
        ax.set_axisbelow(True)
        ax.grid(axis="y", color="#DDDDDD", lw=0.6)
    fig.tight_layout()
    save(fig, "comparison")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", action="store_true", help="Read current project evidence and refresh the paper-only snapshot.")
    args = parser.parse_args()
    for folder in [DATA, FIGURES, TABLES]:
        folder.mkdir(parents=True, exist_ok=True)
    if args.snapshot:
        snapshot()
    evidence = json.loads((DATA / "evidence_snapshot.json").read_text(encoding="utf-8"))
    validate(evidence)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
                         "pdf.fonttype": 42, "axes.spines.top": False, "axes.spines.right": False})
    tables(evidence)
    architecture()
    feeder(evidence)
    transients(evidence)
    comparison(evidence)
    write_json(DATA / "artifact_validation.json", {"scenario_count": 6, "channels_per_scenario": 31,
               "preview_points_per_channel": 501, "checks": "passed", "new_pscad_runs": 0,
               "source_revision": evidence["provenance"]["repository_revision"]})
    print("Validated six saved scenarios; generated four figures, five tables, and one CSV inside research_paper/.")


if __name__ == "__main__":
    main()
