import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import ToolRouter
from core.action_loader import discover_actions


def test_tool_router():
    print("=== Testing Intelligent Tool Router Component ===")

    # Discover active tools
    actions_dir = Path(__file__).resolve().parent.parent / "actions"
    registry = discover_actions(actions_dir, logger=lambda m: None)
    print(f"Loaded {len(registry.names())} tool declarations from ActionRegistry.")

    router = ToolRouter(action_registry=registry)

    # 10 Diverse User Request Test Scenarios
    test_cases = [
        {
            "id": 1,
            "prompt": "What's the weather?",
            "expected_tools": {"weather_report"}
        },
        {
            "id": 2,
            "prompt": "Open VS Code and inspect my project",
            "expected_tools": {"computer_control", "desktop_control", "open_app", "code_helper", "file_controller"}
        },
        {
            "id": 3,
            "prompt": "Research AI agent trends and create a report",
            "expected_tools": {"web_search", "browser_control", "file_controller"}
        },
        {
            "id": 4,
            "prompt": "Fix this Python project",
            "expected_tools": {"code_helper", "dev_agent", "file_controller"}
        },
        {
            "id": 5,
            "prompt": "Set a reminder for my meeting at 3 PM",
            "expected_tools": {"reminder"}
        },
        {
            "id": 6,
            "prompt": "Send a WhatsApp message to John",
            "expected_tools": {"send_message"}
        },
        {
            "id": 7,
            "prompt": "Play relaxing music on YouTube",
            "expected_tools": {"youtube_video"}
        },
        {
            "id": 8,
            "prompt": "Adjust laptop brightness and check volume settings",
            "expected_tools": {"computer_settings"}
        },
        {
            "id": 9,
            "prompt": "Parse financial records from invoice.pdf document",
            "expected_tools": {"file_processor", "file_controller"}
        },
        {
            "id": 10,
            "prompt": "Help me with a general ambiguous request",
            "expected_tools": {"file_controller", "web_search", "code_helper", "browser_control"}  # Core fallback
        }
    ]

    total_orig_chars = 0
    total_routed_chars = 0

    print("\n--- Test Results Across 10 Scenarios ---\n")

    for tc in test_cases:
        prompt = tc["prompt"]
        expected = tc["expected_tools"]
        
        routed_names = router.route_tool_names(prompt)
        stats = router.measure_prompt_reduction(prompt, registry)

        # Assert at least one expected tool is included (never hidden)
        overlap = routed_names.intersection(expected)
        assert len(overlap) > 0, f"Test {tc['id']} failed: Expected one of {expected}, got {routed_names}"

        total_orig_chars += stats["full_char_length"]
        total_routed_chars += stats["routed_char_length"]

        print(f"Test {tc['id']:02d}: \"{prompt}\"")
        print(f"  Routed Tools ({len(stats['routed_tool_names'])}/{stats['full_tool_count']}): {sorted(list(routed_names))}")
        print(f"  Prompt Payload Reduction: {stats['full_char_length']} chars -> {stats['routed_char_length']} chars ({stats['char_reduction_percent']}% saved)\n")

    avg_reduction = round((total_orig_chars - total_routed_chars) / total_orig_chars * 100, 2)
    print("==========================================")
    print(f"Average Prompt Size Reduction: {avg_reduction}%")
    print("==========================================")
    print("\n=== All 10 ToolRouter test assertions PASSED ===")


if __name__ == "__main__":
    test_tool_router()
