"""Smoke tests that the Streamlit dashboard actually renders.

These run the real ``dashboard.py`` through Streamlit's AppTest harness (no
browser, no PSCAD) so a syntax/layout/plotting regression is caught here
rather than only when someone opens the page.
"""

from __future__ import annotations

import pandas as pd
import json
from io import BytesIO

import pytest

from seian_power_pipeline.psout_channels import extract_channel_series, group_channels

from test_psout_channels import LIVE_REPLY

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

DASHBOARD = "../dashboard.py"


def _run_dashboard():
    app = AppTest.from_file(DASHBOARD, default_timeout=60)
    app.run()
    return app


class TestDashboardRenders:
    def test_dashboard_loads_without_exception(self):
        app = _run_dashboard()
        assert not app.exception, [str(e) for e in app.exception]

    def test_expected_controls_are_present(self):
        app = _run_dashboard()
        assert any("SEIAN AMRP to PSCAD" in t.value for t in app.title)
        button_labels = {b.label for b in app.button}
        assert "Replay and Simulate" in button_labels
        assert "Open SEIAN PSCAD Workspace" in button_labels

    def test_replaying_a_scenario_renders_results_without_pscad(self):
        app = _run_dashboard()
        # Auto-run PSCAD off so this stays a pure control/power-plane replay.
        for toggle in app.toggle:
            if toggle.label == "Auto-run PSCAD after replay":
                toggle.set_value(False)
        for button in app.button:
            if button.label == "Replay and Simulate":
                button.click()
        app.run()
        assert not app.exception, [str(e) for e in app.exception]
        # The pipeline result panel should now exist.
        assert any("Pipeline Result" in s.value for s in app.subheader)

    def test_committed_edit_replays_once_and_bad_json_clears_old_result(self):
        app = _run_dashboard()
        for toggle in app.toggle:
            if toggle.label == "Auto-run PSCAD after replay":
                toggle.set_value(False)
        app.run()
        assert app.session_state.pipeline_result is None
        commands = next(area for area in app.text_area if area.label == "Command JSON")
        payload = json.loads(commands.value)
        payload["commands"][1]["timestamp"] = 6.5
        commands.set_value(json.dumps(payload))
        app.run()
        assert not app.exception
        result = app.session_state.pipeline_result
        assert result["switching_timeline"]["duration_s"] == 7.5
        assert result["pscad_execution"] is None
        app.run()
        assert app.session_state.pipeline_result == result
        next(area for area in app.text_area if area.label == "Command JSON").set_value("{")
        app.run()
        assert not app.exception
        assert app.session_state.pipeline_result is None
        assert app.error

    def test_uploaded_commands_do_not_overwrite_later_editor_changes(self, monkeypatch):
        import streamlit

        uploaded = BytesIO(b'{"commands": []}')
        monkeypatch.setattr(
            streamlit, "file_uploader",
            lambda label, **kwargs: uploaded if label == "Control commands JSON" else None,
        )
        app = _run_dashboard()
        for toggle in app.toggle:
            if toggle.label == "Auto-run PSCAD after replay":
                toggle.set_value(False)
        app.run()
        updated = '{"commands": [], "experiment": "edited after upload"}'
        next(area for area in app.text_area if area.label == "Command JSON").set_value(updated)
        app.run()
        assert not app.exception
        assert app.session_state.command_text == updated
        app.run()
        assert app.session_state.command_text == updated

    def test_graphical_command_apply_updates_json_and_replays(self):
        app = _run_dashboard()
        next(toggle for toggle in app.toggle if toggle.label == "Auto-run PSCAD after replay").set_value(False)
        app.run()
        original = json.loads(app.session_state.command_text)
        next(number for number in app.number_input if number.label == "At time (s)").set_value(5.1)
        next(button for button in app.button if button.label == "Apply command").click()
        app.run()
        assert not app.exception, [str(error) for error in app.exception]
        changed = json.loads(app.session_state.command_text)
        assert changed["commands"][0]["timestamp"] == 5.1
        assert changed["commands"][1] == original["commands"][1]
        assert app.session_state.pipeline_result["plans"][0]["command"]["timestamp"] == 5.1

    def test_scenario_presets_and_preview_do_not_require_json_editing(self):
        app = _run_dashboard()
        next(toggle for toggle in app.toggle if toggle.label == "Auto-run PSCAD after replay").set_value(False)
        app.run()
        for preset in ["Baseline", "Fault isolation", "Tie restoration", "Loop rejection", "Degraded control", "Physical fault and restoration"]:
            next(select for select in app.selectbox if select.label == "Scenario preset").set_value(preset)
            app.run()
            assert not app.exception, [str(error) for error in app.exception]
            assert app.session_state.pipeline_result is not None
        before = app.session_state.command_text
        next(select for select in app.segmented_control if select.label == "Switch-state preview").set_value("Scheduled state")
        app.run()
        next(slider for slider in app.slider if slider.label == "Preview time (s)").set_value(5.1)
        app.run()
        assert not app.exception
        assert app.session_state.command_text == before


class TestChartAssembly:
    """The dashboard turns parsed channels into one DataFrame per group."""

    def test_channel_groups_concat_into_a_chartable_frame(self):
        series = extract_channel_series(LIVE_REPLY)
        groups = group_channels(series)
        assert groups

        for _title, group in groups:
            combined = pd.concat(
                {
                    name: pd.Series(data["values"], index=data["time"], name=name)
                    for name, data in sorted(group.items())
                },
                axis=1,
            )
            combined.index.name = "time (s)"
            assert list(combined.columns) == sorted(group)
            assert len(combined) == 3
            assert combined.notna().all().all()
