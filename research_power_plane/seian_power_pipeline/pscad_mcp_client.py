"""Runtime client for applying SEIAN switch manifests through PowerMCP PSCAD."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PscadRuntimeConfig:
    """Runtime settings for the PSCAD execution stage."""

    project_name: str
    workspace_files: list[str] = field(default_factory=list)
    allowed_roots: list[str] = field(default_factory=list)
    run_after_apply: bool = True
    poll_interval_s: float = 2.0
    max_poll_s: float = 120.0
    read_outputs: bool = False


@dataclass(slots=True)
class PscadExecutionResult:
    """Result of a PSCAD MCP execution run."""

    connected: bool
    project_name: str
    applied_operation_count: int
    pscad_status: Any = None
    loaded_projects: Any = None
    project_settings_result: Any = None
    parameter_results: list[dict[str, Any]] = field(default_factory=list)
    build_result: Any = None
    patched_batch_files: list[str] = field(default_factory=list)
    run_result: Any = None
    run_status_history: list[Any] = field(default_factory=list)
    fresh_output_files: list[str] = field(default_factory=list)
    build_messages: Any = None
    project_output: Any = None
    output_channels: Any = None
    channel_data: Any = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def execute_pscad_manifest(
    manifest: dict[str, Any],
    config: PscadRuntimeConfig,
) -> PscadExecutionResult:
    """Synchronously execute a PSCAD manifest through PowerMCP."""

    return asyncio.run(execute_pscad_manifest_async(manifest, config))


async def execute_pscad_manifest_async(
    manifest: dict[str, Any],
    config: PscadRuntimeConfig,
) -> PscadExecutionResult:
    """Apply switch updates, optionally run PSCAD, and collect status/output."""

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        return PscadExecutionResult(
            connected=False,
            project_name=config.project_name,
            applied_operation_count=0,
            errors=[f"Missing MCP client dependency: {exc}"],
        )

    env = os.environ.copy()
    # PSCAD's generated run batch calls <case>.exe from its current directory.
    # With this Windows hardening flag present, cmd.exe skips that directory.
    env.pop("NoDefaultCurrentDirectoryInExePath", None)
    allowed_roots = config.allowed_roots or [str(Path.cwd())]
    env["POWERIO_MCP_ALLOWED_ROOTS"] = ";".join(allowed_roots)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "powermcp", "run", "pscad"],
        env=env,
    )
    result = PscadExecutionResult(
        connected=False,
        project_name=config.project_name,
        applied_operation_count=0,
    )

    try:
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result.pscad_status = await _call(session, "get_pscad_status", {})
                if not _is_connected(result.pscad_status):
                    result.pscad_status = await _call(session, "get_local_pscad", {})
                result.connected = True

                if config.workspace_files:
                    result.loaded_projects = await _call(
                        session,
                        "load_projects",
                        {"filenames": config.workspace_files},
                    )

                project_settings = manifest.get("project_settings")
                if isinstance(project_settings, dict) and project_settings:
                    result.project_settings_result = await _call(
                        session,
                        "set_project_settings",
                        {
                            "project_name": config.project_name,
                            "settings": project_settings,
                        },
                    )

                for call in manifest.get("calls", []):
                    if call.get("tool") != "set_component_parameters":
                        continue
                    call_result = await _call(session, "set_component_parameters", call["arguments"])
                    result.parameter_results.append(
                        {
                            "metadata": call.get("metadata", {}),
                            "result": call_result,
                        }
                    )
                    result.applied_operation_count += 1

                if config.run_after_apply and config.project_name:
                    result.build_result = await _call(
                        session,
                        "build_project",
                        {"project_name": config.project_name, "clean": False},
                    )
                    result.build_messages = await _call(
                        session,
                        "get_build_messages",
                        {"project_name": config.project_name},
                    )
                    build_errors = _reported_errors(result.build_result, result.build_messages)
                    if build_errors:
                        result.errors.extend(f"PSCAD build error: {message}" for message in build_errors)
                    else:
                        output_before = _psout_snapshot(config)
                        result.patched_batch_files = _patch_pscad_run_batches(config)
                        result.run_result = await _call(
                            session,
                            "run_project",
                            {"project_name": config.project_name},
                        )
                        if not _run_started(result.run_result):
                            result.errors.append("PSCAD did not acknowledge the run request.")
                        else:
                            result.run_status_history = await _poll_run_status(session, config)

                        # run_project may trigger another build, so inspect the
                        # messages again before trusting any output artifact.
                        result.build_messages = await _call(
                            session,
                            "get_build_messages",
                            {"project_name": config.project_name},
                        )
                        for message in _reported_errors(result.build_messages):
                            formatted = f"PSCAD build/run error: {message}"
                            if formatted not in result.errors:
                                result.errors.append(formatted)

                        output_after = _psout_snapshot(config)
                        result.fresh_output_files = _fresh_psout_files(
                            output_before,
                            output_after,
                        )
                        if config.workspace_files and not result.fresh_output_files:
                            result.errors.append(
                                "PSCAD run produced no new or modified .psout file."
                            )

                    result.project_output = await _call(
                        session,
                        "get_project_output",
                        {"project_name": config.project_name},
                    )
                    if config.read_outputs and not result.errors:
                        result.output_channels = await _call(
                            session,
                            "list_output_channels",
                            {"name_or_file": config.project_name},
                        )
                        channel_paths = _extract_channel_paths(result.output_channels)
                        if not channel_paths:
                            result.errors.append(
                                "PSCAD output contains no SEIAN recorder channels."
                            )
                        else:
                            result.channel_data = await _call(
                                session,
                                "read_output_channels",
                                {
                                    "name_or_file": config.project_name,
                                    "channels": channel_paths,
                                    "max_points": 500,
                                },
                            )
    except Exception as exc:  # pragma: no cover - depends on local PSCAD process.
        result.errors.append(str(exc))

    return result


# Recorder channel prefixes emitted by build_lv_feeder.py (must stay in step
# with the signal names it assigns: Vrms_<node>, Irms_/P_/State_<line_id>).
RECORDED_CHANNEL_PREFIXES = ("Vrms_", "Irms_", "P_", "Q_", "State_")

# read_output_channels rejects oversized requests (observed server limit: 30).
MAX_READ_CHANNELS = 30


def _extract_channel_paths(output_channels: Any) -> list[str]:
    """Pull recorded channel paths out of a list_output_channels reply.

    Shape observed live: {"file":..., "channels": [{"path":..., "samples":...}, ...]}
    (optionally {"result": ...}-wrapped).

    Filtering, in order: drop channels with no recorded samples; drop names
    containing stray non-printable bytes (a server-side .psout parsing quirk
    seen on the animate-field channels); then keep only this project's own
    pgb recorder channels. That last step matters because PSCAD also exposes
    every component's animate="true" field as a (near-empty, and for switching
    purposes misleading) channel, and because the request is capped.
    """

    payload = output_channels
    if isinstance(payload, dict):
        payload = payload.get("result", payload)
    rows = payload.get("channels") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    paths: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("samples", 1) == 0:
            continue
        path = row.get("path") or row.get("name")
        if not path or not str(path).isprintable():
            continue
        # A pgb channel's path is Root/Main/<signal name>/<record>/<trace>.
        segments = str(path).split("/")
        component = segments[2] if len(segments) >= 3 else str(path)
        if component.startswith(RECORDED_CHANNEL_PREFIXES):
            paths.append(str(path))
    return paths[:MAX_READ_CHANNELS]


def _patch_pscad_run_batches(config: PscadRuntimeConfig) -> list[str]:
    """Make PSCAD run batches work when Windows excludes cwd from executable lookup."""

    patched: list[str] = []
    exe_name = f"{config.project_name}.exe"
    for workspace_file in config.workspace_files:
        project_dir = Path(workspace_file).resolve().parent / f"{config.project_name}.gf46"
        if not project_dir.exists():
            continue
        for batch_file in project_dir.glob(f"{config.project_name}_*.bat"):
            text = batch_file.read_text(encoding="utf-8", errors="ignore")
            updated = text.replace(f"\n{exe_name} ", f"\n.\\{exe_name} ")
            updated = updated.replace(f"\r\n{exe_name} ", f"\r\n.\\{exe_name} ")
            if updated != text:
                batch_file.write_text(updated, encoding="utf-8")
                patched.append(str(batch_file))
    return patched


def _psout_snapshot(config: PscadRuntimeConfig) -> dict[str, tuple[int, int]]:
    """Return modification/size fingerprints for this case's local PSOUT files."""

    snapshot: dict[str, tuple[int, int]] = {}
    roots = {Path(filename).resolve().parent for filename in config.workspace_files}
    for root in roots:
        for project_dir in root.glob(f"{config.project_name}.gf*"):
            for output_file in project_dir.glob("*.psout"):
                try:
                    stat = output_file.stat()
                except OSError:
                    continue
                snapshot[str(output_file.resolve())] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def _fresh_psout_files(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
) -> list[str]:
    """List result files created or changed by the just-completed run."""

    return sorted(path for path, fingerprint in after.items() if before.get(path) != fingerprint)


def _reported_errors(*payloads: Any) -> list[str]:
    """Extract PSCAD error messages from decoded MCP build-report shapes."""

    messages: list[str] = []
    for payload in payloads:
        if isinstance(payload, dict) and "result" in payload:
            payload = payload["result"]
        if not isinstance(payload, dict):
            continue
        values = payload.get("errors", [])
        if isinstance(values, (str, dict)):
            values = [values]
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, dict):
                message = value.get("text") or value.get("message") or value.get("error")
                if message is None:
                    message = json.dumps(value, default=str)
            else:
                message = str(value)
            if message and message not in messages:
                messages.append(message)
    return messages


def _run_started(run_result: Any) -> bool:
    """Interpret the PowerMCP run acknowledgement without relying on prose."""

    payload = run_result.get("result", run_result) if isinstance(run_result, dict) else run_result
    if isinstance(payload, dict) and "started" in payload:
        return bool(payload["started"])
    return "started" in json.dumps(payload).lower()


async def _poll_run_status(session: Any, config: PscadRuntimeConfig) -> list[Any]:
    history: list[Any] = []
    deadline = time.monotonic() + max(0.0, config.max_poll_s)
    saw_non_idle = False
    idle_count = 0
    while time.monotonic() <= deadline:
        status = await _call(session, "get_run_status", {"project_name": config.project_name})
        history.append(status)
        status_text = json.dumps(status).lower()
        if "building" in status_text or "running" in status_text:
            saw_non_idle = True
            idle_count = 0
        elif saw_non_idle and ("idle" in status_text or "finished" in status_text):
            break
        elif "idle" in status_text or "finished" in status_text:
            idle_count += 1
            if idle_count >= 2:
                break
        await asyncio.sleep(max(0.2, config.poll_interval_s))
    return history


async def _call(session: Any, tool_name: str, arguments: dict[str, Any]) -> Any:
    response = await session.call_tool(tool_name, arguments)
    return _decode_tool_response(response)


def _decode_tool_response(response: Any) -> Any:
    content = getattr(response, "content", [])
    decoded: list[Any] = []
    for item in content:
        text = getattr(item, "text", None)
        if text is None:
            decoded.append(str(item))
            continue
        try:
            decoded.append(json.loads(text))
        except json.JSONDecodeError:
            decoded.append(text)
    if len(decoded) == 1:
        return decoded[0]
    return decoded


def _is_connected(status: Any) -> bool:
    if isinstance(status, dict):
        result = status.get("result", status)
        if isinstance(result, dict):
            return bool(result.get("connected"))
    text = json.dumps(status).lower()
    return '"connected": true' in text
