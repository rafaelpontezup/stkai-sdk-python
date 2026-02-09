# stkai SDK Rate Limiting Simulations

Discrete-event simulations using SimPy to validate retry and rate limiting strategies
for the stkai SDK.

## Overview

This simulation infrastructure replicates the SDK's rate limiting logic with high fidelity,
allowing us to validate behavior under various conditions without hitting real servers.

Two workload types are supported:

| Workload | POST Latency | Workers/Process | Requests/Process | Quota | Contention Levels |
|----------|--------------|-----------------|------------------|-------|-------------------|
| **RQC** | ~200ms | 8 | 1000 | 100 req/min | 1, 2, 3, 5, 7, 10 |
| **Agent** | ~15s | 10 | 150 | 50 req/min | 1, 2, 3, 5, 7, 10, 15 |

## Quick Start

```bash
# Navigate to simulations directory
cd simulations

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run RQC sweep test (default)
python run_sweep.py

# Run Agent sweep test
python run_sweep.py --workload agent

# View results
ls results/rqc/latest/*.png
ls results/agent/latest/*.png
```

Or use the helper script from project root:

```bash
./scripts/run_simulations.sh              # RQC (default)
./scripts/run_simulations.sh agent        # Agent
./scripts/run_simulations.sh all          # Both
```

## Strategies Tested

### RQC Workload

| Strategy | Description | Configuration |
|----------|-------------|---------------|
| `none` | No rate limiting (retry only) | Baseline for comparison |
| `token_bucket` | Fixed rate | 33 req/min (100÷3 for 3 processes) |
| `optimistic` | AIMD, aggressive | max_wait=20s, min_floor=30%, penalty=15% |
| `balanced` | AIMD, sensible defaults | max_wait=45s, min_floor=10%, penalty=30% |
| `conservative` | AIMD, stability-first | max_wait=120s, min_floor=5%, penalty=50% |
| `congestion_aware` | AIMD + Little's Law | Same as balanced + pressure_threshold=2.0 |

### Agent Workload

| Strategy | Description | Configuration |
|----------|-------------|---------------|
| `none` | No rate limiting (retry only) | Baseline for comparison |
| `token_bucket` | Fixed rate | 16 req/min (50÷3 for 3 processes) |
| `optimistic` | AIMD, aggressive | max_wait=20s, min_floor=30%, penalty=15% |
| `balanced` | AIMD, sensible defaults | max_wait=45s, min_floor=10%, penalty=30% |
| `conservative` | AIMD, stability-first | max_wait=120s, min_floor=5%, penalty=50% |
| `congestion_aware` | AIMD + Little's Law | Same as balanced + pressure_threshold=2.0 |

## Simulated Server

### RQC Server

- **Shared quota**: 100 req/min across ALL clients
- **Base latency**: 200ms
- **429 responses**: When quota exceeded (with `Retry-After: 5s`)
- **Latency under load**: M/M/1 queuing theory (latency increases with utilization)

### Agent Server

- **Shared quota**: 50 req/min across ALL clients (lower to create contention)
- **Base latency**: 15s (LLM processing time)
- **429 responses**: When quota exceeded (with `Retry-After: 5s`)
- **Latency under load**: M/M/1 queuing theory

| Server Utilization | RQC Latency | Agent Latency |
|-------------------|-------------|---------------|
| 0% (idle) | 200ms | 15s |
| 50% (moderate) | 400ms | 30s |
| 80% (high load) | 1000ms | 75s |
| 95% (near capacity) | 4000ms | 300s |

## Project Structure

```
simulations/
├── run_sweep.py              # Main entry point - runs all scenarios
├── requirements.txt          # Dependencies (simpy, matplotlib, pandas)
├── README.md                 # This file
├── results/                  # Output directory
│   ├── rqc/                  # RQC workload results
│   │   ├── latest -> YYYY-MM-DD.../    # Symlink to most recent run
│   │   ├── YYYY-MM-DD_HH-MM-SS/        # Timestamped results
│   │   └── reference/                   # Versioned reference graphs
│   └── agent/                # Agent workload results
│       ├── latest -> YYYY-MM-DD.../
│       ├── YYYY-MM-DD_HH-MM-SS/
│       └── reference/
├── scenarios/
│   ├── rqc_sweep_test.py     # RQC scenario definitions
│   └── agent_sweep_test.py   # Agent scenario definitions
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
        ├── base.py             # Abstract base class
        ├── token_bucket.py     # Simple Token Bucket
        ├── adaptive.py         # AIMD (Additive Increase Multiplicative Decrease)
        └── congestion_aware.py # Adaptive + Little's Law concurrency control
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

### RQC Workload

1. **AIMD is sufficient**: Adaptive strategies (balanced/conservative) handle contention
   well without needing latency-based concurrency control. Adding latency-based
   concurrency control (via `CongestionAwareHttpClient`) provided no measurable improvement
   over Adaptive strategies.

2. **Token Bucket requires manual tuning**: Works well if you know process count upfront,
   but doesn't adapt dynamically.

3. **Balanced preset is the sweet spot**: Best efficiency for 2-5 processes.

4. **Conservative for high contention**: Better stability at 7-10 processes.

5. **Optimistic for single process**: Best throughput when running alone.

### Agent Workload

1. **Long latency is a natural rate limiter**: The 15s latency per request naturally
   limits throughput to ~4 req/min per worker, reducing the impact of client-side
   rate limiting.

2. **Rate limiting has minimal impact until high contention**: Most strategies perform
   identically until 7+ processes because throughput is latency-bound, not rate-bound.

3. **Conservative excels at high contention**: At 15 processes, conservative achieves
   91.4% success vs 41.9% for none/optimistic.

4. **Token Bucket needs proper tuning**: With 16 req/min (vs 33 for RQC), Token Bucket
   shows improvement at high contention (56.6% vs 41.9% for none).

5. **Congestion Aware achieves high success but low throughput**: 100% success rate
   but significantly fewer total requests completed due to semaphore blocking.

### RQC vs Agent Comparison

| Aspect | RQC | Agent |
|--------|-----|-------|
| Natural throughput/worker | ~300 req/min | ~4 req/min |
| Rate limiting critical? | **Yes** | Only at high contention |
| Token Bucket effective? | **Yes** (limits 300→33) | Limited (4 < 16) |
| Best strategy (general) | `balanced` | `conservative` |
| Contention threshold | 3+ processes | 7+ processes |
