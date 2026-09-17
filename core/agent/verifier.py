"""
core/agent/verifier.py — Verification Layer for autonomous agent steps.

Determines whether an executed plan step actually succeeded using concrete,
observable evidence (e.g. file existence, syntax validity, exit codes).
Employs a conservative verification policy: insufficient evidence yields success=False.
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class VerificationResult:
    """Structured result of step verification."""
    success: bool
    confidence: float  # 0.0 to 1.0
    evidence: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    retryable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert VerificationResult to a JSON-serializable dictionary."""
        return {
            "success": self.success,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "reason": self.reason,
            "retryable": self.retryable,
        }


class Verifier:
    """
    Verifies step execution using concrete, observable evidence.
    Refuses to trust text claims alone if observable evidence is missing or contradicts success.
    """

    def verify_step(
        self,
        step: Dict[str, Any],
        execution_result: Dict[str, Any],
        task_state: Optional[Any] = None
    ) -> VerificationResult:
        """
        Verify whether an executed step actually succeeded based on evidence.

        Args:
            step: Step dictionary (description, suggested_tool, parameters, etc.)
            execution_result: Return dict from Executor (success, tool, result, error, etc.)
            task_state: Optional TaskState context.

        Returns:
            VerificationResult instance.
        """
        # 1. Check if execution itself failed or threw an exception
        if not execution_result.get("success", False):
            error_text = str(execution_result.get("error") or "Step execution failed.")
            return VerificationResult(
                success=False,
                confidence=1.0,
                evidence={"execution_error": error_text},
                reason=f"Execution error: {error_text}",
                retryable=True
            )

        raw_result = execution_result.get("result")
        tool_name = execution_result.get("tool") or step.get("suggested_tool") or step.get("tool") or ""
        params = step.get("parameters") or step.get("tool_params") or {}

        # 2. Check for explicit error signals in tool output string
        if isinstance(raw_result, str):
            lower_res = raw_result.lower()
            failure_signals = [
                "error:", "failed:", "access denied", "permission denied",
                "could not", "crashed", "exception:", "not found",
                "invalid action", "unknown action", "please provide",
                "missing required", "traceback (most recent call last)"
            ]

            for signal in failure_signals:
                if signal in lower_res:
                    return VerificationResult(
                        success=False,
                        confidence=0.95,
                        evidence={"raw_result": raw_result, "matched_signal": signal},
                        reason=f"Tool output contains failure signal: '{signal}'",
                        retryable=True
                    )

        # 3. File / Code operation verification
        target_path = self._extract_path(params, raw_result)
        action_type = str(params.get("action", "")).lower()

        if target_path or tool_name in ("file_controller", "code_helper", "file_processor", "dev_agent"):
            file_res = self._verify_file_evidence(target_path, action_type, raw_result)
            if file_res is not None:
                return file_res

        # 4. Browser / Web operation verification
        if tool_name in ("browser_control", "web_search", "weather_report"):
            browser_res = self._verify_browser_evidence(tool_name, raw_result, params)
            if browser_res is not None:
                return browser_res

        # 5. Fallback check for observable system state or evidence
        # If no observable artifact or evidence exists, conservative verification policy rejects success
        return VerificationResult(
            success=False,
            confidence=0.0,
            evidence={"tool": tool_name, "raw_result": raw_result},
            reason="Insufficient observable evidence to verify step outcome.",
            retryable=True
        )

    def _extract_path(self, params: Dict[str, Any], raw_result: Any) -> Optional[Path]:
        """Extract path candidate from parameters or result string."""
        for key in ("path", "file", "filepath", "destination", "target_file", "filename"):
            val = params.get(key)
            if val and isinstance(val, str) and val.strip():
                try:
                    return Path(val.strip()).resolve()
                except Exception:
                    pass

        if isinstance(raw_result, str):
            # Look for Windows or Posix absolute paths in output string
            match = re.search(r'([a-zA-Z]:\\[^\s\n"\'<>]+|/[^\s\n"\'<>]+)', raw_result)
            if match:
                try:
                    return Path(match.group(1)).resolve()
                except Exception:
                    pass

        return None

    def _verify_file_evidence(
        self,
        path: Optional[Path],
        action_type: str,
        raw_result: Any
    ) -> Optional[VerificationResult]:
        """Verify file creation, modification, syntax, or deletion on disk."""
        if path is None:
            return None

        if action_type in ("delete", "remove"):
            if not path.exists():
                return VerificationResult(
                    success=True,
                    confidence=1.0,
                    evidence={"path": str(path), "deleted": True},
                    reason=f"Verified file '{path.name}' was successfully deleted.",
                    retryable=False
                )
            else:
                return VerificationResult(
                    success=False,
                    confidence=1.0,
                    evidence={"path": str(path), "deleted": False},
                    reason=f"File '{path.name}' still exists on disk after delete action.",
                    retryable=True
                )

        # For query actions (disk_usage, info, largest, find, list, read)
        if action_type in ("disk_usage", "info", "largest", "find", "list", "read"):
            if isinstance(raw_result, str) and len(raw_result.strip()) > 5:
                return VerificationResult(
                    success=True,
                    confidence=1.0,
                    evidence={"action": action_type, "result_preview": raw_result[:150]},
                    reason=f"Query action '{action_type}' produced valid metric/content payload.",
                    retryable=False
                )

        # For creation / write / delete actions
        if path.exists():

            size = path.stat().st_size if path.is_file() else 0
            evidence = {
                "path": str(path),
                "exists": True,
                "is_dir": path.is_dir(),
                "size_bytes": size
            }

            # If it's a python code file, test syntax parsing
            if path.is_file() and path.suffix == ".py":
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    ast.parse(content)
                    evidence["syntax_valid"] = True
                except Exception as syntax_err:
                    evidence["syntax_valid"] = False
                    evidence["syntax_error"] = str(syntax_err)
                    return VerificationResult(
                        success=False,
                        confidence=1.0,
                        evidence=evidence,
                        reason=f"Python file '{path.name}' has syntax errors: {syntax_err}",
                        retryable=True
                    )

            return VerificationResult(
                success=True,
                confidence=1.0,
                evidence=evidence,
                reason=f"Verified observable evidence for file/folder '{path.name}' on disk.",
                retryable=False
            )
        else:
            return VerificationResult(
                success=False,
                confidence=1.0,
                evidence={"path": str(path), "exists": False},
                reason=f"File or directory '{path}' does not exist on disk.",
                retryable=True
            )

    def _verify_browser_evidence(
        self,
        tool_name: str,
        raw_result: Any,
        params: Dict[str, Any]
    ) -> Optional[VerificationResult]:
        """Verify browser/web operations based on state or explicit observable output."""
        if not isinstance(raw_result, str):
            return None

        # Check if output confirms successful browser opening or search response with query
        if "opened in chrome" in raw_result.lower() or "showing the weather" in raw_result.lower():
            return VerificationResult(
                success=True,
                confidence=0.9,
                evidence={"tool": tool_name, "result_summary": raw_result[:100]},
                reason="Browser operation returned positive system state confirmation.",
                retryable=False
            )

        if "web_search" in tool_name and len(raw_result) > 50 and "search" in raw_result.lower():
            return VerificationResult(
                success=True,
                confidence=0.85,
                evidence={"tool": tool_name, "content_length": len(raw_result)},
                reason="Web search produced valid content result payload.",
                retryable=False
            )

        return None
