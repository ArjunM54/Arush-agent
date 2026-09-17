import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import (
    AgentMemory, TaskMemory, TaskState, TaskStatus, AgentOrchestrator, OrchestratorResult
)
from core.action_loader import discover_actions


def test_agent_memory():
    print("=== Testing Three-Level Agent Memory System ===")

    # Use a temporary directory for task persistence testing
    tmp_dir = Path(tempfile.gettempdir()) / "test_agent_tasks"
    memory = AgentMemory(tasks_dir=tmp_dir)

    # ---------------------------------------------------------
    # Test 1: Save task
    # ---------------------------------------------------------
    print("\n--- Test 1: Save Task ---")
    tmp_file1 = Path(tempfile.gettempdir()) / "test_mem_file1.txt"
    if tmp_file1.exists():
        tmp_file1.unlink()

    task1 = TaskState(
        user_request="Create temp file in task memory",
        task_id="task_mem_001",
        status=TaskStatus.EXECUTING
    )
    task1.add_step({
        "step_id": "step_1",
        "description": "Create step 1 file",
        "suggested_tool": "file_controller",
        "parameters": {"action": "create_file", "path": str(tmp_file1), "content": "mem 1"},
        "dependencies": [],
        "status": "COMPLETED"
    })
    task1.completed_steps.append({
        "step_id": "step_1",
        "description": "Create step 1 file",
        "result": f"File created: {tmp_file1}"
    })
    task1.add_result("file_controller", f"File created: {tmp_file1}")

    saved_id = memory.save_task(task1)
    assert saved_id == "task_mem_001"
    assert (tmp_dir / "task_mem_001.json").exists(), "Test 1 failed: JSON task file was not created"
    print(f"PASS: Task '{saved_id}' successfully saved to {tmp_dir / 'task_mem_001.json'}")

    # ---------------------------------------------------------
    # Test 2: Load task
    # ---------------------------------------------------------
    print("\n--- Test 2: Load Task ---")
    loaded_state = memory.load_task("task_mem_001")
    assert loaded_state is not None, "Test 2 failed: Could not load task_mem_001"
    assert loaded_state.task_id == "task_mem_001"
    assert loaded_state.user_request == "Create temp file in task memory"
    assert len(loaded_state.completed_steps) == 1
    assert loaded_state.completed_steps[0]["step_id"] == "step_1"
    assert len(loaded_state.tool_results) == 1
    print("PASS: Task 'task_mem_001' loaded successfully with all state fields intact!")

    # ---------------------------------------------------------
    # Test 3: Resume task (Interrupted task resumption)
    # ---------------------------------------------------------
    print("\n--- Test 3: Resume Task ---")
    tmp_file2 = Path(tempfile.gettempdir()) / "test_mem_file2.txt"
    if tmp_file2.exists():
        tmp_file2.unlink()

    # Create task with step 1 COMPLETED and step 2 PENDING (interrupted before step 2)
    task_interrupted = TaskState(
        user_request="Resume multi-step task",
        task_id="task_mem_resume",
        status=TaskStatus.PAUSED
    )
    step1_dict = {
        "step_id": "step_1",
        "description": "Step 1 already done",
        "suggested_tool": "file_controller",
        "parameters": {"action": "disk_usage", "path": "documents"},
        "dependencies": [],
        "status": "COMPLETED"
    }
    step2_dict = {
        "step_id": "step_2",
        "description": "Step 2 to resume",
        "suggested_tool": "file_controller",
        "parameters": {"action": "create_file", "path": str(tmp_file2), "content": "resumed"},
        "dependencies": ["step_1"],
        "status": "PENDING"
    }
    task_interrupted.add_step(step1_dict)
    task_interrupted.add_step(step2_dict)
    task_interrupted.completed_steps.append(step1_dict)

    memory.save_task(task_interrupted)

    # Resume task via Orchestrator
    actions_dir = Path(__file__).resolve().parent.parent / "actions"
    registry = discover_actions(actions_dir, logger=lambda m: None)
    orchestrator = AgentOrchestrator(action_registry=registry, max_iterations=5)

    res_resume: OrchestratorResult = memory.resume_task("task_mem_resume", orchestrator)
    print(f"Resumed Task Status: {res_resume.status}, Completed steps: {len(res_resume.completed_steps)}")

    assert res_resume.status == "COMPLETED"
    assert len(res_resume.completed_steps) == 2, "Test 3 failed: Expected 2 completed steps"
    assert tmp_file2.exists(), "Test 3 failed: Step 2 file was not created on resumption"
    tmp_file2.unlink()
    print("PASS: Interrupted task resumed seamlessly without re-running step_1!")

    # ---------------------------------------------------------
    # Test 4: Failed task recovery
    # ---------------------------------------------------------
    print("\n--- Test 4: Failed Task Recovery ---")
    tmp_file_rec = Path(tempfile.gettempdir()) / "test_mem_recovered.txt"
    if tmp_file_rec.exists():
        tmp_file_rec.unlink()

    # Create task that previously failed on step 2
    task_failed = TaskState(
        user_request="Recover failed task",
        task_id="task_mem_failed",
        status=TaskStatus.FAILED
    )
    step1_ok = {
        "step_id": "step_1",
        "description": "Step 1 completed before crash",
        "suggested_tool": "file_controller",
        "parameters": {"action": "disk_usage", "path": "documents"},
        "dependencies": [],
        "status": "COMPLETED"
    }
    step2_fail = {
        "step_id": "step_2",
        "description": "Step 2 failed previously",
        "suggested_tool": "file_controller",
        "parameters": {"action": "create_file", "path": str(tmp_file_rec), "content": "recovered"},
        "dependencies": ["step_1"],
        "status": "FAILED"
    }
    task_failed.add_step(step1_ok)
    task_failed.add_step(step2_fail)
    task_failed.completed_steps.append(step1_ok)
    task_failed.failed_steps.append(step2_fail)
    task_failed.add_error("Step 2 failed previously")

    memory.save_task(task_failed)

    # Recover task
    res_recovered: OrchestratorResult = memory.resume_task("task_mem_failed", orchestrator)
    print(f"Recovered Task Status: {res_recovered.status}, Completed steps: {len(res_recovered.completed_steps)}")

    assert res_recovered.status == "COMPLETED", "Test 4 failed: Recovered task should reach COMPLETED"
    assert len(res_recovered.completed_steps) == 2
    assert tmp_file_rec.exists(), "Test 4 failed: Recovered step file not created"
    tmp_file_rec.unlink()
    print("PASS: Failed task recovered successfully!")

    # Clean up test task directory
    for f in tmp_dir.glob("*.json"):
        f.unlink()
    if tmp_dir.exists():
        tmp_dir.rmdir()

    print("\n=== All 4 Agent Memory assertions PASSED ===")


if __name__ == "__main__":
    test_agent_memory()
