"""
Jitter implementation - high fidelity port from stkai._rate_limit.Jitter.

Provides deterministic per-process jitter for desynchronizing clients.
"""

import hashlib
import os
import random
import socket


class Jitter:
    """
    Structural jitter for desynchronizing processes sharing a quota.

    Uses a per-process seeded RNG to ensure:
    - Same process = deterministic sequence (reproducible for debugging)
    - Different processes = different sequences (desynchronization)

    This is a high-fidelity port of stkai._rate_limit.Jitter.
    """

    def __init__(
        self,
        factor: float = 0.20,
        rng: random.Random | None = None,
        process_id: int | None = None,
    ):
        """
        Initialize the jitter generator.

        Args:
            factor: Jitter factor as a fraction (e.g., 0.20 for ±20%).
            rng: Optional RNG for dependency injection in tests.
            process_id: Optional process ID for simulation (overrides os.getpid()).
        """
        assert factor >= 0, "factor must be non-negative"
        assert factor < 1, "factor must be less than 1"

        self.factor = factor
        self._process_id = process_id
        self._rng = rng or self._create_process_local_rng()

    def _create_process_local_rng(self) -> random.Random:
        """
        Create a deterministic RNG seeded with hostname and process ID.

        For simulations, process_id can be passed to simulate multiple processes.
        """
        pid = self._process_id if self._process_id is not None else os.getpid()
        # Use hashlib for consistent cross-platform hashing
        seed_str = f"{socket.gethostname()}:{pid}"
        seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
        return random.Random(seed)

    def next(self) -> float:
        """
        Return a random jitter multiplier in [1-factor, 1+factor].

        Each call returns a new random value.
        """
        return self._rng.uniform(1.0 - self.factor, 1.0 + self.factor)

    def random(self) -> float:
        """
        Return a random value in [0, 1).

        Use for probabilistic decisions.
        """
        return self._rng.random()

    def apply(self, value: float) -> float:
        """
        Multiply value by a jittered factor.
        """
        return value * self.next()

    def __mul__(self, other: float) -> float:
        """Support: jitter * value"""
        return self.apply(other)

    def __rmul__(self, other: float) -> float:
        """Support: value * jitter"""
        return self.apply(other)


def sleep_with_jitter(seconds: float, jitter_factor: float = 0.1) -> float:
    """
    Calculate sleep duration with jitter (for simulation, returns value instead of sleeping).

    Mirrors stkai._utils.sleep_with_jitter but returns the value
    instead of actually sleeping (SimPy handles the delay).

    Args:
        seconds: Base sleep duration.
        jitter_factor: Maximum percentage variation (±).

    Returns:
        Jittered sleep duration (never negative).
    """
    jitter = random.uniform(-jitter_factor, jitter_factor)
    return max(0.0, seconds * (1 + jitter))
