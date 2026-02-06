"""
Cenário Sweep: Varrer diferentes níveis de contenção.

Inspirado em: https://brooker.co.za/blog/2022/02/28/retries.html

Em vez de testar um único ponto, testamos VÁRIOS níveis de contenção
para ver como cada estratégia se comporta conforme a pressão aumenta.

Eixo X: Número de processos (1, 2, 3, 5, 7, 10)
Eixo Y: Success rate, 429 rate
Linhas: Uma para cada estratégia
"""

from simulations.src.config import (
    ScenarioConfig,
    ServerConfig,
    RateLimitConfig,
    RetryConfig,
    SimulationConfig,
)


# =============================================================================
# Configuração comum
# =============================================================================

SERVER = ServerConfig(
    quota_per_minute=100,
    request_latency_ms=200.0,
    retry_after_seconds=5.0,
)

RETRY = RetryConfig(
    max_retries=3,
    initial_delay=0.5,
    jitter_factor=0.10,
)


# =============================================================================
# Estratégias a comparar
# =============================================================================

STRATEGIES = {
    "none": RateLimitConfig(strategy="none"),
    "token_bucket": RateLimitConfig(
        strategy="token_bucket",
        max_requests=33,  # Assumes 3 processes sharing 100 req/min quota
        time_window=60.0,
        max_wait_time=45.0,
    ),
    "optimistic": RateLimitConfig(
        strategy="adaptive",
        max_requests=100,
        time_window=60.0,
        max_wait_time=20.0,
        min_rate_floor=0.3,
        penalty_factor=0.15,
        recovery_factor=0.1,
    ),
    "balanced": RateLimitConfig(
        strategy="adaptive",
        max_requests=100,
        time_window=60.0,
        max_wait_time=45.0,
        min_rate_floor=0.1,
        penalty_factor=0.30,
        recovery_factor=0.05,
    ),
    "conservative": RateLimitConfig(
        strategy="adaptive",
        max_requests=100,
        time_window=60.0,
        max_wait_time=120.0,
        min_rate_floor=0.05,
        penalty_factor=0.50,
        recovery_factor=0.02,
    ),
    # Congestion-Aware (Little's Law) with SDK defaults
    # Uses same AIMD params as balanced + pressure-based backpressure
    "congestion_aware": RateLimitConfig(
        strategy="congestion_aware",
        max_requests=100,
        time_window=60.0,
        max_wait_time=45.0,
        min_rate_floor=0.1,
        penalty_factor=0.30,
        recovery_factor=0.05,
        pressure_threshold=2.0,  # SDK default
    ),
}

# Níveis de contenção (número de processos)
CONTENTION_LEVELS = [1, 2, 3, 5, 7, 10]


def create_scenarios() -> list[ScenarioConfig]:
    """Create all scenarios for the sweep."""
    scenarios = []

    for num_processes in CONTENTION_LEVELS:
        # Demand: 1000 requests / 300s = 200 req/min per process
        # Local quota: 100 req/min per process (token bucket)
        # Demand = 2x quota (to force throttling)
        #
        # Workers: 8 concurrent workers per process (RQC default)
        # This simulates real RQC execute_many() with thread pool
        simulation = SimulationConfig(
            duration_seconds=300.0,
            num_processes=num_processes,
            workers_per_process=8,  # RQC default - concurrent workers share rate limiter
            requests_per_process=1000,  # 200 req/min (2x local quota)
            arrival_pattern="poisson",
            random_seed=42,
        )

        for strategy_name, rate_limit in STRATEGIES.items():
            scenarios.append(
                ScenarioConfig(
                    name=f"{num_processes}proc-{strategy_name}",
                    description=f"{num_processes} processos - {strategy_name}",
                    server=SERVER,
                    rate_limit=rate_limit,
                    retry=RETRY,
                    simulation=simulation,
                )
            )

    return scenarios


SCENARIOS = create_scenarios()
