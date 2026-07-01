# Day 10 Reliability Final Report

## 1. Architecture summary

Gateway routes requests through semantic cache, per-provider circuit breakers, and a provider fallback chain.
Cached hits return immediately with zero provider cost; misses go through the primary provider first, then backup, and finally a static degraded response if every provider is unavailable.

```text
User Request
    |
    v
[ReliabilityGateway]
    |
    +--> [Semantic Cache] ---- hit ----> return cached response
    |
    +--> [Circuit Breaker: primary] --> Provider A
    |                |
    |                +--> open/failed -> [Circuit Breaker: backup] --> Provider B
    |                                                        |
    |                                                        +--> failed -> static fallback
```

## 2. Configuration

| Setting | Value | Reason |
|---|---:|---|
| failure_threshold | 3 | Open after 3 consecutive failures to stop retry storms while still tolerating brief blips. |
| reset_timeout_seconds | 2.0 | Wait 2.0s before a probe request so providers have time to recover. |
| success_threshold | 1 | Require 1 successful probe before closing the circuit again. |
| cache backend | memory | Default config uses fast local memory; Redis backend is implemented for multi-instance sharing. |
| cache TTL | 300 | Keep answers long enough to improve hit rate without keeping stale answers indefinitely. |
| similarity_threshold | 0.92 | High threshold reduces semantic false hits, especially for dated queries. |
| load_test requests | 100 | 100 requests is enough to expose fallback, cache, and breaker behavior in a short local run. |

## 3. SLO definitions

| SLI | SLO target | Actual value | Met? |
|---|---|---:|---|
| Availability | >= 99% | 1.0000 | yes |
| Latency P95 | < 2500 ms | 312.09 | yes |
| Fallback success rate | >= 95% | 1.0000 | yes |
| Cache hit rate | >= 10% | 0.6200 | yes |
| Recovery time | < 5000 ms | 2238.86 | yes |

## 4. Metrics

| Metric | Value |
|---|---:|
| total_requests | 300 |
| availability | 1.0 |
| error_rate | 0.0 |
| latency_p50_ms | 239.91 |
| latency_p95_ms | 312.09 |
| latency_p99_ms | 317.31 |
| fallback_success_rate | 1.0 |
| cache_hit_rate | 0.62 |
| circuit_open_count | 7 |
| recovery_time_ms | 2238.858461380005 |
| estimated_cost | 0.05345 |
| estimated_cost_saved | 0.186 |

## 5. Cache comparison

| Metric | Without cache | With cache | Delta |
|---|---:|---:|---|
| latency_p50_ms | 212.90 | 207.45 | -5.4506 ms |
| latency_p95_ms | 238.14 | 238.86 | +0.7176 ms |
| estimated_cost | 0.056060 | 0.020000 | -0.0361 |
| cache_hit_rate | 0.0000 | 0.6500 | +0.6500 |

## 6. Redis shared cache

In-memory cache is fast but local to one process, so separate gateway instances cannot reuse each other's answers or warm cache state.
The implemented `SharedRedisCache` moves cache entries into Redis hashes with TTL, which allows exact-match reuse and similarity-based lookups across instances.

### Evidence of shared state

```text
Redis verification unavailable in this environment: No module named 'redis'
```

### Redis CLI output

```text
Redis unavailable: no KEYS output captured.
```

## 7. Chaos scenarios

| Scenario | Expected behavior | Observed behavior | Pass/Fail |
|---|---|---|---|
| primary_timeout_100 | Primary provider fails 100% - all traffic should fallback | availability 100.0%; P95 316.61 ms; cache hits 60; fallback successes 40; circuit opens 6 | pass |
| primary_flaky_50 | Primary provider fails 50% - fallback should preserve availability | availability 100.0%; P95 307.72 ms; cache hits 61; fallback successes 16; circuit opens 1; avg recovery 2242.18 ms | pass |
| all_healthy | Baseline - both providers healthy | availability 100.0%; P95 238.78 ms; cache hits 65 | pass |

## 8. Failure analysis

The current cache similarity is lexical rather than embedding-based, so semantically equivalent but differently phrased questions can still miss the cache.
Before production, I would add model- or embedding-based relevance checks plus per-query freshness policies for time-sensitive prompts.

## 9. Next steps

1. Persist circuit breaker state in Redis so multiple gateway replicas share failure knowledge.
2. Add concurrency/load patterns and request deadlines to stress the fallback chain under burst traffic.
3. Add semantic quality validation for cache hits to catch intent drift beyond year/number mismatches.