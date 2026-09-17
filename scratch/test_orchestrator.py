import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import AgentOrchestrator, TaskState, TaskStatus, OrchestratorResult
from core.action_loader import discover_actions, ActionRecord, ActionRegistry


def test_orchestrator():
    print("=== Testing Agent Orchestrator Component ===")

    # Load discoverable actions
    actions_dir = Path(__file__).resolve().parent.parent / "actions"
    registry = discover_actions(actions_dir, logger=lambda m: None)

    orchestrator = AgentOrchestrator(action_registry=registry, max_iterations=10)

    # ---------------------------------------------------------
    # 1. Simple successful task
    # ---------------------------------------------------------
    print("\n--- Test 1: Simple Successful Task ---")
    tmp_path1 = Path(tempfile.gettempdir()) / "test_orch_step1.txt"
    if tmp_path1.exists():
        tmp_path1.unlink()

    task1 = TaskState(user_request="Create temp file 1")
    task1.add_step({
        "step_id": "step_1",
        "description": "Create temp file 1",
        "suggested_tool": "file_controller",
        "parameters": {"action": "create_file", "path": str(tmp_path1), "content": "test content 1"},
        "dependencies": [],
        "status": "PENDING"
    })

    res1: OrchestratorResult = orchestrator.run_task("Create temp file 1", task_state=task1)
    print(f"Result 1 Status: {res1.status}, Completed: {len(res1.completed_steps)}, Time: {res1.execution_time}s")

    assert res1.status == "COMPLETED", f"Test 1 failed: Expected COMPLETED, got {res1.status}"
    assert len(res1.completed_steps) == 1
    assert tmp_path1.exists(), "Test 1 failed: File was not created on disk"
    tmp_path1.unlink()
    print("PASS: Simple successful task verified!")

    # ---------------------------------------------------------
    # 2. Multi-step task with dependency ordering
    # ---------------------------------------------------------
    print("\n--- Test 2: Multi-step Task ---")
    tmp_path2_a = Path(tempfile.gettempdir()) / "test_orch_multi_a.txt"
    tmp_path2_b = Path(tempfile.gettempdir()) / "test_orch_multi_b.txt"
    for p in (tmp_path2_a, tmp_path2_b):
        if p.exists():
            p.unlink()

    task2 = TaskState(user_request="Create multi-step files")
    task2.add_step({
        "step_id": "step_1",
        "description": "Create first file",
        "suggested_tool": "file_controller",
        "parameters": {"action": "create_file", "path": str(tmp_path2_a), "content": "multi a"},
        "dependencies": [],
        "status": "PENDING"
    })
    task2.add_step({
        "step_id": "step_2",
        "description": "Create second file after first",
        "suggested_tool": "file_controller",
        "parameters": {"action": "create_file", "path": str(tmp_path2_b), "content": "multi b"},
        "dependencies": ["step_1"],
        "status": "PENDING"
    })

    res2: OrchestratorResult = orchestrator.run_task("Create multi-step files", task_state=task2)
    print(f"Result 2 Status: {res2.status}, Completed: {len(res2.completed_steps)}")

    assert res2.status == "COMPLETED"
    assert len(res2.completed_steps) == 2
    assert res2.completed_steps[0]["step_id"] == "step_1"
    assert res2.completed_steps[1]["step_id"] == "step_2"
    assert tmp_path2_a.exists() and tmp_path2_b.exists()
    tmp_path2_a.unlink()
    tmp_path2_b.unlink()
    print("PASS: Multi-step task verified!")

    # ---------------------------------------------------------
    # 3. Tool failure
    # ---------------------------------------------------------
    print("\n--- Test 3: Tool Failure ---")
    task3 = TaskState(user_request="Failing tool task")
    task3.add_step({
        "step_id": "step_fail",
        "description": "Call missing tool",
        "suggested_tool": "invalid_missing_tool",
        "parameters": {},
        "dependencies": [],
        "status": "PENDING"
    })

    orchestrator3 = AgentOrchestrator(action_registry=registry, max_retries_per_step=0)
    orchestrator3._replan = lambda state, reason: False  # Disable LLM replan call for pure tool failure test

    res3: OrchestratorResult = orchestrator3.run_task("Failing tool task", task_state=task3)
    print(f"Result 3 Status: {res3.status}, Failed: {len(res3.failed_steps)}, Errors: {len(res3.errors)}")

    assert res3.status == "FAILED"
    assert len(res3.failed_steps) >= 1
    assert len(res3.errors) > 0
    print("PASS: Tool failure recorded and task marked FAILED!")

    # ---------------------------------------------------------
    # 4. Retry mechanism
    # ---------------------------------------------------------
    print("\n--- Test 4: Retry Mechanism ---")
    attempts = {"count": 0}
    tmp_path4 = Path(tempfile.gettempdir()) / "test_orch_retry.txt"
    if tmp_path4.exists():
        tmp_path4.unlink()

    def flaky_handler(parameters, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return "Error: Temporary network timeout"
        # On attempt 2, create the file so verifier sees observable success
        tmp_path4.write_text("retry success content")
        return f"Created file at {tmp_path4}"

    flaky_rec = ActionRecord(
        name="flaky_tool",
        description="Flaky tool that fails on first attempt",
        handler=flaky_handler,
        valid=True
    )
    custom_actions = dict(registry._actions)
    custom_actions["flaky_tool"] = flaky_rec
    retry_registry = ActionRegistry(custom_actions, logger=lambda m: None)

    retry_orch = AgentOrchestrator(action_registry=retry_registry, max_retries_per_step=2)
    retry_orch._replan = lambda state, reason: False  # Do not replan during retry test

    task4 = TaskState(user_request="Flaky task")
    task4.add_step({
        "step_id": "step_flaky",
        "description": "Run flaky step",
        "suggested_tool": "flaky_tool",
        "parameters": {"path": str(tmp_path4)},
        "dependencies": [],
        "status": "PENDING"
    })

    res4: OrchestratorResult = retry_orch.run_task("Flaky task", task_state=task4)
    print(f"Result 4 Status: {res4.status}, Total Attempts: {attempts['count']}")

    assert attempts["count"] == 2, f"Expected 2 attempts, got {attempts['count']}"
    assert res4.status == "COMPLETED"
    assert len(res4.completed_steps) == 1
    if tmp_path4.exists():
        tmp_path4.unlink()
    print("PASS: Retry mechanism successfully recovered step!")

    # ---------------------------------------------------------
    # 5. Replanning
    # ---------------------------------------------------------
    print("\n--- Test 5: Replanning ---")
    task5 = TaskState(user_request="Re-plan test task")
    tmp_path5_a = Path(tempfile.gettempdir()) / "test_orch_replan_a.txt"
    tmp_path5_b = Path(tempfile.gettempdir()) / "test_orch_replan_b.txt"
    for p in (tmp_path5_a, tmp_path5_b):
        if p.exists():
            p.unlink()

    # Step 1 succeeds, Step 2 fails permanently, triggering replan
    task5.add_step({
        "step_id": "step_1",
        "description": "Create step 1 file",
        "suggested_tool": "file_controller",
        "parameters": {"action": "create_file", "path": str(tmp_path5_a), "content": "step 1"},
        "dependencies": [],
        "status": "PENDING"
    })
    task5.add_step({
        "step_id": "step_2_bad",
        "description": "Call non-existent tool",
        "suggested_tool": "non_existent_tool_xyz",
        "parameters": {},
        "dependencies": ["step_1"],
        "status": "PENDING"
    })

    # Mock planner for replan to return a valid replacement step 3
    def mock_replan_plan(user_request, task_state=None):
        ts = task_state or TaskState(user_request=user_request)
        ts.plan = [{
            "step_id": "step_3_replacement",
            "description": "Create replacement file",
            "suggested_tool": "file_controller",
            "parameters": {"action": "create_file", "path": str(tmp_path5_b), "content": "step 3"},
            "dependencies": [],
            "status": "PENDING"
        }]
        return ts

    orchestrator_replan = AgentOrchestrator(action_registry=registry, max_retries_per_step=0)
    orchestrator_replan.planner.create_plan = mock_replan_plan

    res5: OrchestratorResult = orchestrator_replan.run_task("Re-plan test task", task_state=task5)
    print(f"Result 5 Status: {res5.status}, Completed steps count: {len(res5.completed_steps)}")

    assert res5.status == "COMPLETED"
    # Step 1 was preserved, and replacement step 3 succeeded
    completed_ids = [s["step_id"] for s in res5.completed_steps]
    assert "step_1" in completed_ids, "Completed step_1 should be preserved"
    assert "step_3_replacement" in completed_ids, "Replacement step 3 should be executed"
    assert tmp_path5_a.exists() and tmp_path5_b.exists()
    tmp_path5_a.unlink()
    tmp_path5_b.unlink()
    print("PASS: Replanning preserved step_1 and executed replacement step successfully!")

    # ---------------------------------------------------------
    # 6. Maximum iteration protection
    # ---------------------------------------------------------
    print("\n--- Test 6: Maximum Iteration Protection ---")
    task6 = TaskState(user_request="Infinite task protection test", max_iterations=2)
    # Add 5 sequential steps
    for i in range(1, 6):
        tmp_p = Path(tempfile.gettempdir()) / f"test_orch_max_iter_{i}.txt"
        deps = [f"step_{i-1}"] if i > 1 else []
        task6.add_step({
            "step_id": f"step_{i}",
            "description": f"Step {i}",
            "suggested_tool": "file_controller",
            "parameters": {"action": "create_file", "path": str(tmp_p), "content": str(i)},
            "dependencies": deps,
            "status": "PENDING"
        })


    orch_max_iter = AgentOrchestrator(action_registry=registry, max_iterations=2)
    res6: OrchestratorResult = orch_max_iter.run_task("Infinite task protection test", task_state=task6)
    print(f"Result 6 Status: {res6.status}, Completed steps: {len(res6.completed_steps)}, Errors: {res6.errors}")

    assert res6.status == "FAILED"
    assert any("Maximum iteration limit" in err for err in res6.errors)
    print("PASS: Maximum iteration limit protection prevented infinite loop!")

    print("\n=== All 6 Orchestrator assertions PASSED ===")


if __name__ == "__main__":
    test_orchestrator()
