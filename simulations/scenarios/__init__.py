"""
Simulation scenarios for testing rate limiting strategies.

Scenarios:
- rqc_sweep_test: RQC workload (~200ms latency)
- agent_sweep_test: Agent workload (~15s latency)

Both vary contention level and compare all strategies.
Generates line charts like Marc Brooker's blog.
"""

from simulations.scenarios.rqc_sweep_test import (
    SCENARIOS,
    STRATEGIES,
    CONTENTION_LEVELS,
)

__all__ = [
    "SCENARIOS",
    "STRATEGIES",
    "CONTENTION_LEVELS",
]
