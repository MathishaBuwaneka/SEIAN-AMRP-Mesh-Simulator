"""Tests for parsing read_output_channels replies into plottable series."""

from __future__ import annotations

from seian_power_pipeline.psout_channels import extract_channel_series, group_channels

# Trimmed from a real read_output_channels reply for SEIAN_LV_Switching.
LIVE_REPLY = {
    "file": "SEIAN_LV_Switching.psout",
    "run_index": 0,
    "sample_count": 20001,
    "channels": {
        "Root/Main/Vrms_N02/0/1": {
            "path": "Root/Main/Vrms_N02/0/1",
            "name": "Vrms_N02",
            "unit": None,
            "preview": {"step": 10000, "time": [0, 0.5, 1], "values": [0, 0.3929, 0.39296]},
        },
        "Root/Main/Irms_SW_N02_N05_TIE/0/1": {
            "path": "Root/Main/Irms_SW_N02_N05_TIE/0/1",
            "name": "Irms_SW_N02_N05_TIE",
            "unit": None,
            "preview": {"step": 10000, "time": [0, 0.5, 1], "values": [0, 5.68e-09, 5.68e-09]},
        },
        "Root/Main/P_SW_G01_N02/0/1": {
            "path": "Root/Main/P_SW_G01_N02/0/1",
            "name": "P_SW_G01_N02",
            "unit": None,
            "preview": {"step": 10000, "time": [0, 0.5, 1], "values": [0, 0.0379, 0.03795]},
        },
    },
    "not_found": [],
}


class TestExtractChannelSeries:
    def test_parses_live_reply_shape(self):
        series = extract_channel_series(LIVE_REPLY)
        assert set(series) == {"Vrms_N02", "Irms_SW_N02_N05_TIE", "P_SW_G01_N02"}
        assert series["Vrms_N02"]["time"] == [0.0, 0.5, 1.0]
        assert series["Vrms_N02"]["values"][-1] == 0.39296

    def test_accepts_result_wrapper(self):
        assert extract_channel_series({"result": LIVE_REPLY}).keys() == extract_channel_series(LIVE_REPLY).keys()

    def test_falls_back_to_path_when_name_missing(self):
        reply = {
            "channels": {
                "Root/Main/Vrms_N04/0/1": {"preview": {"time": [0, 1], "values": [0, 0.38]}}
            }
        }
        assert list(extract_channel_series(reply)) == ["Vrms_N04"]

    def test_skips_channels_without_preview_data(self):
        reply = {
            "channels": {
                "Root/Main/Empty/0/1": {"name": "Empty", "preview": {"time": [], "values": []}},
                "Root/Main/NoPreview/0/1": {"name": "NoPreview"},
            }
        }
        assert extract_channel_series(reply) == {}

    def test_bad_shapes_return_empty_rather_than_raising(self):
        for payload in (None, "text", 42, {}, {"channels": []}, {"error": "no .psout"}):
            assert extract_channel_series(payload) == {}


class TestGroupChannels:
    def test_groups_by_measurement_prefix_in_display_order(self):
        grouped = group_channels(extract_channel_series(LIVE_REPLY))
        assert [title for title, _ in grouped] == [
            "Bus RMS Voltage (kV)",
            "Line RMS Current (kA)",
            "Line Active Power (MW)",
        ]
        assert list(grouped[0][1]) == ["Vrms_N02"]

    def test_unrecognized_channels_land_in_other(self):
        grouped = group_channels({"SomethingElse": {"time": [0], "values": [1.0]}})
        assert grouped == [("Other Channels", {"SomethingElse": {"time": [0], "values": [1.0]}})]

    def test_empty_input_produces_no_groups(self):
        assert group_channels({}) == []


class TestExtractChannelPaths:
    """The CLI/dashboard path selects which channels to actually read back.

    These names must stay in step with the signal names build_lv_feeder.py
    assigns -- a mismatch here silently yields "no channels" and empty charts.
    """

    def test_selects_recorder_channels_and_skips_animate_fields(self):
        from seian_power_pipeline.pscad_mcp_client import _extract_channel_paths

        reply = {
            "channels": [
                {"path": "Root/Main/Vrms_N02/0/1", "samples": 20001},
                {"path": "Root/Main/Irms_SW_G01_N02/0/1", "samples": 20001},
                {"path": "Root/Main/P_SW_G01_N02/0/1", "samples": 20001},
                {"path": "Root/Main/Q_SW_G01_N02/0/1", "samples": 20001},
                {"path": "Root/Main/State_SW_G01_N02/0/1", "samples": 20001},
                # animate="true" GUI fields -- not results, must be excluded
                {"path": "Root/Main/SW_G01_N02/0/BOpen1", "samples": 1},
                {"path": "Root/Main/PQ_SW_G01_N02/2/Pd", "samples": 3},
                # never recorded
                {"path": "Root/Main/Vrms_N03/2/Pd", "samples": 0},
            ]
        }
        assert _extract_channel_paths(reply) == [
            "Root/Main/Vrms_N02/0/1",
            "Root/Main/Irms_SW_G01_N02/0/1",
            "Root/Main/P_SW_G01_N02/0/1",
            "Root/Main/Q_SW_G01_N02/0/1",
            "Root/Main/State_SW_G01_N02/0/1",
        ]

    def test_drops_names_with_stray_non_printable_bytes(self):
        from seian_power_pipeline.pscad_mcp_client import _extract_channel_paths

        reply = {"channels": [{"path": "Root/Main/Vrms_N02/5/BOpen3\u0014\u0002T0", "samples": 1}]}
        assert _extract_channel_paths(reply) == []

    def test_request_is_capped(self):
        from seian_power_pipeline.pscad_mcp_client import (
            MAX_READ_CHANNELS,
            _extract_channel_paths,
        )

        reply = {
            "channels": [
                {"path": f"Root/Main/Vrms_N{i:03d}/0/1", "samples": 10}
                for i in range(MAX_READ_CHANNELS + 15)
            ]
        }
        assert len(_extract_channel_paths(reply)) == MAX_READ_CHANNELS

    def test_bad_shapes_return_empty(self):
        from seian_power_pipeline.pscad_mcp_client import _extract_channel_paths

        for payload in (None, {}, {"channels": {}}, {"error": "no .psout"}):
            assert _extract_channel_paths(payload) == []


class TestPscadRuntimeGuards:
    def test_extracts_distinct_errors_from_live_build_shapes(self):
        from seian_power_pipeline.pscad_mcp_client import _reported_errors

        assert _reported_errors(
            {"built": False, "errors": ["compile failed"]},
            {"result": {"errors": [{"text": "dimension mismatch"}, "compile failed"]}},
        ) == ["compile failed", "dimension mismatch"]

    def test_detects_new_or_changed_output_files(self):
        from seian_power_pipeline.pscad_mcp_client import _fresh_psout_files

        before = {"old.psout": (10, 100), "same.psout": (20, 200)}
        after = {
            "old.psout": (11, 100),
            "same.psout": (20, 200),
            "new.psout": (30, 300),
        }
        assert _fresh_psout_files(before, after) == ["new.psout", "old.psout"]

    def test_run_acknowledgement_uses_started_flag(self):
        from seian_power_pipeline.pscad_mcp_client import _run_started

        assert _run_started({"started": True})
        assert _run_started({"result": {"started": True}})
        assert not _run_started({"started": False, "note": "not started"})
