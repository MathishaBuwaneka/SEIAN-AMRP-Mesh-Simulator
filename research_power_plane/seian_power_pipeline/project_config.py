"""Canonical paths and PSCAD case names for the research power plane."""

from __future__ import annotations

from pathlib import Path


RESEARCH_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = RESEARCH_ROOT / "pscad_workspace"
WORKSPACE_FILE = WORKSPACE_DIR / "SEIAN_PSCAD_Workspace.pswx"

# Preserve the already-validated snapshot case and its original evidence.
STEADY_CASE_NAME = "SEIAN_LV_Switching"
STEADY_CASE_FILE = WORKSPACE_DIR / f"{STEADY_CASE_NAME}.pscx"
STEADY_MAP_FILE = WORKSPACE_DIR / "seian_pscad_component_map.generated.json"
STEADY_RESULTS_FILE = WORKSPACE_DIR / "scenario_results.json"

# New case used for controller-timestamp-driven breaker operation.
TIMED_CASE_NAME = "SEIAN_LV_Timed_Switching"
TIMED_CASE_FILE = WORKSPACE_DIR / f"{TIMED_CASE_NAME}.pscx"
TIMED_MAP_FILE = WORKSPACE_DIR / "seian_pscad_timed_component_map.generated.json"
TIMED_BUILD_REPORT_FILE = WORKSPACE_DIR / "timed_feeder_build_report.json"
TIMED_BUILD_ERROR_FILE = WORKSPACE_DIR / "timed_feeder_build_error.txt"
TIMED_RESULTS_FILE = WORKSPACE_DIR / "transient_scenario_results.json"

DEFAULT_CASE_NAME = TIMED_CASE_NAME
DEFAULT_MAP_FILE = TIMED_MAP_FILE
