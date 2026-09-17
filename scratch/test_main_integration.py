import os
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Remove agent_test.txt if it already exists
test_file = BASE_DIR / "agent_test.txt"
if test_file.exists():
    os.remove(test_file)

from main import JarvisLive
from core.action_loader import discover_actions
from core.agent import AgentOrchestrator, TaskState, TaskStatus

class MockUI:
    def __init__(self):
        self.muted = False
        self.current_file = None
        self.logs = []
    
    def write_log(self, text):
        print(f"[MockUI Log] {text}")
        self.logs.append(text)

    def set_state(self, state):
        pass

    def show_content(self, label, content):
        pass

def test_integration():
    ui = MockUI()
    jarvis = JarvisLive(ui=ui)
    
    # Enable Agent Mode
    jarvis.agent_mode = True
    jarvis._loop = True  # Mock active event loop presence
    
    test_prompt = "Create a file named agent_test.txt in the project directory containing:\nARUSH AGENT TEST SUCCESS"
    print(f"\n--- Testing AGENT MODE with prompt: {test_prompt} ---")
    
    # Directly invoke _on_text_command
    jarvis._on_text_command(test_prompt)
    
    # Wait for background thread execution to complete
    max_wait = 30
    waited = 0
    while waited < max_wait:
        time.sleep(1)
        waited += 1
        if test_file.exists():
            print(f"File created after {waited} seconds!")
            time.sleep(2)  # Allow orchestrator to finish logging
            break
            
    print("\n--- Verifying Results ---")
    print("1. File exists:", test_file.exists())
    if test_file.exists():
        content = test_file.read_text(encoding="utf-8").strip()
        print("2. File content:\n" + repr(content))
        print("3. Content matches expected:", "ARUSH AGENT TEST SUCCESS" in content)
    else:
        print("ERROR: agent_test.txt was not created!")
        sys.exit(1)

if __name__ == "__main__":
    test_integration()
