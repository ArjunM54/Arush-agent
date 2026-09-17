# Research Agent Runtime Diagnosis & Root Cause Analysis

## 1. Executive Summary
During runtime execution of the research task ("Research the current Python AI agent frameworks..."), the application did not execute `ResearchAgent`, and `research_test.md` was not created.

Through step-by-step empirical tracing and diagnostic logging, **three distinct root causes** were identified:
1. **Keyword Precedence Bug in `SpecialistDelegator`**: The word `"Python"` in the user prompt matched `SpecialistType.DEVELOPER` before the word `"Research"` could match `SpecialistType.RESEARCH`.
2. **Default Execution Mode**: `main.py` hardcodes `self.agent_mode = False` at startup. Running `python main.py` directly without setting `agent_mode = True` causes `_on_text_command()` to route commands to Gemini Live API instead of `AgentOrchestrator`.
3. **API Rate-Limiting & Quota Exhaustion**: The Gemini API returned `429 RESOURCE_EXHAUSTED` for `generate_content` grounded search calls, while DuckDuckGo search encountered rate limits / 403 blocks.

---

## 2. Answers to Diagnostic Questions

### Q1: When Agent Mode is enabled, does `_on_text_command()` really call `AgentOrchestrator.run_task()`?
**Yes.** When `agent_mode = True`, `_on_text_command()` spawns a background thread running `_execute_agent_task()`, which invokes `AgentOrchestrator.run_task()`.

### Q2: If yes, why does a research request still end up as direct `browser_control`?
In the default application startup, `agent_mode` is `False`. Therefore, commands entered via the UI were handled directly by Gemini Live WebSocket (`self.session.send_client_content`), which decided to issue `browser_control` function calls.

### Q3: Does `AgentOrchestrator` actually invoke `ResearchAgent`?
**No.** `AgentOrchestrator` attempts to call `SpecialistDelegator.select_specialist()`. However, due to keyword precedence in `SpecialistDelegator`, `"Python"` matched `DeveloperAgent` first. Because `DeveloperAgent` expected a target code file, delegation failed, and `AgentOrchestrator` fell back to `Planner`, bypassing `ResearchAgent`.

### Q4: Does the Planner know when a task is a RESEARCH task?
**No.** `Planner` decomposes requests into low-level action tools (`web_search`, `file_controller`, `browser_control`) without knowledge of high-level specialist agents like `ResearchAgent`.

### Q5: Does `SpecialistDelegator` actually delegate research tasks to `ResearchAgent`?
**Yes**, but only if `select_specialist()` selects `SpecialistType.RESEARCH`. In this test, because `"Python"` appeared in the prompt, `SpecialistDelegator.select_specialist()` matched `SpecialistType.DEVELOPER` first.

### Q6: Does `ToolRouter` classify research requests correctly?
**Yes.** `ToolRouter` maps research keywords to the `web_research` capability group (`web_search`, `browser_control`).

### Q7: Is Gemini Live still intercepting the command before `AgentOrchestrator`?
**Yes**, whenever `self.agent_mode` is `False` (the default setting in `main.py`).

### Q8: Is Agent Mode actually enabled in the running application?
**No.** `self.agent_mode = False` is hardcoded at process startup in `main.py`, with no CLI argument or UI button to toggle it to `True`.

### Q9: Is there any fallback code that silently sends failed agent requests to Gemini Live?
**No.** There is no silent fallback from `AgentOrchestrator` to Gemini Live.

### Q10: Is `ResearchAgent` using the existing `web_search` action correctly?
**No (previously fixed during diagnosis).** `ResearchAgent` checked `if res.get("status") == "SUCCESS":`, whereas `Executor.execute_step()` returns `{"success": True, ...}`. This compatibility bug caused `ResearchAgent` to treat every successful tool result as empty.

---

## 3. Actual Runtime Path Log Captured

```
[AGENT] INPUT: Research the current Python AI agent frameworks. Find information from multiple web sources, compare them, and create a Markdown report called research_test.md in the project directory.
[AGENT] MODE: agent_mode=True
[AGENT] ORCHESTRATOR: Routing text command to AgentOrchestrator
[AGENT] Task started
[AGENT] ORCHESTRATOR: Running task for request: Research the current Python AI agent frameworks...
[AGENT] Planning
[AGENT] PLANNER: Generating execution plan
[AGENT] PLAN: Generated 4 plan steps
[AGENT] Executing step
[WebSearch] Gemini failed (429 RESOURCE_EXHAUSTED) — trying DDG...
[AGENT] Verifying step
...
VERIFICATION RESULTS:
1. Target File Exists: False
ERROR: research_test.md was not created within timeout.
```

---

## 4. API & Search Errors Encountered
1. **Gemini API Error**: `429 RESOURCE_EXHAUSTED` (Quota exceeded for `gemini-flash-latest` grounded search).
2. **DuckDuckGo Search Error**: Rate limits / 403 Forbidden responses when fallback text search was executed repeatedly.

---

## 5. Status of `research_test.md`
- **File Created**: `False` (File does not exist).
- **Reason**: `ResearchAgent` was bypassed due to keyword precedence collision (`"Python"` matching `DeveloperAgent`), fallback `Planner` executed generic `web_search` steps, and `web_search` failed due to Gemini API quota `429` and DDG rate limiting.

---

## 6. Exact Files & Functions Requiring Modification

1. **[`core/agent/delegator.py`](file:///d:/My%20agent/core/agent/delegator.py#L132-L153)** (`SpecialistDelegator.select_specialist`):
   - **Fix**: Re-order keyword evaluation or refine keyword checks so intent keywords (e.g. `"research"`, `"find information"`, `"compare"`) take priority over context keywords (e.g. `"python"`, `"code"`).

2. **[`main.py`](file:///d:/My%20agent/main.py#L397)** (`JarvisLive.__init__` & startup configuration):
   - **Fix**: Provide a mechanism (e.g. environment variable `AGENT_MODE=1`, startup flag, or UI toggle) to enable `self.agent_mode = True` when running the app.

3. **[`actions/web_search.py`](file:///d:/My%20agent/actions/web_search.py#L155-L163)** (`_search` & `web_search`):
   - **Fix**: Improve error handling and fallback when Gemini API hits `429 RESOURCE_EXHAUSTED` so clean, informative failure messages or cached results are returned instead of throwing exceptions.
