"""
core/agent/executor.py — Task Executor component for autonomous agent.

Executes planned steps using existing ActionRegistry tools, records results into TaskState,
and handles step status transitions and errors safely.
"""
from __future__ import annotations

import traceback
from typing import Any, Dict, List, Optional


class Executor:
    """
    Executes individual plan steps using tools registered in ActionRegistry.
    Updates TaskState without deciding overall task completion or generating final answers.
    """

    def __init__(
        self,
        action_registry: Any,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Initialize Executor with an ActionRegistry instance and optional default context.

        Args:
            action_registry: Instance of core.action_loader.ActionRegistry.
            context: Dictionary of context objects (e.g., player, speak, response, session_memory).
        """
        self.action_registry = action_registry
        self.context = context or {}

    def get_next_step(self, task_state: Any) -> Optional[Dict[str, Any]]:
        """
        Identify the next executable step from task_state.plan.

        A step is executable if:
        1. Its status is "PENDING".
        2. All steps listed in its "dependencies" are completed.

        Args:
            task_state: TaskState instance.

        Returns:
            The step dictionary if executable, or None if no step is currently executable.
        """
        if not hasattr(task_state, "plan") or not isinstance(task_state.plan, list):
            return None

        # Build set of completed step IDs
        completed_step_ids = set()
        if hasattr(task_state, "completed_steps") and isinstance(task_state.completed_steps, list):
            for cs in task_state.completed_steps:
                if isinstance(cs, dict) and "step_id" in cs:
                    completed_step_ids.add(cs["step_id"])

        for step in task_state.plan:
            if not isinstance(step, dict):
                continue

            status = step.get("status", "PENDING")
            if status == "COMPLETED":
                step_id = step.get("step_id")
                if step_id:
                    completed_step_ids.add(step_id)
                continue

            if status != "PENDING":
                continue

            # Check dependencies
            deps = step.get("dependencies", [])
            if isinstance(deps, list) and all(dep in completed_step_ids for dep in deps):
                return step

        return None

    def get_executable_steps(self, task_state: Any) -> List[Dict[str, Any]]:
        """Return all pending steps whose dependencies are satisfied."""
        if not hasattr(task_state, "plan") or not isinstance(task_state.plan, list):
            return []

        completed_step_ids = set()
        if hasattr(task_state, "completed_steps") and isinstance(task_state.completed_steps, list):
            for cs in task_state.completed_steps:
                if isinstance(cs, dict) and "step_id" in cs:
                    completed_step_ids.add(cs["step_id"])

        executable = []
        for step in task_state.plan:
            if not isinstance(step, dict):
                continue
            status = step.get("status", "PENDING")
            if status == "COMPLETED":
                step_id = step.get("step_id")
                if step_id:
                    completed_step_ids.add(step_id)
                continue

            if status != "PENDING":
                continue

            deps = step.get("dependencies", [])
            if isinstance(deps, list) and all(dep in completed_step_ids for dep in deps):
                executable.append(step)

        return executable

    def are_steps_independent(self, steps: List[Dict[str, Any]]) -> bool:
        """Check if steps can safely run concurrently (disjoint target paths/resources)."""
        if len(steps) <= 1:
            return True

        target_paths = set()
        for step in steps:
            params = step.get("parameters") or step.get("tool_params") or {}
            action = str(params.get("action", "")).lower()
            # Read-only actions don't conflict
            if action in ("disk_usage", "info", "list", "read", "largest", "find"):
                continue

            p = params.get("path") or params.get("destination") or params.get("file")
            if p:
                p_str = str(p).lower()
                if p_str in target_paths:
                    return False  # Target collision!
                target_paths.add(p_str)

        return True

    def execute_steps_parallel(
        self,
        task_state: Any,
        steps: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute multiple independent steps concurrently using a ThreadPoolExecutor."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = []
        with ThreadPoolExecutor(max_workers=min(4, len(steps))) as pool:
            futures = {
                pool.submit(self.execute_step, task_state, step, None, context): step
                for step in steps
            }
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                    results.append(res)
                except Exception as e:
                    step = futures[fut]
                    results.append({
                        "success": False,
                        "step_id": step.get("step_id"),
                        "tool": step.get("suggested_tool"),
                        "result": None,
                        "error": str(e)
                    })

        return results


    def execute_next_step(
        self,
        task_state: Any,
        parameters: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Find the next executable step in task_state and execute it.

        Args:
            task_state: TaskState instance.
            parameters: Optional parameter overrides for the tool.
            context: Optional context overrides for this execution.

        Returns:
            Dict containing execution information.
        """
        step = self.get_next_step(task_state)
        if not step:
            return {
                "success": False,
                "step_id": None,
                "tool": None,
                "result": None,
                "error": "No executable step found (plan complete or dependencies blocked)."
            }

        return self.execute_step(
            task_state=task_state,
            step=step,
            parameters=parameters,
            context=context
        )

    def execute_step(
        self,
        task_state: Any,
        step: Dict[str, Any],
        parameters: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a single plan step using ActionRegistry.

        Args:
            task_state: TaskState instance to update.
            step: Step dictionary from task_state.plan.
            parameters: Optional tool parameters override.
            context: Optional runtime context dict override.

        Returns:
            Dict containing execution information:
            {
                "success": bool,
                "step_id": str,
                "tool": str,
                "result": str/Any,
                "error": str or None
            }
        """
        step_id = step.get("step_id", "unknown_step")
        tool_name = step.get("suggested_tool") or step.get("tool") or "general"

        # Merge parameters (explicit overrides take precedence over step['parameters'] / step['tool_params'])
        step_params = step.get("parameters") or step.get("tool_params") or step.get("args") or {}
        final_params = dict(step_params)
        if parameters:
            final_params.update(parameters)

        # Merge context
        ctx = dict(self.context)
        if context:
            ctx.update(context)

        # Mark step as EXECUTING and set as current_step in task_state
        step["status"] = "EXECUTING"
        if hasattr(task_state, "current_step"):
            task_state.current_step = step
        if hasattr(task_state, "iteration_count"):
            task_state.iteration_count += 1
        if hasattr(task_state, "touch"):
            task_state.touch()

        # Check if action exists in registry
        if self.action_registry is None or not hasattr(self.action_registry, "has"):
            error_msg = f"ActionRegistry is unavailable or invalid when running tool '{tool_name}'."
            if hasattr(task_state, "fail_step"):
                task_state.fail_step(step, error=error_msg)
            else:
                step["status"] = "FAILED"
            return {
                "success": False,
                "step_id": step_id,
                "tool": tool_name,
                "result": None,
                "error": error_msg
            }

        if not self.action_registry.has(tool_name):
            error_msg = f"Tool '{tool_name}' is not registered in ActionRegistry."
            if hasattr(task_state, "fail_step"):
                task_state.fail_step(step, error=error_msg)
            else:
                step["status"] = "FAILED"
            return {
                "success": False,
                "step_id": step_id,
                "tool": tool_name,
                "result": None,
                "error": error_msg
            }

        # Execute tool safely
        try:
            raw_result = self.action_registry.run(
                name=tool_name,
                parameters=final_params,
                ctx=ctx
            )

            # ActionRegistry.run returns error messages as strings if failure occurred internally
            is_error_output = isinstance(raw_result, str) and (
                raw_result.startswith(f"Tool '{tool_name}' failed:")
                or raw_result.startswith(f"Action '{tool_name}' crashed")
                or raw_result.startswith(f"Action '{tool_name}' is not available")
            )

            if is_error_output:
                if hasattr(task_state, "fail_step"):
                    task_state.fail_step(step, error=raw_result)
                else:
                    step["status"] = "FAILED"
                return {
                    "success": False,
                    "step_id": step_id,
                    "tool": tool_name,
                    "result": None,
                    "error": raw_result
                }

            # Tool execution succeeded
            if hasattr(task_state, "add_result"):
                task_state.add_result(tool_name, raw_result)

            if hasattr(task_state, "complete_step"):
                task_state.complete_step(step, result=raw_result)
            else:
                step["status"] = "COMPLETED"
                step["result"] = raw_result

            return {
                "success": True,
                "step_id": step_id,
                "tool": tool_name,
                "result": raw_result,
                "error": None
            }

        except Exception as e:
            error_msg = f"Exception executing tool '{tool_name}': {e}"
            traceback.print_exc()
            if hasattr(task_state, "fail_step"):
                task_state.fail_step(step, error=error_msg)
            else:
                step["status"] = "FAILED"
            return {
                "success": False,
                "step_id": step_id,
                "tool": tool_name,
                "result": None,
                "error": error_msg
            }
