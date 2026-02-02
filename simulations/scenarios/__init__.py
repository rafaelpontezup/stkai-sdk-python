"""
Simulation scenarios for testing rate limiting strategies.

Main scenario: sweep_test
- Varies contention level (1, 2, 3, 5, 7, 10 processes)
- Compares all strategies at each level
- Generates line charts like Marc Brooker's blog
"""

from simulations.scenarios.sweep_test import (
    SCENARIOS,
    STRATEGIES,
    CONTENTION_LEVELS,
)

__all__ = [
    "SCENARIOS",
    "STRATEGIES",
    "CONTENTION_LEVELS",
]
