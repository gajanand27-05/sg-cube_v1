"""The log keeps turn metadata but not the user's words, Onyx's replies or
personal tool arguments unless LOG_TRANSCRIPTS is on (default off)."""
import logging

from backend.server.config import settings


def test_log_transcripts_is_off_by_default():
    from backend.server.config import Settings
    assert Settings.model_fields["log_transcripts"].default is False


def test_said_keeps_only_the_length_unless_log_transcripts(monkeypatch):
    from backend.core.privacy import said

    monkeypatch.setattr(settings, "log_transcripts", False)
    assert said("call my doctor about the results") == "<32 chars>"
    monkeypatch.setattr(settings, "log_transcripts", True)
    assert said("call my doctor") == "'call my doctor'"


def test_the_formatter_drops_query_strings_unless_log_transcripts(monkeypatch):
    from backend.daemon.main import RedactingFormatter

    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0,
                            '127.0.0.1:5 - "GET /memory/search?q=my+doctor HTTP/1.1" 200', None, None)
    fmt = RedactingFormatter("%(message)s")
    monkeypatch.setattr(settings, "log_transcripts", False)
    assert fmt.format(rec) == '127.0.0.1:5 - "GET /memory/search?<query> HTTP/1.1" 200'
    monkeypatch.setattr(settings, "log_transcripts", True)
    assert "q=my+doctor" in fmt.format(rec)


def test_a_turns_command_is_not_logged_by_default(monkeypatch, caplog):
    """End to end on one real site: the timeline line for a user query."""
    from backend.core.memory.timeline import timeline

    monkeypatch.setattr(settings, "log_transcripts", False)
    with caplog.at_level(logging.INFO, logger="backend.core.memory.timeline"):
        try:
            timeline.record_event("User asked: remind me about my blood test", "user_query")
        except Exception:
            pass
    assert "blood test" not in caplog.text
