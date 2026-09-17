import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import DeveloperAgent, DevAgentResult, DevWorkflowPhase
from core.action_loader import discover_actions


def test_developer_agent():
    print("=== Testing Developer Agent Component ===")

    actions_dir = Path(__file__).resolve().parent.parent / "actions"
    registry = discover_actions(actions_dir, logger=lambda m: None)

    dev_agent = DeveloperAgent(action_registry=registry, max_repair_attempts=2)

    temp_dir = Path(tempfile.gettempdir()) / "dev_agent_test"
    temp_dir.mkdir(parents=True, exist_ok=True)
    test_file = temp_dir / "sample_code.py"

    initial_code = '''def calculate_total(prices):\n    return sum(prices)\n'''
    test_file.write_text(initial_code, encoding="utf-8")

    # ---------------------------------------------------------
    # Test 1: Pre-modification Inspection & Checkpoint Creation
    # ---------------------------------------------------------
    print("\n--- Test 1: File Inspection and Task Checkpoint ---")

    inspection = dev_agent.inspect_project(str(test_file))
    assert inspection["status"] == "SUCCESS", f"Inspection failed: {inspection}"
    assert inspection["content"] == initial_code

    checkpoint_res = dev_agent.create_checkpoint(
        task_id="dev_task_001",
        user_request="Modify calculate_total in sample_code.py",
        target_file=str(test_file),
    )
    assert checkpoint_res["status"] == "SUCCESS", f"Checkpoint failed: {checkpoint_res}"
    print(f"Checkpoint saved successfully: Task {checkpoint_res['task_id']}")

    # ---------------------------------------------------------
    # Test 2: Modify File & AST Syntax Verification
    # ---------------------------------------------------------
    print("\n--- Test 2: Modify File & Verify AST Syntax ---")

    valid_modified_code = '''def calculate_total(prices, tax_rate=0.05):\n    subtotal = sum(prices)\n    return subtotal * (1 + tax_rate)\n'''

    mod_res = dev_agent.modify_file(str(test_file), valid_modified_code)
    assert mod_res["status"] == "SUCCESS", f"Modification failed: {mod_res}"

    ast_res = dev_agent.verify_ast_syntax(str(test_file))
    assert ast_res["valid"] is True, f"AST verification failed for valid code: {ast_res}"
    print("PASS: Code modified and AST syntax verified clean!")

    # ---------------------------------------------------------
    # Test 3: Observe Syntax Error & Automatic Repair Cycle
    # ---------------------------------------------------------
    print("\n--- Test 3: Observe Error & Auto-Repair Cycle ---")

    # Write broken syntax code into test file
    broken_code = '''def calculate_total(prices:\n    return sum(prices)\n'''
    test_file.write_text(broken_code, encoding="utf-8")

    ast_broken = dev_agent.verify_ast_syntax(str(test_file))
    assert ast_broken["valid"] is False, "Expected AST verification failure for broken syntax"
    print(f"Observed syntax error correctly: {ast_broken['error']}")

    # Repair with valid code patch
    fixed_code = '''def calculate_total(prices):\n    return sum(prices)\n'''
    repair_res = dev_agent.repair_and_verify(
        file_path=str(test_file),
        repaired_content=fixed_code,
        repair_attempt=1,
    )
    assert repair_res["valid"] is True, f"Repair failed: {repair_res}"
    print("PASS: Syntax error observed and repaired successfully!")

    # ---------------------------------------------------------
    # Test 4: Repair Attempt Limit Enforcement
    # ---------------------------------------------------------
    print("\n--- Test 4: Max Repair Attempt Limit Enforcement ---")

    test_file.write_text(broken_code, encoding="utf-8")
    exceeded_res = dev_agent.repair_and_verify(
        file_path=str(test_file),
        repaired_content=broken_code,
        repair_attempt=3,  # max_repair_attempts is set to 2
    )
    assert exceeded_res["valid"] is False, "Expected repair attempt limit failure"
    assert "Exceeded maximum repair attempts" in exceeded_res["error"], f"Unexpected error message: {exceeded_res}"
    print("PASS: Max repair limit enforced correctly!")

    # ---------------------------------------------------------
    # Test 5: Full Autonomous Developer Task Execution
    # ---------------------------------------------------------
    print("\n--- Test 5: Full Developer Task Execution ---")

    target_script = temp_dir / "target_app.py"
    target_script.write_text("print('Hello World')\n", encoding="utf-8")

    dev_result: DevAgentResult = dev_agent.execute_dev_task(
        user_request="Update target_app.py to add greeting function",
        target_file=str(target_script),
        new_content="def greet(name):\n    return f'Hello, {name}'\n",
    )

    assert dev_result.status == "COMPLETED", f"Dev task execution failed: {dev_result}"
    assert dev_result.phase == DevWorkflowPhase.REPORT
    assert dev_result.checkpoint_created is True
    assert target_script.read_text(encoding="utf-8") == "def greet(name):\n    return f'Hello, {name}'\n"
    print(f"Full task completed cleanly in {dev_result.execution_time:.3f}s!")

    # Cleanup
    for f in temp_dir.glob("*"):
        f.unlink()
    temp_dir.rmdir()

    print("\n=== All Developer Agent Tests Passed Successfully! ===")


if __name__ == "__main__":
    test_developer_agent()
