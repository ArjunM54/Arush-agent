import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import TaskState, TaskStatus

def test_task_state():
    print("=== Testing TaskState Implementation ===")

    # 1. Instantiate TaskState
    task = TaskState(
        user_request="Build a REST API in Python using FastAPI",
        goal="Create a working FastAPI application with endpoints and tests",
        max_iterations=5
    )

    print(f"Task ID: {task.task_id}")
    print(f"Initial Status: {task.status}")
    print(f"Can continue? {task.can_continue()}")
    print(f"Is finished? {task.is_finished()}")
    assert task.status == TaskStatus.PENDING
    assert task.can_continue() is True
    assert task.is_finished() is False

    # 2. Planning phase
    task.status = TaskStatus.PLANNING
    task.add_step("Set up project directory and virtual environment")
    task.add_step("Write main.py with FastAPI endpoints")
    task.add_step("Run pytest verification")

    print(f"\nAdded {len(task.plan)} planned steps.")

    # 3. Execution phase
    task.status = TaskStatus.EXECUTING
    task.iteration_count += 1
    task.current_step = task.plan[0]

    # Execute step 1
    task.add_result("open_app", "Created directory 'fastapi_app'")
    task.add_file_created("fastapi_app/main.py")
    task.complete_step(task.plan[0], result="Directory and main.py created")

    # Execute step 2 with error recovery
    task.iteration_count += 1
    task.current_step = task.plan[1]
    task.add_result("code_helper", "Generated API code")
    task.complete_step(task.plan[1], result="Endpoints created")

    # Step 3
    task.iteration_count += 1
    task.status = TaskStatus.VERIFYING
    task.complete_step(task.plan[2], result="All tests passed")

    # Complete task
    task.status = TaskStatus.COMPLETED

    print(f"Final Status: {task.status}")
    print(f"Is finished? {task.is_finished()}")
    print(f"Can continue? {task.can_continue()}")
    assert task.is_finished() is True
    assert task.can_continue() is False

    # Serialize to dict
    d = task.to_dict()
    print("\nSerialized Dictionary Output:")
    print(json.dumps(d, indent=2))

    print("\n=== All TaskState assertions PASSED ===")
    return d

if __name__ == "__main__":
    test_task_state()
