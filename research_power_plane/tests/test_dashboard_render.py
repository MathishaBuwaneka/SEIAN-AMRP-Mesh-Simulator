"""Smoke tests that the Streamlit dashboard actually renders.

These run the real ``dashboard.py`` through Streamlit's AppTest harness (no
browser, no PSCAD) so a syntax/layout/plotting regression is caught here
rather than only when someone opens the page.
"""

from __future__ import annotations

import pandas as pd
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
