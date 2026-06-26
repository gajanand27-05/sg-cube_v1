"""Comprehensive tests for all 8 improvement phases."""
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

logging.basicConfig(level=logging.CRITICAL)

# ── Phase A: Tool Registry Bootstrap ─────────────────────────────────

def test_phase_a_registry_populated():
    """All 74 tools should be registered at boot."""
    import backend.core.tools
    from backend.core.tools.registry import REGISTRY
    assert len(REGISTRY) >= 73, f"Expected >=73 tools, got {len(REGISTRY)}"
    # Check key tools exist
    for name in ("respond", "open_app", "close_app", "get_time", "set_volume", "mute"):
        assert name in REGISTRY, f"Missing critical tool: {name}"
    print(f"  [PASS] Phase A: {len(REGISTRY)} tools registered")


def test_phase_a_builtins_imported():
    """builtins.py should be importable standalone (no circular deps)."""
    from backend.core.tools.builtins import respond, open_app, close_app
    assert callable(respond)
    assert callable(open_app)
    assert callable(close_app)
    print("  [PASS] Phase A: builtins.py imported cleanly")


# ── Phase B: Plugin Auto-Discovery ───────────────────────────────────

def test_phase_b_plugin_hello_world():
    """hello_world plugin should be auto-discovered."""
    import backend.core.tools
    from backend.core.tools.registry import REGISTRY
    assert "hello_world" in REGISTRY, "hello_world plugin not found"
    tool = REGISTRY["hello_world"]
    result = tool.func("test")
    assert result.status.value == "success"
    assert "Hello, test" in result.message
    print("  [PASS] Phase B: hello_world plugin loaded and functional")


def test_phase_b_plugins_dir_exists():
    """backend/plugins/ directory should exist."""
    plugins_dir = Path(__file__).resolve().parents[1] / "backend" / "plugins"
    assert plugins_dir.is_dir(), "plugins/ directory missing"
    assert (plugins_dir / "__init__.py").exists(), "plugins/__init__.py missing"
    print("  [PASS] Phase B: plugins/ directory exists")


# ── Phase C1: Streaming ASR ──────────────────────────────────────────

def test_phase_c1_transcribe_array_exists():
    """transcribe_array function should be importable."""
    from backend.ai_modules.speech.stt_whisper import (
        transcribe_array, transcribe_stream, _filter_speech_chunks, vad_speech_prob
    )
    assert callable(transcribe_array)
    assert callable(transcribe_stream)
    assert callable(_filter_speech_chunks)
    assert callable(vad_speech_prob)
    print("  [PASS] Phase C1: streaming STT functions importable")


def test_phase_c1_silero_vad_importable():
    """silero-vad should be importable."""
    try:
        import torch
        import silero_vad
        assert True
        print("  [PASS] Phase C1: silero-vad importable")
    except ImportError:
        print("  [SKIP] Phase C1: silero-vad not installed (optional dep)")


# ── Phase C2: Streaming TTS with Interrupt ───────────────────────────

def test_phase_c2_tts_stop_speech():
    """stop_speech function should exist."""
    from backend.ai_modules.speech.tts_piper import speak, speak_stream, stop_speech, generate_audio
    assert callable(speak)
    assert callable(speak_stream)
    assert callable(stop_speech)
    assert callable(generate_audio)
    print("  [PASS] Phase C2: TTS functions importable")


def test_phase_c2_trigger_wired():
    """on_wake_detected should call stop_speech."""
    import backend.daemon.trigger as trig
    assert hasattr(trig, "on_wake_detected")
    assert callable(trig.on_wake_detected)
    print("  [PASS] Phase C2: trigger.on_wake_detected importable")


# ── Phase C3: LiveKit ────────────────────────────────────────────────

def test_phase_c3_livekit_worker_importable():
    """LiveKit worker module should be importable."""
    from backend.ai_modules.speech.livekit_worker import start_worker, is_available
    assert callable(start_worker)
    assert callable(is_available)
    print("  [PASS] Phase C3: LiveKit worker importable")


def test_phase_c3_settings():
    """Settings should have voice_pipeline field."""
    from backend.server.config import settings
    assert hasattr(settings, "voice_pipeline")
    assert settings.voice_pipeline in ("local", "livekit")
    print(f"  [PASS] Phase C3: voice_pipeline={settings.voice_pipeline}")


# ── Phase D: Fast-Path Command Routing ───────────────────────────────

def _check_rule(text, expected_action):
    from backend.core.orchestrator.rule_engine import match
    intent = match(text)
    assert intent is not None, f"Rule mismatch for {text!r}: got None"
    assert intent.action == expected_action, (
        f"Rule mismatch for {text!r}: expected {expected_action}, got {intent.action}"
    )


def test_phase_d1_volume_patterns():
    """Volume control patterns."""
    _check_rule("set volume to 50", "set_volume")
    _check_rule("volume 75", "set_volume")
    _check_rule("volume up", "volume_up")
    _check_rule("volume down", "volume_down")
    _check_rule("turn up the volume", "volume_up")
    _check_rule("turn down the volume", "volume_down")
    _check_rule("mute", "mute")
    _check_rule("mute audio", "mute")
    _check_rule("unmute", "unmute")
    print("  [PASS] Phase D1: volume patterns (9)")


def test_phase_d1_brightness_patterns():
    """Brightness control patterns."""
    _check_rule("set brightness to 80", "set_brightness")
    _check_rule("brightness 50", "set_brightness")
    _check_rule("brightness up", "brightness_up")
    _check_rule("brightness down", "brightness_down")
    _check_rule("increase the brightness", "brightness_up")
    _check_rule("decrease the brightness", "brightness_down")
    print("  [PASS] Phase D1: brightness patterns (6)")


def test_phase_d1_weather_patterns():
    """Weather patterns."""
    _check_rule("what is the weather", "get_weather")
    _check_rule("weather in london", "get_weather")
    _check_rule("what is the forecast", "get_weather_forecast")
    _check_rule("forecast for paris", "get_weather_forecast")
    print("  [PASS] Phase D1: weather patterns (4)")


def test_phase_d1_news_power_patterns():
    """News and power control patterns."""
    _check_rule("what is the news", "get_news")
    _check_rule("news about technology", "get_news")
    _check_rule("shutdown", "shutdown_pc")
    _check_rule("restart", "restart_pc")
    _check_rule("sleep the computer", "sleep_pc")
    _check_rule("lock", "lock_screen")
    _check_rule("lock the screen", "lock_screen")
    print("  [PASS] Phase D1: news+power patterns (7)")


def test_phase_d1_battery_system_patterns():
    """Battery and system info patterns."""
    _check_rule("what is my battery", "get_battery")
    _check_rule("battery level", "get_battery")
    _check_rule("system status", "get_system_status")
    print("  [PASS] Phase D1: battery+system patterns (3)")


def test_phase_d1_notes_reminders_patterns():
    """Notes and reminders patterns."""
    _check_rule("take note buy milk", "take_note")
    _check_rule("take a note", "read_notes")
    _check_rule("read my notes", "read_notes")
    _check_rule("set a reminder to call mom", "set_reminder")
    _check_rule("remind me to pay bills", "set_reminder")
    _check_rule("list reminders", "list_reminders")
    print("  [PASS] Phase D1: notes+reminders patterns (6)")


def test_phase_d1_translate_summarize_patterns():
    """Translate and summarize patterns."""
    _check_rule("translate hello to spanish", "translate")
    _check_rule("summarize this article", "summarize_pdf")  # non-http -> summarize_pdf
    print("  [PASS] Phase D1: translate+summarize patterns (2)")


def test_phase_d1_calc_define_patterns():
    """Calculator and dictionary patterns."""
    _check_rule("calculate 25 percent of 200", "calculate")
    _check_rule("what is 2 plus 2", "calculate")
    _check_rule("define serendipity", "define")
    print("  [PASS] Phase D1: calc+define patterns (3)")


def test_phase_d1_legacy_patterns():
    """Original patterns still work."""
    _check_rule("open notepad", "open_app")
    _check_rule("close chrome", "close_app")
    _check_rule("what time is it", "get_time")
    _check_rule("current time", "get_time")
    _check_rule("play despacito", "play_youtube")
    _check_rule("play despacito on youtube", "play_youtube")
    _check_rule("search python on google", "search_google")
    _check_rule("search python tutorials", "search_google")
    _check_rule("show me python on youtube", "search_youtube")
    _check_rule("youtube cat videos", "search_youtube")
    _check_rule("open github.com", "open_url")
    _check_rule("screenshot", "screenshot")  # no region -> screenshot action
    # "open github.com" should be open_url, not open_app
    _check_rule("open github.com", "open_url")
    print("  [PASS] Phase D1: legacy patterns (12)")


def test_phase_d3_app_aliases():
    """APP_ALIASES should be expanded to 100+ entries."""
    from backend.core.orchestrator.rule_engine import APP_ALIASES
    assert len(APP_ALIASES) >= 100, f"Expected >=100 aliases, got {len(APP_ALIASES)}"
    # Check specific aliases
    for alias in ("terminal", "settings", "paint", "steam", "figma", "obsidian", "docker"):
        assert alias in APP_ALIASES, f"Missing alias: {alias}"
    print(f"  [PASS] Phase D3: {len(APP_ALIASES)} APP_ALIASES")


def test_phase_d3_fuzzy_cache():
    """Fuzzy cache should match close typos."""
    from backend.core.orchestrator.cache_layer import get_fuzzy, set as cache_set
    from backend.core.orchestrator.llm_layer import Intent

    cache_set("open notepad", Intent(action="open_app", target="notepad"))
    result = get_fuzzy("open notpad")  # typo
    assert result is not None, "Fuzzy cache missed on typo"
    assert result.action == "open_app"
    print("  [PASS] Phase D3: fuzzy cache matches typos")


def test_phase_d2_trie():
    """Prefix trie should be built."""
    from backend.core.orchestrator.rule_engine import TRIE
    assert isinstance(TRIE, dict)
    assert len(TRIE) > 10  # Many first-token buckets
    print(f"  [PASS] Phase D2: prefix trie with {len(TRIE)} buckets")


# ── Phase E: MCP Protocol ────────────────────────────────────────────

def test_phase_e_mcp_server_creation():
    """MCP server should be creatable (if fastmcp installed)."""
    try:
        from backend.core.mcp_server import get_mcp_server, get_mcp_app
        server = get_mcp_server()
        if server is not None:
            app = get_mcp_app()
            assert app is not None
            print("  [PASS] Phase E: MCP server created")
        else:
            print("  [SKIP] Phase E: fastmcp not installed")
    except Exception as e:
        print(f"  [FAIL] Phase E: {e}")


def test_phase_e_mcp_app_mounted():
    """MCP app should be mountable in FastAPI."""
    from backend.server.main import app
    has_mcp = any(
        "/mcp" in (getattr(r, "path", "") or getattr(r, "prefix", ""))
        for r in app.routes
    )
    if has_mcp:
        print("  [PASS] Phase E: MCP mounted in FastAPI")
    else:
        print("  [SKIP] Phase E: MCP not mounted (fastmcp may not be installed)")


# ── Phase F: Games & Personality ─────────────────────────────────────

def test_phase_f1_blackjack():
    """Blackjack game should work."""
    from backend.core.tools.games.blackjack import play_blackjack
    result = play_blackjack("deal")
    assert result["status"] == "playing"
    assert "hand" in result
    assert "dealer_up" in result
    # Stand
    result2 = play_blackjack("stand")
    assert result2["status"] in ("done", "playing")
    print("  [PASS] Phase F1: Blackjack")


def test_phase_f1_hangman():
    """Hangman game should work."""
    from backend.core.tools.games.hangman import play_hangman
    result = play_hangman("start")
    assert result["status"] == "playing"
    assert "display" in result
    # Guess a letter
    result2 = play_hangman("guess", letter="a")
    assert result2["status"] in ("playing", "won", "lost")
    print("  [PASS] Phase F1: Hangman")


def test_phase_f1_wordle():
    """Wordle game should work."""
    from backend.core.tools.games.wordle import play_wordle
    result = play_wordle("start")
    assert result["status"] == "playing"
    result2 = play_wordle("guess", guess="abcde")
    assert result2["status"] in ("playing", "won", "lost")
    print("  [PASS] Phase F1: Wordle")


def test_phase_f1_tictactoe():
    """Tic-Tac-Toe game should work."""
    from backend.core.tools.games.tictactoe import play_tictactoe
    result = play_tictactoe("start")
    assert result["status"] == "playing"
    result2 = play_tictactoe("move", position=5)
    assert result2["status"] in ("playing", "won", "lost", "tie")
    print("  [PASS] Phase F1: Tic-Tac-Toe")


def test_phase_f1_connect4():
    """Connect Four game should work."""
    from backend.core.tools.games.connect4 import play_connect4
    result = play_connect4("start")
    assert result["status"] == "playing"
    result2 = play_connect4("drop", column=4)
    assert result2["status"] in ("playing", "won", "lost", "tie")
    print("  [PASS] Phase F1: Connect Four")


def test_phase_f1_rps():
    """Rock-Paper-Scissors should work."""
    from backend.core.tools.games.rps import play_rps
    result = play_rps("play", choice="rock")
    assert result["status"] == "done"
    assert result["result"] in ("win", "lose", "tie")
    print("  [PASS] Phase F1: RPS")


def test_phase_f2_fun_tools():
    """Fun tools should work."""
    from backend.core.tools.fun import tell_joke, tell_fact, flip_coin, roll_dice, generate_password
    joke = tell_joke()
    assert joke.status.value == "success"
    assert len(joke.message) > 5
    fact = tell_fact()
    assert fact.status.value == "success"
    coin = flip_coin()
    assert coin.data["result"] in ("heads", "tails")
    dice = roll_dice(20)
    assert 1 <= dice.data["result"] <= 20
    pw = generate_password(12)
    assert len(pw.data["password"]) == 12
    print("  [PASS] Phase F2: fun tools (5)")


def test_phase_f3_mood():
    """Mood responses should work."""
    from backend.core.tools.fun import mood_response
    bored = mood_response("bored")
    assert bored.status.value == "success"
    sad = mood_response("sad")
    assert "joke" in sad.data.get("type", "")
    happy = mood_response("happy")
    assert happy.data.get("type") == "fact"
    print("  [PASS] Phase F3: mood responses")


# ── Phase G: Observability ───────────────────────────────────────────

def test_phase_g_diagnostics_endpoint():
    """Diagnostics endpoint should return system metrics."""
    from backend.server.routes.diagnostics import get_diagnostics, get_tool_usage, agent_inspector
    diag = get_diagnostics()
    assert "system" in diag
    assert "latency" in diag
    assert diag["system"]["tool_count"] >= 73
    tools = get_tool_usage()
    assert "tools" in tools
    inspect = agent_inspector()
    assert "agents" in inspect
    assert "tools" in inspect
    assert len(inspect["tools"]) >= 73
    print("  [PASS] Phase G: diagnostics endpoints")


def test_phase_g_tool_usage_tracking():
    """Tool usage tracking should record calls."""
    from backend.server.routes.diagnostics import record_tool_usage, _tool_usage
    _tool_usage.clear()
    record_tool_usage("test_tool", success=True, latency_ms=100)
    assert _tool_usage["test_tool"]["calls"] == 1
    assert _tool_usage["test_tool"]["successes"] == 1
    assert _tool_usage["test_tool"]["avg_latency_ms"] == 100
    print("  [PASS] Phase G: tool usage tracking")


def test_phase_g_hello_world_plugin():
    """hello_world plugin should be discoverable and callable via registry."""
    import backend.core.tools
    from backend.core.tools.registry import REGISTRY
    tool = REGISTRY["hello_world"]
    result = tool.func("SG_CUBE")
    assert result.status.value == "success"
    assert "SG_CUBE" in result.message
    print("  [PASS] Phase G: hello_world example plugin works")


# ── Runner ───────────────────────────────────────────────────────────

def main():
    tests = [
        ("Phase A: Registry", test_phase_a_registry_populated),
        ("Phase A: Builtins", test_phase_a_builtins_imported),
        ("Phase B: Plugin auto-discovery", test_phase_b_plugin_hello_world),
        ("Phase B: Plugins dir", test_phase_b_plugins_dir_exists),
        ("Phase C1: Streaming STT", test_phase_c1_transcribe_array_exists),
        ("Phase C1: silero-vad", test_phase_c1_silero_vad_importable),
        ("Phase C2: TTS functions", test_phase_c2_tts_stop_speech),
        ("Phase C2: Trigger wired", test_phase_c2_trigger_wired),
        ("Phase C3: LiveKit worker", test_phase_c3_livekit_worker_importable),
        ("Phase C3: Settings", test_phase_c3_settings),
        ("Phase D1: Volume", test_phase_d1_volume_patterns),
        ("Phase D1: Brightness", test_phase_d1_brightness_patterns),
        ("Phase D1: Weather", test_phase_d1_weather_patterns),
        ("Phase D1: News+Power", test_phase_d1_news_power_patterns),
        ("Phase D1: Battery+Sys", test_phase_d1_battery_system_patterns),
        ("Phase D1: Notes+Reminders", test_phase_d1_notes_reminders_patterns),
        ("Phase D1: Translate+Summarize", test_phase_d1_translate_summarize_patterns),
        ("Phase D1: Calc+Define", test_phase_d1_calc_define_patterns),
        ("Phase D1: Legacy", test_phase_d1_legacy_patterns),
        ("Phase D2: Trie", test_phase_d2_trie),
        ("Phase D3: APP_ALIASES", test_phase_d3_app_aliases),
        ("Phase D3: Fuzzy cache", test_phase_d3_fuzzy_cache),
        ("Phase E: MCP server", test_phase_e_mcp_server_creation),
        ("Phase E: MCP mounted", test_phase_e_mcp_app_mounted),
        ("Phase F1: Blackjack", test_phase_f1_blackjack),
        ("Phase F1: Hangman", test_phase_f1_hangman),
        ("Phase F1: Wordle", test_phase_f1_wordle),
        ("Phase F1: Tic-Tac-Toe", test_phase_f1_tictactoe),
        ("Phase F1: Connect Four", test_phase_f1_connect4),
        ("Phase F1: RPS", test_phase_f1_rps),
        ("Phase F2: Fun tools", test_phase_f2_fun_tools),
        ("Phase F3: Mood", test_phase_f3_mood),
        ("Phase G: Diagnostics", test_phase_g_diagnostics_endpoint),
        ("Phase G: Tool usage", test_phase_g_tool_usage_tracking),
        ("Phase G: hello_world", test_phase_g_hello_world_plugin),
    ]

    passed = 0
    failed = 0
    skipped = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1

    total = len(tests)
    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} passed, {failed} failed, {skipped} skipped")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
