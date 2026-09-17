import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import AgentOrchestrator
from core.action_loader import discover_actions

def main():
    print("=== Testing Agent (Arush) Autonomous Orchestrator Live Task ===")

    # 1. Discover bundled actions
    actions_dir = Path(__file__).resolve().parent.parent / "actions"
    registry = discover_actions(actions_dir, logger=lambda msg: print(f"[Loader] {msg}"))

    # 2. Instantiate Orchestrator
    orchestrator = AgentOrchestrator(action_registry=registry, max_iterations=5)

    # 3. Give a real task
    user_task = "Check system disk usage and save a report to scratch/disk_report.txt"
    print(f"\n[Task Request]: \"{user_task}\"\n")

    # 4. Run Task through Autonomous Loop
    result = orchestrator.run_task(user_task)

    # 5. Output Summary & Result Payload
    print("\n=== Execution Summary ===")
    print(f"Task ID        : {result.task_id}")
    print(f"Status         : {result.status}")
    print(f"Execution Time : {result.execution_time}s")
    print(f"Completed Steps: {len(result.completed_steps)}")
    print(f"Failed Steps   : {len(result.failed_steps)}")
    print(f"Errors         : {result.errors}")

    print("\n=== Result Payload ===")
    print(json.dumps(result.to_dict(), indent=2))

if __name__ == "__main__":
    main()
