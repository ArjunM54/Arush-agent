import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Remove research_test.md if it already exists
target_file = BASE_DIR / "research_test.md"
if target_file.exists():
    os.remove(target_file)

from main import JarvisLive

class MockUI:
    def __init__(self):
        self.muted = False
        self.current_file = None
        self.logs = []
    
    def write_log(self, text):
        print(f"[UI Log] {text}")
        self.logs.append(text)

    def set_state(self, state):
        pass

    def show_content(self, label, content):
        pass

def test_research_runtime():
    ui = MockUI()
    jarvis = JarvisLive(ui=ui)
    
    # Enable Agent Mode explicitly for runtime test
    jarvis.agent_mode = True
    jarvis._loop = True  # Mock event loop presence
    
    test_prompt = (
        "Research the current Python AI agent frameworks. "
        "Find information from multiple web sources, compare them, "
        "and create a Markdown report called research_test.md in the project directory."
    )
    print(f"\n=======================================================")
    print(f"RUNNING DIAGNOSTIC TEST FOR RESEARCH TASK")
    print(f"Prompt: {test_prompt}")
    print(f"=======================================================\n")
    
    # Trigger text command
    jarvis._on_text_command(test_prompt)
    
    # Wait for execution in background thread
    max_wait = 60
    waited = 0
    while waited < max_wait:
        time.sleep(1)
        waited += 1
        if target_file.exists() and target_file.stat().st_size > 100:
            print(f"\n[TEST SUCCESS] research_test.md created after {waited} seconds!")
            time.sleep(2)
            break
            
    print("\n=======================================================")
    print("VERIFICATION RESULTS:")
    print("1. Target File Exists:", target_file.exists())
    if target_file.exists():
        content = target_file.read_text(encoding="utf-8")
        print(f"2. File Size: {len(content)} bytes")
        print("3. Preview (first 500 chars):\n")
        print(content[:500])
    else:
        print("ERROR: research_test.md was not created within timeout.")
    print("=======================================================\n")

if __name__ == "__main__":
    test_research_runtime()
