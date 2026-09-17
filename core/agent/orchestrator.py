"""
core/agent/orchestrator.py — Autonomous Agent Orchestrator.

Orchestrates the full agent loop:
User Request -> TaskState -> Plan -> Execute Step -> Observe Result -> Verify -> Retry/Replan if needed -> Final Verification -> Final Response.
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.agent.task_state import TaskState, TaskStatus
from core.agent.planner import Planner
from core.agent.executor import Executor
from core.agent.verifier import Verifier, VerificationResult
from core.agent.delegator import SpecialistDelegator, SpecialistType


@dataclass
class OrchestratorResult:
    """Structured response returned by AgentOrchestrator.run_task()."""
    task_id: str
    status: str
    summary: str
    completed_steps: List[Dict[str, Any]]
    failed_steps: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    files_created: List[str]
    errors: List[str]
    execution_time: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert OrchestratorResult to a JSON-serializable dictionary."""
        return {
            "task_id": self.task_id,
            "status": self.status,
            "summary": self.summary,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "tool_results": self.tool_results,
            "files_created": self.files_created,
            "errors": self.errors,
            "execution_time": round(self.execution_time, 3),
        }


class AgentOrchestrator:
    """
    Main autonomous orchestrator connecting TaskState, Planner, Executor, Verifier, and SpecialistDelegator.
    """

    def __init__(
        self,
        action_registry: Any = None,
        context: Optional[Dict[str, Any]] = None,
        max_iterations: int = 10,
        max_retries_per_step: int = 2,
        on_update: Optional[Any] = None
    ) -> None:
        self.action_registry = action_registry
        self.context = context or {}
        self.max_iterations = max_iterations
        self.max_retries_per_step = max_retries_per_step
        self.on_update = on_update

        self.planner = Planner(action_registry=action_registry)
        self.executor = Executor(action_registry=action_registry, context=context)
        self.verifier = Verifier()
        self.delegator = SpecialistDelegator(action_registry=action_registry, context=context)

    def run_task(
        self,
        user_request: str,
        task_state: Optional[TaskState] = None,
        on_update: Optional[Any] = None
    ) -> OrchestratorResult:
        start_time = time.time()
        callback = on_update or getattr(self, "on_update", None)

        def _notify(st: TaskState):
            if callback and callable(callback):
                try:
                    callback(st)
                except Exception:
                    pass

        print(f"[AGENT] ORCHESTRATOR: Running task for request: {user_request[:100]}")

        # 1. CREATE / PREPARE TASK STATE
        state = task_state or TaskState(
            user_request=user_request,
            max_iterations=self.max_iterations
        )
        _notify(state)

        if state.status in (TaskStatus.CANCELLED, TaskStatus.PAUSED):
            return self._build_result(state, start_time, f"Task in {state.status.value} state before starting.")

        # Check for Specialist Delegation (e.g. ResearchAgent or DeveloperAgent)
        specialist_type = self.delegator.select_specialist(user_request)
        if specialist_type == SpecialistType.RESEARCH:
            print(f"[AGENT] ROUTER: Identified research capability group")
            print(f"[AGENT] DELEGATION: Delegating to SpecialistType.RESEARCH (ResearchAgent)")
            state.status = TaskStatus.PLANNING
            _notify(state)

            print("[AGENT] RESEARCH: Executing ResearchAgent sub-task")
            delegated_task = self.delegator.delegate_task(
                parent_task_id=state.task_id,
                specialist_type=SpecialistType.RESEARCH,
                objective=user_request
            )

            if delegated_task.status == "COMPLETED" and delegated_task.output_data.get("markdown"):
                md_content = delegated_task.output_data["markdown"]
                print(f"[AGENT] RESEARCH: ResearchAgent produced report ({len(md_content)} chars)")
                
                # Check if user asked to save to a file
                file_match = re.search(r'([\w\-\.\/]+\.md)', user_request, re.IGNORECASE)
                target_filename = file_match.group(1) if file_match else "research_report.md"
                
                print(f"[AGENT] TOOL: file_controller action='create_file' path='{target_filename}'")
                step_save = {
                    "step_id": "step_save_research",
                    "description": f"Create Markdown research report '{target_filename}'",
                    "suggested_tool": "file_controller",
                    "parameters": {"action": "create_file", "path": target_filename, "content": md_content},
                    "status": "PENDING"
                }
                state.add_step(step_save)
                exec_save = self.executor.execute_step(state, step_save)
                ver_save = self.verifier.verify_step(step_save, exec_save, state)
                print(f"[AGENT] VERIFIER: VerificationResult success={ver_save.success} reason='{ver_save.reason}'")

                if ver_save.success:
                    state.status = TaskStatus.COMPLETED
                    state.add_file_created(target_filename)
                    summary = f"Research completed and saved to {target_filename}.\n\n{delegated_task.output_data.get('summary', '')}"
                    _notify(state)
                    print(f"[AGENT] RESULT: Status=COMPLETED Summary='{summary[:100]}'")
                    return self._build_result(state, start_time, summary)
                else:
                    state.add_error(f"Failed to verify research output file '{target_filename}': {ver_save.reason}")

        # 2. PLAN (standard flow for non-specialist or fallback)
        if not state.plan:
            state.status = TaskStatus.PLANNING
            state.touch()
            _notify(state)
            print("[AGENT] PLANNER: Generating execution plan")
            try:
                state = self.planner.create_plan(user_request=user_request, task_state=state)
                print(f"[AGENT] PLAN: Generated {len(state.plan)} plan steps")
                _notify(state)
            except Exception as e:
                err_msg = f"Planning failed: {e}"
                state.add_error(err_msg)
                state.status = TaskStatus.FAILED
                _notify(state)
                print(f"[AGENT] RESULT: Status=FAILED Reason='{err_msg}'")
                return self._build_result(state, start_time, err_msg)

        state.status = TaskStatus.EXECUTING
        state.touch()
        _notify(state)

        step_retry_counts: Dict[str, int] = {}
        replan_count = 0
        max_replans = 3

        # 3. MAIN EXECUTION & VERIFICATION LOOP
        while state.can_continue():
            # Check pause / cancellation state
            if state.status == TaskStatus.CANCELLED:
                return self._build_result(state, start_time, "Task execution cancelled.")
            if state.status == TaskStatus.PAUSED:
                return self._build_result(state, start_time, "Task execution paused.")

            # Identify all currently executable steps
            ready_steps = self.executor.get_executable_steps(state)

            if not ready_steps:
                # Check if all steps in current plan are completed
                if self._all_steps_completed(state):
                    break  # Success! All planned steps completed.
                else:
                    # Steps remain but dependencies are blocked or failing
                    if replan_count < max_replans:
                        replan_count += 1
                        ok = self._replan(state, reason="Plan blocked by dependencies or failing steps.")
                        if not ok:
                            state.add_error("Re-planning produced no new executable steps.")
                            state.status = TaskStatus.FAILED
                            break
                        continue
                    else:
                        state.add_error("Maximum replan attempts exceeded.")
                        state.status = TaskStatus.FAILED
                        break

            # If multiple independent steps ready, execute in parallel safely
            if len(ready_steps) > 1 and self.executor.are_steps_independent(ready_steps):
                exec_infos = self.executor.execute_steps_parallel(state, ready_steps)
                for step, exec_info in zip(ready_steps, exec_infos):
                    step_id = step.get("step_id", "unknown_step")
                    retries = step_retry_counts.get(step_id, 0)
                    ver_res: VerificationResult = self.verifier.verify_step(
                        step=step,
                        execution_result=exec_info,
                        task_state=state
                    )
                    if ver_res.success:
                        step_retry_counts[step_id] = 0
                        state.failed_steps = [s for s in state.failed_steps if s.get("step_id") != step_id]
                    else:
                        state.completed_steps = [s for s in state.completed_steps if s.get("step_id") != step_id]
                        if step.get("status") != "FAILED":
                            state.fail_step(step, error=ver_res.reason)
                        state.add_error(f"Step '{step_id}' verification failed: {ver_res.reason}")
                continue

            # Sequential fallback for single or dependent step
            step = ready_steps[0]
            step_id = step.get("step_id", "unknown_step")
            retries = step_retry_counts.get(step_id, 0)

            # 4. EXECUTE STEP
            exec_info = self.executor.execute_step(state, step)

            # 5. OBSERVE & VERIFY STEP RESULT

            ver_res: VerificationResult = self.verifier.verify_step(
                step=step,
                execution_result=exec_info,
                task_state=state
            )

            if ver_res.success:
                # Verified success! Ensure step is in completed_steps and cleared from failed_steps
                step_retry_counts[step_id] = 0
                state.failed_steps = [s for s in state.failed_steps if s.get("step_id") != step_id]
            else:
                # Verification failed or evidence missing
                # Remove step from completed_steps if Executor added it prematurely
                state.completed_steps = [s for s in state.completed_steps if s.get("step_id") != step_id]
                if step.get("status") != "FAILED":
                    state.fail_step(step, error=ver_res.reason)

                err_log = f"Step '{step_id}' verification failed: {ver_res.reason}"
                state.add_error(err_log)

                # Deciding Retry vs Re-plan
                if ver_res.retryable and retries < self.max_retries_per_step:
                    step_retry_counts[step_id] = retries + 1
                    # Reset step status to PENDING so Executor can retry it
                    step["status"] = "PENDING"
                    # Remove from failed_steps list to allow clean retry
                    state.failed_steps = [s for s in state.failed_steps if s.get("step_id") != step_id]
                else:
                    # Retries exhausted or non-retryable failure -> Trigger Re-plan
                    if replan_count < max_replans:
                        replan_count += 1
                        replan_ok = self._replan(state, reason=f"Step '{step_id}' failed: {ver_res.reason}")
                        if not replan_ok:
                            state.add_error(f"Re-planning failed after step '{step_id}' failure.")
                            state.status = TaskStatus.FAILED
                            break
                    else:
                        state.add_error(f"Step '{step_id}' unrecoverable and replan limit reached.")
                        state.status = TaskStatus.FAILED
                        break

            _notify(state)

        # Check for iteration limit exhaustion
        if state.iteration_count >= state.max_iterations and not self._all_steps_completed(state):
            state.add_error(f"Maximum iteration limit ({state.max_iterations}) reached.")
            state.status = TaskStatus.FAILED

        # 6. FINAL VERIFICATION & RESPONSE
        if self._all_steps_completed(state) and state.status != TaskStatus.FAILED:
            state.status = TaskStatus.COMPLETED
            summary = self._generate_success_summary(state)
        else:
            if state.status != TaskStatus.PAUSED and state.status != TaskStatus.CANCELLED:
                state.status = TaskStatus.FAILED
            summary = self._generate_failure_summary(state)

        _notify(state)
        return self._build_result(state, start_time, summary)

    def pause_task(self, state: TaskState) -> TaskState:
        """Pause a running task state."""
        state.status = TaskStatus.PAUSED
        state.touch()
        return state

    def resume_task(self, state: TaskState) -> TaskState:
        """Resume a paused task state."""
        if state.status == TaskStatus.PAUSED:
            state.status = TaskStatus.EXECUTING
            state.touch()
        return state

    def cancel_task(self, state: TaskState) -> TaskState:
        """Cancel a task state."""
        state.status = TaskStatus.CANCELLED
        state.touch()
        return state

    def _replan(self, state: TaskState, reason: str) -> bool:
        """
        Re-plans remaining uncompleted work while preserving completed steps.
        """
        state.add_error(f"Triggering re-plan: {reason}")
        completed_ids = {s.get("step_id") for s in state.completed_steps if isinstance(s, dict)}

        try:
            completed_summary = [s.get("description", "") for s in state.completed_steps]
            replan_prompt = (
                f"Original User Request: \"{state.user_request}\"\n"
                f"Already Completed Steps: {completed_summary}\n"
                f"Failure Reason: {reason}\n"
                "Generate a revised plan for the remaining uncompleted steps."
            )
            new_state = self.planner.create_plan(user_request=replan_prompt)
            if new_state.plan:
                # Filter out steps already completed
                remaining = [
                    s for s in new_state.plan
                    if s.get("step_id") not in completed_ids and s.get("status") == "PENDING"
                ]
                if remaining:
                    # Update plan preserving completed steps
                    completed_plan = [s for s in state.plan if s.get("status") == "COMPLETED"]
                    state.plan = completed_plan + remaining
                    return True
        except Exception as e:
            state.add_error(f"Re-planning exception: {e}")

        return False

    def _all_steps_completed(self, state: TaskState) -> bool:
        """Returns True if state has at least one step and all steps are COMPLETED."""
        if not state.plan:
            return False
        return all(step.get("status") == "COMPLETED" for step in state.plan)

    def _generate_success_summary(self, state: TaskState) -> str:
        completed_descs = [f"- {s.get('description', 'Step')}" for s in state.completed_steps]
        steps_text = "\n".join(completed_descs)
        return (
            f"Task '{state.task_id}' completed successfully.\n"
            f"Goal: {state.goal}\n"
            f"Completed Steps ({len(state.completed_steps)}):\n{steps_text}"
        )

    def _generate_failure_summary(self, state: TaskState) -> str:
        last_error = state.errors[-1] if state.errors else "Task could not be completed."
        return (
            f"Task '{state.task_id}' halted or failed.\n"
            f"Status: {state.status.value if hasattr(state.status, 'value') else state.status}\n"
            f"Reason: {last_error}"
        )

    def _build_result(self, state: TaskState, start_time: float, summary: str) -> OrchestratorResult:
        exec_time = time.time() - start_time
        status_val = state.status.value if hasattr(state.status, "value") else str(state.status)
        return OrchestratorResult(
            task_id=state.task_id,
            status=status_val,
            summary=summary,
            completed_steps=list(state.completed_steps),
            failed_steps=list(state.failed_steps),
            tool_results=list(state.tool_results),
            files_created=list(state.files_created),
            errors=list(state.errors),
            execution_time=exec_time
        )
