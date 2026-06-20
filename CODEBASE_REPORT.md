# SG_CUBE Codebase Structural Report

This report contains a structural breakdown of every file in the project.

**Total Files Scanned:** 174
**Total Lines of Code:** 10643

---

## `.claude\settings.local.json`
- **Type:** Non-Python File
- **Lines:** 19

---

## `.env.example`
- **Type:** Non-Python File
- **Lines:** 22

---

## `.env`
- **Type:** Non-Python File
- **Lines:** 22

---

## `.gitignore`
- **Type:** Non-Python File
- **Lines:** 57

---

## `GEMINI.md`
- **Type:** Non-Python File
- **Lines:** 16

---

## `IMPLEMENTATION_PLAN.md`
- **Type:** Non-Python File
- **Lines:** 429

---

## `IMPLEMENTATION_PLAN_V2.md`
- **Type:** Non-Python File
- **Lines:** 78

---

## `README.md`
- **Type:** Non-Python File
- **Lines:** 205

---

## `assets\README.md`
- **Type:** Non-Python File
- **Lines:** 26

---

## `assets\sgcube.tcss`
- **Type:** Non-Python File
- **Lines:** 130

---

## `backend\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\ai_modules\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\ai_modules\llm\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\ai_modules\llm\ollama_client.py`
- **Type:** Python Module
- **Lines:** 69

### Classes
- **`OllamaError`**

### Functions
- **`generate`**
  - *Doc:* Call Ollama /api/generate and return the response string.
- **`embed`**
  - *Doc:* Call Ollama /api/embeddings and return the vector.

---

## `backend\ai_modules\speech\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\ai_modules\speech\piper_voices\.gitkeep`
- **Type:** Non-Python File
- **Lines:** 0

---

## `backend\ai_modules\speech\piper_voices\en_US-ryan-high.onnx.json`
- **Type:** Non-Python File
- **Lines:** 420

---

## `backend\ai_modules\speech\piper_voices\en_US-ryan-high.onnx`
- **Type:** Binary File

---

## `backend\ai_modules\speech\stt_whisper.py`
- **Type:** Python Module
- **Lines:** 89

### Functions
- **`get_model`**
  - *Doc:* Load Whisper once, cache for the process lifetime.
- **`transcribe`**
  - *Doc:* Transcribe a short voice-command clip.

---

## `backend\ai_modules\speech\tts_piper.py`
- **Type:** Python Module
- **Lines:** 70

### Functions
- **`_get_voice`**
- **`generate_audio`**
  - *Doc:* Synthesize `text` and return raw PCM bytes (16kHz) and sample rate.
- **`speak`**
  - *Doc:* Synthesize `text` via Piper and play through the default audio device. Blocks.

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\README`
- **Type:** Non-Python File
- **Lines:** 9

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\am\final.mdl`
- **Type:** Binary File

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\conf\mfcc.conf`
- **Type:** Non-Python File
- **Lines:** 7

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\conf\model.conf`
- **Type:** Non-Python File
- **Lines:** 10

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\graph\Gr.fst`
- **Type:** Binary File

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\graph\HCLr.fst`
- **Type:** Binary File

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\graph\disambig_tid.int`
- **Type:** Non-Python File
- **Lines:** 17

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\graph\phones\word_boundary.int`
- **Type:** Non-Python File
- **Lines:** 166

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\ivector\final.dubm`
- **Type:** Binary File

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\ivector\final.ie`
- **Type:** Binary File

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\ivector\final.mat`
- **Type:** Binary File

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\ivector\global_cmvn.stats`
- **Type:** Non-Python File
- **Lines:** 3

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\ivector\online_cmvn.conf`
- **Type:** Non-Python File
- **Lines:** 1

---

## `backend\ai_modules\speech\vosk_models\vosk-model-small-en-us-0.15\ivector\splice.conf`
- **Type:** Non-Python File
- **Lines:** 2

---

## `backend\core\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\core\agent\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\core\agent\agent.py`
- **Type:** Python Module
- **Lines:** 7

### Functions
- **`run`**
  - *Doc:* Legacy interface for the new Multi-Agent Internal Architecture.

---

## `backend\core\agent\context.py`
- **Type:** Python Module
- **Lines:** 44

**Module Docstring:**
```text
Short-term conversation memory for the agent.

Holds the last N user/assistant exchanges so the LLM can resolve follow-ups
("louder", "more like that", "and then close it"). Single global instance —
the daemon is single-user. Add per-user keying when multi-user lands.
```

### Classes
- **`Turn`**
- **`ConversationContext`**
  - *Methods:* __init__, add_user, add_assistant, render, clear

### Functions
- **`get_context`**
  - *Doc:* Process-wide singleton. Cleared on daemon restart.

---

## `backend\core\agent\verifier.py`
- **Type:** Python Module
- **Lines:** 173

### Classes
- **`VerificationResult`**
  - *Methods:* __init__

### Functions
- **`_is_malicious`**
  - *Doc:* Scan all tool arguments for injection patterns or dangerous tokens.
- **`_secondary_check`**
  - *Doc:* Ask a smaller, faster model (phi3) if this tool call makes sense.
- **`verify`**
  - *Doc:* The SG_CUBE Verification Stack:

---

## `backend\core\agents\base.py`
- **Type:** Python Module
- **Lines:** 34

### Classes
- **`InternalAgentEvent`**
- **`TokenStreamEvent`**
- **`BaseInternalAgent`**
  - *Doc:* Base class for specialized reasoning roles.
  - *Methods:* __init__, _emit

---

## `backend\core\agents\commander.py`
- **Type:** Python Module
- **Lines:** 148

### Classes
- **`CommanderAgent`**
  - *Doc:* The central orchestrator of the specialized internal agents.
  - *Methods:* __init__, interrupt, run, _run_loop

---

## `backend\core\agents\guardian.py`
- **Type:** Python Module
- **Lines:** 36

### Classes
- **`GuardianAgent`**
  - *Doc:* Specialized in safety, verification, and rules.
  - *Methods:* __init__, verify_plan

---

## `backend\core\agents\operator.py`
- **Type:** Python Module
- **Lines:** 32

### Classes
- **`OperatorAgent`**
  - *Doc:* Specialized in tool execution and runtime interaction.
  - *Methods:* __init__, execute_batch

---

## `backend\core\agents\planner.py`
- **Type:** Python Module
- **Lines:** 83

### Classes
- **`PlannerAgent`**
  - *Doc:* Specialized in strategic breakdown and tool selection.
  - *Methods:* __init__, generate_plan, _build_prompt

---

## `backend\core\agents\watcher.py`
- **Type:** Python Module
- **Lines:** 108

### Classes
- **`WatcherAgent`**
  - *Doc:* Autonomous Background Agent.
  - *Methods:* __init__, start, stop, add_battery_task, add_folder_task, _loop, _check_task, _fire

---

## `backend\core\auth\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\core\auth\auth_service.py`
- **Type:** Python Module
- **Lines:** 83

### Functions
- **`register`**
- **`login`**

---

## `backend\core\auth\deps.py`
- **Type:** Python Module
- **Lines:** 43

### Functions
- **`get_bearer_token`**
- **`get_current_user`**
- **`require_admin`**

---

## `backend\core\auth\jwt_verifier.py`
- **Type:** Python Module
- **Lines:** 62

### Functions
- **`_get_jwks_client`**
- **`verify_token`**
  - *Doc:* Verify a Supabase-issued JWT.

---

## `backend\core\events.py`
- **Type:** Python Module
- **Lines:** 42

### Classes
- **`EventBus`**
  - *Doc:* A simple thread-safe in-memory pub/sub event bus.
  - *Methods:* __init__, subscribe, publish

---

## `backend\core\healing.py`
- **Type:** Python Module
- **Lines:** 71

### Classes
- **`RecoveryPath`**
- **`SelfHealingEvent`**
  - *Methods:* __init__, __repr__
- **`SelfHealer`**
  - *Doc:* Analyzes tool failures and recommends recovery strategies.
  - *Methods:* analyze, get_instruction

---

## `backend\core\memory\base.py`
- **Type:** Python Module
- **Lines:** 25

### Classes
- **`MemoryType`**
- **`MemoryEntry`**

---

## `backend\core\memory\episodic.py`
- **Type:** Python Module
- **Lines:** 72

### Classes
- **`EpisodeSummarizer`**
  - *Doc:* The 'Learning Layer' - extracts patterns and facts from interactions.
  - *Methods:* summarize_and_store

---

## `backend\core\memory\long_term.py`
- **Type:** Python Module
- **Lines:** 122

### Classes
- **`OllamaEmbeddingFunction`**
  - *Doc:* Bridge between ChromaDB and local Ollama embeddings.
  - *Methods:* __call__
- **`LongTermMemory`**
  - *Doc:* Persistent semantic storage using ChromaDB and Ollama embeddings.
  - *Methods:* __init__, store, search, get_all

---

## `backend\core\memory\long_term_legacy.py`
- **Type:** Python Module
- **Lines:** 78

### Classes
- **`LongTermMemory`**
  - *Doc:* Persistent storage for semantic facts and patterns.
  - *Methods:* __init__, _init_db, store, search, get_all

---

## `backend\core\memory\manager.py`
- **Type:** Python Module
- **Lines:** 110

### Classes
- **`MemoryManager`**
  - *Doc:* The central hub for all memory tiers in SG_CUBE.
  - *Methods:* __init__, remember_fact, remember_preference, get_relevant_context

---

## `backend\core\memory\screen_memory.py`
- **Type:** Python Module
- **Lines:** 103

### Classes
- **`ScreenMemory`**
  - *Doc:* Manages the visual situational awareness memory (Screen-RAG).
  - *Methods:* __init__, store_observation, get_latest_observation, search_visual

---

## `backend\core\memory\short_term.py`
- **Type:** Python Module
- **Lines:** 16

### Classes
- **`ShortTermMemory`**
  - *Doc:* Session-based chat history.
  - *Methods:* __init__, add, render, clear

---

## `backend\core\memory\timeline.py`
- **Type:** Python Module
- **Lines:** 111

### Classes
- **`TimelineMemory`**
  - *Doc:* Manages the chronological activity tracking (Timeline Memory).
  - *Methods:* __init__, record_event, get_recent_timeline, search_timeline

---

## `backend\core\memory\working.py`
- **Type:** Python Module
- **Lines:** 21

### Classes
- **`WorkingMemory`**
  - *Doc:* Temporary storage for the current multi-step task.
  - *Methods:* __init__, set, get, clear, render_prompt

---

## `backend\core\observability.py`
- **Type:** Python Module
- **Lines:** 98

### Classes
- **`ObservabilityEngine`**
  - *Doc:* The central engine for tracking concrete system reliability metrics.
  - *Methods:* __init__, report_ai_quality, report_tool_quality, report_context_quality, report_latency, _publish_update

---

## `backend\core\orchestrator\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\core\orchestrator\cache_layer.py`
- **Type:** Python Module
- **Lines:** 19

### Functions
- **`get`**
- **`set`**
- **`size`**
- **`clear`**

---

## `backend\core\orchestrator\llm_layer.py`
- **Type:** Python Module
- **Lines:** 96

### Classes
- **`Intent`**
- **`LLMResolveError`**

### Functions
- **`resolve`**
  - *Doc:* Convert natural-language input into an Intent via Ollama.

---

## `backend\core\orchestrator\normalize.py`
- **Type:** Python Module
- **Lines:** 16

### Functions
- **`normalize`**
  - *Doc:* Cache-key normalizer: lowercase, drop punctuation, collapse whitespace.

---

## `backend\core\orchestrator\router.py`
- **Type:** Python Module
- **Lines:** 92

### Classes
- **`RouterResult`**

### Functions
- **`_log_to_db`**
- **`process_input`**

---

## `backend\core\orchestrator\rule_engine.py`
- **Type:** Python Module
- **Lines:** 115

### Functions
- **`_canonical_app`**
- **`_open_app`**
- **`_close_app`**
- **`_get_time`**
- **`_play_youtube`**
- **`_search_youtube`**
- **`_search_google`**
- **`match`**
  - *Doc:* Match against normalized (lowercased, depunctuated) text. Returns None on miss.

---

## `backend\core\plugins\base.py`
- **Type:** Python Module
- **Lines:** 33

### Classes
- **`PluginContext`**
  - *Doc:* Provides restricted access to system resources for plugins.
  - *Methods:* __init__, run_tool, log
- **`SGCubePlugin`**
  - *Doc:* Base class for all SG_CUBE plugins.
  - *Methods:* name, execute

---

## `backend\core\plugins\installed\spotify.py`
- **Type:** Python Module
- **Lines:** 32

### Classes
- **`SpotifyPlugin`**
  - *Doc:* Example plugin for Spotify integration.
  - *Methods:* name, execute

---

## `backend\core\plugins\manager.py`
- **Type:** Python Module
- **Lines:** 42

### Classes
- **`PluginManager`**
  - *Methods:* __init__, discover, get_plugin

---

## `backend\core\runtime.py`
- **Type:** Python Module
- **Lines:** 142

### Classes
- **`TaskStatus`**
- **`TaskEvent`**
- **`Task`**
  - *Methods:* __init__, cancel
- **`Runtime`**
  - *Doc:* Async execution runtime for SG_CUBE tools.
  - *Methods:* __init__, run_tool, cancel_task

---

## `backend\core\safe_executor\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\core\safe_executor\command_whitelist.py`
- **Type:** Python Module
- **Lines:** 461

### Functions
- **`is_target_dangerous`**
- **`is_system_app`**
- **`_launch_elevated`**
  - *Doc:* Trigger Windows UAC for `command`. Windows shows the password / consent
- **`_load_start_apps`**
  - *Doc:* Enumerate every installed app (UWP + Win32 + Start Menu shortcuts)
- **`_get_apps_cache`**
- **`refresh_apps_cache`**
  - *Doc:* Re-scan installed apps. Call this if the user installs something new
- **`_match_app`**
  - *Doc:* Pick the best app name from `candidates` for the spoken `query`.
- **`_resolve_app_id`**
  - *Doc:* Resolve a user query to (display_name, AppID) using Get-StartApps.
- **`_running_proc_names`**
  - *Doc:* Snapshot of running process names (e.g. ['chrome.exe', 'CalculatorApp.exe']).
- **`_find_running_proc`**
  - *Doc:* Pick the best running .exe name matching `query`. Handles cases where
- **`handle_open_app`**
- **`handle_close_app`**
- **`handle_get_time`**
- **`handle_unknown`**
- **`_open_url`**
  - *Doc:* Open `url` in the user's default browser via Windows `start`.
- **`handle_open_url`**
- **`handle_search_google`**
- **`handle_search_youtube`**
- **`handle_play_youtube`**
  - *Doc:* Resolve the first YouTube search result via yt-dlp, then open that
- **`handle_agent_complete`**
  - *Doc:* Synthetic intent emitted by the Phase 11a agent path. The agent has

---

## `backend\core\safe_executor\executor.py`
- **Type:** Python Module
- **Lines:** 70

### Classes
- **`ExecutionResult`**

### Functions
- **`execute`**

---

## `backend\core\state.py`
- **Type:** Python Module
- **Lines:** 51

### Classes
- **`AssistantState`**
- **`StateChangedEvent`**
  - *Methods:* __init__, __repr__
- **`StateMachine`**
  - *Doc:* Manages the assistant's current state and publishes transitions.
  - *Methods:* __init__, current, transition_to

---

## `backend\core\tools\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\core\tools\audio.py`
- **Type:** Python Module
- **Lines:** 62

**Module Docstring:**
```text
Audio control tools (Phase 11b) — system master volume and mute via pycaw.
```

### Functions
- **`_endpoint`**
- **`_clamp`**
- **`set_volume`**
  - *Doc:* Set system master volume. `level` is 0-100.
- **`get_volume`**
  - *Doc:* Return current system master volume (0-100).
- **`volume_up`**
  - *Doc:* Raise system volume by `amount` percentage points (default 10).
- **`volume_down`**
  - *Doc:* Lower system volume by `amount` percentage points (default 10).
- **`mute`**
  - *Doc:* Toggle system mute on/off.

---

## `backend\core\tools\automation.py`
- **Type:** Python Module
- **Lines:** 24

**Module Docstring:**
```text
Automation and background monitoring tools (Phase 14).
```

### Functions
- **`monitor_battery`**
  - *Doc:* Monitor the system battery in the background. When it drops below
- **`monitor_folder`**
  - *Doc:* Monitor a folder for new files matching a pattern. When a new file appears,

---

## `backend\core\tools\builtins.py`
- **Type:** Python Module
- **Lines:** 129

**Module Docstring:**
```text
Built-in tools.

Importing this module populates the registry with every shipped tool.
backend.core.agent.agent imports it eagerly at boot.

- Phase 11a tools defined here (wrap the Phase 6/10 handlers).
- Phase 11b tools live in dedicated modules under backend.core.tools.* —
  their @tool decorators run when their module is imported below.
```

### Functions
- **`respond`**
  - *Doc:* Speak `text` as the final answer to the user. Use this to end the
- **`open_app`**
  - *Doc:* Open a desktop application by name. ANY installed app works
- **`close_app`**
  - *Doc:* Close a running desktop application by name.
- **`play_youtube`**
  - *Doc:* Play the FIRST YouTube search result for `query` in the default
- **`search_web`**
  - *Doc:* Open a web search for `query` in the default browser.
- **`open_url`**
  - *Doc:* Open a URL or domain (e.g. "github.com" or "https://example.com")
- **`get_time`**
  - *Doc:* Return the current local time, formatted for speaking aloud.

---

## `backend\core\tools\comms.py`
- **Type:** Python Module
- **Lines:** 79

**Module Docstring:**
```text
Communications tools (Phase 11c) — clipboard + WhatsApp + email.
```

### Functions
- **`clipboard_copy`**
  - *Doc:* Set the system clipboard to `text`. Use for "copy this", "save to clipboard".
- **`clipboard_get`**
  - *Doc:* Read the current system clipboard contents (text only).
- **`send_to_phone`**
  - *Doc:* Send a link or a text snippet directly to the connected Android device.
- **`send_whatsapp`**
  - *Doc:* Open WhatsApp with a pre-filled message to `contact`.
- **`send_email`**
  - *Doc:* Open the default mail client with a draft email pre-filled.

---

## `backend\core\tools\display.py`
- **Type:** Python Module
- **Lines:** 48

**Module Docstring:**
```text
Display tools (Phase 11b) — screen brightness via screen-brightness-control.
```

### Functions
- **`_clamp`**
- **`_current`**
- **`set_brightness`**
  - *Doc:* Set screen brightness. `level` is 0-100.
- **`get_brightness`**
  - *Doc:* Return current screen brightness (0-100).
- **`brightness_up`**
  - *Doc:* Raise brightness by `amount` percentage points (default 10).
- **`brightness_down`**
  - *Doc:* Lower brightness by `amount` percentage points (default 10).

---

## `backend\core\tools\files.py`
- **Type:** Python Module
- **Lines:** 124

**Module Docstring:**
```text
File ops + dictation tools (Phase 11b).
```

### Functions
- **`delete_file`**
  - *Doc:* Delete a file. `file` is a full path or a substring of a file name in
- **`open_folder`**
  - *Doc:* Open a folder in File Explorer. `name` can be a special name
- **`find_file`**
  - *Doc:* Search for files whose name contains `query` under your common
- **`type_text`**
  - *Doc:* Type `text` into the currently focused window — as if you typed it on

---

## `backend\core\tools\finance.py`
- **Type:** Python Module
- **Lines:** 128

**Module Docstring:**
```text
Finance tools (Phase 11d) — stocks via Yahoo Finance JSON, crypto via CoinGecko.

Both are free, no API key. Uses httpx directly to avoid pulling in pandas
(which yfinance does). Caches the CoinGecko coin-id list lazily.
```

### Functions
- **`get_stock_price`**
  - *Doc:* Get the current price for a stock ticker (e.g. "AAPL", "TSLA", "MSFT",
- **`get_crypto_price`**
  - *Doc:* Get the current USD price for a cryptocurrency (e.g. "btc", "bitcoin",

---

## `backend\core\tools\llm_helper.py`
- **Type:** Python Module
- **Lines:** 35

**Module Docstring:**
```text
Shared LLM helper for Phase 11e content tools.

Calls Ollama's `/api/generate` endpoint in plain-text mode (no JSON format
constraint) using `agent_model` (gemma4). Used by summarize / translate /
explain_code — anything that needs a freeform-prose response rather than the
structured tool-call JSON that the agent loop uses.
```

### Functions
- **`llm_generate`**
  - *Doc:* Send `prompt` to the agent model and return its response as plain text.

---

## `backend\core\tools\memory.py`
- **Type:** Python Module
- **Lines:** 29

### Functions
- **`remember`**
  - *Doc:* Store a piece of information for long-term recall.
- **`set_preference`**
  - *Doc:* Store a user preference for future behavior.
- **`update_task_state`**
  - *Doc:* Store temporary state for the current complex task.

---

## `backend\core\tools\news.py`
- **Type:** Python Module
- **Lines:** 132

**Module Docstring:**
```text
News + trending + daily briefing (Phase 11d).

- News via RSS (BBC, Hacker News, TechCrunch, Al Jazeera, NYT).
- Trending via Reddit r/popular JSON (no API key, just a user-agent).
- daily_briefing chains time + weather + top news into one spoken summary.
```

### Functions
- **`get_news`**
  - *Doc:* Read top headlines from an RSS feed. Categories: world, tech,
- **`get_trending`**
  - *Doc:* Read what is trending right now on Reddit's r/popular. Useful for
- **`daily_briefing`**
  - *Doc:* Read out a morning briefing: current time + local weather + top three

---

## `backend\core\tools\notes.py`
- **Type:** Python Module
- **Lines:** 61

**Module Docstring:**
```text
Notes tools (Phase 11c) — daily markdown file under ~/sg_cube/notes/.
```

### Functions
- **`_today`**
- **`_notes_path`**
- **`take_note`**
  - *Doc:* Append a timestamped note to today's markdown file at
- **`read_notes`**
  - *Doc:* Return the notes for a given date (YYYY-MM-DD). Defaults to today.
- **`open_notes_today`**
  - *Doc:* Open today's notes file in the default markdown editor.

---

## `backend\core\tools\ocr.py`
- **Type:** Python Module
- **Lines:** 52

**Module Docstring:**
```text
OCR tool (Phase 11e) — extract text from the screen.

Requires the Tesseract binary on PATH (separate Windows installer:
https://github.com/UB-Mannheim/tesseract/wiki). If it's missing we return a
helpful error rather than crashing the agent loop.
```

### Functions
- **`ocr_screen`**
  - *Doc:* Read text visible anywhere on the screen using OCR. Takes a screenshot

---

## `backend\core\tools\read_aloud.py`
- **Type:** Python Module
- **Lines:** 42

**Module Docstring:**
```text
Read-aloud tool (Phase 11e).

Reads whatever is on the clipboard out loud via Piper TTS. The user copies
text (Ctrl+C in any app), then says "read this" / "read it out loud".
```

### Functions
- **`_speak_async`**
- **`read_aloud`**
  - *Doc:* Read the current clipboard contents out loud. Copy text in any app

---

## `backend\core\tools\registry.py`
- **Type:** Python Module
- **Lines:** 283

**Module Docstring:**
```text
Tool registry + @tool decorator.

A tool is a Python function annotated with `@tool`. We introspect its
signature + docstring to produce a JSON-schema description the LLM can read,
and we keep the function callable for the executor to invoke.

Example:

    @tool
    def set_volume(level: int) -> dict:
        '''Set system volume to a value between 0 and 100.'''
        ...

    REGISTRY["set_volume"]          # -> Tool instance
    REGISTRY["set_volume"].schema   # -> JSON schema dict
    REGISTRY["set_volume"](level=50)  # -> dict result
```

### Classes
- **`ToolStatus`**
- **`SecurityLevel`**
- **`ToolResult`**
  - *Doc:* Standardized result returned by every tool.
  - *Methods:* success, blocked, error, pending
- **`Tool`**
  - *Methods:* __call__

### Functions
- **`_type_to_json`**
- **`tool`**
  - *Doc:* Register a function as a tool. Supports:
- **`all_schemas`**
- **`schemas_prompt`**
  - *Doc:* Render the registry as compact JSON suitable for inclusion in the
- **`_resolve_name`**
  - *Doc:* Fuzzy-match a tool name. LLMs (gemma4 in particular) often drop
- **`call`**
  - *Doc:* Invoke a registered tool. Falls back to fuzzy name resolution before
- **`_coerce_args`**
  - *Doc:* Remap argument names when the LLM hallucinates parameter aliases.

---

## `backend\core\tools\reminders.py`
- **Type:** Python Module
- **Lines:** 116

**Module Docstring:**
```text
Reminders + timers (Phase 11c).

Uses threading.Timer for scheduling. On fire, the message is spoken aloud via
Piper. Reminders are in-memory only — daemon restart clears them.

Each reminder has an integer id you can use with cancel_reminder.
```

### Functions
- **`_speak_async`**
  - *Doc:* Speak `text` in a fresh thread so the Timer thread returns quickly
- **`_schedule`**
- **`set_reminder`**
  - *Doc:* Schedule a spoken reminder. After `minutes` minutes, SG_CUBE will say
- **`set_timer`**
  - *Doc:* Start a countdown timer. After `seconds` seconds, SG_CUBE will say
- **`list_reminders`**
  - *Doc:* List active reminders and timers with their remaining time.
- **`cancel_reminder`**
  - *Doc:* Cancel a scheduled reminder or timer by its id (from list_reminders).

---

## `backend\core\tools\sandbox.py`
- **Type:** Python Module
- **Lines:** 67

### Classes
- **`PermissionDenied`**
- **`PendingConfirmation`**
  - *Methods:* __init__
- **`PermissionGuard`**
  - *Doc:* Intercepts tool calls to enforce security levels.
  - *Methods:* __init__, check, confirm

---

## `backend\core\tools\summarize.py`
- **Type:** Python Module
- **Lines:** 200

**Module Docstring:**
```text
Summarize tools (Phase 11e) — PDFs, web pages, and source files.

All three flow the same way: extract text → LLM (gemma4) → short summary.
```

### Functions
- **`_resolve_file`**
  - *Doc:* Resolve `name` to a real file path.
- **`summarize_pdf`**
  - *Doc:* Summarize a PDF file. `file` is a full path or a substring of a PDF
- **`summarize_url`**
  - *Doc:* Summarize a web page. Fetches `url`, strips HTML to text with
- **`explain_code`**
  - *Doc:* Explain what a source code file does in three short sentences.

---

## `backend\core\tools\system_info.py`
- **Type:** Python Module
- **Lines:** 32

### Functions
- **`get_battery`**
  - *Doc:* Return current battery percentage and charging status.
- **`get_system_status`**
  - *Doc:* Return CPU% (0.5s sample) and RAM% used.

---

## `backend\core\tools\translate.py`
- **Type:** Python Module
- **Lines:** 66

**Module Docstring:**
```text
Translation tool (Phase 11e) — uses gemma4 as the translator.

No external API; the same Ollama model that does reasoning handles the
translation. Quality is good for common language pairs.
```

### Functions
- **`translate`**
  - *Doc:* Translate `text` to `target_language`. Common names and ISO codes work:

---

## `backend\core\tools\weather.py`
- **Type:** Python Module
- **Lines:** 204

**Module Docstring:**
```text
Weather tools (Phase 11d) — Open-Meteo (free, no API key).

- Default location is inferred from the user's IP once per process and cached.
- Geocoding (city name → coords) via Open-Meteo's free endpoint.
- Forecast is current weather + next-N-day daily summary.
```

### Functions
- **`_get_default_location`**
- **`_geocode`**
  - *Doc:* City name -> {latitude, longitude, name, country}.
- **`_describe`**
- **`get_weather`**
  - *Doc:* Get current weather for `location` (a city name). If `location` is
- **`_fetch_current`**
- **`get_weather_forecast`**
  - *Doc:* Get a daily forecast for the next `days` days (default 3, max 7).

---

## `backend\core\tools\windowing.py`
- **Type:** Python Module
- **Lines:** 112

**Module Docstring:**
```text
Window management + power tools (Phase 11b).

Window mgmt via pygetwindow + pyautogui hotkeys. Power via shutdown.exe / rundll32.
```

### Functions
- **`minimize_all`**
  - *Doc:* Minimize every window and show the desktop (Win+D).
- **`focus_window`**
  - *Doc:* Bring a window to the front by matching its title against `app`.
- **`close_active_window`**
  - *Doc:* Close the currently focused window (Alt+F4).
- **`list_open_windows`**
  - *Doc:* List the titles of all open windows.
- **`lock_screen`**
  - *Doc:* Lock the workstation (Win+L).
- **`sleep_pc`**
  - *Doc:* Put the PC to sleep after a `seconds` countdown (default 5).
- **`shutdown_pc`**
  - *Doc:* Shut down the PC after a `seconds` countdown (default 10).
- **`restart_pc`**
  - *Doc:* Restart the PC after a `seconds` countdown (default 10).
- **`cancel_shutdown`**
  - *Doc:* Cancel a pending shutdown or restart.

---

## `backend\core\vision\capture.py`
- **Type:** Python Module
- **Lines:** 48

### Functions
- **`capture_screen`**
  - *Doc:* Capture the full screen and the active window title.

---

## `backend\core\vision\vlm.py`
- **Type:** Python Module
- **Lines:** 45

### Functions
- **`analyze_screenshot`**
  - *Doc:* Use a local VLM to summarize the screenshot.

---

## `backend\daemon\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\daemon\clipboard_watcher.py`
- **Type:** Python Module
- **Lines:** 46

### Classes
- **`ClipboardWatcher`**
  - *Methods:* __init__, _get_clipboard, start, stop, _watch

---

## `backend\daemon\main.py`
- **Type:** Python Module
- **Lines:** 139

### Functions
- **`_run_terminal`**
- **`_run_tray`**
- **`_run_headless`**
- **`main`**

---

## `backend\daemon\tray.py`
- **Type:** Python Module
- **Lines:** 56

### Classes
- **`TrayController`**
  - *Doc:* Manages the SG_CUBE system tray icon. Must run on the main thread on Windows.
  - *Methods:* __init__, _quit_clicked, run, stop

### Functions
- **`_generate_default_icon`**
  - *Doc:* Pillow-generated fallback when assets/tray.png is missing.
- **`_load_icon`**

---

## `backend\daemon\trigger.py`
- **Type:** Python Module
- **Lines:** 286

### Functions
- **`_play_chime`**
  - *Doc:* Play assets/chime.wav if present; fall back to a generated sine tone
- **`_save_wav`**
- **`_spoken_response`**
- **`_emit`**
- **`on_wake_detected`**
  - *Doc:* Fires the instant the wake phrase is recognised.
- **`_speak_selective`**
  - *Doc:* Speak locally or push audio to a remote device.
- **`handle_wake`**
  - *Doc:* Synchronous entry point for the wake word listener.
- **`_process_and_execute`**
- **`_handle_wake_async`**
  - *Doc:* Main daemon orchestration via async events.
- **`on_proactive_event`**
  - *Doc:* Handle events fired by the Watcher Agent in the background.
- **`_handle_proactive_async`**

---

## `backend\daemon\ui.py`
- **Type:** Python Module
- **Lines:** 393

### Classes
- **`Panel`**
  - *Doc:* Bordered container with a titled header and a body identified by `body_id`.
  - *Methods:* __init__, compose, on_mount
- **`SGCubeApp`**
  - *Methods:* __init__, _confidence_body, _refresh_confidence, compose, on_mount, on_unmount, _tick_clock, _minimize, _restore, _schedule_idle_minimize, _routing_body, _refresh_routing, _refresh_recent, handle_daemon_event

### Functions
- **`_wordmark`**
- **`_bar`**
- **`main`**

---

## `backend\daemon\ui_events.py`
- **Type:** Python Module
- **Lines:** 112

**Module Docstring:**
```text
Typed events emitted by trigger.handle_wake() and consumed by the Textual UI.

Using dataclasses lets us pattern-match in the UI dispatcher and stay decoupled
from the daemon internals.
```

### Classes
- **`WakeHeard`**
- **`CommandTranscribed`**
- **`IntentResolved`**
- **`Executed`**
- **`SpokenResponse`**
- **`ClipboardChangedEvent`**
- **`HandoverEvent`**
- **`TriggerError`**
- **`VerificationEvent`**
- **`ReliabilityMetrics`**
- **`ConfidenceEvent`**
- **`SelfHealingEvent`**
- **`InternalAgentEvent`**
- **`TokenStreamEvent`**
- **`AgentThinkingEvent`**
- **`ProactiveEvent`**

---

## `backend\daemon\vision_loop.py`
- **Type:** Python Module
- **Lines:** 94

### Classes
- **`VisionLoop`**
  - *Doc:* Background service that periodically 'looks' at the screen.
  - *Methods:* __init__, start, stop, _run_loop, _step

---

## `backend\daemon\wake_word.py`
- **Type:** Python Module
- **Lines:** 258

### Classes
- **`WakeWordListener`**
  - *Doc:* Continuously samples the mic and fires `on_wake(captured_audio_bytes)`
  - *Methods:* __init__, _cb, _drain, _capture, listen, stop

---

## `backend\database\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\database\chroma_db\047813c6-197c-4e43-8b5b-db2a6a02fd2c\data_level0.bin`
- **Type:** Binary File

---

## `backend\database\chroma_db\047813c6-197c-4e43-8b5b-db2a6a02fd2c\header.bin`
- **Type:** Binary File

---

## `backend\database\chroma_db\047813c6-197c-4e43-8b5b-db2a6a02fd2c\length.bin`
- **Type:** Binary File

---

## `backend\database\chroma_db\047813c6-197c-4e43-8b5b-db2a6a02fd2c\link_lists.bin`
- **Type:** Non-Python File
- **Lines:** 0

---

## `backend\database\chroma_db\22cdf2fd-c31a-4be4-a001-a8f2a12fdf4c\data_level0.bin`
- **Type:** Binary File

---

## `backend\database\chroma_db\22cdf2fd-c31a-4be4-a001-a8f2a12fdf4c\header.bin`
- **Type:** Binary File

---

## `backend\database\chroma_db\22cdf2fd-c31a-4be4-a001-a8f2a12fdf4c\length.bin`
- **Type:** Binary File

---

## `backend\database\chroma_db\22cdf2fd-c31a-4be4-a001-a8f2a12fdf4c\link_lists.bin`
- **Type:** Non-Python File
- **Lines:** 0

---

## `backend\database\chroma_db\904412e9-fea1-4470-b00e-4bff366b8966\data_level0.bin`
- **Type:** Binary File

---

## `backend\database\chroma_db\904412e9-fea1-4470-b00e-4bff366b8966\header.bin`
- **Type:** Binary File

---

## `backend\database\chroma_db\904412e9-fea1-4470-b00e-4bff366b8966\length.bin`
- **Type:** Binary File

---

## `backend\database\chroma_db\904412e9-fea1-4470-b00e-4bff366b8966\link_lists.bin`
- **Type:** Non-Python File
- **Lines:** 0

---

## `backend\database\chroma_db\chroma.sqlite3`
- **Type:** Binary File

---

## `backend\database\migrations\0001_init.sql`
- **Type:** Non-Python File
- **Lines:** 109

---

## `backend\database\supabase_client.py`
- **Type:** Python Module
- **Lines:** 23

### Functions
- **`get_anon_client`**
  - *Doc:* Anon-key client. Respects RLS. Use for end-user-acting calls.
- **`get_service_client`**
  - *Doc:* Service-role client. BYPASSES RLS. Backend-only — never expose to clients.

---

## `backend\logs\.gitkeep`
- **Type:** Non-Python File
- **Lines:** 0

---

## `backend\server\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\server\config.py`
- **Type:** Python Module
- **Lines:** 31

### Classes
- **`Settings`**

---

## `backend\server\main.py`
- **Type:** Python Module
- **Lines:** 27

### Functions
- **`health`**

---

## `backend\server\routes\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `backend\server\routes\admin.py`
- **Type:** Python Module
- **Lines:** 52

### Functions
- **`list_requests`**
- **`approve`**
- **`reject`**

---

## `backend\server\routes\auth.py`
- **Type:** Python Module
- **Lines:** 37

### Classes
- **`RegisterRequest`**
- **`LoginRequest`**

### Functions
- **`register`**
- **`login`**
- **`whoami`**

---

## `backend\server\routes\execute.py`
- **Type:** Python Module
- **Lines:** 17

### Functions
- **`execute_endpoint`**

---

## `backend\server\routes\orchestrate.py`
- **Type:** Python Module
- **Lines:** 30

### Classes
- **`ProcessRequest`**

### Functions
- **`process`**

---

## `backend\server\routes\remote.py`
- **Type:** Python Module
- **Lines:** 199

### Classes
- **`RemoteConnection`**
  - *Methods:* __init__, _check_local, send_json, send_bytes
- **`RemoteManager`**
  - *Methods:* __init__, _setup_event_bridge, _broadcast_event, broadcast, _serialize_event, connect, disconnect, broadcast_bytes_to_device

### Functions
- **`websocket_endpoint`**

---

## `backend\server\routes\voice.py`
- **Type:** Python Module
- **Lines:** 175

### Classes
- **`SayRequest`**

### Functions
- **`transcribe_endpoint`**
- **`say_endpoint`**
- **`_build_spoken_response`**
- **`process_endpoint`**
  - *Doc:* End-to-end voice loop: audio → STT → orchestrate → execute → TTS reply.

---

## `requirements.txt`
- **Type:** Non-Python File
- **Lines:** 62

---

## `resources\Screenshot 2026-03-13 092901.png`
- **Type:** Binary File

---

## `resources\ieeePaperProject.pdf`
- **Type:** Binary File

---

## `resources\terminal_theme.png`
- **Type:** Binary File

---

## `resources\theme.jpg`
- **Type:** Binary File

---

## `scratch_cube.py`
- **Type:** Python Module
- **Lines:** 30

---

## `scratch_rich.py`
- **Type:** Python Module
- **Lines:** 36

---

## `tests\__init__.py`
- **Type:** Python Module
- **Lines:** 0

---

## `tools\_recordings\clip.wav`
- **Type:** Binary File

---

## `tools\_recordings\demo.wav`
- **Type:** Binary File

---

## `tools\chat.py`
- **Type:** Python Module
- **Lines:** 85

**Module Docstring:**
```text
Interactive type-to-chat REPL for the agent.

No mic, no STT, no TTS — just type what you'd say to SG_CUBE and see what
gemma calls and what it would speak back. Conversation context is kept
across turns, so follow-ups work.

Usage:
    python tools/chat.py

Commands inside the REPL:
    /tools    list registered tools
    /history  show conversation context
    /clear    reset conversation context
    /quit     exit
```

### Functions
- **`main`**

---

## `tools\check_supabase.py`
- **Type:** Python Module
- **Lines:** 16

---

## `tools\demo.py`
- **Type:** Python Module
- **Lines:** 67

**Module Docstring:**
```text
Phase 8 end-to-end demo:
   record 5s from your mic → POST /voice/process → app runs the command,
   speaks the response, and prints the structured result.

Usage:
    python tools/demo.py                     # records 5s, default user
    python tools/demo.py --duration 8
    python tools/demo.py --device "Rockerz"  # specific input device
```

### Functions
- **`login`**
- **`process`**
- **`main`**

---

## `tools\diagnose_mic.py`
- **Type:** Python Module
- **Lines:** 74

**Module Docstring:**
```text
Sweep every input device, record 2 seconds from each, report peak amplitude.

Use this when audio recording is unexpectedly silent. The device with the
highest peak while you speak is the one to pass via --device <index>.

Usage:
    python tools/diagnose_mic.py
    python tools/diagnose_mic.py --seconds 3
```

### Functions
- **`main`**

---

## `tools\download_piper_voice.py`
- **Type:** Python Module
- **Lines:** 46

**Module Docstring:**
```text
Download a Piper voice model + config from HuggingFace.

Usage:
    python tools/download_piper_voice.py                       # default: en_US-ryan-high
    python tools/download_piper_voice.py en_US-lessac-medium

Voice naming: <lang_country>-<speaker>-<quality>
Browse the full catalog at https://huggingface.co/rhasspy/piper-voices
```

### Functions
- **`_voice_subpath`**
- **`download`**

---

## `tools\download_vosk_model.py`
- **Type:** Python Module
- **Lines:** 61

**Module Docstring:**
```text
Download a Vosk acoustic model and unpack it into backend/ai_modules/speech/vosk_models/.

Usage:
    python tools/download_vosk_model.py                       # default small English model
    python tools/download_vosk_model.py vosk-model-en-us-0.22-lgraph

Browse: https://alphacephei.com/vosk/models
```

### Functions
- **`download`**

---

## `tools\install_autostart.py`
- **Type:** Python Module
- **Lines:** 100

**Module Docstring:**
```text
Install / uninstall the SG_CUBE daemon as a Windows Task Scheduler entry
that runs at every user logon. Uses pythonw.exe so no console window appears.

Usage:
    python tools/install_autostart.py install
    python tools/install_autostart.py uninstall
    python tools/install_autostart.py status

Optional flags for `install`:
    --device 22       # input device index (default: system default mic)
    --task-name NAME  # override task name (default: SGCubeDaemon)

Notes:
- No admin required (uses /RL LIMITED).
- The task runs as the current user; it stops on logoff.
- Re-running `install` overwrites the existing task.
```

### Functions
- **`_ensure_prereqs`**
- **`install`**
- **`uninstall`**
- **`status`**
- **`main`**

---

## `tools\pre_load_whisper.py`
- **Type:** Python Module
- **Lines:** 5

---

## `tools\record_clip.py`
- **Type:** Python Module
- **Lines:** 104

**Module Docstring:**
```text
Record a short audio clip from a microphone and save as WAV.

Usage:
    python tools/record_clip.py                     # 5s, default mic, default path
    python tools/record_clip.py --duration 8
    python tools/record_clip.py --device 22         # use input device #22
    python tools/record_clip.py --device "Rockerz"  # match by substring
    python tools/record_clip.py --list              # list input devices and exit

Records 16kHz mono int16 PCM (what Whisper wants).
```

### Functions
- **`list_input_devices`**
- **`resolve_device`**
- **`record`**

---

## `tools\run_daemon.py`
- **Type:** Python Module
- **Lines:** 18

**Module Docstring:**
```text
Launch the SG_CUBE always-on wake-word daemon.

Says "onyx" to wake it, then your command in the next 5 seconds.
Example: "onyx" ... beep ... "open notepad"

Usage:
    python tools/run_daemon.py
    python tools/run_daemon.py --device 22         # bluetooth headset (see record_clip.py --list)
    python tools/run_daemon.py --wake-phrase "hey onyx"
```

---

## `tools\test_action_approval.py`
- **Type:** Python Module
- **Lines:** 65

### Functions
- **`test_approval_levels`**

---

## `tools\test_agent_memory.py`
- **Type:** Python Module
- **Lines:** 32

### Functions
- **`test_agent_with_memory`**

---

## `tools\test_executor.py`
- **Type:** Python Module
- **Lines:** 102

**Module Docstring:**
```text
Phase 6 + 10a + 10b + 10c verification: call SafeExecutor.execute() with assorted Intents.

Default run: only side effect is opening Notepad (test 1). Validation/blocked
cases never spawn anything.

  python tools/test_executor.py

UAC run: also fires real Windows UAC prompts for regedit / task manager /
powershell. Click No on each dialog to keep the test non-destructive.

  python tools/test_executor.py --include-uac

Browser run: also opens 4 browser tabs (Google, YouTube search, YouTube watch
via yt-dlp first-result, and a URL). Close them after.

  python tools/test_executor.py --include-browser

  All three:  --include-uac --include-browser
```

### Functions
- **`main`**

---

## `tools\test_llm.py`
- **Type:** Python Module
- **Lines:** 41

**Module Docstring:**
```text
Phase 4 verification: send a phrase to Ollama, print parsed Intent.

Usage:
    python tools/test_llm.py "open notepad"
    python tools/test_llm.py "what time is it"
    python tools/test_llm.py "close chrome"

Requires Ollama running at http://localhost:11434 with the configured model
pulled (`ollama pull phi3` for default).
```

### Functions
- **`main`**

---

## `tools\test_noise_robustness.py`
- **Type:** Python Module
- **Lines:** 62

### Functions
- **`create_test_audio`**
- **`test_robustness`**

---

## `tools\test_orchestrate.py`
- **Type:** Python Module
- **Lines:** 56

**Module Docstring:**
```text
Phase 5 verification: send phrases through /orchestrate/process and print
which layer answered each one + latency.

Usage:  python tools/test_orchestrate.py
```

### Functions
- **`main`**

---

## `tools\test_phase13.py`
- **Type:** Python Module
- **Lines:** 58

### Functions
- **`manual_glance`**
- **`ask_agent`**
- **`run_test_1`**

---

## `tools\test_semantic_memory.py`
- **Type:** Python Module
- **Lines:** 56

### Functions
- **`run_tests`**

---

## `tools\test_transcribe.py`
- **Type:** Python Module
- **Lines:** 74

**Module Docstring:**
```text
End-to-end Phase 3 test:
  1. Record 5s from your mic
  2. Login to get a Supabase JWT
  3. POST the WAV to /voice/transcribe
  4. Print the transcribed text + latency

Usage:
    python tools/test_transcribe.py
    python tools/test_transcribe.py --duration 8
    TEST_USER_EMAIL=foo@gmail.com TEST_USER_PASSWORD=... python tools/test_transcribe.py

Requires the server running on http://127.0.0.1:8000.
```

### Functions
- **`login`**
- **`transcribe`**
- **`main`**

---

## `tools\test_trigger_rms.py`
- **Type:** Python Module
- **Lines:** 27

### Functions
- **`test_trigger_logic`**

---

## `tools\test_tts.py`
- **Type:** Python Module
- **Lines:** 26

**Module Docstring:**
```text
Phase 7 verification: speak a phrase via pyttsx3.

Side effect: AUDIO OUT. Plug in headphones if you don't want speakers.

Usage:
    python tools/test_tts.py
    python tools/test_tts.py "hello from onyx"
```

### Functions
- **`main`**

---

## `tools\test_vision_memory.py`
- **Type:** Python Module
- **Lines:** 42

### Functions
- **`test_vision_rag`**

---

## `tools\test_watcher.py`
- **Type:** Python Module
- **Lines:** 56

### Functions
- **`test_watcher`**

---

## `tools\verify_commander_gate.py`
- **Type:** Python Module
- **Lines:** 68

### Functions
- **`test_commander_gate`**

---

## `tools\verify_confidence.py`
- **Type:** Python Module
- **Lines:** 63

### Functions
- **`verify_tool_confidence`**

---

## `tools\verify_context.py`
- **Type:** Python Module
- **Lines:** 19

### Functions
- **`verify_context`**

---

## `tools\verify_reliability.py`
- **Type:** Python Module
- **Lines:** 52

### Functions
- **`verify_metrics`**

---

## `tools\verify_timeline.py`
- **Type:** Python Module
- **Lines:** 46

### Functions
- **`verify_timeline`**

---

## `tools\verify_wake_word.py`
- **Type:** Python Module
- **Lines:** 34

### Functions
- **`verify_onyx`**

---

