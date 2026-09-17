"""
core/agent/task_state.py — Task state representation for autonomous agent execution.

Tracks task lifecycle, plan execution steps, tool results, generated files,
errors, and iteration limits for complex multi-step user tasks.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskState:
    user_request: str
    goal: str = ""
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    status: TaskStatus = TaskStatus.PENDING
    plan: List[Dict[str, Any]] = field(default_factory=list)
    current_step: Optional[Dict[str, Any]] = None
    completed_steps: List[Dict[str, Any]] = field(default_factory=list)
    failed_steps: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    files_created: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    iteration_count: int = 0
    max_iterations: int = 10
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def touch(self) -> None:
        """Update the last modified timestamp."""
        self.updated_at = _now_iso()

    def add_step(self, step: Any) -> None:
        """Add a planned step to the task plan."""
        step_dict = step if isinstance(step, dict) else {"description": str(step)}
        if "status" not in step_dict:
            step_dict["status"] = "PENDING"
        self.plan.append(step_dict)
        self.touch()

    def complete_step(self, step: Any, result: Any = None) -> None:
        """Record a step as successfully completed."""
        step_dict = step if isinstance(step, dict) else {"description": str(step)}
        step_dict["status"] = "COMPLETED"
        if result is not None:
            step_dict["result"] = result
        self.completed_steps.append(step_dict)
        self.current_step = None
        self.touch()

    def fail_step(self, step: Any, error: Any = None) -> None:
        """Record a step as failed."""
        step_dict = step if isinstance(step, dict) else {"description": str(step)}
        step_dict["status"] = "FAILED"
        if error is not None:
            step_dict["error"] = str(error)
            self.add_error(str(error))
        self.failed_steps.append(step_dict)
        self.current_step = None
        self.touch()

    def add_result(self, tool_name: str, result: Any) -> None:
        """Record the output of a tool call."""
        entry = {
            "tool": tool_name,
            "result": result,
            "timestamp": _now_iso()
        }
        self.tool_results.append(entry)
        self.touch()

    def add_error(self, error: str) -> None:
        """Append an error string to the task error log."""
        self.errors.append(str(error))
        self.touch()

    def add_file_created(self, file_path: str) -> None:
        """Register a new file created during task execution."""
        if file_path not in self.files_created:
            self.files_created.append(file_path)
            self.touch()

    def is_finished(self) -> bool:
        """Check if the task has reached a terminal state."""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

    def can_continue(self) -> bool:
        """Check if the task can execute another iteration."""
        if self.is_finished():
            return False
        if self.status == TaskStatus.PAUSED:
            return False
        if self.iteration_count >= self.max_iterations:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert the task state to a JSON-serializable dictionary."""
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskState:
        """Reconstruct a TaskState instance from a JSON-serializable dictionary."""
        status_raw = data.get("status", "PENDING")
        try:
            status_enum = TaskStatus(status_raw)
        except Exception:
            status_enum = TaskStatus.PENDING

        return cls(
            user_request=data.get("user_request", ""),
            goal=data.get("goal", ""),
            task_id=data.get("task_id", f"task_{uuid.uuid4().hex[:8]}"),
            status=status_enum,
            plan=data.get("plan", []),
            current_step=data.get("current_step"),
            completed_steps=data.get("completed_steps", []),
            failed_steps=data.get("failed_steps", []),
            tool_results=data.get("tool_results", []),
            files_created=data.get("files_created", []),
            errors=data.get("errors", []),
            iteration_count=data.get("iteration_count", 0),
            max_iterations=data.get("max_iterations", 10),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
        )

