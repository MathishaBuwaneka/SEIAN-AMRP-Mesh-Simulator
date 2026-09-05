"""Run the project-local PowerMCP server and persist its PSCAD connection.

The nonblocking ribbon run can acknowledge a request without producing output
on this PSCAD installation. This wrapper uses a blocking project run and retains
the automation connection between dashboard actions through localhost HTTP.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from powermcp.registry import get_tool

try:
    from .pscad_gui import find_pscad_pid, show_pscad_window, wait_for_pscad_window
except ImportError:  # Executed directly by the detached server process.
    from pscad_gui import find_pscad_pid, show_pscad_window, wait_for_pscad_window


def _load_powermcp_modules() -> Any:
    tool = get_tool("pscad")
    module_root = str(tool.resolve_module_root())
    if module_root not in sys.path:
        sys.path.insert(0, module_root)

    from pscad_mcp.tools import app_tools, project_tools

    return app_tools, project_tools


def _install_project_focus_patch(project_tools: Any) -> None:
    async def run_project(project_name: str) -> dict[str, Any]:
        """Focus and synchronously run one PSCAD project to completion."""

        pscad = project_tools.pscad_manager.pscad
        if not await project_tools.robust_executor.run_safe(pscad.licensed):
            return {"started": False, "completed": False, "error": "PSCAD is not licensed."}
        project = await project_tools.robust_executor.run_safe(pscad.project, project_name)
        await project_tools.robust_executor.run_safe(project.focus)
        await project_tools.robust_executor.run_safe(setattr, pscad, "silence", True)
        await project_tools.robust_executor.run_safe(project.run, _timeout=0)
        return {
            "started": True,
            "completed": True,
            "project": project_name,
        }

    project_tools.run_project = run_project


def _install_connection_patch(
    app_tools: Any,
    project_tools: Any,
    *,
    workspace_file: Path | None,
    project_name: str | None,
) -> Callable[[], Awaitable[dict[str, Any]]]:
    """Make the HTTP server the long-lived owner of a visible PSCAD GUI."""

    manager = project_tools.pscad_manager
    robust_executor = project_tools.robust_executor
    state = {"launched": False}

    def connect_or_launch() -> tuple[Any, bool]:
        import mhi.pscad

        pscad = None
        try:
            candidate = mhi.pscad.connect(timeout=2)
        except Exception:
            candidate = None

        if candidate is not None:
            _, port = candidate.server_address()
            pid = find_pscad_pid(port)
            if wait_for_pscad_window(pid, timeout_s=2.0) is None:
                raise RuntimeError(
                    f"Connected PSCAD process {pid} has no accessible editor window. "
                    "Open PSCAD in the interactive Windows session and retry."
                )
            pscad = candidate

        launched = pscad is None
        if pscad is None:
            load = [str(workspace_file)] if workspace_file is not None else None
            pscad = mhi.pscad.launch(
                silence=False,
                minimize=False,
                splash=True,
                timeout=90,
                load=load,
            )
        if workspace_file is not None:
            pscad.wait_for_idle()
            expected = workspace_file.resolve()
            current = Path(str(pscad.workspace_path)).resolve()
            if launched or current != expected:
                pscad.load(str(expected))
                pscad.wait_for_idle()

        if project_name:
            pscad.project(project_name).focus()
        _, port = pscad.server_address()
        pid = find_pscad_pid(port)
        if wait_for_pscad_window(pid, timeout_s=30.0) is None:
            raise RuntimeError(f"PSCAD process {pid} has no visible editor window.")
        show_pscad_window(pid)
        return pscad, launched

    async def attach_local() -> str:
        try:
            pscad = manager._pscad  # pylint: disable=protected-access
            if pscad is not None and pscad.is_alive():
                _, port = pscad.server_address()
                pid = find_pscad_pid(port)
                if show_pscad_window(pid):
                    state["launched"] = False
                    return f"Successfully attached to PSCAD {pscad.version} (persistent local server)."
        except Exception:
            pass

        manager._pscad = None  # pylint: disable=protected-access
        pscad, launched = await robust_executor.run_safe(connect_or_launch, _timeout=180)
        manager._pscad = pscad  # pylint: disable=protected-access
        state["launched"] = launched
        return f"Successfully attached to PSCAD {pscad.version} (persistent local server)."

    async def ensure_visible_pscad() -> dict[str, Any]:
        """Attach/launch PSCAD and prove that its actual editor is visible."""

        message = await attach_local()
        pscad = manager.pscad
        _, port = pscad.server_address()
        pid = find_pscad_pid(port)
        visible = show_pscad_window(pid)
        return {
            "connected": True,
            "visible": visible,
            "launched": state["launched"],
            "pid": pid,
            "workspace": str(pscad.workspace_path),
            "message": message,
        }

    manager.attach_local = attach_local
    app_tools.pscad_manager = manager
    project_tools.pscad_manager = manager
    return ensure_visible_pscad


def create_server(
    *,
    workspace_file: Path | None = None,
    project_name: str | None = None,
) -> Any:
    app_tools, project_tools = _load_powermcp_modules()
    _install_project_focus_patch(project_tools)
    ensure_visible_pscad = _install_connection_patch(
        app_tools,
        project_tools,
        workspace_file=workspace_file,
        project_name=project_name,
    )

    from pscad_mcp.main import create_server as create_powermcp_server

    server = create_powermcp_server()
    server.tool()(ensure_visible_pscad)
    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace-file", type=Path)
    parser.add_argument("--project-name")
    args = parser.parse_args()

    workspace_file = args.workspace_file.resolve() if args.workspace_file else None
    server = create_server(
        workspace_file=workspace_file,
        project_name=args.project_name,
    )
    if args.transport == "streamable-http":
        server.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            streamable_http_path="/mcp",
        )
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
