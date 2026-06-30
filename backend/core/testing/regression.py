"""Regression Testing Framework — canonical cases + execution verification."""
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from backend.core.brain import brain, BrainRequest
from backend.core.prompts.registry import prompt_registry

log = logging.getLogger(__name__)

CANONICAL_CASES_FILE = Path(__file__).resolve().parents[2] / "database" / "canonical_cases.yaml"


@dataclass
class CanonicalCase:
    """Single canonical test case."""
    name: str
    input_text: str
    input_mode: str = "text"
    expected_intent: dict = field(default_factory=dict)
    expected_tools: list[str] = field(default_factory=list)
    expected_response_contains: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class RegressionResult:
    """Result of running a regression test."""
    case_name: str
    passed: bool
    latency_ms: int
    actual_intent: dict
    actual_tools: list[str]
    actual_response: str
    diff: dict = field(default_factory=dict)
    error: str | None = None


class RegressionRunner:
    """Runs regression tests against canonical cases."""
    
    def __init__(self):
        self.cases: list[CanonicalCase] = []
        self.results: list[RegressionResult] = []
    
    def load_cases(self, file_path: Path = CANONICAL_CASES_FILE) -> int:
        """Load canonical cases from YAML file."""
        if not file_path.exists():
            log.warning(f"Canonical cases file not found: {file_path}")
            return 0
        
        import yaml
        with open(file_path) as f:
            data = yaml.safe_load(f)
        
        self.cases = []
        for case_data in data.get("cases", []):
            self.cases.append(CanonicalCase(**case_data))
        
        log.info(f"Loaded {len(self.cases)} canonical cases")
        return len(self.cases)
    
    def save_cases(self, file_path: Path = CANONICAL_CASES_FILE) -> None:
        """Save canonical cases to YAML file."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        import yaml
        data = {
            "cases": [
                {
                    "name": c.name,
                    "input_text": c.input_text,
                    "input_mode": c.input_mode,
                    "expected_intent": c.expected_intent,
                    "expected_tools": c.expected_tools,
                    "expected_response_contains": c.expected_response_contains,
                    "metadata": c.metadata,
                }
                for c in self.cases
            ]
        }
        with open(file_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        log.info(f"Saved {len(self.cases)} canonical cases to {file_path}")
    
    async def run_case(self, case: CanonicalCase) -> RegressionResult:
        """Run a single canonical case."""
        t0 = time.perf_counter()
        request_id = f"reg_{case.name}"
        
        request = BrainRequest(
            user_id="regression_test",
            input_text=case.input_text,
            input_mode=case.input_mode,
            session_id=request_id,
            metadata={"regression": True, "case": case.name},
        )
        
        try:
            response = await brain.run(request)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            
            actual_intent = response.intent
            actual_tools = [tc.name for tc in response.tool_calls]
            actual_response = response.spoken_text
            
            # Compare with expected
            diff = {}
            passed = True
            
            # Check intent
            if case.expected_intent:
                for key, expected in case.expected_intent.items():
                    actual = actual_intent.get(key)
                    if actual != expected:
                        diff[f"intent.{key}"] = {"expected": expected, "actual": actual}
                        passed = False
            
            # Check tools
            if case.expected_tools:
                expected_set = set(case.expected_tools)
                actual_set = set(actual_tools)
                if expected_set != actual_set:
                    diff["tools"] = {
                        "expected": sorted(expected_set),
                        "actual": sorted(actual_set),
                        "missing": sorted(expected_set - actual_set),
                        "extra": sorted(actual_set - expected_set),
                    }
                    passed = False
            
            # Check response contains
            if case.expected_response_contains:
                missing = [s for s in case.expected_response_contains if s not in actual_response]
                if missing:
                    diff["response_contains"] = {"missing": missing}
                    passed = False
            
            return RegressionResult(
                case_name=case.name,
                passed=passed,
                latency_ms=latency_ms,
                actual_intent=actual_intent,
                actual_tools=actual_tools,
                actual_response=actual_response,
                diff=diff,
            )
            
        except Exception as e:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            log.exception(f"Regression case {case.name} failed: {e}")
            return RegressionResult(
                case_name=case.name,
                passed=False,
                latency_ms=latency_ms,
                actual_intent={},
                actual_tools=[],
                actual_response="",
                error=str(e),
            )
    
    async def run_all(self) -> dict:
        """Run all canonical cases."""
        if not self.cases:
            self.load_cases()
        
        self.results = []
        for case in self.cases:
            log.info(f"Running regression case: {case.name}")
            result = await self.run_case(case)
            self.results.append(result)
            status = "PASS" if result.passed else "FAIL"
            log.info(f"  {case.name}: {status} ({result.latency_ms}ms)")
        
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        
        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "results": [
                {
                    "case": r.case_name,
                    "passed": r.passed,
                    "latency_ms": r.latency_ms,
                    "diff": r.diff,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


def create_default_canonical_cases() -> list[CanonicalCase]:
    """Create default canonical cases for SG_CUBE."""
    return [
        CanonicalCase(
            name="open_notepad",
            input_text="open notepad",
            input_mode="voice",
            expected_intent={"action": "open_app"},
            expected_tools=["open_app"],
            expected_response_contains=["opening", "notepad"],
        ),
        CanonicalCase(
            name="close_chrome",
            input_text="close chrome",
            input_mode="voice",
            expected_intent={"action": "close_app"},
            expected_tools=["close_app"],
            expected_response_contains=["closing", "chrome"],
        ),
        CanonicalCase(
            name="what_time",
            input_text="what time is it",
            input_mode="voice",
            expected_intent={"action": "get_time"},
            expected_tools=["get_time"],
            expected_response_contains=["time"],
        ),
        CanonicalCase(
            name="play_music",
            input_text="play lo-fi beats on youtube",
            input_mode="voice",
            expected_intent={"action": "play_youtube"},
            expected_tools=["play_youtube"],
            expected_response_contains=["playing", "lo-fi"],
        ),
        CanonicalCase(
            name="search_web",
            input_text="search for python tutorials",
            input_mode="text",
            expected_intent={"action": "search_google"},
            expected_tools=["search_web"],
            expected_response_contains=["searching", "python"],
        ),
        CanonicalCase(
            name="set_volume",
            input_text="set volume to 50",
            input_mode="voice",
            expected_intent={"action": "set_volume"},
            expected_tools=["set_volume"],
            expected_response_contains=["volume", "50"],
        ),
        CanonicalCase(
            name="weather_query",
            input_text="what's the weather in new york",
            input_mode="voice",
            expected_intent={"action": "get_weather"},
            expected_tools=["get_weather"],
            expected_response_contains=["weather"],
        ),
        CanonicalCase(
            name="lock_screen",
            input_text="lock my screen",
            input_mode="voice",
            expected_intent={"action": "lock_screen"},
            expected_tools=["lock_screen"],
            expected_response_contains=["lock"],
        ),
    ]


def initialize_canonical_cases():
    """Initialize default canonical cases if file doesn't exist."""
    if not CANONICAL_CASES_FILE.exists():
        cases = create_default_canonical_cases()
        runner = RegressionRunner()
        runner.cases = cases
        runner.save_cases()
        log.info(f"Created default canonical cases: {len(cases)}")


if __name__ == "__main__":
    initialize_canonical_cases()