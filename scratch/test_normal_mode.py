import sys
import asyncio
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from main import JarvisLive

class MockSession:
    def __init__(self):
        self.sent_content = []
    
    async def send_client_content(self, turns, turn_complete):
        self.sent_content.append((turns, turn_complete))

class MockUI:
    def write_log(self, text):
        pass

async def main_test():
    ui = MockUI()
    jarvis = JarvisLive(ui=ui)
    
    # NORMAL MODE: agent_mode is False
    jarvis.agent_mode = False
    jarvis._loop = asyncio.get_running_loop()
    mock_session = MockSession()
    jarvis.session = mock_session
    
    # Trigger text command
    jarvis._on_text_command("Hello Jarvis")
    
    # Wait briefly for coroutine execution
    await asyncio.sleep(0.1)
    
    print("Normal mode test results:")
    print("Sent turns:", len(mock_session.sent_content))
    if len(mock_session.sent_content) > 0:
        turns, tc = mock_session.sent_content[0]
        print("Turns payload:", turns)
        print("Turn complete:", tc)

if __name__ == "__main__":
    asyncio.run(main_test())
