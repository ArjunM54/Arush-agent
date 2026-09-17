"""Central, user-controlled safety policy for every callable tool.

Tool descriptions are untrusted model context.  This module classifies the
*actual* requested operation before it reaches a handler and uses the UI-backed
confirmation gate for changes, external communication, and sensitive-data
disclosure.  A model parameter is never accepted as confirmation.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core import confirm

_READ_ONLY_FILE_ACTIONS = {"list", "read", "find", "largest", "disk_usage", "info"}
_READ_ONLY_BROWSER_ACTIONS = {"list_browsers", "get_text", "get_url", "screenshot", "scroll", "back", "forward", "reload"}
_READ_ONLY_DESKTOP_ACTIONS = {"list", "stats", "current_wallpaper"}
_READ_ONLY_COMPUTER_ACTIONS = {"move", "scroll", "screenshot", "screen_find", "wait", "random_data", "user_data"}


@dataclass(frozen=True)
class Decision:
    requires_confirmation: bool
    title: str = ""
    detail: str = ""


def assess(tool_name: str, parameters: dict[str, Any] | None, *, plugin: bool = False) -> Decision:
    """Return the least-privilege decision for an invocation.

    Unknown or third-party tools are deliberately treated as impactful.  This
    makes a newly installed plugin safe by default instead of relying on its
    author to remember a local convention.
    """
    params = parameters or {}
    action = str(params.get("action", "")).strip().lower()

    if plugin:
        return Decision(True, "Run third-party plugin", f"Allow plugin '{tool_name}' to run?")
    if tool_name == "file_controller" and action not in _READ_ONLY_FILE_ACTIONS:
        return Decision(True, "Change files", _file_detail(action, params))
    if tool_name == "send_message":
        recipient = str(params.get("receiver", "a recipient"))[:80]
        platform = str(params.get("platform", "messaging service"))[:40]
        return Decision(True, "Send message", f"Send a message to {recipient} via {platform}?")
    if tool_name == "browser_control" and action not in _READ_ONLY_BROWSER_ACTIONS:
        return Decision(True, "Control browser", f"Allow browser action '{action or 'unknown'}'? It may submit data or change a site.")
    if tool_name == "computer_control" and action not in _READ_ONLY_COMPUTER_ACTIONS:
        return Decision(True, "Control computer", f"Allow computer action '{action or 'unknown'}'?")
    if tool_name in {"computer_settings", "desktop", "open_app", "reminder", "youtube_video", "game_updater"}:
        if tool_name != "desktop" or action not in _READ_ONLY_DESKTOP_ACTIONS:
            return Decision(True, "Change device or service", f"Allow {tool_name} action '{action or 'requested action'}'?")
    if tool_name == "file_processor":
        return Decision(True, "Process local file", "Allow the assistant to read and process the selected local file?")
    if tool_name == "save_memory":
        return Decision(True, "Save personal memory", "Allow the assistant to save this personal detail for future sessions?")
    if tool_name == "manage_monitor" and action in {"add", "remove"}:
        return Decision(True, "Change background monitoring", f"Allow monitoring action '{action}'?")
    return Decision(False)


def run_guarded(tool_name: str, parameters: dict[str, Any] | None, run: Callable[[], str], *, plugin: bool = False) -> str:
    """Execute a safe call now or park an impactful call behind UI consent."""
    decision = assess(tool_name, parameters, plugin=plugin)
    _audit(tool_name, parameters, "confirmation_requested" if decision.requires_confirmation else "allowed")
    if not decision.requires_confirmation:
        return run() or "Done."
    if confirm.pending_title():
        return "Action blocked: another confirmation is already waiting for the user."

    def _confirmed_run() -> str:
        _audit(tool_name, parameters, "confirmed")
        return run() or "Done."

    result = confirm.request(
        key=f"{tool_name}:{hashlib.sha256(repr(sorted((parameters or {}).items())).encode()).hexdigest()[:12]}",
        title=decision.title,
        detail=decision.detail,
        run=_confirmed_run,
    )
    if not result.startswith("[CONFIRMATION_PENDING]"):
        _audit(tool_name, parameters, "blocked")
    return result


def _file_detail(action: str, params: dict[str, Any]) -> str:
    target = str(params.get("name") or params.get("path") or "selected files")[:120]
    return f"Allow file action '{action or 'unknown'}' on {target}?"


def _audit(tool_name: str, parameters: dict[str, Any] | None, outcome: str) -> None:
    """Keep a small local audit trail without recording message/file contents."""
    try:
        safe = {k: str(v)[:120] for k, v in (parameters or {}).items() if k not in {"content", "message_text", "text"}}
        record = {"time": int(time.time()), "tool": tool_name, "outcome": outcome, "parameters": safe}
        root = Path(__file__).resolve().parent.parent
        log = root / "logs" / "safety_audit.jsonl"
        log.parent.mkdir(exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Auditing must never become an availability risk for the assistant.
        pass
