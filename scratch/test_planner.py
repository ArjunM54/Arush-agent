import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import Planner, TaskState, TaskStatus
from core.action_loader import discover_actions

def test_planner():
    print("=== Testing Agent Planner Component ===")

    # 1. Discover existing actions from actions/ directory
    actions_dir = Path(__file__).resolve().parent.parent / "actions"
    registry = discover_actions(actions_dir, logger=lambda m: None)
    print(f"Discovered {len(registry.names())} active tools from actions/.")

    # 2. Instantiate Planner with Action Registry
    planner = Planner(action_registry=registry)

    # 3. Test complex user prompt
    user_prompt = "Research the best Python AI agent frameworks, compare them, create a report and save it to Documents."
    print(f"\nUser Request: \"{user_prompt}\"\n")

    # 4. Generate plan
    print("Generating structured execution plan (no tools will be executed)...")
    task_state = planner.create_plan(user_request=user_prompt)

    print(f"\nGoal: {task_state.goal}")
    print(f"Task ID: {task_state.task_id}")
    print(f"Total Steps Generated: {len(task_state.plan)}\n")

    # 5. Validate every step has required fields
    required_keys = {"step_id", "description", "objective", "suggested_tool", "dependencies", "status"}
    for idx, step in enumerate(task_state.plan, start=1):
        missing = required_keys - set(step.keys())
        assert not missing, f"Step {idx} missing keys: {missing}"
        print(f"Step {idx} [{step['step_id']}] ({step['suggested_tool']}):")
        print(f"  Description : {step['description']}")
        print(f"  Objective   : {step['objective']}")
        print(f"  Dependencies: {step['dependencies']}")
        print(f"  Status      : {step['status']}\n")

    # 6. Verify Planner did NOT execute any tools
    assert len(task_state.completed_steps) == 0, "Planner must NOT execute tools!"
    assert len(task_state.tool_results) == 0, "Planner must NOT record tool results!"

    print("=== Planner JSON Structure Output ===")
    print(json.dumps(task_state.to_dict(), indent=2))

    print("\n=== All Planner assertions PASSED ===")

if __name__ == "__main__":
    test_planner()
