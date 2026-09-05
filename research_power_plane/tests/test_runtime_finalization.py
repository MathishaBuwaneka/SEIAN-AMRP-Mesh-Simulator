"""Regression coverage for failures observed during interactive PSCAD runs."""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from seian_power_pipeline.pscad_mcp_client import (
    PscadRuntimeConfig,
    _call,
    _remove_previous_psout,
)
from seian_power_pipeline.pscad_run_lock import exclusive_pscad_run


def test_cleanup_removes_only_this_cases_generated_output(tmp_path):
    folder = tmp_path / "case.gf46"
    folder.mkdir()
    output = folder / "case.psout"
    retained = folder / "archived_experiment.psout"
    output.write_bytes(b"old solver output")
    retained.write_bytes(b"research archive")
    other = tmp_path / "other.gf46"
    other.mkdir()
    (other / "other.psout").write_bytes(b"other case")
    config = PscadRuntimeConfig("case", workspace_files=[str(tmp_path / "project.pswx")])

    assert _remove_previous_psout(config) == [str(output)]
    assert not output.exists()
    assert retained.read_bytes() == b"research archive"
    assert (other / "other.psout").exists()


@pytest.mark.parametrize("name", ["../other", "case*", "C:\\case"])
def test_cleanup_rejects_path_or_glob_project_names(tmp_path, name):
    config = PscadRuntimeConfig(name, workspace_files=[str(tmp_path / "project.pswx")])
    with pytest.raises(ValueError, match="plain case name"):
        _remove_previous_psout(config)


@pytest.mark.parametrize("payload,is_error", [({"error": "write rejected"}, False), ("write rejected", True)])
def test_mcp_tool_errors_abort_instead_of_counting_a_write(payload, is_error):
    class Session:
        async def call_tool(self, *_args):
            return SimpleNamespace(
                isError=is_error,
                content=[SimpleNamespace(text=json.dumps(payload))],
            )

    with pytest.raises(RuntimeError, match="write rejected"):
        asyncio.run(_call(Session(), "set_component_parameters", {}))


def test_run_lock_rejects_overlap_and_releases_after_exception():
    endpoint = "http://127.0.0.1:63971/mcp"
    with pytest.raises(ValueError, match="release test"):
        with exclusive_pscad_run(endpoint):
            with pytest.raises(RuntimeError, match="in progress"):
                with exclusive_pscad_run("http://localhost:63971/mcp"):
                    pytest.fail("Overlapping operation was permitted")
            raise ValueError("release test")
    with exclusive_pscad_run(endpoint):
        pass


@pytest.mark.skipif(os.name != "nt", reason="Windows GUI API")
def test_minimized_pscad_editor_is_detected(monkeypatch):
    from seian_power_pipeline.pscad_gui import find_pscad_window

    def process_id(_handle, pointer):
        pointer._obj.value = 1234

    def title(_handle, buffer, _length):
        buffer.value = "PSCAD 5.0.1 (64-bit) Educational"

    def rect(_handle, pointer):
        pointer._obj.left = -32000
        pointer._obj.top = -32000
        pointer._obj.right = -31801
        pointer._obj.bottom = -31966
        return True

    user32 = SimpleNamespace(
        GetWindowThreadProcessId=Mock(side_effect=process_id),
        IsWindowVisible=Mock(return_value=True),
        IsIconic=Mock(return_value=True),
        GetWindowTextLengthW=Mock(return_value=40),
        GetWindowTextW=Mock(side_effect=title),
        GetWindowRect=Mock(side_effect=rect),
        EnumWindows=Mock(side_effect=lambda callback, _arg: callback(100, 0)),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: user32)
    window = find_pscad_window(1234)
    assert window is not None
    assert window.handle == 100


def test_psout_preview_keeps_endpoints_and_full_rate_peak(monkeypatch, tmp_path):
    from seian_power_pipeline import psout_reader

    class FakeFile:
        def __init__(self, _path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def run(self, _index):
            return None

    fake_mhi = ModuleType("mhi")
    fake_psout = ModuleType("mhi.psout")
    fake_psout.File = FakeFile
    fake_mhi.psout = fake_psout
    monkeypatch.setitem(sys.modules, "mhi", fake_mhi)
    monkeypatch.setitem(sys.modules, "mhi.psout", fake_psout)
    trace = SimpleNamespace(data=[0, 50, 2, 3, 4], domain=SimpleNamespace(data=[0, 1, 2, 3, 4]))
    path = "Root/Main/IfaultA_FAULT_N03/0/1"
    monkeypatch.setattr(psout_reader, "_iter_traces", lambda *_: [({"Name": "IfaultA_FAULT_N03"}, trace, path)])
    result = psout_reader.read_selected_channels(tmp_path / "case.psout", [path], max_points=3)
    channel = result["channels"][path]
    assert channel["preview"] == {"time": [0, 2, 4], "values": [0, 2, 4]}
    assert channel["summary"]["max"] == 50
    assert result["sample_count"] == 5
    assert result["not_found"] == []
