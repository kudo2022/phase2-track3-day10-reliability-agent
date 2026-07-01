# Learning Notes

## Muc tieu

Hoan thien Day 10 reliability lab de gateway co the:
- chong retry storm bang circuit breaker 3 trang thai
- tan dung semantic cache co guardrail
- fallback qua provider du phong khi provider chinh loi
- xuat metrics, chaos report, va tai lieu nop bai

## Nhung gi da lam

- Hoan thien `CircuitBreaker` trong `src/reliability_lab/circuit_breaker.py`:
  - them `allow_request()`
  - them `call()`
  - them `record_success()`
  - them `record_failure()`
  - ghi `transition_log` dung reason cho `failure_threshold_reached`, `probe_failure`, `probe_success`

- Hoan thien cache trong `src/reliability_lab/cache.py`:
  - them semantic similarity bang cosine tren word token + character 3-gram
  - them TTL eviction
  - them privacy guardrail qua `_is_uncacheable()`
  - them false-hit detection cho query khac nam/so 4 chu so
  - them `false_hit_log`

- Hoan thien Redis cache layer:
  - them `SharedRedisCache.get()`
  - them `SharedRedisCache.set()`
  - ho tro exact hit, similarity scan, TTL, va false-hit guardrail

- Hoan thien `ReliabilityGateway.complete()` trong `src/reliability_lab/gateway.py`:
  - pipeline cache -> circuit breaker -> provider fallback -> static fallback
  - luu ket qua vao cache sau khi provider tra loi thanh cong

- Hoan thien `src/reliability_lab/chaos.py`:
  - them `run_scenario()`
  - them `calculate_recovery_time_ms()`
  - them pass/fail logic cho cac scenario
  - them deterministic seed de ket qua chaos co the lap lai giua cac lan chay

- Hoan thien `src/reliability_lab/metrics.py`:
  - them `write_csv()` de xuat metrics CSV

- Cai thien kha nang chay tool:
  - sua `scripts/run_chaos.py` de chay duoc voi `src` local va xuat ca `metrics.json` + `metrics.csv`
  - nang cap `scripts/generate_report.py` de tao `reports/final_report.md` day du hon tu config + metrics
  - sua `Makefile` de dung `python -m ...` thay vi phu thuoc executable tren PATH
  - cap nhat `configs/default.yaml` de scenario phan anh dung mo ta

## Kiem chung

- Chay test tong:
  - `python -m pytest -q`
  - ket qua: `29 passed, 6 skipped, 7 xpassed`

- Chay chaos simulation:
  - `python scripts/run_chaos.py --config configs/default.yaml --out reports/metrics.json`

- Sinh report:
  - `python scripts/generate_report.py --metrics reports/metrics.json --out reports/final_report.md --config configs/default.yaml`

## Ket qua cuoi

- `reports/metrics.json` da duoc tao
- `reports/metrics.csv` da duoc tao
- `reports/final_report.md` da duoc tao

Chi so o lan chay hien tai:
- availability: `1.0`
- error_rate: `0.0`
- latency_p95_ms: `312.09`
- cache_hit_rate: `0.62`
- fallback_success_rate: `1.0`
- circuit_open_count: `7`
- recovery_time_ms: `2238.858461380005`
- estimated_cost_saved: `0.186`

## Ghi chu con lai

- Phan code Redis da duoc implement.
- Tuy nhien moi truong hien tai chua co Redis dependency/daemon san sang, nen:
  - Redis tests dang bi skip
  - report ghi ro Redis verification unavailable trong environment hien tai
- Neu can verify Redis end-to-end, can cai dependency `redis` va bat Redis server/Docker daemon roi chay lai:
  - `python -m pytest tests/test_redis_cache.py -q`
  - `python scripts/run_chaos.py --config configs/default.yaml --out reports/metrics.json`
