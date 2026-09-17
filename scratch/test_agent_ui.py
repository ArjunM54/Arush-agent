import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import AgentOrchestrator, TaskState, TaskStatus
from core.action_loader import discover_actions
from dashboard.server import DashboardServer


def test_agent_ui_integration():
    print("=== Testing Agent Mode UI & Dashboard Integration ===")

    # Load discoverable actions
    actions_dir = Path(__file__).resolve().parent.parent / "actions"
    registry = discover_actions(actions_dir, logger=lambda m: None)

    received_updates = []

    def on_state_update(st: TaskState):
        d = st.to_dict()
        received_updates.append(d)
        print(f"  [Callback] Task '{st.user_request}' -> Status: {st.status.value}, Completed: {len(st.completed_steps)}/{len(st.plan)}")

    orchestrator = AgentOrchestrator(action_registry=registry, max_iterations=5, on_update=on_state_update)

    # ---------------------------------------------------------
    # Test 1: Task Execution & Live State Broadcast Callback
    # ---------------------------------------------------------
    print("\n--- Test 1: Task Execution & Live Callback Broadcast ---")

    task_request = "Research AI frameworks and create a report"
    task = TaskState(user_request=task_request)
    task.add_step({"step_id": "step_1", "description": "Understanding task", "suggested_tool": "planner", "status": "COMPLETED"})
    task.add_step({"step_id": "step_2", "description": "Creating plan", "suggested_tool": "planner", "status": "COMPLETED"})
    task.add_step({"step_id": "step_3", "description": "Searching sources", "suggested_tool": "web_search", "status": "COMPLETED"})
    task.add_step({"step_id": "step_4", "description": "Comparing results", "suggested_tool": "web_search", "status": "COMPLETED"})
    task.add_step({"step_id": "step_5", "description": "Creating report", "suggested_tool": "file_controller", "status": "EXECUTING"})
    task.add_step({"step_id": "step_6", "description": "Verifying report", "suggested_tool": "verifier", "status": "PENDING"})

    assert len(task.plan) == 6
    assert len(task.completed_steps) == 0

    # Simulate step completions & callback triggers
    for s in task.plan[:4]:
        task.complete_step(s, result="Done")
        on_state_update(task)

    assert len(received_updates) >= 4
    latest_update = received_updates[-1]

    pct = round((len(latest_update["completed_steps"]) / len(latest_update["plan"])) * 100)
    assert pct == 67
    assert latest_update["user_request"] == task_request
    print(f"Calculated progress percentage: {pct}%")
    print("PASS: Task progress calculations and live state callback verified!")

    # ---------------------------------------------------------
    # Test 2: Dashboard Server Agent State Broadcast
    # ---------------------------------------------------------
    print("\n--- Test 2: Dashboard Server Broadcast Payload ---")

    server = DashboardServer()
    server.broadcast_agent_state(latest_update)

    assert len(server._history) > 0
    history_msg = server._history[-1]
    assert history_msg["type"] == "agent_state_update"
    assert history_msg["state"]["user_request"] == task_request
    print("PASS: DashboardServer broadcast_agent_state payload verified!")

    # ---------------------------------------------------------
    # Test 3: Interactive Control (Pause, Resume, Stop)
    # ---------------------------------------------------------
    print("\n--- Test 3: Agent Control Actions (Pause, Resume, Stop) ---")

    # Pause
    paused_state = orchestrator.pause_task(task)
    assert paused_state.status == TaskStatus.PAUSED
    print("PAUSE action verified cleanly!")

    # Resume
    resumed_state = orchestrator.resume_task(paused_state)
    assert resumed_state.status == TaskStatus.EXECUTING
    print("RESUME action verified cleanly!")

    # Stop / Cancel
    cancelled_state = orchestrator.cancel_task(resumed_state)
    assert cancelled_state.status == TaskStatus.CANCELLED
    print("STOP action verified cleanly!")

    print("PASS: Agent control actions verified!")

    print("\n=== All Agent Mode UI & Dashboard Tests Passed Successfully! ===")


if __name__ == "__main__":
    test_agent_ui_integration()
