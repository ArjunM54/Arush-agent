import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import (
    SpecialistDelegator,
    DelegatedTask,
    SpecialistType,
)
from core.action_loader import discover_actions


def test_specialist_delegator():
    print("=== Testing Controlled Specialist Delegation Component ===")

    actions_dir = Path(__file__).resolve().parent.parent / "actions"
    registry = discover_actions(actions_dir, logger=lambda m: None)

    delegator = SpecialistDelegator(action_registry=registry, max_delegation_depth=2)

    parent_id = "orch_task_main_001"

    # ---------------------------------------------------------
    # Test 1: Specialist Selection
    # ---------------------------------------------------------
    print("\n--- Test 1: Specialist Selection Routing ---")

    spec_dev = delegator.select_specialist("Modify python script and fix bug in AST")
    assert spec_dev == SpecialistType.DEVELOPER, f"Expected DEVELOPER, got {spec_dev}"

    spec_res = delegator.select_specialist("Research AI agent frameworks and compare items")
    assert spec_res == SpecialistType.RESEARCH, f"Expected RESEARCH, got {spec_res}"

    spec_file = delegator.select_specialist("Save report markdown file to disk")
    assert spec_file == SpecialistType.FILE, f"Expected FILE, got {spec_file}"

    print("PASS: Specialist selection routing verified!")

    # ---------------------------------------------------------
    # Test 2: Task Metadata Tracking
    # ---------------------------------------------------------
    print("\n--- Test 2: Task Metadata Tracking ---")

    task1: DelegatedTask = delegator.delegate_task(
        parent_task_id=parent_id,
        specialist_type=SpecialistType.RESEARCH,
        objective="Research Python AI Frameworks",
        input_data={"topic": "Python AI Frameworks"}
    )

    assert task1.task_id.startswith("sub_")
    assert task1.parent_task_id == parent_id
    assert task1.specialist_type == SpecialistType.RESEARCH
    assert task1.status == "COMPLETED"
    assert "summary" in task1.output_data
    assert task1.execution_time > 0.0
    print(f"DelegatedTask Metadata Verified: Task ID={task1.task_id}, Status={task1.status}")
    print("PASS: Task metadata tracking verified!")

    # ---------------------------------------------------------
    # Test 3: Recursion Loop & Depth Protection
    # ---------------------------------------------------------
    print("\n--- Test 3: Recursion Loop & Depth Protection ---")

    # Exceeded depth test
    deep_task: DelegatedTask = delegator.delegate_task(
        parent_task_id=parent_id,
        specialist_type=SpecialistType.DEVELOPER,
        objective="Nested deep call",
        delegation_depth=3  # max_delegation_depth is set to 2
    )

    assert deep_task.status == "FAILED"
    assert len(deep_task.errors) > 0
    assert "Exceeded maximum delegation depth" in deep_task.errors[0]
    print(f"Depth limit enforced correctly: '{deep_task.errors[0]}'")

    # Active chain recursion loop test
    delegator.active_chain.append(SpecialistType.DEVELOPER)
    loop_task: DelegatedTask = delegator.delegate_task(
        parent_task_id=parent_id,
        specialist_type=SpecialistType.DEVELOPER,
        objective="Recursive call to same specialist",
        delegation_depth=1
    )
    delegator.active_chain.remove(SpecialistType.DEVELOPER)

    assert loop_task.status == "FAILED"
    assert len(loop_task.errors) > 0
    assert "Recursive delegation loop detected" in loop_task.errors[0]
    print(f"Recursion loop prevented correctly: '{loop_task.errors[0]}'")
    print("PASS: Recursion protection verified!")

    # ---------------------------------------------------------
    # Test 4: Multi-Specialist Task Pipeline Execution
    # ---------------------------------------------------------
    print("\n--- Test 4: Multi-Specialist Task Pipeline ---")
    temp_dir = Path(tempfile.gettempdir()) / "delegator_test"
    temp_dir.mkdir(parents=True, exist_ok=True)
    demo_file = temp_dir / "agent_demo.py"
    report_file = temp_dir / "research_report.md"

    # Step 1: ResearchAgent
    res_task = delegator.delegate_task(
        parent_task_id=parent_id,
        specialist_type=SpecialistType.RESEARCH,
        objective="Research AI agent frameworks",
        input_data={"topic": "AI agent frameworks"}
    )
    assert res_task.status == "COMPLETED"

    # Step 2: DeveloperAgent -> create Python demo
    dev_task = delegator.delegate_task(
        parent_task_id=parent_id,
        specialist_type=SpecialistType.DEVELOPER,
        objective="Create agent demo script",
        input_data={
            "target_file": str(demo_file),
            "new_content": "def run_demo():\n    print('Agent Demo Running')\n\nif __name__ == '__main__':\n    run_demo()\n"
        }
    )
    assert dev_task.status == "COMPLETED"
    assert demo_file.exists()

    # Step 3: FileAgent -> save report
    report_content = res_task.output_data.get("markdown", "# Default Report")
    file_task = delegator.delegate_task(
        parent_task_id=parent_id,
        specialist_type=SpecialistType.FILE,
        objective="Save report markdown",
        input_data={
            "action": "create_file",
            "path": str(report_file),
            "content": report_content
        }
    )
    assert file_task.status == "COMPLETED"
    assert report_file.exists()

    print(f"Multi-specialist pipeline completed: {len(delegator.delegated_tasks)} total tasks tracked.")

    # Cleanup
    for f in temp_dir.glob("*"):
        f.unlink()
    temp_dir.rmdir()

    print("\n=== All Specialist Delegator Tests Passed Successfully! ===")


if __name__ == "__main__":
    test_specialist_delegator()
