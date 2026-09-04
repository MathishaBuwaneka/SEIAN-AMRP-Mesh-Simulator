# SEIAN Power Plane PSCAD Pipeline

This folder is the research layer for Oshadha's PSCAD co-simulation work.
The original AMRP simulator remains at the repository root and is imported as
the network/control-plane model.

## Folder Layout

```text
research_power_plane/
  dashboard.py                         Streamlit co-simulation dashboard
  run_dashboard.py                     Dashboard launcher
  cli.py                               Batch replay and PSCAD execution CLI
  examples/
    lv_power_plane_microgrid.json      Electrical topology and switch state
    network_control_commands.json      Example SDN/AMRP command batch
    pscad_component_map.example.json   Logical switch to PSCAD component IDs
    scenarios/                         Five paper-ready experiment command sets
  pscad_workspace/
    SEIAN_PSCAD_Workspace.pswx         Project-specific PSCAD workspace
    SEIAN_LV_Switching.pscx            Generated PSCAD LV feeder (source, buses,
                                        breakers, R/L lines, loads, meters)
    seian_pscad_component_map.generated.json
                                        Real generated PSCAD component map
    feeder_build_report.json           Component IDs from the last feeder build
    scenario_results.json              Measured PSCAD results for all 5 scenarios
  scripts/
    build_lv_feeder.py                 Build the real LV feeder onto the case
                                        (run this against a running PSCAD
                                        instance whenever the case needs
                                        regenerating from scratch)
    run_scenarios.py                   Run all 5 scenarios through PSCAD and
                                        record measured results
    diagnose_feeder.py                 Dump component/wire geometry for debugging
    bootstrap_pscad_workspace.py       Create/open the SEIAN PSCAD workspace
    check_pscad_mcp.py                 Verify the MCP server handshake
  seian_power_pipeline/
    control_plane.py                   Stable JSON command contract
    controller_adapter.py              AMRP controller output -> command JSON
    power_plane.py                     LV switch-state and energization model
    pscad_adapter.py                   PSCAD MCP manifest builder
    pscad_mcp_client.py                Live PowerMCP PSCAD execution client
    psout_channels.py                  .psout channels -> plottable series
    pipeline.py                        End-to-end orchestration
  tests/
    test_power_plane_pipeline.py       Power-plane / pipeline tests
    test_controller_adapter.py         Controller adapter + PSCAD binding tests
    test_psout_channels.py             Output-channel parsing tests
    test_dashboard_render.py           Streamlit render smoke tests
```

## Pipeline

```text
AMRP/SDN controller command
        |
        v
NetworkControlCommand JSON
        |
        v
PowerPlaneState safety/reachability replay
        |
        v
PSCAD MCP manifest
        |
        v
PowerMCP PSCAD server
        |
        v
PSCAD parameter update + project run + output collection
```

## Dashboard

```powershell
py research_power_plane\run_dashboard.py
```

The dashboard starts with the example topology, example SDN/AMRP commands, and
the generated PSCAD map when it exists. Use `Open SEIAN PSCAD Workspace` if
PSCAD opens an old unrelated workspace. With the generated map present,
`Auto-run PSCAD after replay` defaults on, so pressing `Replay and Simulate`
updates PSCAD switch parameters and starts the PSCAD case.

The PSCAD case is a real LV EMT feeder (source, buses, breaker+R/L lines,
loads, per-bus voltage meters, per-line power/current meters) matching the
topology in `examples/lv_power_plane_microgrid.json`. It builds and runs with
zero errors/warnings and records 20,001-sample `.psout` traces for bus RMS
voltage (`Vrms_<node>`), line RMS current (`Irms_<line_id>`) and line power
(`P_`/`Q_<line_id>`). With `List output channels after run` on, the dashboard
plots them under "PSCAD Output Channels (.psout)".

## Experiments

Run all five scenarios through PSCAD and record measured results:

```powershell
py research_power_plane\scripts\run_scenarios.py
```

This writes `pscad_workspace/scenario_results.json` and prints a steady-state
summary. It deliberately does everything in a single PSCAD session rather than
going through `cli.py --execute-pscad`, because two PSCAD processes writing the
same `.pscx` duplicate the canvas (see `AI_CONTEXT.md`, Known Limitations).

## CLI

Generate a research artifact without executing PSCAD:

```powershell
py research_power_plane\cli.py research_power_plane\examples\lv_power_plane_microgrid.json research_power_plane\examples\network_control_commands.json --component-map research_power_plane\examples\pscad_component_map.example.json --output results\pipeline_manifest.json
```

Apply switch parameters and run PSCAD:

```powershell
py research_power_plane\cli.py research_power_plane\examples\lv_power_plane_microgrid.json research_power_plane\examples\network_control_commands.json --component-map research_power_plane\pscad_workspace\seian_pscad_component_map.generated.json --workspace-file research_power_plane\pscad_workspace\SEIAN_PSCAD_Workspace.pswx --project-name SEIAN_LV_Switching --execute-pscad --output results\live_pscad_run.json
```

Rebuild the PSCAD feeder from scratch (clears and regenerates the whole `Main`
canvas, and rewrites the component map):

```powershell
py research_power_plane\scripts\build_lv_feeder.py
```

`scripts\bootstrap_pscad_workspace.py` is the older workspace/scaffold
creator; it is only needed to create the `.pswx`/`.pscx` pair from nothing.

## PSCAD Mapping

The mapping file connects a logical line ID to a PSCAD component and parameter.

In PSCAD a `breaker3`'s `NAME` parameter is a *control signal reference*: the
breaker reads a real signal of that name each timestep, where **0 = closed and
1 = open**. The generated feeder therefore gives every line a `const` feeding a
`datalabel` named after the line, and the map binds the line to that `const`'s
`Value`:

```json
{
  "line_id": "SW_N04_N06_TIE",
  "component_id": 1075164593,
  "closed_parameter": "Value",
  "closed_value": 0,
  "open_value": 1
}
```

(`breaker3`'s own `BOpen1/2/3` parameters are GUI animation state only and do
**not** switch anything -- see `AI_CONTEXT.md`. `PscadLineBinding` also
supports a multi-parameter `closed_parameters`/`open_parameters` form for
components that need several parameters written together.)

The live PSCAD manifest is snapshot-based: every dashboard replay writes all
mapped final switch states into PSCAD, while the research artifact still records
how many switch changes came directly from controller commands.

`component_id` changes every time `scripts/build_lv_feeder.py` regenerates the
case (it deletes and rebuilds the whole canvas), so the map file is
regenerated alongside it -- don't hand-edit component IDs into a stale map.

## AI Context

`AI_CONTEXT.md` is the handoff file for future AI/dev sessions. Keep it updated
when PSCAD model structure, dashboard workflow, or controller command contracts
change.

## Tests

```powershell
py -m pytest tests research_power_plane\tests -q -p no:cacheprovider
```

The root `tests/` directory belongs to the cloned AMRP simulator. The
`research_power_plane/tests/` directory belongs to the PSCAD pipeline.
