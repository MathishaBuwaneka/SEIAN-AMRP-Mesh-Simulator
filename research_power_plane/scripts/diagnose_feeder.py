"""Dump component/wire geometry from the live SEIAN_LV_Switching case for debugging."""

from __future__ import annotations

import json
from pathlib import Path

import mhi.pscad

CASE_NAME = "SEIAN_LV_Switching"
OUT_FILE = Path(__file__).resolve().parent.parent / "pscad_workspace" / "feeder_diagnostic.json"


def main() -> int:
    pscad = mhi.pscad.application()
    project = pscad.project(CASE_NAME)
    main_canvas = project.canvas("Main")

    components = []
    for c in main_canvas.components():
        row = {
            "iid": int(getattr(c, "iid", -1)),
            "classid": getattr(c, "classid", None),
            "defn": _defn(c),
            "x": getattr(c, "x", None),
            "y": getattr(c, "y", None),
        }
        try:
            row["ports"] = {name: (p.x, p.y) for name, p in c.ports().items()}
        except Exception as exc:
            row["ports_error"] = str(exc)
        if "wire" in row["defn"].lower():
            try:
                row["vertices"] = [(v.x, v.y) for v in c.vertices()]
            except Exception as exc:
                row["vertices_error"] = str(exc)
        components.append(row)

    OUT_FILE.write_text(json.dumps(components, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"component_count": len(components), "out_file": str(OUT_FILE)}, indent=2))
    return 0


def _defn(c) -> str:
    value = getattr(c, "defn_name", getattr(c, "classid", ""))
    if isinstance(value, tuple):
        return ":".join(str(part) for part in value)
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
