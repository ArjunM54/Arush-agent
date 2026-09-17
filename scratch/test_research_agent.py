import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import (
    ResearchAgent,
    ResearchReport,
    SourceClaim,
    ResearchPhase,
    ClaimCategory,
)
from core.action_loader import discover_actions


def test_research_agent():
    print("=== Testing Specialized Research Agent Component ===")

    # Load discoverable actions (including web_search)
    actions_dir = Path(__file__).resolve().parent.parent / "actions"
    registry = discover_actions(actions_dir, logger=lambda m: None)

    research_agent = ResearchAgent(action_registry=registry)

    topic = "Quantum Computing Breakthroughs 2026"

    # ---------------------------------------------------------
    # Test 1: Define Questions & Create Search Plan
    # ---------------------------------------------------------
    print("\n--- Test 1: Question Definition & Search Plan ---")

    questions = research_agent.define_questions(topic)
    assert len(questions) >= 3, f"Expected at least 3 research questions, got {len(questions)}"
    print(f"Generated {len(questions)} research questions:")
    for q in questions:
        print(f"  • {q}")

    search_plan = research_agent.create_search_plan(topic, questions)
    assert len(search_plan) >= 3, f"Expected at least 3 search queries, got {len(search_plan)}"
    print(f"Created search plan with {len(search_plan)} queries.")
    print("PASS: Question definition and search plan verified!")

    # ---------------------------------------------------------
    # Test 2: Source Collection & Extraction with Mock Data
    # ---------------------------------------------------------
    print("\n--- Test 2: Extraction & Categorization (Facts, Inferences, Uncertainties) ---")

    mock_sources = [
        {
            "query": topic,
            "mode": "research",
            "raw_output": (
                "IBM announced a 1,000+ qubit processor in 2026.\n"
                "Source: https://example.com/ibm-quantum-2026\n"
                "This development suggests quantum advantage is rapidly approaching for chemical simulation.\n"
                "It remains disputed whether current error mitigation works at practical scale.\n"
            ),
        }
    ]

    claims = research_agent.extract_and_cross_check(mock_sources)
    assert "sourced_facts" in claims
    assert "inferences" in claims
    assert "uncertainties" in claims

    facts = claims["sourced_facts"]
    inferences = claims["inferences"]
    uncertainties = claims["uncertainties"]

    assert len(facts) > 0, "Expected at least 1 sourced fact"
    assert len(inferences) > 0, "Expected at least 1 inference"
    assert len(uncertainties) > 0, "Expected at least 1 uncertainty"

    print(f"Extracted: {len(facts)} Facts, {len(inferences)} Inferences, {len(uncertainties)} Uncertainties")
    print(f"Fact Claim: '{facts[0].claim}' (Source: {facts[0].source})")
    print(f"Inference Claim: '{inferences[0].claim}'")
    print(f"Uncertainty Claim: '{uncertainties[0].claim}'")
    print("PASS: Source claim extraction and categorization verified!")

    # ---------------------------------------------------------
    # Test 3: Report Synthesis & Verification
    # ---------------------------------------------------------
    print("\n--- Test 3: Report Synthesis & Verification ---")

    report: ResearchReport = research_agent.synthesize_report(
        topic=topic,
        claims=claims,
        collected_sources=mock_sources,
        start_time=0.0
    )

    verified = research_agent.verify_report(report)
    assert verified is True, "Report verification failed"
    assert report.verified is True

    md_output = report.to_markdown()
    assert "# Research Report:" in md_output
    assert "## 📌 Sourced Facts" in md_output
    assert "## 💡 Inferences & Logical Deductions" in md_output
    assert "## ⚠️ Uncertainties & Conflicting Claims" in md_output
    assert "## 🔗 Sources Collected" in md_output

    print("PASS: Report synthesis, verification, and markdown formatting verified!")

    # ---------------------------------------------------------
    # Test 4: End-to-End Autonomous Research Task Execution
    # ---------------------------------------------------------
    print("\n--- Test 4: End-to-End Research Task Execution ---")

    test_topic = "Autonomous AI Agents in Software Engineering"
    full_report: ResearchReport = research_agent.run_research_task(test_topic)

    assert full_report.topic == test_topic
    assert full_report.verified is True
    assert full_report.summary != ""
    assert isinstance(full_report.to_markdown(), str)

    print(f"Research task completed cleanly in {full_report.execution_time:.3f}s!")
    print(f"Report Summary: {full_report.summary}")

    print("\n=== All Research Agent Tests Passed Successfully! ===")


if __name__ == "__main__":
    test_research_agent()
