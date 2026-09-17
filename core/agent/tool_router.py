"""
core/agent/tool_router.py — Intelligent Tool Router for autonomous agent.

Groups existing ActionRegistry tools by capability and deterministically selects only
the relevant tool declarations for a user request, reducing LLM prompt size and latency.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

# Capability Group Mapping to existing bundled tools
TOOL_CAPABILITY_GROUPS: Dict[str, Dict[str, Any]] = {
    "weather": {
        "tools": {"weather_report"},
        "keywords": {"weather", "forecast", "rain", "temperature", "climate", "degree", "sunny", "cloudy", "humidity"},
    },
    "web_research": {
        "tools": {"web_search", "browser_control"},
        "keywords": {"search", "google", "lookup", "research", "find online", "website", "url", "browse", "scrape", "latest news", "internet"},
    },
    "file_system": {
        "tools": {"file_controller", "file_processor"},
        "keywords": {"file", "folder", "directory", "disk", "space", "create file", "delete", "copy", "move", "rename", "pdf", "docx", "csv", "txt", "document", "report", "path"},
    },
    "developer": {
        "tools": {"code_helper", "dev_agent", "file_controller"},
        "keywords": {"code", "script", "python", "bug", "error", "refactor", "function", "fix", "project", "repo", "repository", "compile", "build", "vs code", "vscode", "test"},
    },
    "desktop_automation": {
        "tools": {"computer_control", "desktop_control", "open_app"},
        "keywords": {"open app", "launch", "start app", "click", "type", "keyboard", "mouse", "screenshot", "window", "desktop", "vs code", "vscode", "inspect"},
    },
    "system_control": {
        "tools": {"computer_settings", "system_monitor", "background_monitor"},
        "keywords": {"volume", "brightness", "wifi", "battery", "sound", "mute", "cpu", "ram", "gpu", "performance", "metric", "setting"},
    },
    "communication": {
        "tools": {"send_message"},
        "keywords": {"message", "whatsapp", "text user", "send message", "chat", "send msg"},
    },
    "media": {
        "tools": {"youtube_video"},
        "keywords": {"youtube", "video", "play music", "play song", "track", "audio"},
    },
    "reminders": {
        "tools": {"reminder"},
        "keywords": {"reminder", "remind", "timer", "schedule", "alarm", "alert"},
    },
}

CORE_FALLBACK_TOOLS: Set[str] = {"file_controller", "web_search", "code_helper", "browser_control"}


class ToolRouter:
    """
    Deterministically routes user requests to relevant capability tool groups.
    Reduces prompt payload size without making extra LLM calls.
    """

    def __init__(self, action_registry: Optional[Any] = None) -> None:
        self.action_registry = action_registry

    def route_tool_names(self, user_request: str) -> Set[str]:
        """
        Determine relevant tool names for user_request using deterministic rule matching.

        Args:
            user_request: User request string.

        Returns:
            Set of tool names deemed relevant.
        """
        if not user_request or not user_request.strip():
            return set(CORE_FALLBACK_TOOLS)

        req_lower = user_request.lower()
        selected_tools: Set[str] = set()

        # Check for explicit tool name mentions in user prompt
        all_known_tools = set()
        for group in TOOL_CAPABILITY_GROUPS.values():
            all_known_tools.update(group["tools"])

        for tname in all_known_tools:
            if tname.lower() in req_lower:
                selected_tools.add(tname)

        # Keyword matching against capability groups
        for group_name, group_data in TOOL_CAPABILITY_GROUPS.items():
            keywords = group_data["keywords"]
            if any(kw in req_lower for kw in keywords):
                selected_tools.update(group_data["tools"])

        # Fallback mechanism if router is uncertain or prompt is ambiguous
        if not selected_tools:
            selected_tools = set(CORE_FALLBACK_TOOLS)

        # Always include general helper tool if no tool matched
        selected_tools.add("general")
        return selected_tools

    def route_declarations(
        self,
        user_request: str,
        action_registry: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """
        Get filtered tool declaration dicts from ActionRegistry matching selected tools.

        Args:
            user_request: User request string.
            action_registry: ActionRegistry instance (falls back to self.action_registry).

        Returns:
            List of tool declaration dictionaries.
        """
        registry = action_registry or self.action_registry
        selected_names = self.route_tool_names(user_request)

        if registry is None:
            return []

        decls: List[Dict[str, Any]] = []
        if hasattr(registry, "get_tool_declarations"):
            all_decls = registry.get_tool_declarations()
        elif isinstance(registry, list):
            all_decls = registry
        else:
            all_decls = []

        for tool in all_decls:
            if isinstance(tool, dict):
                name = tool.get("name")
                if name in selected_names:
                    decls.append(tool)

        return decls

    def measure_prompt_reduction(
        self,
        user_request: str,
        action_registry: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Measure character and estimated token reduction comparing full vs routed tool declarations.

        Returns:
            Dict containing prompt size stats before and after tool routing.
        """
        registry = action_registry or self.action_registry
        if not registry or not hasattr(registry, "get_tool_declarations"):
            return {
                "user_request": user_request,
                "full_tool_count": 0,
                "routed_tool_count": 0,
                "full_char_length": 0,
                "routed_char_length": 0,
                "char_reduction_percent": 0.0,
            }

        all_decls = registry.get_tool_declarations()
        full_text = "\n".join([f"- {t.get('name')}: {t.get('description', '')}" for t in all_decls if isinstance(t, dict)])
        
        routed_decls = self.route_declarations(user_request, registry)
        routed_text = "\n".join([f"- {t.get('name')}: {t.get('description', '')}" for t in routed_decls if isinstance(t, dict)])

        full_len = len(full_text)
        routed_len = len(routed_text)
        reduction_pct = round(((full_len - routed_len) / full_len * 100), 2) if full_len > 0 else 0.0

        return {
            "user_request": user_request,
            "full_tool_count": len(all_decls),
            "routed_tool_count": len(routed_decls),
            "routed_tool_names": [t.get("name") for t in routed_decls if isinstance(t, dict)],
            "full_char_length": full_len,
            "routed_char_length": routed_len,
            "char_reduction_percent": reduction_pct,
        }
