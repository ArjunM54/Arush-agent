"""
core/agent/delegator.py — Controlled Specialist Delegation.

Enables the main Orchestrator to delegate sub-tasks to dedicated specialist agents:
- DeveloperAgent (code inspection, modifications, AST syntax checks, repair loops)
- ResearchAgent (web search, source tracking, fact/inference/uncertainty extraction)
- BrowserAgent (web browsing, page interaction, element extraction)
- FileAgent (file reading, writing, parsing, structured file operations)

Enforces strict task metadata tracking (task_id, parent_task_id, objective, input, output, status, errors)
and prevents recursive delegation loops via depth tracking and caller chain verification.
"""
from __future__ import annotations

import uuid
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from core.agent.task_state import TaskState, TaskStatus
from core.agent.executor import Executor
from core.agent.verifier import Verifier
from core.agent.developer_agent import DeveloperAgent, DevAgentResult
from core.agent.research_agent import ResearchAgent, ResearchReport
from core.action_loader import ActionRegistry


class SpecialistType(str, Enum):
    DEVELOPER = "DeveloperAgent"
    RESEARCH = "ResearchAgent"
    BROWSER = "BrowserAgent"
    FILE = "FileAgent"


@dataclass
class DelegatedTask:
    """Structure tracking every delegated task execution."""
    task_id: str
    parent_task_id: str
    specialist_type: SpecialistType
    objective: str
    input_data: Dict[str, Any]
    output_data: Dict[str, Any] = field(default_factory=dict)
    status: str = "PENDING"
    errors: List[str] = field(default_factory=list)
    delegation_depth: int = 1
    execution_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "parent_task_id": self.parent_task_id,
            "specialist_type": self.specialist_type.value if isinstance(self.specialist_type, SpecialistType) else str(self.specialist_type),
            "objective": self.objective,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "status": self.status,
            "errors": self.errors,
            "delegation_depth": self.delegation_depth,
            "execution_time": round(self.execution_time, 3),
        }


class BrowserAgent:
    """Lightweight specialist wrapping browser & web navigation tools."""

    def __init__(self, action_registry: Optional[ActionRegistry] = None, context: Optional[Dict[str, Any]] = None) -> None:
        self.action_registry = action_registry
        self.executor = Executor(action_registry=action_registry, context=context)

    def run_browser_task(self, objective: str, url: str = "", action: str = "navigate", parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = parameters or {}
        params.update({"url": url, "action": action})

        state = TaskState(user_request=objective)
        step = {
            "step_id": "browser_step_1",
            "description": f"Browser action '{action}' on {url or 'web'}",
            "suggested_tool": "browser_control" if (self.action_registry and self.action_registry.has("browser_control")) else "web_search",
            "parameters": params,
            "status": "PENDING"
        }
        res = self.executor.execute_step(state, step)
        return res


class FileAgent:
    """Lightweight specialist wrapping file controller & processor tools."""

    def __init__(self, action_registry: Optional[ActionRegistry] = None, context: Optional[Dict[str, Any]] = None) -> None:
        self.action_registry = action_registry
        self.executor = Executor(action_registry=action_registry, context=context)

    def run_file_task(self, objective: str, action: str = "create_file", path: str = "", content: str = "") -> Dict[str, Any]:
        state = TaskState(user_request=objective)
        step = {
            "step_id": "file_step_1",
            "description": f"File action '{action}' on {path}",
            "suggested_tool": "file_controller",
            "parameters": {"action": action, "path": path, "content": content},
            "status": "PENDING"
        }
        res = self.executor.execute_step(state, step)
        return res


class SpecialistDelegator:
    """
    Manager delegator embedded in Orchestrator that decides when specialists are needed,
    dispatches tasks safely, prevents recursive loops, and tracks execution metadata.
    """

    def __init__(
        self,
        action_registry: Optional[ActionRegistry] = None,
        context: Optional[Dict[str, Any]] = None,
        max_delegation_depth: int = 2
    ) -> None:
        self.action_registry = action_registry
        self.context = context or {}
        self.max_delegation_depth = max_delegation_depth

        self.developer_agent = DeveloperAgent(action_registry=action_registry, context=context)
        self.research_agent = ResearchAgent(action_registry=action_registry, context=context)
        self.browser_agent = BrowserAgent(action_registry=action_registry, context=context)
        self.file_agent = FileAgent(action_registry=action_registry, context=context)

        self.delegated_tasks: List[DelegatedTask] = []
        self.active_chain: List[SpecialistType] = []

    def select_specialist(self, task_description: str) -> Optional[SpecialistType]:
        """Determine which specialist is best suited for a task description."""
        desc_lower = task_description.lower()

        # Code / Developer tasks
        if any(w in desc_lower for w in ["code", "python", "fix bug", "ast", "modify file", "refactor", "build script"]):
            return SpecialistType.DEVELOPER

        # Research tasks
        if any(w in desc_lower for w in ["research", "fact check", "compare items", "find background", "search web for"]):
            return SpecialistType.RESEARCH

        # Browser tasks
        if any(w in desc_lower for w in ["browser", "open website", "navigate to", "click element"]):
            return SpecialistType.BROWSER

        # File tasks
        if any(w in desc_lower for w in ["save report", "write file", "read document", "create file", "save markdown"]):
            return SpecialistType.FILE

        return None

    def can_delegate(
        self,
        parent_task_id: str,
        specialist_type: SpecialistType,
        current_depth: int
    ) -> Tuple[bool, str]:
        """
        Check if delegation is allowed.
        Enforces max_delegation_depth and prevents recursive delegation loops.
        """
        if current_depth > self.max_delegation_depth:
            return False, f"Exceeded maximum delegation depth ({self.max_delegation_depth}). Current depth: {current_depth}"

        if specialist_type in self.active_chain:
            return False, f"Recursive delegation loop detected! Specialist {specialist_type.value} is already in active chain: {[s.value for s in self.active_chain]}"

        return True, "Delegation allowed"

    def delegate_task(
        self,
        parent_task_id: str,
        specialist_type: SpecialistType,
        objective: str,
        input_data: Optional[Dict[str, Any]] = None,
        delegation_depth: int = 1
    ) -> DelegatedTask:
        """
        Execute sub-task on requested specialist and track full metadata.
        """
        input_params = input_data or {}
        sub_task_id = f"sub_{specialist_type.value.lower()}_{uuid.uuid4().hex[:6]}"

        task_record = DelegatedTask(
            task_id=sub_task_id,
            parent_task_id=parent_task_id,
            specialist_type=specialist_type,
            objective=objective,
            input_data=input_params,
            status="IN_PROGRESS",
            delegation_depth=delegation_depth
        )

        allowed, reason = self.can_delegate(parent_task_id, specialist_type, delegation_depth)
        if not allowed:
            task_record.status = "FAILED"
            task_record.errors.append(reason)
            self.delegated_tasks.append(task_record)
            return task_record

        start_time = time.perf_counter()
        self.active_chain.append(specialist_type)

        try:
            if specialist_type == SpecialistType.DEVELOPER:
                target_file = input_params.get("target_file", "")
                new_content = input_params.get("new_content", "")
                res: DevAgentResult = self.developer_agent.execute_dev_task(
                    user_request=objective,
                    target_file=target_file,
                    new_content=new_content
                )
                task_record.output_data = res.to_dict()
                task_record.status = "COMPLETED" if res.status in ("COMPLETED", "SUCCESS") else "FAILED"
                if res.errors:
                    task_record.errors.extend(res.errors)

            elif specialist_type == SpecialistType.RESEARCH:
                topic = input_params.get("topic", objective)
                report: ResearchReport = self.research_agent.run_research_task(topic)
                task_record.output_data = {
                    "summary": report.summary,
                    "sourced_facts_count": len(report.sourced_facts),
                    "inferences_count": len(report.inferences),
                    "uncertainties_count": len(report.uncertainties),
                    "markdown": report.to_markdown(),
                    "verified": report.verified
                }
                task_record.status = "COMPLETED" if report.verified else "FAILED"

            elif specialist_type == SpecialistType.BROWSER:
                url = input_params.get("url", "")
                action = input_params.get("action", "navigate")
                res_dict = self.browser_agent.run_browser_task(objective, url=url, action=action, parameters=input_params)
                task_record.output_data = res_dict
                task_record.status = res_dict.get("status", "COMPLETED")
                if res_dict.get("error"):
                    task_record.errors.append(str(res_dict["error"]))

            elif specialist_type == SpecialistType.FILE:
                action = input_params.get("action", "create_file")
                path = input_params.get("path", "")
                content = input_params.get("content", "")
                res_dict = self.file_agent.run_file_task(objective, action=action, path=path, content=content)
                task_record.output_data = res_dict
                task_record.status = res_dict.get("status", "COMPLETED")
                if res_dict.get("error"):
                    task_record.errors.append(str(res_dict["error"]))

        except Exception as e:
            task_record.status = "FAILED"
            task_record.errors.append(f"Specialist execution exception: {e}")

        finally:
            if specialist_type in self.active_chain:
                self.active_chain.remove(specialist_type)

        task_record.execution_time = time.perf_counter() - start_time
        self.delegated_tasks.append(task_record)
        return task_record
