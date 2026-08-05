"""Command-line topology checker for exported SEIAN topology JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from seian_sim.scenarios import build_from_topology
from seian_sim.topology import analyze_topology, link_table, node_failure_impact


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a SEIAN mesh topology JSON file.")
    parser.add_argument("topology", type=Path, help="Path to a topology JSON file")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for the complete JSON analysis report",
    )
    args = parser.parse_args()

    try:
        payload = json.loads(args.topology.read_text(encoding="utf-8"))
        simulator = build_from_topology(payload)
        report = {
            "topology": analyze_topology(simulator),
            "links": link_table(simulator),
            "single_node_failure_impact": node_failure_impact(simulator),
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    print(json.dumps(report["topology"], indent=2))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nComplete report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
