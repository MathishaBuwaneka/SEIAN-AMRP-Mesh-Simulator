# SEIAN Power Plane PSCAD Pipeline

This folder is the research co-simulation layer for SEIAN AMRP. It translates
network-controller decisions into safety-checked LV switching schedules, runs
those schedules as physical breaker events in PSCAD, and returns measured EMT
traces to a Streamlit dashboard.

The colleagues' simulator remains unchanged at the repository root. All new
work is contained here in `research_power_plane/`.

## Quick Start

From the repository root:

```powershell
# Install the research-layer dependencies (PSCAD/licence installed separately).
py -3.13 -m pip install -r research_power_plane\requirements.txt

# Start the dashboard using the included, validated timed case.
py -3.13 research_power_plane\run_dashboard.py

# Run all tests.
py -3.13 -m pytest tests research_power_plane\tests -q -p no:cacheprovider
```

The launcher prints its URL, normally http://localhost:8502, and selects a
different port if occupied. The colleagues' dashboard on 8501 is independent.
The research dashboard defaults to Scenario 06, the generated timed case,
and its matching component map.

Keep `Auto-run PSCAD after replay` and `Simulate input changes` enabled.
Edit the command JSON and commit the edit by leaving the field (Tab works).
The dashboard automatically validates commands, schedules breakers, runs
PSCAD, verifies a fresh `.psout`, and charts the measurements. `Replay and
Simulate` runs the initial example or repeats unchanged inputs. Initial page
loads and download clicks do not trigger extra simulations.

The project-local MCP service starts automatically at
`http://127.0.0.1:8765/mcp` and retains its PSCAD connection across runs.
PSCAD 5.0.1 Educational, a working licence, GNU Fortran, PowerMCP 0.3.0,
and `mhi.psout` were used for validation on this PC.

## Pipeline

```text
AMRP/SDN controller output
        |
        v
NetworkControlCommand batch, ordered by timestamp
        |
        v
PowerPlaneState safety and radiality validation
        |
        v
Accepted SwitchingTimeline events + physical fault schedule
        |
        v
PSCAD tbreakn/tfaultn/tpflt parameter manifest
        |
        v
Persistent PowerMCP: apply -> clear current output -> build -> focus -> run
        |
        v
Fresh .psout with voltage, current, power, breaker, and fault traces
```

Rejected commands are still recorded in the research artifact, but produce no
physical PSCAD switch transition.

Each edit starts a new continuous EMT experiment with scheduled switching.
This is automatic batch co-simulation, not a real-time command injection into
an already-running EMT solver. The controller's always-connected transport
and measurement-to-controller feedback are a separate next-stage integration.

## Folder Layout

```text
research_power_plane/
  dashboard.py                         Streamlit co-simulation dashboard
  run_dashboard.py                     Dashboard launcher
  cli.py                               Batch and live PSCAD CLI
  AI_CONTEXT.md                        Detailed handoff and verified facts
  examples/
    lv_power_plane_microgrid.json      Six-bus LV topology
    network_control_commands.json      Default dashboard command batch
    scenarios/01..06_*.json            Research experiment cases
  pscad_workspace/
    SEIAN_PSCAD_Workspace.pswx
    SEIAN_LV_Switching.pscx             Preserved static validation case
    SEIAN_LV_Timed_Switching.pscx       Current transient case
    seian_pscad_timed_component_map.generated.json
    transient_scenario_results.json    Six-scenario measured dataset
    dashboard_pipeline_validation.json Live PowerMCP validation artifact
    dashboard_physical_fault_validation.json
    validation/                       Browser-run artifacts and screenshots
  scripts/
    build_lv_feeder.py                 Generate the timed EMT model
    run_scenarios.py                   Run the experiment matrix
    diagnose_feeder.py                 Inspect schematic geometry
    check_pscad_mcp.py                 Check MCP availability
    validate_dashboard.py             Real browser -> PSCAD validation
  seian_power_pipeline/
    control_plane.py                   Stable controller command contract
    controller_adapter.py              Colleagues' events -> commands
    faults.py                          Physical fault JSON contract
    power_plane.py                     Topology/safety state machine
    timeline.py                        Commands -> physical event schedules
    pscad_adapter.py                   Schedules -> PSCAD MCP manifest
    pscad_mcp_server.py                Persistent local PowerMCP service
    pscad_mcp_client.py                Apply/build/run/read orchestration
    pscad_gui.py                       Find/restore the actual PSCAD editor
    pscad_run_lock.py                  Exclude overlapping CLI/dashboard runs
    psout_reader.py                    Full-rate summaries + chart previews
    transient_analysis.py              Event samples and outage intervals
    psout_channels.py                  MCP output -> dashboard series
    pipeline.py                        End-to-end coordinator
  tests/                               Research-layer tests
```

## PSCAD Model

`SEIAN_LV_Timed_Switching` is a generated six-bus, seven-line LV EMT feeder:

- 0.4 kV line-line, 50 Hz Thevenin source at G01.
- R/L line branches with a three-phase breaker on every logical line.
- Y-connected loads at N02 through N06.
- Timed breaker logic driven by controller timestamps.
- Native timed ABC-to-ground fault branch at N03.
- Full-rate voltage, current, active-power, breaker-state, and fault recording.

There are 31 selected research channels:

```text
Vrms_<node>       6 bus RMS voltages (kV)
Irms_<line_id>    7 line RMS currents (kA)
P_<line_id>       7 line active powers (MW)
State_<line_id>   7 breaker commands (0 closed, 1 open)
Ifault[A-C]_<id>  3 instantaneous phase-fault currents (kA)
FaultState_<id>   1 physical fault state (0 clear, 1 active)
```

The earlier `SEIAN_LV_Switching` case and its static results are intentionally
preserved. The build script regenerates only `SEIAN_LV_Timed_Switching`.

## Switching Mapping

PSCAD's `breaker3.NAME` reads a real control signal: `0` closes the breaker and
`1` opens it. Each line therefore uses:

```text
master:tbreakn -> datalabel(Name=<line_id>) -> breaker3(NAME=<line_id>)
```

The generated map binds a logical line to the timed controller:

```json
{
  "line_id": "SW_N04_N06_TIE",
  "component_id": 123456,
  "timed_control": {
    "initial_state_parameter": "INIT",
    "operation_count_parameter": "NUMS",
    "operation_time_parameters": ["TO1", "TO2"],
    "closed_value": 0,
    "open_value": 1
  }
}
```

Component IDs change whenever the timed case is regenerated, so always use the
map written by the same `build_lv_feeder.py` run.

The same map also binds the N03 fault timing and electrical element:

```json
{
  "fault_id": "FAULT_N03",
  "node_id": "N03",
  "logic_component_id": 123456,
  "fault_component_id": 123457
}
```

A scenario activates it alongside controller commands:

```json
{
  "physical_faults": [{
    "fault_id": "FAULT_N03",
    "node_id": "N03",
    "start_s": 4.8,
    "duration_s": 0.4,
    "fault_type": "abc_ground",
    "resistance_ohm": 0.05
  }]
}
```

## CLI

Run the physical-fault restoration scenario through the exact PowerMCP path
used by the dashboard:

```powershell
py research_power_plane\cli.py `
  research_power_plane\examples\lv_power_plane_microgrid.json `
  research_power_plane\examples\scenarios\06_physical_fault_restoration.json `
  --component-map research_power_plane\pscad_workspace\seian_pscad_timed_component_map.generated.json `
  --workspace-file research_power_plane\pscad_workspace\SEIAN_PSCAD_Workspace.pswx `
  --project-name SEIAN_LV_Timed_Switching `
  --simulation-mode transient `
  --execute-pscad --read-outputs `
  --output research_power_plane\pscad_workspace\dashboard_physical_fault_validation.json
```

Omit `--execute-pscad` to generate and inspect the manifest without launching
PSCAD. Use `--simulation-mode steady-state` for final-state comparison runs.

## Verified Experiments

`scripts/run_scenarios.py` writes
`pscad_workspace/transient_scenario_results.json`. All six cases currently
build with zero errors and zero warnings.

The standalone model builder and experiment runner directly own PSCAD
automation. Stop the project MCP service and close its PSCAD session before
using them; do not run them alongside an active dashboard simulation:

```powershell
py -3.13 research_power_plane\scripts\build_lv_feeder.py
py -3.13 research_power_plane\scripts\run_scenarios.py
```

| Scenario | Physical events | Main result |
|---|---:|---|
| Baseline | 0 | All buses energized |
| Fault isolation | 3 at 5 s | N03 through N06 de-energized |
| Tie restoration | 3 at 5 s, 2 at 6 s | N04 through N06 restored after about 1 s |
| Loop rejection | 0 | Unsafe closure rejected before PSCAD |
| Degraded control | 3 at 5 s, 2 at 45 s | Restored buses remain out for about 40 s |
| Physical fault restoration | fault 4.8-5.2 s; switches at 5/6 s | About 1.55 kA fault peak; N04-N06 restored |

See [AI_CONTEXT.md](AI_CONTEXT.md) for measured voltages, currents, sample
counts, known constraints, and the exact remaining research work.

The real-browser test edits baseline and fault scenarios without pressing
Replay. It checks fresh files, 31 channels, expected breaker/voltage/fault
measurements, the same visible PSCAD process across runs, and mobile overflow.
It uses installed Edge and saves artifacts/screenshots in
`pscad_workspace/validation/`:

```powershell
py -3.13 -m pip install playwright
py -3.13 research_power_plane\scripts\validate_dashboard.py --url http://localhost:8502
```

## PowerMCP Note

The installed PowerMCP version is 0.3.0. Its stock nonblocking PSCAD run tool
can acknowledge a request without generating new results on this installation.
The local `pscad_mcp_server.py` wrapper focuses the requested case and calls
blocking `project.run()`. It does not modify the global Python installation.

The client also fails a run when PSCAD reports compiler errors or when no
new/modified `.psout` appears. This prevents a stale successful waveform from
being presented as the result of a new dashboard command.

PSCAD's overwrite dialog occurs during the build stage. Before building, the
client removes only `<case>.gf*/<case>.psout` under the selected workspace.
Named archives and other cases are untouched. The current raw file is
replaced on each run; download the research artifact or archive the raw file
under a different name to retain a particular experiment.

PowerMCP supplies channel metadata; `mhi.psout` reads all 31 recorded traces
locally. Summaries use every sample; chart previews contain at most 500 points
and include both endpoints. Use the raw PSOUT or scenario-runner event metrics
for precise switching times and publication plots, not the reduced preview.

The endpoint lock prevents overlapping dashboard/CLI runs. A minimized PSCAD
window is restored, never terminated. Logs are at
`%TEMP%\seian-pscad-mcp-8765.log`. A failed run is shown as an error and the CLI
exits nonzero; previous waveforms are not reported as a new successful run.

## Current Research Boundary

Electrical values are illustrative because the network topology supplies line
capacity but not cable, transformer, load, DER, grounding, or protection data.
Scenario 06 now inserts and measures a physical PSCAD fault. Its fault and
controller command times are currently supplied in one deterministic scenario
file; PSCAD protection has not yet sent a detected event back through a live
controller transport. The adapter can be connected to that persistent loop
when the colleagues' final API and calibrated protection settings are available.
