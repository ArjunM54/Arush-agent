import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import Executor, TaskState, TaskStatus
from core.action_loader import discover_actions


def test_executor():
    print("=== Testing Agent Executor Component ===")

    # 1. Discover existing actions from actions/ directory
    actions_dir = Path(__file__).resolve().parent.parent / "actions"
    registry = discover_actions(actions_dir, logger=lambda m: None)
    print(f"Discovered {len(registry.names())} active tools from actions/.")

    # 2. Instantiate Executor
    executor = Executor(action_registry=registry)

    # 3. Create a TaskState with a 2-step plan (step 2 depends on step 1)
    task_state = TaskState(
        user_request="Check system disk usage and process report",
        goal="Check system disk usage and process report"
    )

    step1 = {
        "step_id": "step_1",
        "description": "Check disk usage",
        "objective": "Get current disk usage metrics",
        "suggested_tool": "file_controller",
        "parameters": {"action": "disk_usage", "path": "documents"},
        "dependencies": [],
        "status": "PENDING"
    }

    step2 = {
        "step_id": "step_2",
        "description": "Process report",
        "objective": "Log completion",
        "suggested_tool": "file_controller",
        "parameters": {"action": "info", "path": "documents"},
        "dependencies": ["step_1"],
        "status": "PENDING"
    }

    task_state.add_step(step1)
    task_state.add_step(step2)

    # 4. Verify get_next_step identifies step_1 (step_2 blocked by dependency step_1)
    next_step = executor.get_next_step(task_state)
    assert next_step is not None, "get_next_step should return step_1"
    assert next_step["step_id"] == "step_1", f"Expected step_1, got {next_step['step_id']}"
    print(f"Next executable step correctly identified: {next_step['step_id']}")

    # 5. Execute step_1 using harmless action (file_controller disk_usage)
    print("\nExecuting step_1 with tool 'file_controller'...")
    res1 = executor.execute_step(task_state, step1)

    print(f"Step 1 execution output: {res1}")
    assert res1["success"] is True, f"Step 1 failed: {res1.get('error')}"
    assert res1["step_id"] == "step_1"
    assert res1["tool"] == "file_controller"
    assert step1["status"] == "COMPLETED"
    assert len(task_state.completed_steps) == 1
    assert task_state.completed_steps[0]["step_id"] == "step_1"
    assert len(task_state.tool_results) == 1
    assert task_state.tool_results[0]["tool"] == "file_controller"
    assert task_state.iteration_count == 1
    print("Step 1 successfully completed and state updated.")

    # 6. Now test dependency resolution: step_2 should now be executable since step_1 is completed
    next_step2 = executor.get_next_step(task_state)
    assert next_step2 is not None, "get_next_step should return step_2 now"
    assert next_step2["step_id"] == "step_2", f"Expected step_2, got {next_step2['step_id']}"
    print(f"Next executable step after step_1 completion: {next_step2['step_id']}")

    # 7. Test execute_next_step helper
    print("\nExecuting step_2 via execute_next_step...")
    res2 = executor.execute_next_step(task_state)
    print(f"Step 2 execution output: {res2}")
    assert res2["success"] is True, f"Step 2 failed: {res2.get('error')}"
    assert res2["step_id"] == "step_2"
    assert step2["status"] == "COMPLETED"
    assert len(task_state.completed_steps) == 2
    assert task_state.iteration_count == 2

    # 8. Verify error handling with non-existent tool
    error_step = {
        "step_id": "step_error",
        "description": "Call invalid tool",
        "objective": "Test failure capture",
        "suggested_tool": "non_existent_tool_123",
        "dependencies": [],
        "status": "PENDING"
    }
    task_state.add_step(error_step)
    res_err = executor.execute_step(task_state, error_step)
    print(f"\nNon-existent tool step execution output: {res_err}")
    assert res_err["success"] is False
    assert res_err["error"] is not None
    assert error_step["status"] == "FAILED"
    assert len(task_state.failed_steps) == 1
    assert len(task_state.errors) > 0
    print("Error handling for invalid tool verified successfully.")

    # 9. Verify Executor bounds (must NOT finish task or generate answers)
    assert task_state.status != TaskStatus.COMPLETED, "Executor must NOT set overall task status to COMPLETED!"
    assert task_state.status != TaskStatus.FAILED, "Executor must NOT set overall task status to FAILED!"

    print("\n=== All Executor assertions PASSED ===")


if __name__ == "__main__":
    test_executor()
