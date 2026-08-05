# SEIAN Adaptive LoRa Mesh Topology Simulator

A local Streamlit application for designing and checking SEIAN smart-inverter LoRa mesh topologies using the proposed SEIAN Adaptive Mesh Routing Protocol (SEIAN-AMRP).

The simulator is intended for topology design, protocol research, demonstrations, and controlled experiments. It does **not** control real inverters or replace electrical protection studies.

## Main topology checks

The **Topology Check** dashboard identifies:

- Whether the active mesh is connected.
- Disconnected components and isolated nodes.
- Nodes that cannot reach an online gateway.
- Critical relay nodes whose failure can split the mesh.
- Bridge links that have no alternate physical path.
- The current route between any source and destination.
- Invalid or stale routing-table paths.
- Asymmetric neighbor relationships.
- The number of nodes affected by each possible single-node failure.
- Mesh density, average degree, and topology diameter.

## Existing protocol simulation

The project also models:

- HELLO-style discovery and neighbor tables.
- Grid-aware route selection and backup next hops.
- Approximate LoRa RSSI, SNR, range, loss, collision, and channel-busy behaviour.
- Grid-state telemetry and gateway forwarding.
- Gateway outage and cached telemetry.
- Fault-alert flooding, severity-based TTL, duplicate suppression, and fault ACKs.
- Priority queues for telemetry, control, fault, and emergency packets.
- Fault-boundary classification.
- Packet, route, fault, grid, and event metrics.

See [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) for a precise list of what was already present, what was updated, and what still needs to be implemented.

## Project structure

```text
app.py                         Streamlit dashboard
seian_sim/config.py            User-configurable constants
seian_sim/enums.py             Protocol and grid enums
seian_sim/models.py            Neighbor, route, event, and fault records
seian_sim/node.py              Node state and priority queue
seian_sim/packets.py           Packet model and duplicate cache
seian_sim/lora_channel.py      Approximate LoRa channel
seian_sim/routing.py           Grid-aware topology routing
seian_sim/topology.py          Connectivity and resilience analysis
seian_sim/grid_model.py        Simplified grid measurements
seian_sim/fault_model.py       Fault injection and boundary classification
seian_sim/simulator.py         Deterministic simulation engine
seian_sim/scenarios.py         Built-in, random, import, and export scenarios
seian_sim/visualization.py     Plotly figures
tests/                         Automated tests
examples/                      Example topology JSON files
docs/                          Implementation and alignment notes
```

## Run on Windows PowerShell

From the extracted project folder:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\run_windows.ps1
```

Manual commands:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Run on Linux or WSL

```bash
chmod +x run_linux.sh
./run_linux.sh
```

Manual commands:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The terminal will display a local URL, normally `http://localhost:8501`.

## Basic workflow

1. Select a built-in scenario or **Random topology**.
2. Set the LoRa range, area size, packet-loss probability, and node count.
3. Click **Create / Reset Network**.
4. Open **Topology Check**.
5. Inspect disconnected components, isolated nodes, critical relays, bridge links, and gateway reachability.
6. Select a route source and destination to highlight the routing path.
7. Fail a relay or gateway and inspect the recalculated topology.
8. Export the topology and analysis results.

## Load a custom topology

Use the **Load topology JSON** control. A reloadable file has this format:

```json
{
  "network_id": "SEIAN-LAB",
  "area_width_m": 600,
  "area_height_m": 360,
  "lora_range_m": 175,
  "nodes": [
    {
      "node_id": "N01",
      "x": 50,
      "y": 180,
      "gateway_capable": true,
      "gateway_online": true,
      "active": true
    }
  ]
}
```

A complete example is available at `examples/topology_checker_demo.json`.

## Command-line topology check

A topology can also be checked without opening the dashboard:

```bash
python check_topology.py examples/topology_checker_demo.json --output topology_report.json
```

The command prints the connectivity summary and writes the complete link and single-node-failure analysis to the selected output file.

## Automated tests

```bash
python -m pytest -q -p no:cacheprovider
```

Current result for this version:

```text
19 passed
```

## Important modelling limitation

The current routing engine uses a complete NetworkX graph to calculate routes. This makes it effective for **topology feasibility and resilience checking**, but it is not yet a fully decentralized packet-level implementation of ROUTE_ADVERTISEMENT learning. That is the next major protocol update.
