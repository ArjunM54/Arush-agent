"""Regression check: a confirmed action runs exactly once and reports completion."""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import confirm


def test_confirmation():
    shown, logs, ran = [], [], []
    confirm.bind(lambda title, detail: shown.append((title, detail)), lambda: None, logs.append)
    confirm.request("test", "Test action", "detail", lambda: ran.append(True) or "finished")
    confirm.resolve(True)
    for _ in range(20):
        if ran:
            break
        time.sleep(0.02)
    assert shown and ran == [True]
    assert any("Completed — Test action. finished" in entry for entry in logs)
    print("Confirmation flow check passed.")


if __name__ == "__main__":
    test_confirmation()
