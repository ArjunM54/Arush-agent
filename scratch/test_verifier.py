import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import Verifier, VerificationResult


def test_verifier():
    print("=== Testing Agent Verifier Component ===")
    verifier = Verifier()

    # ---------------------------------------------------------
    # Test 1: Successful operation with observable evidence on disk
    # ---------------------------------------------------------
    print("\n--- Test 1: Successful Operation (File Created & Verified) ---")
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(b"print('Hello, Verifier!')\n")

    try:
        step_success = {
            "step_id": "step_1",
            "description": "Create python script",
            "suggested_tool": "file_controller",
            "parameters": {"action": "create_file", "path": str(tmp_path)}
        }
        exec_res_success = {
            "success": True,
            "step_id": "step_1",
            "tool": "file_controller",
            "result": f"Successfully created file at {tmp_path}",
            "error": None
        }

        res1: VerificationResult = verifier.verify_step(step_success, exec_res_success)
        print(f"Verification Result 1: {res1.to_dict()}")

        assert res1.success is True, "Test 1 failed: Expected success=True for existing file on disk"
        assert res1.confidence == 1.0, "Test 1 failed: Expected confidence=1.0 for physical disk evidence"
        assert res1.evidence.get("exists") is True, "Test 1 failed: Evidence should record exists=True"
        assert res1.evidence.get("syntax_valid") is True, "Test 1 failed: Python syntax should be valid"
        assert res1.retryable is False, "Test 1 failed: Successful step should not be retryable"
        print("PASS: Successful operation with observable evidence verified!")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    # ---------------------------------------------------------
    # Test 2: Failed operation (Explicit failure signal / error output)
    # ---------------------------------------------------------
    print("\n--- Test 2: Failed Operation (Explicit Error Signal) ---")
    step_fail = {
        "step_id": "step_2",
        "description": "Access system file",
        "suggested_tool": "file_controller",
        "parameters": {"action": "read", "path": "C:\\Windows\\System32\\config\\SAM"}
    }
    exec_res_fail = {
        "success": True,  # Tool executed, but tool output returned permission error
        "step_id": "step_2",
        "tool": "file_controller",
        "result": "Access denied: Cannot read restricted system file",
        "error": None
    }

    res2: VerificationResult = verifier.verify_step(step_fail, exec_res_fail)
    print(f"Verification Result 2: {res2.to_dict()}")

    assert res2.success is False, "Test 2 failed: Expected success=False for error signal in tool output"
    assert res2.confidence >= 0.9, "Test 2 failed: Expected high confidence for explicit failure signal"
    assert res2.retryable is True, "Test 2 failed: Failed step should be marked retryable"
    print("PASS: Failed operation with explicit error signal verified!")

    # ---------------------------------------------------------
    # Test 3: Missing evidence (Ambiguous operation without observable evidence)
    # ---------------------------------------------------------
    print("\n--- Test 3: Missing Evidence (Conservative Policy Enforcement) ---")
    step_missing = {
        "step_id": "step_3",
        "description": "Perform background computation",
        "suggested_tool": "general",
        "parameters": {}
    }
    exec_res_missing = {
        "success": True,
        "step_id": "step_3",
        "tool": "general",
        "result": "Done with general task.",  # Text claim without observable system state
        "error": None
    }

    res3: VerificationResult = verifier.verify_step(step_missing, exec_res_missing)
    print(f"Verification Result 3: {res3.to_dict()}")

    assert res3.success is False, "Test 3 failed: Conservative policy must reject success when evidence is missing!"
    assert res3.confidence == 0.0, "Test 3 failed: Expected confidence=0.0 when evidence is missing"
    assert "Insufficient observable evidence" in res3.reason
    print("PASS: Missing evidence conservative rejection verified!")

    print("\n=== All Verifier assertions PASSED ===")


if __name__ == "__main__":
    test_verifier()
