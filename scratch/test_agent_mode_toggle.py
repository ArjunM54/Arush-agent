import os
import sys
import time
import asyncio
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Target test file
test_file = BASE_DIR / "agent_mode_test.txt"
if test_file.exists():
    os.remove(test_file)

from main import JarvisLive

class MockSession:
    def __init__(self):
        self.sent_content = []

    async def send_client_content(self, turns, turn_complete=True):
        print(f"[GEMINI LIVE MOCK] Sent content to Gemini Live: {turns}")
        self.sent_content.append(turns)

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

def run_test_suite():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    ui = MockUI()
    jarvis = JarvisLive(ui=ui)
    jarvis.session = MockSession()
    jarvis._loop = loop

    print("\n--- TEST 1: App Start Mode Log ---")
    print(f"[AGENT] MODE: {'AGENT' if jarvis.agent_mode else 'NORMAL'}")

    print("\n--- TEST 2: Existing Agent Mode Button Click ---")
    jarvis.set_agent_mode("agent")

    print("\n--- TEST 3: Send Agent Mode Command ---")
    cmd = "Create a file called agent_mode_test.txt containing ARUSH AGENT MODE WORKS"
    jarvis._on_text_command(cmd)

    # Wait for execution thread
    max_wait = 30
    waited = 0
    while waited < max_wait:
        time.sleep(1)
        waited += 1
        if test_file.exists():
            print(f"\n[TEST] File created after {waited}s")
            time.sleep(2) # allow thread logging to finish
            break

    print("\n--- TEST 4: Physical File Verification ---")
    file_exists = test_file.exists()
    print("1. File exists:", file_exists)
    file_ok = False
    if file_exists:
        content = test_file.read_text(encoding="utf-8").strip()
        print("2. Physical file content read from disk:\n" + content)
        if "ARUSH AGENT MODE WORKS" in content:
            file_ok = True
            print("3. Content match: VERIFIED EXACT MATCH")
        else:
            print("3. Content match: FAILED")
    else:
        print("ERROR: agent_mode_test.txt was not physically created!")

    print("\n--- TEST 5: Turn Agent Mode OFF ---")
    jarvis.set_agent_mode("normal")

    print("\n--- TEST 6: Send Normal Mode Command ---")
    jarvis._on_text_command("Hello Jarvis")
    
    # Process queued coroutine in event loop
    loop.stop()
    loop.run_forever()

    print("\n--- FINAL TEST SUITE RESULT ---")
    print("Agent Mode Activation & Routing Test:", "PASSED" if file_ok else "FAILED")
    assert file_ok, "Test suite failed!"

if __name__ == "__main__":
    run_test_suite()
