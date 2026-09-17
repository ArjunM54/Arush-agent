"""Focused regression checks for the central responsible-agent policy."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import confirm
from core.safety import assess, run_guarded
from memory.config_manager import get_plugin_enabled


def test_policy():
    assert not assess("file_controller", {"action": "list"}).requires_confirmation
    assert assess("file_controller", {"action": "delete", "path": "documents"}).requires_confirmation
    assert assess("send_message", {"receiver": "Alex"}).requires_confirmation
    assert not assess("browser_control", {"action": "get_text"}).requires_confirmation
    assert assess("browser_control", {"action": "fill_form"}).requires_confirmation
    assert assess("unreviewed_plugin", {}, plugin=True).requires_confirmation
    assert not get_plugin_enabled("newly_discovered_plugin")

    shown = []
    ran = []
    confirm.bind(lambda title, detail: shown.append((title, detail)), lambda: None)
    pending = run_guarded("send_message", {"receiver": "Alex"}, lambda: ran.append(True) or "sent")
    assert pending.startswith("[CONFIRMATION_PENDING]")
    assert shown and not ran, "the action must not run before a UI response"
    confirm.resolve(False)
    assert not ran, "cancelling confirmation must not run the action"
    print("Safety policy checks passed.")


if __name__ == "__main__":
    test_policy()
