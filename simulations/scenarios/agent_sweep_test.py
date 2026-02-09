"""
Cenário Sweep para Agent: Varrer diferentes níveis de contenção.

Similar ao rqc_sweep_test.py mas com parâmetros ajustados para Agent::chat():
- Latência: 10-30s (vs 200ms do RQC)
- Workers: 1-2 (vs 8 do RQC) - Agent é mais interativo
- Requests: Menos requests devido à latência maior
"""

from simulations.src.config import (
    ScenarioConfig,
    ServerConfig,
    RateLimitConfig,
    RetryConfig,
    SimulationConfig,
)


# =============================================================================
# Configuração comum para Agent
# =============================================================================

SERVER = ServerConfig(
    quota_per_minute=50,           # Lower quota to create contention with slow Agent requests
    request_latency_ms=200.0,      # RQC latency (not used for agent)
    agent_latency_ms=15000.0,      # 15s per Agent request
    retry_after_seconds=5.0,
)

RETRY = RetryConfig(
    max_retries=3,
    initial_delay=0.5,
    jitter_factor=0.10,
)


# =============================================================================
# Estratégias a comparar (mesmas do RQC para comparação justa)
# =============================================================================

STRATEGIES = {
    "none": RateLimitConfig(strategy="none"),
    "token_bucket": RateLimitConfig(
        strategy="token_bucket",
        max_requests=16,  # 50 req/min ÷ 3 processes ≈ 16 req/min per process
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
    # Congestion-Aware pode ser mais útil para Agent devido à latência longa
    "congestion_aware": RateLimitConfig(
        strategy="congestion_aware",
        max_requests=100,
        time_window=60.0,
        max_wait_time=45.0,
        min_rate_floor=0.1,
        penalty_factor=0.30,
        recovery_factor=0.05,
        pressure_threshold=2.0,
    ),
}

# Níveis de contenção (número de processos)
# Inclui 15 para simular ambiente de produção com muitos pods/replicas
CONTENTION_LEVELS = [1, 2, 3, 5, 7, 10, 15]


def create_scenarios() -> list[ScenarioConfig]:
    """Create all scenarios for the Agent sweep."""
    scenarios = []

    for num_processes in CONTENTION_LEVELS:
        # Agent workload characteristics:
        # - 15s latency per request
        # - Duration: 600s (10 min) for meaningful data
        # - With 15s latency, 1 worker can do ~40 requests in 600s
        # - With 6 workers: ~240 requests per process (theoretical max)
        # - We set 150 requests to create demand pressure (exceed quota)
        #
        # Goal: Create contention to see rate limiting effects
        # - 10 workers × (600s/15s) = 400 req/process theoretical max
        # - 150 requests = 15 req/min per process
        # - With 15 processes: 225 req/min >> 50 quota → severe contention!
        simulation = SimulationConfig(
            duration_seconds=600.0,  # 10 minutes (longer due to slow requests)
            num_processes=num_processes,
            workers_per_process=10,  # More workers to simulate multiple users per app
            requests_per_process=150,  # Enough to exceed quota at high contention
            arrival_pattern="poisson",
            random_seed=42,
            client_type="agent",  # Use agent latency
        )

        for strategy_name, rate_limit in STRATEGIES.items():
            scenarios.append(
                ScenarioConfig(
                    name=f"{num_processes}proc-{strategy_name}",
                    description=f"Agent: {num_processes} processos - {strategy_name}",
                    server=SERVER,
                    rate_limit=rate_limit,
                    retry=RETRY,
                    simulation=simulation,
                )
            )

    return scenarios


SCENARIOS = create_scenarios()
