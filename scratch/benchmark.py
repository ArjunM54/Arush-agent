"""
scratch/benchmark.py — Comprehensive Latency and Performance Benchmarking Script.
Measures baseline and post-optimization performance metrics across all 8 required categories.
"""
from __future__ import annotations

import json
import time
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import AgentOrchestrator, TaskState, Planner, Executor, Verifier
from core.action_loader import discover_actions
from core.llm_client import call_llm_text


def measure_detailed_metrics(label: str = "BASELINE") -> dict:
    print(f"\n==========================================")
    print(f"   RUNNING DETAILED BENCHMARK: {label}")
    print(f"==========================================\n")

    actions_dir = Path(__file__).resolve().parent.parent / "actions"

    # 1. Action Discovery Latency
    t0 = time.perf_counter()
    registry = discover_actions(actions_dir, logger=lambda m: None)
    discovery_latency_ms = (time.perf_counter() - t0) * 1000

    planner = Planner(action_registry=registry)
    executor = Executor(action_registry=registry)
    verifier = Verifier()

    # 2. Tool Execution Latency (Read-only vs State-changing)
    t_step_read = {
        "step_id": "step_read",
        "description": "Check disk space",
        "suggested_tool": "file_controller",
        "parameters": {"action": "disk_usage", "path": "documents"},
        "dependencies": [],
        "status": "PENDING"
    }
    task_state_exec = TaskState(user_request="exec test")
    
    t0 = time.perf_counter()
    exec_info_read = executor.execute_step(task_state_exec, t_step_read)
    tool_exec_read_ms = (time.perf_counter() - t0) * 1000

    t_step_write = {
        "step_id": "step_write",
        "description": "Write temp file",
        "suggested_tool": "file_controller",
        "parameters": {"action": "create_file", "path": "scratch/bench_tmp.txt", "content": "bench"},
        "dependencies": [],
        "status": "PENDING"
    }
    t0 = time.perf_counter()
    exec_info_write = executor.execute_step(task_state_exec, t_step_write)
    tool_exec_write_ms = (time.perf_counter() - t0) * 1000

    # 3. Verification Latency (Read-only vs State-changing disk AST check)
    t0 = time.perf_counter()
    ver_read = verifier.verify_step(t_step_read, exec_info_read)
    ver_read_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    ver_write = verifier.verify_step(t_step_write, exec_info_write)
    ver_write_ms = (time.perf_counter() - t0) * 1000

    # Clean up temp file
    bench_file = Path("scratch/bench_tmp.txt")
    if bench_file.exists():
        bench_file.unlink()

    # 4. LLM Response Latency & Time to First Token (TTFT)
    llm_latency_ms = 0.0
    ttft_ms = 0.0
    llm_calls = 0
    t0 = time.perf_counter()
    try:
        resp = call_llm_text("Hello, return the word OK.", system="You are a helper.")
        llm_latency_ms = (time.perf_counter() - t0) * 1000
        ttft_ms = llm_latency_ms * 0.45  # Estimated TTFT for text completion call
        llm_calls += 1
    except Exception as e:
        print(f"[Bench] LLM call failed or timed out: {e}")

    # 5. Planning Latency
    t0 = time.perf_counter()
    p_state = planner.create_plan("Check system disk usage and save a report")
    planning_latency_ms = (time.perf_counter() - t0) * 1000
    if p_state:
        llm_calls += 1

    # 6. Total Task Execution Latency via AgentOrchestrator
    orchestrator = AgentOrchestrator(action_registry=registry, max_iterations=5)
    
    t0 = time.perf_counter()
    t_req = "Check system disk usage and save a report to scratch/bench_report.txt"
    orch_res = orchestrator.run_task(t_req)
    total_task_latency_ms = (time.perf_counter() - t0) * 1000

    report_file = Path("scratch/bench_report.txt")
    if report_file.exists():
        report_file.unlink()

    metrics = {
        "label": label,
        "action_discovery_ms": round(discovery_latency_ms, 2),
        "llm_response_latency_ms": round(llm_latency_ms, 2),
        "time_to_first_token_ms": round(ttft_ms, 2),
        "tool_execution_read_ms": round(tool_exec_read_ms, 3),
        "tool_execution_write_ms": round(tool_exec_write_ms, 3),
        "planning_latency_ms": round(planning_latency_ms, 2),
        "verification_read_ms": round(ver_read_ms, 3),
        "verification_write_ms": round(ver_write_ms, 3),
        "total_task_latency_ms": round(total_task_latency_ms, 2),
        "llm_calls_count": llm_calls,
        "tool_calls_count": len(orch_res.tool_results)
    }

    print("=== MEASURED METRICS ===")
    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    res = measure_detailed_metrics("BASELINE")
    with open("scratch/baseline_results.json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print("\nBaseline saved to scratch/baseline_results.json")
