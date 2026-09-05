"""Validate graphical editing in Edge against the live PSCAD pipeline."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8502")
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "pscad_workspace/validation"
    output.mkdir(exist_ok=True)
    evidence = {"validated_at_utc": datetime.now(timezone.utc).isoformat(), "url": args.url, "runs": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1528, "height": 1100}, accept_downloads=True)
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(args.url)
        apply_command = page.get_by_role("button", name=re.compile(r"Apply command$"))
        expect(apply_command).to_be_visible(timeout=30000)
        chart = page.locator("[data-testid=stPlotlyChart]").first
        expect(chart.locator(".scatterlayer .point").first).to_be_visible(timeout=30000)
        expect(page.get_by_role("textbox", name="Command JSON", exact=True)).not_to_be_visible()
        page.screenshot(path=str(output / "graphical_desktop.png"))

        # Select a real node marker, rather than only exercising its dropdown.
        node = chart.locator(".scatterlayer .trace").filter(has=page.get_by_text("N03", exact=True))
        chart.scroll_into_view_if_needed()
        bounds = node.locator(".point").bounding_box()
        assert bounds
        page.mouse.click(bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2)
        expect(page.get_by_role("combobox", name="Bus", exact=True)).to_have_value("N03")

        def collect(name: str) -> dict:
            spinner = page.get_by_text("Running PSCAD simulation...", exact=True)
            expect(spinner).to_be_visible(timeout=30000)
            expect(spinner).not_to_be_visible(timeout=240000)
            expect(page.get_by_text("PSCAD completed the run and produced fresh output data.", exact=True)).to_be_visible(timeout=30000)
            with page.expect_download() as download:
                page.get_by_role("button", name="Download Full Research Artifact", exact=True).click()
            artifact = output / f"graphical_{name}.json"
            download.value.save_as(artifact)
            result = json.loads(artifact.read_text(encoding="utf-8"))
            run = result["pscad_execution"]
            assert not run["errors"], run["errors"]
            assert run["fresh_output_files"] and run["pscad_gui_visible"]
            assert run["channel_data"]["channel_count"] == 31
            summaries = {row["name"]: row["summary"] for row in run["channel_data"]["channels"].values()}
            peak = max(abs(summaries["IfaultA_FAULT_N03"][key]) for key in ("min", "max"))
            evidence["runs"].append({"action": name, "pscad_pid": run["pscad_gui_pid"], "samples": run["channel_data"]["sample_count"], "channels": 31, "fault_peak_ka": peak, "errors": []})
            print(json.dumps(evidence["runs"][-1]), flush=True)
            return result

        for name, preset in [("baseline", "Baseline"), ("physical_fault", "Physical fault and restoration")]:
            print(f"Selecting graphical preset: {preset}", flush=True)
            page.get_by_role("combobox", name="Scenario preset", exact=True).click()
            page.get_by_role("option", name=preset, exact=True).click()
            result = collect(name)
            peak = evidence["runs"][-1]["fault_peak_ka"]
            assert peak < 1e-5 if name == "baseline" else peak > 1

        # A draft field change must not run PSCAD until the form is applied.
        print("Applying graphical command time: 5.1 s", flush=True)
        time_input = page.get_by_role("spinbutton", name="At time (s)", exact=True)
        time_input.fill("5.1")
        time_input.press("Tab")
        expect(page.get_by_text("Running PSCAD simulation...", exact=True)).not_to_be_visible()
        apply_command.click()
        result = collect("command_edit")
        assert result["plans"][0]["command"]["timestamp"] == 5.1
        assert result["plans"][1]["command"]["metadata"]["paper_case"]
        page.get_by_text("Advanced JSON", exact=True).click()
        raw = page.get_by_role("textbox", name="Command JSON", exact=True)
        payload = json.loads(raw.input_value())
        assert payload["commands"][0]["timestamp"] == 5.1
        assert payload["physical_faults"][0]["start_s"] == 4.8
        page.get_by_text("Advanced JSON", exact=True).click()

        for name in ["Faults", "Breakers", "Bindings", "Commands"]:
            page.get_by_role("tab", name=name, exact=True).click()
            expect(page.locator("[data-testid=stException]")).to_have_count(0)
        page.get_by_role("radio", name="Scheduled state", exact=True).click()
        expect(page.get_by_text("Preview time (s)", exact=True)).to_be_visible()
        expect(page.get_by_text("Running PSCAD simulation...", exact=True)).not_to_be_visible()
        page.get_by_role("heading", name="Power Topology", exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(output / "graphical_scheduled.png"))
        page.get_by_role("radio", name="Initial state", exact=True).click()

        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("heading", name="Power Topology", exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(output / "graphical_mobile.png"))
        page.get_by_role("heading", name="Experiment Controls", exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(output / "graphical_mobile_controls.png"))
        evidence["mobile_horizontal_overflow_px"] = page.evaluate("Math.max(0, document.documentElement.scrollWidth - innerWidth)")
        assert evidence["mobile_horizontal_overflow_px"] == 0
        assert len({run["pscad_pid"] for run in evidence["runs"]}) == 1
        assert not page_errors, page_errors
        browser.close()

    (output / "graphical_gui_validation.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print("Graphical dashboard -> JSON -> PSCAD validation passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
