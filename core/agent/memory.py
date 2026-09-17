"""
core/agent/memory.py — Three-Level Agent Memory Architecture.

1. ShortTermMemory: In-RAM memory for conversation turns & transient context.
2. TaskMemory: Persistent local JSON storage (memory/tasks/{task_id}.json) for complete task resumption.
3. LongTermMemory: Persistent user/project facts (memory/long_term.json).
4. AgentMemory: Unified facade providing clean high-level memory API.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Set

from core.agent.task_state import TaskState, TaskStatus


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


BASE_DIR = _get_base_dir()
TASKS_DIR = BASE_DIR / "memory" / "tasks"
LONG_TERM_PATH = BASE_DIR / "memory" / "long_term.json"

_memory_lock = Lock()


class ShortTermMemory:
    """RAM-only memory for current conversation turns & transient context."""

    def __init__(self, max_turns: int = 20) -> None:
        self.max_turns = max_turns
        self.turns: List[Dict[str, Any]] = []

    def add_turn(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Add a conversation or interaction turn."""
        self.turns.append({
            "role": role,
            "content": content,
            "metadata": metadata or {}
        })
        if len(self.turns) > self.max_turns:
            self.turns.pop(0)

    def get_recent_turns(self, count: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve recent interaction turns."""
        n = count or len(self.turns)
        return list(self.turns[-n:])

    def clear(self) -> None:
        """Clear short-term memory buffer."""
        self.turns.clear()


class TaskMemory:
    """Persistent local task state storage (.json files in memory/tasks/)."""

    def __init__(self, tasks_dir: Optional[Path] = None) -> None:
        self.tasks_dir = tasks_dir or TASKS_DIR
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def save_task(self, task_state: TaskState) -> str:
        """
        Serialize and persist TaskState to a local JSON file.

        Stores:
        - task_id, user_request, plan, completed_steps, failed_steps,
          tool_results, files_created, errors, status.
        """
        with _memory_lock:
            task_dict = task_state.to_dict()
            # Clean sensitive key candidates if present
            for res in task_dict.get("tool_results", []):
                if isinstance(res, dict) and "api_key" in res.get("result", ""):
                    res["result"] = "[SENSITIVE_DATA_REDACTED]"

            target_path = self.tasks_dir / f"{task_state.task_id}.json"
            target_path.write_text(json.dumps(task_dict, indent=2), encoding="utf-8")
            return task_state.task_id

    def load_task(self, task_id: str) -> Optional[TaskState]:
        """Load and reconstruct TaskState from a local JSON file."""
        target_path = self.tasks_dir / f"{task_id}.json"
        if not target_path.exists():
            return None
        try:
            data = json.loads(target_path.read_text(encoding="utf-8"))
            return TaskState.from_dict(data)
        except Exception as e:
            print(f"[TaskMemory] Error loading task {task_id}: {e}")
            return None

    def list_tasks(self) -> List[Dict[str, Any]]:
        """List summary info for all saved tasks."""
        tasks = []
        if not self.tasks_dir.exists():
            return tasks

        for path in sorted(self.tasks_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                tasks.append({
                    "task_id": data.get("task_id", path.stem),
                    "user_request": data.get("user_request", ""),
                    "status": data.get("status", "PENDING"),
                    "completed_steps": len(data.get("completed_steps", [])),
                    "total_steps": len(data.get("plan", [])),
                    "updated_at": data.get("updated_at", ""),
                })
            except Exception:
                continue
        return tasks

    def delete_task(self, task_id: str) -> bool:
        """Delete a saved task file."""
        with _memory_lock:
            target_path = self.tasks_dir / f"{task_id}.json"
            if target_path.exists():
                target_path.unlink()
                return True
            return False

    def resume_task(self, task_id: str, orchestrator: Optional[Any] = None) -> Any:
        """
        Resume an interrupted or failed task without repeating completed steps.

        Args:
            task_id: Task ID string.
            orchestrator: Optional AgentOrchestrator instance to run task resumption.

        Returns:
            OrchestratorResult if orchestrator provided, otherwise restored TaskState.
        """
        state = self.load_task(task_id)
        if state is None:
            raise ValueError(f"Task '{task_id}' not found.")

        if state.status == TaskStatus.COMPLETED:
            return state

        # Prepare state for resumption:
        # Keep completed steps intact, reset remaining or failed steps to PENDING
        completed_ids = {s.get("step_id") for s in state.completed_steps if isinstance(s, dict)}
        for step in state.plan:
            step_id = step.get("step_id")
            if step_id in completed_ids:
                step["status"] = "COMPLETED"
            else:
                step["status"] = "PENDING"

        state.current_step = None
        state.failed_steps.clear()
        state.status = TaskStatus.EXECUTING
        state.touch()

        # Save updated state before running
        self.save_task(state)

        if orchestrator is not None:
            result = orchestrator.run_task(user_request=state.user_request, task_state=state)
            self.save_task(state)
            return result

        return state


class LongTermMemory:
    """Wrapper for persistent long-term user/project knowledge."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or LONG_TERM_PATH

    def store_fact(self, key: str, value: Any) -> None:
        """Store a key-value fact into persistent long-term memory."""
        with _memory_lock:
            data = self._read_data()
            data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_fact(self, key: str, default: Any = None) -> Any:
        """Retrieve a fact from long-term memory."""
        data = self._read_data()
        return data.get(key, default)

    def _read_data(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}


class AgentMemory:
    """Unified Facade for ShortTermMemory, TaskMemory, and LongTermMemory."""

    def __init__(self, tasks_dir: Optional[Path] = None, long_term_path: Optional[Path] = None) -> None:
        self.short_term = ShortTermMemory()
        self.task_memory = TaskMemory(tasks_dir=tasks_dir)
        self.long_term = LongTermMemory(path=long_term_path)

    # TaskMemory API delegators
    def save_task(self, task_state: TaskState) -> str:
        return self.task_memory.save_task(task_state)

    def load_task(self, task_id: str) -> Optional[TaskState]:
        return self.task_memory.load_task(task_id)

    def list_tasks(self) -> List[Dict[str, Any]]:
        return self.task_memory.list_tasks()

    def delete_task(self, task_id: str) -> bool:
        return self.task_memory.delete_task(task_id)

    def resume_task(self, task_id: str, orchestrator: Optional[Any] = None) -> Any:
        return self.task_memory.resume_task(task_id, orchestrator)
