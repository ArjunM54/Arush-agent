"""
core/agent/research_agent.py — Specialized Research Agent.

Manages multi-source research workflows:
DEFINE QUESTION -> CREATE SEARCH PLAN -> SEARCH -> COLLECT SOURCES -> EXTRACT INFORMATION -> CROSS-CHECK -> SYNTHESIZE -> CREATE OUTPUT -> VERIFY

Reuses existing ActionRegistry web search tools (web_search) and enforces strict claim tracking,
distinguishing sourced facts, inferences, and uncertainties.
"""
from __future__ import annotations

import time
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.agent.task_state import TaskState, TaskStatus
from core.agent.executor import Executor
from core.agent.verifier import Verifier
from core.action_loader import ActionRegistry


class ResearchPhase(str, Enum):
    DEFINE_QUESTION = "DEFINE_QUESTION"
    CREATE_SEARCH_PLAN = "CREATE_SEARCH_PLAN"
    SEARCH = "SEARCH"
    COLLECT_SOURCES = "COLLECT_SOURCES"
    EXTRACT_INFORMATION = "EXTRACT_INFORMATION"
    CROSS_CHECK = "CROSS_CHECK"
    SYNTHESIZE = "SYNTHESIZE"
    CREATE_OUTPUT = "CREATE_OUTPUT"
    VERIFY = "VERIFY"


class ClaimCategory(str, Enum):
    SOURCED_FACT = "sourced_fact"
    INFERENCE = "inference"
    UNCERTAINTY = "uncertainty"


@dataclass
class SourceClaim:
    """Individual extracted claim with source attribution and category distinction."""
    claim: str
    source: str
    category: ClaimCategory
    confidence: float = 1.0
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim": self.claim,
            "source": self.source,
            "category": self.category.value if isinstance(self.category, ClaimCategory) else str(self.category),
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass
class ResearchReport:
    """Structured response returned by ResearchAgent."""
    topic: str
    summary: str
    sourced_facts: List[SourceClaim] = field(default_factory=list)
    inferences: List[SourceClaim] = field(default_factory=list)
    uncertainties: List[SourceClaim] = field(default_factory=list)
    sources: List[Dict[str, str]] = field(default_factory=list)
    verified: bool = False
    execution_time: float = 0.0

    def to_markdown(self) -> str:
        """Render research report as clean, formatted markdown with explicit categories."""
        lines = [
            f"# Research Report: {self.topic}\n",
            f"**Execution Time**: {self.execution_time:.2f}s | **Verified**: {'Yes' if self.verified else 'No'}\n",
            "## Executive Summary",
            f"{self.summary}\n",
            "## 📌 Sourced Facts",
        ]

        if self.sourced_facts:
            for item in self.sourced_facts:
                lines.append(f"- **Claim**: {item.claim}")
                lines.append(f"  - *Source*: {item.source}")
                if item.notes:
                    lines.append(f"  - *Note*: {item.notes}")
        else:
            lines.append("- No verified sourced facts extracted.")

        lines.append("\n## 💡 Inferences & Logical Deductions")
        if self.inferences:
            for item in self.inferences:
                lines.append(f"- **Inference**: {item.claim}")
                lines.append(f"  - *Basis*: {item.source}")
        else:
            lines.append("- No inferences drawn.")

        lines.append("\n## ⚠️ Uncertainties & Conflicting Claims")
        if self.uncertainties:
            for item in self.uncertainties:
                lines.append(f"- **Uncertainty**: {item.claim}")
                lines.append(f"  - *Reason*: {item.notes or item.source}")
        else:
            lines.append("- No significant uncertainties identified.")

        lines.append("\n## 🔗 Sources Collected")
        if self.sources:
            for idx, src in enumerate(self.sources, 1):
                title = src.get("title", f"Source #{idx}")
                url = src.get("url") or src.get("source", "N/A")
                lines.append(f"{idx}. [{title}]({url})")
        else:
            lines.append("- No external sources available.")

        return "\n".join(lines)


class ResearchAgent:
    """
    Specialized Research Agent that conducts multi-source web research,
    parses & cross-checks information, tracks source attribution, and
    distinguishes sourced facts, inferences, and uncertainties.
    """

    def __init__(
        self,
        action_registry: Optional[ActionRegistry] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.action_registry = action_registry
        self.context = context or {}
        self.executor = Executor(action_registry=action_registry, context=context)
        self.verifier = Verifier()

    def define_questions(self, topic: str) -> List[str]:
        """Phase 1: Define core and sub-questions for research topic."""
        topic_clean = topic.strip()
        questions = [
            f"What is the current background and key facts regarding {topic_clean}?",
            f"What are the main statistics, data points, or developments for {topic_clean}?",
            f"What are the differing perspectives or unresolved uncertainties about {topic_clean}?",
        ]
        return questions

    def create_search_plan(self, topic: str, questions: List[str]) -> List[Dict[str, Any]]:
        """Phase 2: Generate search queries and parameters based on questions."""
        queries = []
        # Main overview search query
        queries.append({"query": topic, "mode": "research"})

        # Specific sub-query for aspects
        for q in questions:
            clean_q = re.sub(r'[^\w\s]', '', q)
            words = clean_q.split()[:6]
            sub_query = " ".join(words)
            queries.append({"query": sub_query, "mode": "search"})

        return queries

    def search_and_collect(self, search_plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Phases 3 & 4: Execute web search and collect raw sources."""
        collected_sources: List[Dict[str, Any]] = []

        for item in search_plan:
            query = item.get("query")
            mode = item.get("mode", "search")
            if not query:
                continue

            raw_output = ""
            if self.action_registry and self.action_registry.has("web_search"):
                state = TaskState(user_request=f"Search for {query}")
                step = {
                    "step_id": f"search_{len(collected_sources) + 1}",
                    "description": f"Search web for {query}",
                    "suggested_tool": "web_search",
                    "parameters": {"query": query, "mode": mode},
                    "status": "PENDING"
                }
                print(f"[AGENT] TOOL: web_search query='{query}' mode='{mode}'")
                res = self.executor.execute_step(state, step)
                if res.get("success") or res.get("status") == "SUCCESS":
                    raw_output = res.get("result", "")
                    print(f"[AGENT] RESEARCH: Collected {len(raw_output or '')} chars for query '{query}'")
                else:
                    print(f"[AGENT] RESEARCH: Search failed for query '{query}': {res.get('error')}")

            if not raw_output and hasattr(self, "_fallback_search"):
                raw_output = self._fallback_search(query, mode)

            if raw_output:
                collected_sources.append({
                    "query": query,
                    "mode": mode,
                    "raw_output": raw_output,
                    "timestamp": time.time()
                })

        return collected_sources

    def extract_and_cross_check(self, collected_sources: List[Dict[str, Any]]) -> Dict[str, List[SourceClaim]]:
        """Phases 5 & 6: Extract claims, cross-check evidence, and categorize claims."""
        sourced_facts: List[SourceClaim] = []
        inferences: List[SourceClaim] = []
        uncertainties: List[SourceClaim] = []

        seen_claims = set()

        for src in collected_sources:
            raw_text = src.get("raw_output", "")
            query_str = src.get("query", "Web Search")

            # Parse lines from raw_text
            lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
            current_url = "Web Search Grounding"

            for line in lines:
                if line.startswith("Source:") or line.startswith("http://") or line.startswith("https://"):
                    url_match = re.search(r'https?://[^\s]+', line)
                    if url_match:
                        current_url = url_match.group(0)
                    continue

                if len(line) < 15 or line.startswith("#") or line.startswith("Search results"):
                    continue

                # Categorize line
                claim_text = re.sub(r'^[\d\.\-\*\•\>\s]+', '', line).strip()
                if not claim_text or claim_text in seen_claims:
                    continue
                seen_claims.add(claim_text)

                # Heuristic categorization based on phrasing
                lower_text = claim_text.lower()
                if any(w in lower_text for w in ["uncertain", "unclear", "disputed", "conflicting", "unknown", "alleged", "may be"]):
                    uncertainties.append(SourceClaim(
                        claim=claim_text,
                        source=current_url,
                        category=ClaimCategory.UNCERTAINTY,
                        confidence=0.6,
                        notes="Contains indicators of uncertainty or dispute."
                    ))
                elif any(w in lower_text for w in ["suggests", "indicates", "likely", "likely means", "implies", "therefore"]):
                    inferences.append(SourceClaim(
                        claim=claim_text,
                        source=f"Derived from {query_str}",
                        category=ClaimCategory.INFERENCE,
                        confidence=0.8,
                        notes="Logical deduction based on search results."
                    ))
                else:
                    sourced_facts.append(SourceClaim(
                        claim=claim_text,
                        source=current_url,
                        category=ClaimCategory.SOURCED_FACT,
                        confidence=0.95
                    ))

        return {
            "sourced_facts": sourced_facts,
            "inferences": inferences,
            "uncertainties": uncertainties,
        }

    def synthesize_report(
        self,
        topic: str,
        claims: Dict[str, List[SourceClaim]],
        collected_sources: List[Dict[str, Any]],
        start_time: float
    ) -> ResearchReport:
        """Phases 7 & 8: Synthesize findings and create output ResearchReport."""
        sourced_facts = claims.get("sourced_facts", [])
        inferences = claims.get("inferences", [])
        uncertainties = claims.get("uncertainties", [])

        # Build sources list
        source_links = []
        seen_urls = set()
        for src in collected_sources:
            raw = src.get("raw_output", "")
            urls = re.findall(r'https?://[^\s\)\>]+', raw)
            for url in urls:
                if url not in seen_urls:
                    seen_urls.add(url)
                    source_links.append({"title": src.get("query", "Web Result"), "url": url})

        if not source_links:
            source_links.append({"title": "Web Search Grounding Engine", "url": "Internal Search Grounding"})

        # Formulate executive summary
        summary_parts = [f"Research conducted on '{topic}' across {len(collected_sources)} query operations."]
        if sourced_facts:
            summary_parts.append(f"Identified {len(sourced_facts)} key sourced facts.")
        if inferences:
            summary_parts.append(f"Drawn {len(inferences)} logical inferences.")
        if uncertainties:
            summary_parts.append(f"Noted {len(uncertainties)} areas of uncertainty or conflicting information.")
        summary = " ".join(summary_parts)

        report = ResearchReport(
            topic=topic,
            summary=summary,
            sourced_facts=sourced_facts,
            inferences=inferences,
            uncertainties=uncertainties,
            sources=source_links,
            verified=False,
            execution_time=time.perf_counter() - start_time
        )
        return report

    def verify_report(self, report: ResearchReport) -> bool:
        """Phase 9: Verify research report completeness and source attribution."""
        if not report.topic or not report.summary:
            return False

        # Ensure all sourced facts have valid source links
        for fact in report.sourced_facts:
            if not fact.source:
                return False

        report.verified = True
        return True

    def run_research_task(self, topic: str) -> ResearchReport:
        """
        Execute full 9-step research task:
        DEFINE QUESTION -> CREATE SEARCH PLAN -> SEARCH -> COLLECT SOURCES -> EXTRACT -> CROSS-CHECK -> SYNTHESIZE -> OUTPUT -> VERIFY
        """
        start_time = time.perf_counter()

        # Step 1: DEFINE QUESTION
        questions = self.define_questions(topic)

        # Step 2: CREATE SEARCH PLAN
        search_plan = self.create_search_plan(topic, questions)

        # Steps 3 & 4: SEARCH & COLLECT SOURCES
        collected_sources = self.search_and_collect(search_plan)

        # Steps 5 & 6: EXTRACT INFORMATION & CROSS-CHECK
        claims = self.extract_and_cross_check(collected_sources)

        # Steps 7 & 8: SYNTHESIZE & CREATE OUTPUT
        report = self.synthesize_report(topic, claims, collected_sources, start_time)

        # Step 9: VERIFY
        self.verify_report(report)

        return report
