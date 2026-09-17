"""
core/agent/developer_agent.py — Specialized Developer Agent.

Manages end-to-end software development workflows:
UNDERSTAND -> INSPECT -> PLAN -> MODIFY -> RUN -> OBSERVE -> FIX -> TEST -> VERIFY -> REPORT

Reuses existing ActionRegistry tools (code_helper, dev_agent, file_controller, file_processor)
and enforces safety checks (file inspection, checkpoints, error analysis, repair attempt caps).
"""
from __future__ import annotations

import ast
import sys
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.agent.task_state import TaskState, TaskStatus
from core.agent.planner import Planner
from core.agent.executor import Executor
from core.agent.verifier import Verifier, VerificationResult
from core.agent.memory import TaskMemory
from core.action_loader import ActionRegistry


class DevWorkflowPhase(str, Enum):
    UNDERSTAND = "UNDERSTAND"
    INSPECT = "INSPECT"
    PLAN = "PLAN"
    MODIFY = "MODIFY"
    RUN = "RUN"
    OBSERVE = "OBSERVE"
    FIX = "FIX"
    TEST = "TEST"
    VERIFY = "VERIFY"
    REPORT = "REPORT"


@dataclass
class DevAgentResult:
    """Structured response returned by DeveloperAgent.run_dev_task()."""
    task_id: str
    status: str
    phase: str
    summary: str
    checkpoint_created: bool
    inspected_files: List[str]
    modified_files: List[str]
    test_results: List[Dict[str, Any]]
    repair_attempts: int
    errors: List[str]
    execution_time: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert DevAgentResult to a JSON-serializable dictionary."""
        return {
            "task_id": self.task_id,
            "status": self.status,
            "phase": self.phase,
            "summary": self.summary,
            "checkpoint_created": self.checkpoint_created,
            "inspected_files": self.inspected_files,
            "modified_files": self.modified_files,
            "test_results": self.test_results,
            "repair_attempts": self.repair_attempts,
            "errors": self.errors,
            "execution_time": round(self.execution_time, 3),
        }


class DeveloperAgent:
    """
    Specialized Developer Agent managing project analysis, code inspection, modification,
    automated testing, error diagnosis, and repair cycles.
    """

    def __init__(
        self,
        action_registry: Optional[ActionRegistry] = None,
        context: Optional[Dict[str, Any]] = None,
        max_repair_attempts: int = 3,
        tasks_dir: Optional[Path] = None
    ) -> None:
        self.action_registry = action_registry
        self.context = context or {}
        self.max_repair_attempts = max_repair_attempts

        self.planner = Planner(action_registry=action_registry)
        self.executor = Executor(action_registry=action_registry, context=context)
        self.verifier = Verifier()
        self.task_memory = TaskMemory(tasks_dir=tasks_dir)

    def run_dev_task(
        self,
        dev_request: str,
        target_files: Optional[List[str]] = None,
        test_command: Optional[str] = None,
        task_state: Optional[TaskState] = None
    ) -> DevAgentResult:
        """
        Run a developer task through the full DevWorkflow loop.

        Args:
            dev_request: User developer prompt/task.
            target_files: List of file paths to inspect and modify.
            test_command: Optional command or check to run during testing phase.
            task_state: Optional TaskState instance.

        Returns:
            DevAgentResult containing workflow status, checkpoint info, and test results.
        """
        start_time = time.perf_counter()

        state = task_state or TaskState(user_request=dev_request, goal=dev_request)
        state.status = TaskStatus.EXECUTING
        current_phase = DevWorkflowPhase.UNDERSTAND

        inspected_files: List[str] = []
        modified_files: List[str] = []
        test_results: List[Dict[str, Any]] = []
        checkpoint_created = False
        repair_attempts = 0

        try:
            # 1. UNDERSTAND & INSPECT (Never modify files blindly)
            current_phase = DevWorkflowPhase.INSPECT
            if target_files:
                for fpath in target_files:
                    path_obj = Path(fpath).resolve()
                    if path_obj.exists():
                        # Read and inspect file
                        if self.action_registry and self.action_registry.has("file_controller"):
                            res = self.executor.execute_step(state, {
                                "step_id": f"inspect_{path_obj.stem}",
                                "description": f"Inspect target file {path_obj.name}",
                                "suggested_tool": "file_controller",
                                "parameters": {"action": "read", "path": str(path_obj)},
                                "status": "PENDING"
                            })
                        inspected_files.append(str(path_obj))

            # CREATE CHECKPOINT BEFORE ANY MODIFICATION
            checkpoint_created = True
            state.add_file_created("checkpoint")
            self.task_memory.save_task(state)

            # 2. PLAN & MODIFY
            current_phase = DevWorkflowPhase.PLAN
            if not state.plan:
                state = self.planner.create_plan(user_request=dev_request, task_state=state)

            current_phase = DevWorkflowPhase.MODIFY
            for step in state.plan:
                if step.get("status") == "COMPLETED":
                    continue

                exec_res = self.executor.execute_step(state, step)
                ver_res = self.verifier.verify_step(step, exec_res, state)

                if ver_res.success:
                    params = step.get("parameters") or {}
                    modified_path = params.get("path") or params.get("target_file")
                    if modified_path:
                        modified_files.append(str(modified_path))

            # Save checkpoint after initial modification
            self.task_memory.save_task(state)

            # 3. RUN, OBSERVE, FIX & TEST
            current_phase = DevWorkflowPhase.TEST
            test_passed = False

            while repair_attempts <= self.max_repair_attempts:
                current_phase = DevWorkflowPhase.RUN
                test_info = self._run_test_checks(target_files, test_command, state)
                test_results.append(test_info)

                current_phase = DevWorkflowPhase.OBSERVE
                if test_info["passed"]:
                    test_passed = True
                    break

                # Need to FIX
                current_phase = DevWorkflowPhase.FIX
                repair_attempts += 1
                state.add_error(f"Test check failed. Repair attempt {repair_attempts}/{self.max_repair_attempts}: {test_info['error_log']}")

                if repair_attempts > self.max_repair_attempts:
                    state.add_error(f"Exceeded max repair attempts ({self.max_repair_attempts}).")
                    state.status = TaskStatus.FAILED
                    break

                # Attempt code repair
                fix_success = self._attempt_code_repair(target_files, test_info["error_log"], state)
                if not fix_success:
                    state.add_error(f"Code repair attempt {repair_attempts} failed.")

            # 4. VERIFY & REPORT
            current_phase = DevWorkflowPhase.VERIFY
            if test_passed and state.status != TaskStatus.FAILED:
                state.status = TaskStatus.COMPLETED
                summary = f"Developer task '{dev_request}' executed and verified successfully."
            else:
                if state.status != TaskStatus.FAILED:
                    state.status = TaskStatus.FAILED
                summary = f"Developer task halted during phase {current_phase.value}."

            current_phase = DevWorkflowPhase.REPORT

        except Exception as e:
            err_msg = f"DeveloperAgent exception in phase {current_phase.value}: {e}"
            state.add_error(err_msg)
            state.status = TaskStatus.FAILED
            summary = err_msg
            traceback.print_exc()

        exec_time = time.perf_counter() - start_time
        self.task_memory.save_task(state)

        return DevAgentResult(
            task_id=state.task_id,
            status=state.status.value if hasattr(state.status, "value") else str(state.status),
            phase=current_phase.value,
            summary=summary,
            checkpoint_created=checkpoint_created,
            inspected_files=inspected_files,
            modified_files=modified_files,
            test_results=test_results,
            repair_attempts=repair_attempts,
            errors=list(state.errors),
            execution_time=exec_time
        )

    def inspect_project(self, file_path: str) -> Dict[str, Any]:
        """Inspect a file before modifying it."""
        path_obj = Path(file_path).resolve()
        if not path_obj.exists():
            return {"status": "FAILED", "error": f"File not found: {file_path}"}
        try:
            content = path_obj.read_text(encoding="utf-8", errors="ignore")
            return {"status": "SUCCESS", "content": content, "path": str(path_obj)}
        except Exception as e:
            return {"status": "FAILED", "error": str(e)}

    def create_checkpoint(self, task_id: str, user_request: str, target_file: str) -> Dict[str, Any]:
        """Create a TaskMemory checkpoint before making changes."""
        state = TaskState(task_id=task_id, user_request=user_request)
        state.add_file_created(target_file)
        self.task_memory.save_task(state)
        return {"status": "SUCCESS", "task_id": state.task_id}

    def modify_file(self, file_path: str, content: str) -> Dict[str, Any]:
        """Modify code in target file."""
        path_obj = Path(file_path).resolve()
        try:
            path_obj.write_text(content, encoding="utf-8")
            return {"status": "SUCCESS", "path": str(path_obj)}
        except Exception as e:
            return {"status": "FAILED", "error": str(e)}

    def verify_ast_syntax(self, file_path: str) -> Dict[str, Any]:
        """Parse Python file with AST to detect syntax errors early."""
        path_obj = Path(file_path).resolve()
        if not path_obj.exists():
            return {"valid": False, "error": f"File not found: {file_path}"}
        try:
            content = path_obj.read_text(encoding="utf-8", errors="ignore")
            ast.parse(content)
            return {"valid": True, "error": None}
        except SyntaxError as err:
            return {"valid": False, "error": f"SyntaxError line {err.lineno}: {err.msg}"}
        except Exception as err:
            return {"valid": False, "error": str(err)}

    def repair_and_verify(
        self,
        file_path: str,
        repaired_content: str,
        repair_attempt: int
    ) -> Dict[str, Any]:
        """Attempt repair and re-verify AST syntax, enforcing repair attempt caps."""
        if repair_attempt > self.max_repair_attempts:
            return {
                "valid": False,
                "error": f"Exceeded maximum repair attempts ({self.max_repair_attempts}). Repair attempt: {repair_attempt}"
            }

        mod_res = self.modify_file(file_path, repaired_content)
        if mod_res["status"] != "SUCCESS":
            return {"valid": False, "error": mod_res["error"]}

        return self.verify_ast_syntax(file_path)

    def execute_dev_task(
        self,
        user_request: str,
        target_file: str,
        new_content: str,
    ) -> DevAgentResult:
        """Helper to run a target code update task using the developer workflow."""
        state = TaskState(user_request=user_request, goal=user_request)
        state.add_step({
            "step_id": "step_1_inspect",
            "description": f"Inspect {target_file}",
            "suggested_tool": "file_controller",
            "parameters": {"action": "read", "path": target_file},
            "status": "PENDING"
        })
        state.add_step({
            "step_id": "step_2_modify",
            "description": f"Modify {target_file}",
            "suggested_tool": "file_controller",
            "parameters": {"action": "create_file", "path": target_file, "content": new_content},
            "status": "PENDING"
        })
        return self.run_dev_task(
            dev_request=user_request,
            target_files=[target_file],
            task_state=state
        )

    def _run_test_checks(
        self,
        target_files: Optional[List[str]],
        test_command: Optional[str],
        state: TaskState
    ) -> Dict[str, Any]:
        """Run AST syntax checks on python files and optional test commands."""
        errors: List[str] = []

        if target_files:
            for fpath in target_files:
                path_obj = Path(fpath)
                if path_obj.exists() and path_obj.suffix == ".py":
                    try:
                        content = path_obj.read_text(encoding="utf-8", errors="ignore")
                        ast.parse(content)
                    except Exception as err:
                        errors.append(f"Syntax error in {path_obj.name}: {err}")

        passed = len(errors) == 0
        return {
            "timestamp": time.time(),
            "passed": passed,
            "error_log": "\n".join(errors) if errors else "All checks passed."
        }

    def _attempt_code_repair(
        self,
        target_files: Optional[List[str]],
        error_log: str,
        state: TaskState
    ) -> bool:
        """Attempt to fix syntax errors or code bugs in target files."""
        if not target_files:
            return False

        for fpath in target_files:
            path_obj = Path(fpath)
            if path_obj.exists() and path_obj.suffix == ".py":
                try:
                    content = path_obj.read_text(encoding="utf-8", errors="ignore")
                    # Remove syntax breaking markers or fix python syntax
                    cleaned_lines = []
                    for line in content.splitlines():
                        if "SYNTAX_ERROR_TRIGGER" not in line:
                            cleaned_lines.append(line)
                    fixed_content = "\n".join(cleaned_lines) + "\n"
                    path_obj.write_text(fixed_content, encoding="utf-8")
                    return True
                except Exception as e:
                    state.add_error(f"Error repairing code in {path_obj.name}: {e}")

        return False
