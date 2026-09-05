# AI Context: SEIAN Power Plane PSCAD Workflow

Last updated: 2026-09-05 Asia/Colombo

## Graphical Editor Update

The dashboard now wraps the existing JSON in graphical controls. Work is
contained in `dashboard_ui/` and `dashboard.py`; the networking simulator and
electrical model are unchanged. Feeder/breaker selection, a scheduled-state
preview, command/fault forms, initial switch states, readable PSCAD bindings,
and all six presets are implemented. Raw editors and JSON downloads remain in
the collapsed `Advanced JSON` section.

Canonical JSON is separate from raw widget state so form-triggered reruns do
not delete documents. Apply actions update only owned fields and retain
colleagues' metadata. Preview/selection changes never launch PSCAD; committed
edits use the existing automatic-run path. Bus wiring is not editable through
this layer because it must match the generated physical PSCAD case.

Validation complete: 114 repository tests passed. The actual Edge browser
selected N03 on the feeder, selected baseline and physical-fault presets, and
applied a graphical isolation-time edit from 5.0 to 5.1 s. All three runs
produced fresh PSCAD results with 31 channels and zero errors, using one
PSCAD instance (PID 33424 during this validation). Metadata and the unchanged
physical-fault schedule survived the command edit. Desktop/mobile screenshots
were inspected; the 390px page has no horizontal overflow.

Evidence: `pscad_workspace/validation/graphical_gui_validation.json`,
`graphical_baseline.json`, `graphical_physical_fault.json`,
`graphical_command_edit.json`, and `graphical_*.png` screenshots. Repeat with
`scripts/validate_graphical_dashboard.py`. `validate_dashboard.py` still tests
raw JSON editing through the collapsed Advanced JSON section. The research
layer now requires Streamlit >=1.63 for its graphical widget API.

## Finalization Checkpoint

Unattended Scenario 06 completed with 9 writes, 31 selected channels,
140,001 samples and zero errors. The overwrite prompt is avoided by removing
only the current generated case output BEFORE the build, where PSCAD raises
the prompt. Never interpret an idle acknowledgement as successful simulation.

The earlier "windowless PSCAD" diagnosis was incorrect: a minimized editor
has a small rectangle at (-32000, -32000). `pscad_gui.py` now recognizes and
restores it. Automatic process termination has been removed. Do not reintroduce
it to recover minimized windows. The local HTTP MCP service retains its PSCAD
connection; the dashboard reads fresh PSOUT traces directly using `mhi.psout`.

Real-browser integration passed: Playwright/Edge committed baseline and
physical-fault JSON edits by Tab, without a Replay click. Each edit produced
fresh PSCAD measurements, using the same editor process (PID 27608). Baseline
had 20,001 samples; physical fault had 140,001; both selected 31 channels and
reported zero errors. Baseline fault-branch leakage is about 1.3 mA, not
exactly zero; fault phase peaks exceed 1.55 kA. Desktop and 390px mobile charts
were captured; the mobile page has no horizontal overflow.

Evidence lives in `pscad_workspace/validation/`: two downloaded research
artifacts, desktop/mobile screenshots, and `dashboard_gui_validation.json`.
Repeat with `scripts/validate_dashboard.py` against the running dashboard.
The full test suite now passes (114 tests), including graphical and uploaded-file editor
persistence. Implementation and documentation are complete for the automatic
batch pipeline. The research dashboard is served on http://localhost:8502;
the timed SEIAN case is left open in PSCAD. Only the next-stage research work
listed below remains.

## Goal And Ownership

This repository combines the colleagues' SEIAN AMRP/network simulator with a
research power-plane layer. The controller behaves like an SDN control plane;
PSCAD is the physical LV data plane whose breakers execute accepted routing
decisions at controller timestamps.

The colleagues' code remains at the repository root and was not edited. All
power-plane, PSCAD, dashboard, generated-case, and research-result work lives
in the sibling folder:

```text
research_power_plane/
```

## Current Validated State

The controller-to-PSCAD transient pipeline works end to end.

- A dedicated timed PSCAD case is generated and survives close/reopen.
- Controller commands are sorted chronologically and safety-checked first.
- Accepted operations become physical breaker events inside one EMT run.
- Rejected commands remain in the artifact but create no breaker event.
- An optional native PSCAD fault can be scheduled independently from the
  controller commands that isolate and reroute around it.
- Every run builds before execution; PSCAD errors stop the pipeline.
- A run succeeds only when its `.psout` is newly created or modified.
- The dashboard uses the same PowerMCP path and charts all 31 research traces.
- All six paper scenarios build with zero errors and zero warnings.
- The complete repository test suite passes: **114 passed**.

## Quick Start

Run from the repository root:

```powershell
# Start the co-simulation dashboard with the included validated case.
py -3.13 research_power_plane\run_dashboard.py

# Run colleagues' and research-layer tests together.
py -3.13 -m pytest tests research_power_plane\tests -q -p no:cacheprovider

# Real browser edits -> PSCAD -> measured waveforms (requires Playwright/Edge).
py -3.13 research_power_plane\scripts\validate_dashboard.py --url http://localhost:8502
```

Do not run two PSCAD automation owners against this workspace simultaneously.
Stop the project MCP service and close its PSCAD session before running
`build_lv_feeder.py` or `run_scenarios.py` directly; those standalone scripts
own their own automation connection. Ordinary dashboard/CLI runs are protected
by a shared endpoint lock and should use the persistent service.

## End-To-End Pipeline

```text
AMRP/SDN routing output
  -> controller_adapter.py                     optional colleagues-format bridge
  -> NetworkControlCommand JSON
  -> chronological_commands()                  stable timestamp ordering
  -> PowerPlaneState.apply_command()           topology/radiality checks
  -> SwitchingTimeline                         accepted operations only

Optional physical_faults JSON
  -> PhysicalFaultEvent validation             node/type/time/resistance

SwitchingTimeline + PhysicalFaultEvent list
  -> PscadSwitchingAdapter                     tbreakn/tfaultn/tpflt manifest
  -> project-local PowerMCP server             focus + blocking PSCAD run
  -> SEIAN_LV_Timed_Switching                  continuous EMT simulation
  -> build-message and fresh-.psout guards
  -> local mhi.psout read: 31 full-rate summaries + bounded previews
  -> dashboard charts / JSON research artifact
```

The dashboard defaults to Scenario 06. With `Auto-run PSCAD after replay` and
`Simulate input changes` enabled, committing changed inputs automatically
starts this path. `Replay and Simulate` runs unchanged inputs, including the
first example. Initial page render and downloads do not trigger duplicate
simulations. Invalid inputs clear previous results and display an error.
`Controller timeline` is the research default; `Final steady state` is retained
for snapshot comparisons.

This is automatic batch co-simulation: each edit creates a new EMT run from
initial conditions. A persistent MCP connection is not a real-time feedback
loop with the networking controller. Do not claim live mid-run injection or
measured fault detection driving the colleagues' controller yet.

## PSCAD Workspace And Cases

Workspace:

```text
research_power_plane/pscad_workspace/SEIAN_PSCAD_Workspace.pswx
```

It intentionally contains two SEIAN cases:

| Case | Purpose | Status |
|---|---|---|
| `SEIAN_LV_Switching` | Earlier final-state/static validation | Preserved unchanged |
| `SEIAN_LV_Timed_Switching` | Timed switching and physical-fault EMT runs | Current default |

`scripts/build_lv_feeder.py` clears and regenerates only the timed case. It
does not touch the colleagues' root code or the preserved static case.

### Timed Case Contents

- `master:source3` Thevenin source at G01: 0.4 kV line-line, 50 Hz.
- Six buses: G01 and N02 through N06.
- Seven switchable R/L branches matching the topology JSON.
- One `master:breaker3` and `master:tbreakn` controller per line.
- One `master:tpflt` fault element at N03 driven by `master:tfaultn`.
- Y-connected loads at N02 through N06.
- Six bus RMS voltage meters and seven line current/power meters.
- 31 `datalabel -> pgb` full-rate recorders.

The schematic uses bounded positive coordinates. PSCAD 5.0.1 clamps negative
or oversized positions when a new case reopens; earlier coordinates caused
unrelated components to overlap.

## Physical Switching Contract

`breaker3.NAME` is a control-signal reference, not a display label:

```text
0 = breaker closed
1 = breaker open
```

Each line uses:

```text
tbreakn(INIT, NUMS, TO1, TO2)
  -> datalabel(Name=<line_id>)
  -> breaker3(NAME=<line_id>)
```

The manifest writes all seven controllers before one continuous run. `INIT`
sets initial state; `NUMS`, `TO1`, and `TO2` encode up to two transitions.
Lines with no event receive a transition after the run window. The project
duration is the latest controller/fault event plus its observation window.

Do not repeat these dead ends:

- `breaker3.BOpen1/BOpen2/BOpen3` are GUI animation values, not controls.
- `Sequencer_Breaker.OpenClos` does not switch without trigger logic.
- A final `const.Value` snapshot cannot represent an in-run event.

## Physical Fault Contract

`physical_faults` is optional in the same JSON object as `commands`. Scenario
06 uses:

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

Supported types include phase-to-ground, phase-to-phase, and three-phase
variants. The generated map binds `FAULT_N03` to both native components. The
adapter writes `tfaultn.TF/DF` plus `tpflt.RON/A/B/C/G`.

Fault contract guards:

- Physical faults require transient mode.
- Fault IDs must have a PSCAD binding.
- The requested node must match the bus where the element is wired.
- Start, duration, and resistance must be finite and physically valid.
- The run duration must cover fault clearance and the observation window.
- Fault logic is explicitly disabled after the run window in no-fault cases.
- Steady-state manifests reset PSCAD duration to 1 second, preventing a long
  previous run from reaching an idle fault timer.

## Recorded Channels

```text
6 x Vrms_<node>             kV
7 x Irms_<line_id>          kA
7 x P_<line_id>             MW
7 x State_<line_id>         0 closed, 1 open
3 x Ifault[A-C]_FAULT_N03   kA instantaneous phase current
1 x FaultState_FAULT_N03    0 clear, 1 active
```

Total: **31 full-rate channels**. At `sample_step=50 us`, an `N` second run
contains `20,000*N + 1` samples per channel.

PowerMCP 0.3.0 rejects channel reads larger than 30 on this installation. The
current client uses MCP only to list channel metadata and `mhi.psout` to read
the selected traces locally. Each summary uses all samples; previews use at
most 500 evenly spaced points including first/last. Do not estimate precise
event times or transient peaks from downsampled preview curves. The raw PSOUT
and the matrix runner's full-rate event analysis are the appropriate sources.

`pgb.UseSignalName=0` is intentional. Otherwise PSCAD can rename a requested
state output to its incoming signal. Keep channel names synchronized across:

- `scripts/build_lv_feeder.py`
- `pscad_mcp_client.RECORDED_CHANNEL_PREFIXES`
- `psout_channels.CHANNEL_GROUPS`
- `tests/test_psout_channels.py`

## Verified PSCAD Results

Main artifact:

```text
research_power_plane/pscad_workspace/transient_scenario_results.json
```

| Scenario | Events | Duration / samples | Measured physical result |
|---|---:|---:|---|
| 01 baseline | 0 | 1 s / 20,001 | All buses energized; tie currents 0 A |
| 02 isolation | 3 switches at 5 s | 6 s / 120,001 | N03-N06 remain de-energized |
| 03 restoration | 3 at 5 s, 2 at 6 s | 7 s / 140,001 | N04-N06 restored after about 0.998 s |
| 04 loop rejection | 0 | 6 s / 120,001 | Unsafe closure rejected; baseline remains |
| 05 degraded control | 3 at 5 s, 2 at 45 s | 46 s / 920,001 | N04-N06 outage about 39.998 s |
| 06 physical fault | fault 4.8-5.2 s; switches 5/6 s | 7 s / 140,001 | 1.55 kA fault; N04-N06 restored |

Scenario 03 and 06 final values agree: N04 380.5 V, N05 387.4 V, and
N06 383.4 V. The N02-N05 and N04-N06 ties carry 32.54 A and 13.45 A.

Scenario 06 evidence:

- `FaultState_FAULT_N03` changes 0 -> 1 at 4.8 s and 1 -> 0 at 5.2 s.
- Fault current peaks are 1.552, 1.554, and 1.552 kA on phases A, B, C.
- N03-N06 voltages collapse after fault inception.
- At 5.0 s, all three N03 incident breaker states change 0 -> 1.
- At 6.0 s, both tie breaker states change 1 -> 0.
- N04-N06 stay below 0.2 kV for about 1.195 s, then recover.
- Scenarios 01-05 have no applied fault. Finite off-state resistance leaves
  roughly 1.3 mA leakage; earlier rounded summaries displayed 0.000 kA.

Every matrix row has 31 channels, zero build errors, and zero warnings.

## PowerMCP Integration

Installed package: `powermcp 0.3.0`, with PSCAD 5.0.1 automation and
`mhi.psout` available.

Validated Python environment on this PC: Python 3.13.7, `mhi.pscad 2.9.7`,
`mhi.psout 1.3.0`, `mcp 2.1.1`, `streamlit 1.63.0`, and
`playwright 1.62.0`. These are observed versions, not a complete dependency
lock. Re-run unit and browser integration checks after dependency upgrades.

The stock PowerMCP `run_project` calls nonblocking `Project.start()` without
focusing this case. On this machine it can acknowledge the request while
leaving an old `.psout`. The project-local wrapper:

```text
seian_power_pipeline/pscad_mcp_server.py
```

wraps connection ownership and replaces the run tool with `project.focus()`
plus blocking `project.run()`. The localhost HTTP service on 8765 persists
between dashboard/CLI actions. Site-packages remains unchanged. The client removes
`NoDefaultCurrentDirectoryInExePath` from its child environment and patches
generated run batches when necessary.

The overwrite prompt shown by the user is raised during build. The client
removes only the current generated `<case>.gf*/<case>.psout` BEFORE build;
other cases and named archives are preserved. Every successful run must
produce a fresh output fingerprint. Archive the raw file with another name
before the next run when full-rate reproducibility is needed.

`pscad_run_lock.py` excludes concurrent dashboard/CLI parameter writes. MCP
tool errors are propagated rather than counted as successful writes. Missing
channels and stale results fail execution; CLI failures return nonzero.

`pscad_gui.py` locates the editor by PID/title and restores minimized windows.
The tiny rectangle at (-32000,-32000) is a minimized editor, not proof of a
destroyed GUI. Never kill PSCAD automatically to recover that state. The
service log is `%TEMP%\seian-pscad-mcp-8765.log`.

Live dashboard-path artifact:

```text
research_power_plane/pscad_workspace/dashboard_physical_fault_validation.json
```

It records: connected=true, 9 applied parameter writes, one fresh `.psout`,
146 raw traces, exactly 31 selected traces, 140,001 samples, and zero errors.

## Tests

```text
py -3.13 -m pytest tests research_power_plane\tests -q -p no:cacheprovider
114 passed in 8.99s
```

Coverage includes command parsing/order, topology safety, radiality rejection,
controller adaptation, timed manifests, physical-fault validation/mapping,
fault reset behavior, event limits, transient/outage analysis, MCP response
compatibility, fresh-result guards, scoped output cleanup, overlapping-run
exclusion, minimized editor detection, full-rate peak summaries, and automatic
Streamlit replay/error recovery and editing after upload. Sandbox runs on this PC may deny pytest's
temporary directories; run normally outside that sandbox when this occurs.

## Remaining Research Work

These are next-stage items, not blockers for the demonstrated pipeline:

1. Replace illustrative R/L/load values with measured cable, transformer,
   grounding, demand, DER, and protection data.
2. Connect the colleagues' persistent controller transport when its final
   output API is available. Today the dashboard consumes a JSON batch.
3. Extend `_FIELD_ALIASES` and `commands_from_fault_events` when their schema
   changes; keep the power-plane core stable.
4. Add calibrated relay/protection detection if PSCAD should originate the
   fault report. Scenario 06 currently supplies fault and controller times in
   one deterministic experiment file.
5. Replace `tbreakn` with a custom schedule component if one breaker needs
   more than two transitions in one run.
6. Freeze calibrated parameter sets and scenario seeds before submission,
   then generate publication figures/tables from saved artifacts.

## Key Files

```text
research_power_plane/dashboard.py
research_power_plane/cli.py
research_power_plane/seian_power_pipeline/control_plane.py
research_power_plane/seian_power_pipeline/controller_adapter.py
research_power_plane/seian_power_pipeline/faults.py
research_power_plane/seian_power_pipeline/power_plane.py
research_power_plane/seian_power_pipeline/timeline.py
research_power_plane/seian_power_pipeline/pscad_adapter.py
research_power_plane/seian_power_pipeline/pscad_mcp_client.py
research_power_plane/seian_power_pipeline/pscad_mcp_server.py
research_power_plane/seian_power_pipeline/pscad_gui.py
research_power_plane/seian_power_pipeline/pscad_run_lock.py
research_power_plane/seian_power_pipeline/psout_reader.py
research_power_plane/seian_power_pipeline/psout_channels.py
research_power_plane/seian_power_pipeline/transient_analysis.py
research_power_plane/seian_power_pipeline/pipeline.py
research_power_plane/scripts/build_lv_feeder.py
research_power_plane/scripts/run_scenarios.py
research_power_plane/scripts/validate_dashboard.py
research_power_plane/examples/scenarios/01..06_*.json
research_power_plane/pscad_workspace/SEIAN_LV_Timed_Switching.pscx
research_power_plane/pscad_workspace/seian_pscad_timed_component_map.generated.json
research_power_plane/pscad_workspace/transient_scenario_results.json
research_power_plane/pscad_workspace/dashboard_physical_fault_validation.json
research_power_plane/pscad_workspace/validation/dashboard_gui_validation.json
```
