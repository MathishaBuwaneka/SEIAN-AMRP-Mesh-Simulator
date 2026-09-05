"""Exercise committed dashboard edits against real PSCAD using Playwright.

Requires the research dashboard already running and ``pip install playwright``.
Uses the installed Edge browser; it does not download a browser runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))


def main() -> int:
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8502")
    args = parser.parse_args()
    output = HERE / "pscad_workspace" / "validation"
    output.mkdir(exist_ok=True)
    scenarios = [
        ("baseline", {"commands": []}),
        ("physical_fault", json.loads((HERE / "examples/scenarios/06_physical_fault_restoration.json").read_text())),
    ]
    evidence = {"validated_at_utc": datetime.now(timezone.utc).isoformat(), "url": args.url, "runs": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.goto(args.url)
        editor = page.get_by_role("textbox", name="Command JSON", exact=True)
        expect(editor).to_be_visible(timeout=30000)
        for name, payload in scenarios:
            print(f"Committing {name} dashboard edit", flush=True)
            editor.fill(json.dumps(payload, indent=2))
            editor.press("Tab")
            spinner = page.get_by_text("Running PSCAD simulation...", exact=True)
            expect(spinner).to_be_visible(timeout=30000)
            expect(spinner).not_to_be_visible(timeout=240000)
            expect(page.get_by_text("PSCAD completed the run and produced fresh output data.", exact=True)).to_be_visible(timeout=30000)
            with page.expect_download() as downloaded:
                page.get_by_role("button", name="Download Full Research Artifact", exact=True).click()
            artifact = output / f"dashboard_{name}.json"
            downloaded.value.save_as(artifact)
            result = json.loads(artifact.read_text(encoding="utf-8"))
            execution = result["pscad_execution"]
            assert execution["errors"] == [], execution["errors"]
            assert execution["channel_data"]["channel_count"] == 31
            assert execution["fresh_output_files"]
            assert execution["pscad_gui_visible"]
            data = {row["name"]: row for row in execution["channel_data"]["channels"].values()}
            peaks = {
                signal: max(abs(row["summary"]["min"]), abs(row["summary"]["max"]))
                for signal, row in data.items() if signal.startswith("Ifault")
            }
            assert len(peaks) == 3
            if name == "baseline":
                # The finite off-state resistance leaves about 1.3 mA leakage.
                assert all(peak < 1e-5 for peak in peaks.values()), peaks
                assert data["FaultState_FAULT_N03"]["summary"]["max"] == 0
                assert data["State_SW_N02_N05_TIE"]["summary"]["final"] == 1
            else:
                assert all(peak > 1 for peak in peaks.values()), peaks
                assert data["FaultState_FAULT_N03"]["summary"]["max"] == 1
                assert data["State_SW_N02_N05_TIE"]["summary"]["final"] == 0
                assert data["Vrms_N03"]["summary"]["final"] < 0.01
                assert all(data[f"Vrms_{node}"]["summary"]["final"] > 0.35 for node in ("N04", "N05", "N06"))
            evidence["runs"].append({
                "scenario": name,
                "trigger": "command JSON edit committed by Tab; no Replay click",
                "pscad_pid": execution["pscad_gui_pid"],
                "fresh_outputs": execution["fresh_output_files"],
                "channels": execution["channel_data"]["channel_count"],
                "samples": execution["channel_data"]["sample_count"],
                "fault_peak_ka": peaks,
                "final_bus_kv": {signal: row["summary"]["final"] for signal, row in data.items() if signal.startswith("Vrms_")},
                "errors": execution["errors"],
            })
            print(json.dumps(evidence["runs"][-1]), flush=True)
            page.get_by_text("PSCAD Output Channels (.psout)", exact=True).scroll_into_view_if_needed()
            page.screenshot(path=str(output / f"dashboard_{name}.png"))

        assert len({run["pscad_pid"] for run in evidence["runs"]}) == 1, "PSCAD instance was unexpectedly replaced"
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_text("PSCAD Output Channels (.psout)", exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(output / "dashboard_mobile.png"))
        evidence["mobile_horizontal_overflow_px"] = page.evaluate("Math.max(0, document.documentElement.scrollWidth - innerWidth)")
        assert evidence["mobile_horizontal_overflow_px"] == 0
        browser.close()

    (output / "dashboard_gui_validation.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"Validated browser -> dashboard -> PSCAD -> waveforms: {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
