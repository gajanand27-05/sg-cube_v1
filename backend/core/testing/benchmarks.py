"""Benchmark Suite — latency, throughput, accuracy measurements."""
import asyncio
import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from backend.core.brain import brain, BrainRequest

log = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parents[2] / "database" / "benchmarks"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class BenchmarkResult:
    """Single benchmark run result."""
    name: str
    iterations: int
    latencies_ms: list[int]
    errors: int
    timestamp: str
    metadata: dict = field(default_factory=dict)
    
    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0
    
    @property
    def p50_ms(self) -> float:
        return statistics.median(self.latencies_ms) if self.latencies_ms else 0
    
    @property
    def p95_ms(self) -> float:
        if not self.latencies_ms:
            return 0
        sorted_lat = sorted(self.latencies_ms)
        idx = int(len(sorted_lat) * 0.95)
        return sorted_lat[idx]
    
    @property
    def p99_ms(self) -> float:
        if not self.latencies_ms:
            return 0
        sorted_lat = sorted(self.latencies_ms)
        idx = int(len(sorted_lat) * 0.99)
        return sorted_lat[idx]
    
    @property
    def throughput_qps(self) -> float:
        total_s = sum(self.latencies_ms) / 1000.0
        return len(self.latencies_ms) / total_s if total_s > 0 else 0
    
    @property
    def error_rate(self) -> float:
        return self.errors / self.iterations if self.iterations > 0 else 0
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "avg_ms": round(self.avg_ms, 2),
            "p50_ms": round(self.p50_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "p99_ms": round(self.p99_ms, 2),
            "throughput_qps": round(self.throughput_qps, 2),
            "error_rate": round(self.error_rate, 4),
            "errors": self.errors,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class BenchmarkSuite:
    """Runs benchmark suite against the brain."""
    
    def __init__(self):
        self.results: list[BenchmarkResult] = []
    
    async def run_benchmark(self, name: str, queries: list[str], iterations: int = 10, 
                           user_id: str = "benchmark", input_mode: str = "text") -> BenchmarkResult:
        """Run a benchmark with given queries."""
        latencies = []
        errors = 0
        
        for i in range(iterations):
            query = queries[i % len(queries)]
            t0 = time.perf_counter()
            
            request = BrainRequest(
                user_id=user_id,
                input_text=query,
                input_mode=input_mode,
                session_id=f"bench_{name}_{i}",
                metadata={"benchmark": name, "iteration": i},
            )
            
            try:
                response = await brain.run(request)
                latencies.append(int((time.perf_counter() - t0) * 1000))
            except Exception as e:
                log.warning(f"Benchmark {name} iteration {i} failed: {e}")
                errors += 1
        
        result = BenchmarkResult(
            name=name,
            iterations=iterations,
            latencies_ms=latencies,
            errors=errors,
            timestamp=datetime.now().isoformat(),
            metadata={"queries": queries, "user_id": user_id},
        )
        
        self.results.append(result)
        return result
    
    def get_summary(self) -> dict:
        """Get summary of all benchmark results."""
        return {
            "benchmarks": [r.to_dict() for r in self.results],
            "total_iterations": sum(r.iterations for r in self.results),
            "total_errors": sum(r.errors for r in self.results),
        }
    
    def save_results(self, path: Path = None) -> Path:
        """Save benchmark results to JSON."""
        if path is None:
            path = RESULTS_DIR / f"benchmark_{int(time.time())}.json"
        
        data = {
            "timestamp": datetime.now().isoformat(),
            "results": [r.to_dict() for r in self.results],
            "summary": self.get_summary(),
        }
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        
        log.info(f"Benchmark results saved to {path}")
        return path


# Standard benchmark queries
STANDARD_QUERIES = {
    "simple_commands": [
        "open notepad",
        "close notepad",
        "what time is it",
        "lock screen",
        "set volume to 50",
    ],
    "web_interactions": [
        "search for python tutorials",
        "play lo-fi beats on youtube",
        "open github.com",
        "search google for ai news",
    ],
    "system_control": [
        "set brightness to 70",
        "mute audio",
        "take screenshot",
        "get battery level",
    ],
    "information_queries": [
        "what's the weather in london",
        "get news about technology",
        "calculate 15 * 24",
        "define artificial intelligence",
    ],
    "complex_multi_step": [
        "open notepad and type hello world",
        "search for python and open first result",
        "play music and set volume to 30",
    ],
}


async def run_full_benchmark_suite(iterations: int = 20) -> dict:
    """Run the full benchmark suite."""
    suite = BenchmarkSuite()
    
    for name, queries in STANDARD_QUERIES.items():
        log.info(f"Running benchmark: {name} ({iterations} iterations)")
        result = await suite.run_benchmark(name, queries, iterations=iterations)
        log.info(f"  {name}: avg={result.avg_ms:.0f}ms p95={result.p95_ms:.0f}ms throughput={result.throughput_qps:.2f} qps errors={result.errors}")
    
    path = suite.save_results()
    
    return {
        "summary": suite.get_summary(),
        "results_file": str(path),
    }


if __name__ == "__main__":
    import asyncio
    from datetime import datetime
    
    asyncio.run(run_full_benchmark_suite())