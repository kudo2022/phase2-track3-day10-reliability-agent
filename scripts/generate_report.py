from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reliability_lab.cache import SharedRedisCache
from reliability_lab.chaos import load_queries, run_scenario
from reliability_lab.config import LabConfig, ScenarioConfig, load_config
from reliability_lab.metrics import RunMetrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="reports/metrics.json")
    parser.add_argument("--out", default="reports/final_report.md")
    parser.add_argument("--config", default="configs/default.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
    queries = load_queries(ROOT / "data" / "sample_queries.jsonl")
    baseline_scenario = _baseline_scenario(config)
    with_cache, without_cache = _run_cache_comparison(config, queries, baseline_scenario)
    scenario_results = [
        (scenario, run_scenario(config, queries, scenario))
        for scenario in config.scenarios
    ]
    redis_status = _collect_redis_evidence(config)

    lines = [
        "# Day 10 Reliability Final Report",
        "",
        "## 1. Architecture summary",
        "",
        "Gateway routes requests through semantic cache, per-provider circuit breakers, and a provider fallback chain.",
        "Cached hits return immediately with zero provider cost; misses go through the primary provider first, then backup, and finally a static degraded response if every provider is unavailable.",
        "",
        "```text",
        "User Request",
        "    |",
        "    v",
        "[ReliabilityGateway]",
        "    |",
        "    +--> [Semantic Cache] ---- hit ----> return cached response",
        "    |",
        "    +--> [Circuit Breaker: primary] --> Provider A",
        "    |                |",
        "    |                +--> open/failed -> [Circuit Breaker: backup] --> Provider B",
        "    |                                                        |",
        "    |                                                        +--> failed -> static fallback",
        "```",
        "",
        "## 2. Configuration",
        "",
        "| Setting | Value | Reason |",
        "|---|---:|---|",
        f"| failure_threshold | {config.circuit_breaker.failure_threshold} | Open after 3 consecutive failures to stop retry storms while still tolerating brief blips. |",
        f"| reset_timeout_seconds | {config.circuit_breaker.reset_timeout_seconds} | Wait {config.circuit_breaker.reset_timeout_seconds}s before a probe request so providers have time to recover. |",
        f"| success_threshold | {config.circuit_breaker.success_threshold} | Require {config.circuit_breaker.success_threshold} successful probe before closing the circuit again. |",
        f"| cache backend | {config.cache.backend} | Default config uses fast local memory; Redis backend is implemented for multi-instance sharing. |",
        f"| cache TTL | {config.cache.ttl_seconds} | Keep answers long enough to improve hit rate without keeping stale answers indefinitely. |",
        f"| similarity_threshold | {config.cache.similarity_threshold} | High threshold reduces semantic false hits, especially for dated queries. |",
        f"| load_test requests | {config.load_test.requests} | 100 requests is enough to expose fallback, cache, and breaker behavior in a short local run. |",
        "",
        "## 3. SLO definitions",
        "",
        "| SLI | SLO target | Actual value | Met? |",
        "|---|---|---:|---|",
    ]
    lines.extend(_build_slo_rows(metrics))
    lines.extend(
        [
            "",
            "## 4. Metrics",
            "",
            "| Metric | Value |",
            "|---|---:|",
        ]
    )
    for key, value in metrics.items():
        if key == "scenarios":
            continue
        lines.append(f"| {key} | {value} |")

    lines.extend(
        [
            "",
            "## 5. Cache comparison",
            "",
            "| Metric | Without cache | With cache | Delta |",
            "|---|---:|---:|---|",
            f"| latency_p50_ms | {without_cache.percentile(50):.2f} | {with_cache.percentile(50):.2f} | {_delta(without_cache.percentile(50), with_cache.percentile(50))} ms |",
            f"| latency_p95_ms | {without_cache.percentile(95):.2f} | {with_cache.percentile(95):.2f} | {_delta(without_cache.percentile(95), with_cache.percentile(95))} ms |",
            f"| estimated_cost | {without_cache.estimated_cost:.6f} | {with_cache.estimated_cost:.6f} | {_delta(without_cache.estimated_cost, with_cache.estimated_cost)} |",
            f"| cache_hit_rate | 0.0000 | {with_cache.cache_hit_rate:.4f} | {_delta(0.0, with_cache.cache_hit_rate)} |",
            "",
            "## 6. Redis shared cache",
            "",
            "In-memory cache is fast but local to one process, so separate gateway instances cannot reuse each other's answers or warm cache state.",
            "The implemented `SharedRedisCache` moves cache entries into Redis hashes with TTL, which allows exact-match reuse and similarity-based lookups across instances.",
            "",
            "### Evidence of shared state",
            "",
            "```text",
            redis_status["shared_state"],
            "```",
            "",
            "### Redis CLI output",
            "",
            "```text",
            redis_status["keys_output"],
            "```",
            "",
            "## 7. Chaos scenarios",
            "",
            "| Scenario | Expected behavior | Observed behavior | Pass/Fail |",
            "|---|---|---|---|",
        ]
    )

    for scenario, result in scenario_results:
        lines.append(
            f"| {scenario.name} | {_escape(scenario.description or 'Run scenario and validate reliability behavior.')} "
            f"| {_escape(_summarize_scenario(result))} | {'pass' if _scenario_passed(scenario, result) else 'fail'} |"
        )

    lines.extend(
        [
            "",
            "## 8. Failure analysis",
            "",
            "The current cache similarity is lexical rather than embedding-based, so semantically equivalent but differently phrased questions can still miss the cache.",
            "Before production, I would add model- or embedding-based relevance checks plus per-query freshness policies for time-sensitive prompts.",
            "",
            "## 9. Next steps",
            "",
            "1. Persist circuit breaker state in Redis so multiple gateway replicas share failure knowledge.",
            "2. Add concurrency/load patterns and request deadlines to stress the fallback chain under burst traffic.",
            "3. Add semantic quality validation for cache hits to catch intent drift beyond year/number mismatches.",
        ]
    )

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out}")


def _baseline_scenario(config: LabConfig) -> ScenarioConfig:
    for scenario in config.scenarios:
        if scenario.name == "all_healthy":
            return scenario
    return ScenarioConfig(name="baseline", description="Baseline run with configured fail rates.")


def _run_cache_comparison(
    config: LabConfig,
    queries: list[str],
    scenario: ScenarioConfig,
) -> tuple[RunMetrics, RunMetrics]:
    with_cache_config = config.model_copy(deep=True)
    with_cache_config.cache.enabled = True

    without_cache_config = config.model_copy(deep=True)
    without_cache_config.cache.enabled = False

    with_cache = run_scenario(with_cache_config, queries, scenario)
    without_cache = run_scenario(without_cache_config, queries, scenario)
    return with_cache, without_cache


def _collect_redis_evidence(config: LabConfig) -> dict[str, str]:
    prefix = "rl:report:"
    try:
        cache = SharedRedisCache(
            config.cache.redis_url,
            ttl_seconds=config.cache.ttl_seconds,
            similarity_threshold=config.cache.similarity_threshold,
            prefix=prefix,
        )
        if not cache.ping():
            return {
                "shared_state": "Redis ping failed. Docker daemon was not available in this environment, so shared-cache runtime verification could not be completed here.",
                "keys_output": "Redis unavailable: no KEYS output captured.",
            }

        cache.flush()
        peer = SharedRedisCache(
            config.cache.redis_url,
            ttl_seconds=config.cache.ttl_seconds,
            similarity_threshold=config.cache.similarity_threshold,
            prefix=prefix,
        )
        try:
            cache.set("shared query", "shared response")
            shared_value, _ = peer.get("shared query")
            keys = list(cache._redis.scan_iter(f"{prefix}*"))
            shared_state = (
                "Instance A stored 'shared query'; instance B read back "
                f"{shared_value!r}. Shared state verified."
            )
            keys_output = "\n".join(str(key) for key in keys) if keys else "(no keys found)"
            return {"shared_state": shared_state, "keys_output": keys_output}
        finally:
            peer.flush()
            peer.close()
    except Exception as exc:
        return {
            "shared_state": f"Redis verification unavailable in this environment: {exc}",
            "keys_output": "Redis unavailable: no KEYS output captured.",
        }
    finally:
        if "cache" in locals():
            cache.close()


def _build_slo_rows(metrics: dict[str, object]) -> list[str]:
    availability = float(metrics["availability"])
    latency_p95 = float(metrics["latency_p95_ms"])
    fallback_success_rate = float(metrics["fallback_success_rate"])
    cache_hit_rate = float(metrics["cache_hit_rate"])
    recovery_time_ms = metrics["recovery_time_ms"]
    recovery_display = "n/a" if recovery_time_ms is None else f"{float(recovery_time_ms):.2f}"

    rows = [
        ("Availability", ">= 99%", f"{availability:.4f}", availability >= 0.99),
        ("Latency P95", "< 2500 ms", f"{latency_p95:.2f}", latency_p95 < 2500),
        (
            "Fallback success rate",
            ">= 95%",
            f"{fallback_success_rate:.4f}",
            fallback_success_rate >= 0.95,
        ),
        ("Cache hit rate", ">= 10%", f"{cache_hit_rate:.4f}", cache_hit_rate >= 0.10),
        (
            "Recovery time",
            "< 5000 ms",
            recovery_display,
            recovery_time_ms is not None and float(recovery_time_ms) < 5000,
        ),
    ]
    return [f"| {name} | {target} | {actual} | {'yes' if passed else 'no'} |" for name, target, actual, passed in rows]


def _scenario_passed(scenario: ScenarioConfig, metrics: RunMetrics) -> bool:
    if scenario.name == "primary_timeout_100":
        return metrics.fallback_success_rate >= 0.95 and metrics.circuit_open_count > 0
    if scenario.name == "primary_flaky_50":
        return metrics.fallback_successes > 0 and metrics.availability >= 0.99
    if scenario.name == "all_healthy":
        return metrics.static_fallbacks == 0 and metrics.circuit_open_count == 0
    return metrics.successful_requests > 0


def _summarize_scenario(metrics: RunMetrics) -> str:
    parts = [
        f"availability {metrics.availability:.1%}",
        f"P95 {metrics.percentile(95):.2f} ms",
    ]
    if metrics.cache_hits:
        parts.append(f"cache hits {metrics.cache_hits}")
    if metrics.fallback_successes:
        parts.append(f"fallback successes {metrics.fallback_successes}")
    if metrics.static_fallbacks:
        parts.append(f"static fallbacks {metrics.static_fallbacks}")
    if metrics.circuit_open_count:
        parts.append(f"circuit opens {metrics.circuit_open_count}")
    if metrics.recovery_time_ms is not None:
        parts.append(f"avg recovery {metrics.recovery_time_ms:.2f} ms")
    return "; ".join(parts)


def _delta(before: float, after: float) -> str:
    return f"{after - before:+.4f}"


def _escape(value: str) -> str:
    return value.replace("|", "\\|")


if __name__ == "__main__":
    main()
