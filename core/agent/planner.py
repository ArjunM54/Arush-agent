"""
core/agent/planner.py — Task Planner component for autonomous agent.

Converts complex user requests into structured, multi-step execution plans
without executing any tools. Integrates with core/llm_client.py and uses
tool declarations from the action registry.
"""
from __future__ import annotations

import json
import re
import traceback
from typing import Any, Dict, List, Optional, Union

from core.llm_client import call_llm_text
from core.agent.task_state import TaskState, TaskStatus


PLANNER_SYSTEM_PROMPT = """You are an expert AI Agent Planner.
Your sole job is to analyze a complex user request and decompose it into a structured, step-by-step execution plan.

CRITICAL RULES:
1. Do NOT execute any tools. Only generate the plan.
2. Produce ONLY a valid JSON object strictly matching the schema below. No markdown wrapper outside the JSON block.
3. Every step MUST include: step_id, description, objective, suggested_tool, parameters, dependencies, status.
4. Match suggested_tool to one of the provided AVAILABLE TOOLS, or use "general" if no specific tool applies.
5. Provide relevant tool parameters in the "parameters" object for each step (e.g. action, path, content, query).

AVAILABLE TOOLS:
{available_tools_text}

JSON RESPONSE SCHEMA:
{{
  "goal": "Summary of overall goal",
  "steps": [
    {{
      "step_id": "step_1",
      "description": "Short description of the first action",
      "objective": "Specific goal and expected outcome for this step",
      "suggested_tool": "file_controller",
      "parameters": {{
        "action": "disk_usage",
        "path": "documents"
      }},
      "dependencies": [],
      "status": "PENDING"
    }},
    {{
      "step_id": "step_2",
      "description": "Short description of the next action",
      "objective": "Specific goal and expected outcome for this step",
      "suggested_tool": "file_controller",
      "parameters": {{
        "action": "create_file",
        "path": "scratch/disk_report.txt",
        "content": "Disk usage summary report"
      }},
      "dependencies": ["step_1"],
      "status": "PENDING"
    }}
  ]
}}
"""


from core.agent.tool_router import ToolRouter


class Planner:
    """Generates structured execution plans for complex user tasks."""

    def __init__(self, action_registry: Optional[Any] = None) -> None:
        """
        Initialize Planner with optional action registry or list of tool declarations.
        """
        self.action_registry = action_registry
        self.tool_router = ToolRouter(action_registry=action_registry)

    def _get_tools_text(self, user_request: str = "") -> tuple[str, set[str]]:
        """Format dynamically routed tool schemas into prompt text using ToolRouter."""
        tools_desc: list[str] = []
        tool_names: set[str] = {"general"}

        routed_decls = self.tool_router.route_declarations(user_request, self.action_registry)
        for tool in routed_decls:
            if isinstance(tool, dict):
                name = tool.get("name", "")
                desc = tool.get("description", "")
                if name:
                    tool_names.add(name)
                    tools_desc.append(f"- {name}: {desc[:120]}")

        if not tools_desc:
            default_tools = [
                "- file_controller: Search, move, rename, copy, delete files, disk_usage, list, create_file",
                "- web_search: Search the internet for news, research, product costs, or info",
                "- code_helper: Generate, analyze, and refactor code files",
                "- browser_control: Automate web browser, navigate pages, click, type, scrape",
            ]
            tools_text = "\n".join(default_tools)
            tool_names.update(["file_controller", "web_search", "code_helper", "browser_control"])
        else:
            tools_text = "\n".join(tools_desc)

        return tools_text, tool_names



    def create_plan(
        self,
        user_request: str,
        task_state: Optional[TaskState] = None
    ) -> TaskState:
        """
        Generate a structured execution plan for the given user request.

        Args:
            user_request: The user's input prompt.
            task_state: Optional existing TaskState instance to populate.

        Returns:
            TaskState populated with status=PLANNING/EXECUTING and structured plan steps.
        """
        state = task_state or TaskState(user_request=user_request)
        state.status = TaskStatus.PLANNING
        state.touch()

        tools_text, valid_tool_names = self._get_tools_text(user_request)

        system_prompt = PLANNER_SYSTEM_PROMPT.format(available_tools_text=tools_text)

        user_prompt = (
            f"User Request: \"{user_request}\"\n\n"
            "Generate the structured JSON execution plan for this request now."
        )

        try:
            raw_response = call_llm_text(prompt=user_prompt, system=system_prompt)
            plan_data = self._parse_json_response(raw_response)
            steps = self._validate_and_sanitize_steps(
                plan_data.get("steps", []),
                valid_tool_names
            )
            goal = plan_data.get("goal") or f"Execute user request: {user_request}"

            if not steps:
                steps = self._build_fallback_plan(user_request)

        except Exception as e:
            print(f"[Planner] Failed to generate plan via LLM ({e}). Using robust fallback.")
            traceback.print_exc()
            goal = f"Execute request: {user_request}"
            steps = self._build_fallback_plan(user_request)
            state.add_error(f"Planner fallback used: {e}")

        state.goal = goal
        state.plan = steps
        state.status = TaskStatus.PENDING
        state.touch()

        return state

    def _parse_json_response(self, text: str) -> dict:
        """Extract and parse JSON object from LLM response string safely."""
        cleaned = text.strip()
        # Remove markdown code block wrappers
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        # Find first { and last }
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            json_str = match.group(0)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        return json.loads(cleaned)

    def _validate_and_sanitize_steps(
        self,
        raw_steps: List[Any],
        valid_tools: set[str]
    ) -> List[Dict[str, Any]]:
        """Validate every step in the raw plan to ensure required keys and types."""
        sanitized: List[Dict[str, Any]] = []

        if not isinstance(raw_steps, list):
            return sanitized

        for idx, step in enumerate(raw_steps, start=1):
            if not isinstance(step, dict):
                continue

            step_id = str(step.get("step_id") or f"step_{idx}").strip()
            desc = str(step.get("description") or f"Step {idx}").strip()
            objective = str(step.get("objective") or desc).strip()
            tool = str(step.get("suggested_tool") or "general").strip()

            if tool not in valid_tools:
                tool = "general"

            deps = step.get("dependencies", [])
            if not isinstance(deps, list):
                deps = []
            deps = [str(d) for d in deps if isinstance(d, (str, int))]

            params = step.get("parameters") or step.get("tool_params") or step.get("args") or {}
            if not isinstance(params, dict):
                params = {}

            sanitized.append({
                "step_id": step_id,
                "description": desc,
                "objective": objective,
                "suggested_tool": tool,
                "parameters": params,
                "dependencies": deps,
                "status": "PENDING",
            })

        return sanitized


    def _build_fallback_plan(self, user_request: str) -> List[Dict[str, Any]]:
        """Construct a safe, structured fallback plan if LLM parsing fails."""
        req_lower = user_request.lower()

        if "disk" in req_lower or "space" in req_lower or "file" in req_lower:
            return [
                {
                    "step_id": "step_1",
                    "description": "Check system disk space",
                    "objective": "Retrieve current disk space and metrics",
                    "suggested_tool": "file_controller",
                    "parameters": {"action": "disk_usage", "path": "documents"},
                    "dependencies": [],
                    "status": "PENDING",
                },
                {
                    "step_id": "step_2",
                    "description": "Write report file",
                    "objective": "Save disk usage report to file",
                    "suggested_tool": "file_controller",
                    "parameters": {"action": "create_file", "path": "scratch/disk_report.txt", "content": "Disk usage report completed."},
                    "dependencies": ["step_1"],
                    "status": "PENDING",
                }
            ]

        return [
            {
                "step_id": "step_1",
                "description": "Gather context and information",
                "objective": f"Analyze request and collect details for: {user_request}",
                "suggested_tool": "web_search",
                "parameters": {"query": user_request},
                "dependencies": [],
                "status": "PENDING",
            },
            {
                "step_id": "step_2",
                "description": "Process and create deliverable",
                "objective": "Execute necessary processing and generate requested output",
                "suggested_tool": "code_helper",
                "parameters": {},
                "dependencies": ["step_1"],
                "status": "PENDING",
            },
        ]

