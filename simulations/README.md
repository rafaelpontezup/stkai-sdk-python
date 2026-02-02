# stkai SDK Rate Limiting Simulations

Discrete-event simulations using SimPy to validate retry and rate limiting strategies
for the stkai SDK.

## Overview

This simulation infrastructure replicates the SDK's rate limiting logic with high fidelity,
allowing us to validate behavior under various conditions without hitting real servers.

## Quick Start

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run all scenarios
python run_all.py

# Run specific scenario group
python run_single.py --group 1 --scenario 1

# View results
ls results/*.png
```

## Simulation Groups

### Group 1: Baseline vs Rate Limiting Strategies
Compares no rate limiting vs token_bucket vs adaptive vs congestion_controlled.

### Group 2: Preset Comparison (Adaptive)
Compares conservative, balanced, and optimistic presets under different quota pressures.

### Group 3: Process Concurrency Impact
Tests how 1, 3, 5, and 10 concurrent processes affect AIMD behavior.

### Group 4: Agent Scenarios (Secondary)
Validates presets work for Agent's long POST requests (10-30s latency).

## SDK Fidelity

The simulation replicates exact logic from:
- `_rate_limit.py`: Token Bucket, AIMD, Jitter (±20%)
- `_retry.py`: Exponential backoff with jitter (±10%), Retry-After handling
- `_config.py`: Conservative, Balanced, Optimistic presets

## Metrics Collected

- **Success Rate**: % requests completed successfully
- **Latency P50/P95/P99**: Including retries and waits
- **429 Rate**: % of 429 responses from server
- **Throughput**: Successful requests per minute
- **RPS Amplification**: Total requests / original requests (retry overhead)
- **Effective Rate**: Bucket capacity over time (AIMD adaptation)
