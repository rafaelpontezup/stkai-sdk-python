# stkai SDK Rate Limiting Simulations

Discrete-event simulations using SimPy to validate retry and rate limiting strategies
for the stkai SDK.

## Overview

This simulation infrastructure replicates the SDK's rate limiting logic with high fidelity,
allowing us to validate behavior under various conditions without hitting real servers.

## Quick Start

```bash
# Navigate to simulations directory
cd simulations

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run sweep test (all strategies × all contention levels)
python run_sweep.py

# View results
ls results/latest/*.png
```

## Strategies Tested

| Strategy | Description | Configuration |
|----------|-------------|---------------|
| `none` | No rate limiting (retry only) | Baseline for comparison |
| `token_bucket` | Fixed rate (33 req/min) | Manual: 100÷3 for 3 processes |
| `optimistic` | AIMD, aggressive | max_wait=20s, min_floor=30%, penalty=15% |
| `balanced` | AIMD, sensible defaults | max_wait=45s, min_floor=10%, penalty=30% |
| `conservative` | AIMD, stability-first | max_wait=120s, min_floor=5%, penalty=50% |
| `cong_aware` | AIMD + Little's Law | Same as balanced + pressure_threshold=2.0 |

## Contention Levels

The sweep tests run each strategy against multiple contention levels:
**1, 2, 3, 5, 7, 10** concurrent processes.

Each process has **8 workers** (mirrors SDK's `max_workers` for RQC).

## Simulated Server

The server simulates realistic behavior:

- **Shared quota**: 100 req/min across ALL clients
- **429 responses**: When quota exceeded (with `Retry-After: 5s`)
- **Latency under load**: M/M/1 queuing theory (latency increases with utilization)

| Server Utilization | Latency |
|-------------------|---------|
| 0% (idle) | 200ms |
| 50% (moderate) | 400ms |
| 80% (high load) | 1000ms |
| 95% (near capacity) | 4000ms |

## Project Structure

```
simulations/
├── run_sweep.py              # Main entry point - runs all scenarios
├── requirements.txt          # Dependencies (simpy, matplotlib, pandas)
├── README.md                 # This file
├── results/                  # Output directory
│   ├── latest -> YYYY-MM-DD_HH-MM-SS/   # Symlink to most recent run
│   └── YYYY-MM-DD_HH-MM-SS/             # Timestamped results
│       ├── graph_01_success_rate_vs_server_load.png
│       ├── graph_02_success_rate_vs_rejection_rate.png
│       ├── graph_03_failure_breakdown.png
│       ├── graph_04_efficiency_score.png
│       └── graph_05_success_rate_vs_latency.png
├── scenarios/
│   └── sweep_test.py         # Scenario definitions (strategies, contention levels)
└── src/
    ├── client.py             # Simulated SDK client (rate limiter integration)
    ├── config.py             # Configuration dataclasses
    ├── jitter.py             # Jitter implementation (±20% for AIMD)
    ├── metrics.py            # Metrics collection and aggregation
    ├── retry.py              # Retry logic (exponential backoff, Retry-After)
    ├── server.py             # Simulated server (quota, latency, 429s)
    ├── simulator.py          # SimPy simulation orchestration
    ├── visualize.py          # Graph generation utilities
    └── rate_limiters/
        ├── base.py           # Abstract base class
        ├── token_bucket.py   # Simple Token Bucket
        ├── adaptive.py       # AIMD (Additive Increase Multiplicative Decrease)
        └── congestion_aware.py  # AIMD + Little's Law pressure detection
```

## SDK Fidelity

The simulation replicates exact logic from:

- `_rate_limit.py`: Token Bucket, AIMD, Jitter (±20%)
- `_retry.py`: Exponential backoff with jitter (±10%), Retry-After handling
- `_config.py`: Conservative, Balanced, Optimistic presets

## Metrics Collected

- **Success Rate**: % requests completed successfully
- **Rejection Rate**: % of 429 responses from server
- **Client-side Timeout Rate**: % of `TokenAcquisitionTimeoutError`
- **Latency P50/P95/P99**: Including retries and waits
- **Throughput**: Successful requests per minute
- **Efficiency Score**: Success rate × throughput (higher is better)

## Output Graphs

1. **Success Rate vs Server Load**: How success rate degrades with contention
2. **Success Rate vs Rejection Rate**: Trade-off between success and server rejections
3. **Failure Breakdown**: Types of failures per strategy (429, timeout, client-side)
4. **Efficiency Score**: Combined metric (success × throughput)
5. **Success Rate vs Latency**: How latency affects success

## Key Findings

1. **AIMD is sufficient**: Adaptive strategies (balanced/conservative) handle contention
   well without needing latency-based concurrency control. Adding latency-based
   concurrency control (via `CongestionAwareHttpClient` or the old `CongestionControlledHttpClient`) provided no measurable improvement
   over Adaptive strategies. See `docs/internal/aws-sdk-comparison.md` for details.

2. **Token Bucket requires manual tuning**: Works well if you know process count upfront,
   but doesn't adapt dynamically.

3. **Balanced preset is the sweet spot**: Best efficiency for 2-5 processes.

4. **Conservative for high contention**: Better stability at 7-10 processes.

5. **Optimistic for single process**: Best throughput when running alone.
