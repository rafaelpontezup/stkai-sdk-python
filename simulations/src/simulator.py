"""
Main simulation engine using SimPy.

Orchestrates multiple client processes and collects metrics.
"""

import random
from typing import Generator

import simpy

from simulations.src.config import ScenarioConfig
from simulations.src.server import SimulatedServer
from simulations.src.client import SimulatedClient
from simulations.src.metrics import MetricsCollector, SimulationMetrics


class Simulator:
    """
    Discrete-event simulator for retry and rate limiting scenarios.

    Uses SimPy to simulate concurrent client processes making requests
    to a rate-limited server.
    """

    def __init__(self, config: ScenarioConfig):
        """
        Initialize the simulator.

        Args:
            config: Complete scenario configuration.
        """
        self.config = config
        self.env: simpy.Environment | None = None
        self.server: SimulatedServer | None = None
        self.metrics_collector: MetricsCollector | None = None
        self.clients: list[SimulatedClient] = []

    def run(self) -> SimulationMetrics:
        """
        Execute the simulation and return aggregated metrics.

        Returns:
            SimulationMetrics with all collected data.
        """
        # Set random seed for reproducibility
        if self.config.simulation.random_seed is not None:
            random.seed(self.config.simulation.random_seed)

        # Create SimPy environment
        self.env = simpy.Environment()

        # Create server
        self.server = SimulatedServer(self.config.server)

        # Create metrics collector
        self.metrics_collector = MetricsCollector(
            scenario_name=self.config.name,
            strategy=self.config.rate_limit.strategy,
            num_processes=self.config.simulation.num_processes,
            server_quota=self.config.server.quota_per_minute,
        )

        # Create client processes with multiple workers each
        self.clients = []
        workers_per_process = self.config.simulation.workers_per_process
        requests_per_process = self.config.simulation.requests_per_process

        for process_id in range(self.config.simulation.num_processes):
            # All workers in a process share the same client (and rate limiter)
            client = SimulatedClient(
                process_id=process_id,
                rate_limit_config=self.config.rate_limit,
                retry_config=self.config.retry,
                server=self.server,
                metrics_collector=self.metrics_collector,
                env=self.env,
            )
            self.clients.append(client)

            # Distribute requests among workers
            requests_per_worker = requests_per_process // workers_per_process
            remainder = requests_per_process % workers_per_process

            # Start multiple workers per process (all sharing the same client)
            for worker_id in range(workers_per_process):
                # Distribute remainder requests to first workers
                worker_requests = requests_per_worker + (1 if worker_id < remainder else 0)
                if worker_requests > 0:
                    self.env.process(
                        self._worker_process(
                            client,
                            worker_id,
                            worker_requests,
                        )
                    )

        # Run simulation
        self.env.run(until=self.config.simulation.duration_seconds)

        # Aggregate and return metrics
        return self.metrics_collector.aggregate(
            duration=self.config.simulation.duration_seconds
        )

    def _worker_process(
        self,
        client: SimulatedClient,
        worker_id: int,
        num_requests: int,
    ) -> Generator[simpy.Event, None, None]:
        """
        SimPy process for a single worker within a client process.

        Multiple workers share the same client (and rate limiter), running concurrently.
        This simulates the thread pool pattern used by RQC's execute_many().

        Args:
            client: The shared client to use for requests.
            worker_id: Worker identifier within the process.
            num_requests: Number of requests this worker will make.

        Yields:
            SimPy events.
        """
        # Stagger worker start times slightly to avoid thundering herd
        initial_delay = worker_id * 0.01  # 10ms stagger per worker
        if initial_delay > 0:
            yield self.env.timeout(initial_delay)

        for _ in range(num_requests):
            # Calculate inter-arrival delay based on pattern
            delay = self._get_inter_arrival_delay()
            if delay > 0:
                yield self.env.timeout(delay)

            # Check if simulation time exceeded
            if self.env.now >= self.config.simulation.duration_seconds:
                break

            # Execute request (may block on rate limiter shared with other workers)
            yield self.env.process(
                client.execute_request(
                    client_type=self.config.simulation.client_type
                )
            )

    def _get_inter_arrival_delay(self) -> float:
        """
        Calculate delay between requests based on arrival pattern.

        With multiple workers per process, each worker independently generates
        arrivals. The mean_interval is calculated so that all workers together
        achieve the target request rate.

        Returns:
            Delay in seconds before next request.
        """
        pattern = self.config.simulation.arrival_pattern
        num_processes = self.config.simulation.num_processes
        workers_per_process = self.config.simulation.workers_per_process
        requests_per_process = self.config.simulation.requests_per_process
        duration = self.config.simulation.duration_seconds

        # Total workers across all processes
        total_workers = num_processes * workers_per_process

        # Calculate target rate for all workers combined
        total_requests = num_processes * requests_per_process
        target_rate = total_requests / duration  # requests per second total

        # Each worker should generate at rate = target_rate / total_workers
        # Mean interval for each worker = total_workers / target_rate
        mean_interval = total_workers / target_rate if target_rate > 0 else 1.0

        if pattern == "constant":
            # Constant rate
            return mean_interval

        if pattern == "poisson":
            # Poisson arrivals (exponential inter-arrival times)
            return random.expovariate(1.0 / mean_interval) if mean_interval > 0 else 0.0

        if pattern == "burst":
            # Bursty traffic: 80% short delays, 20% long pauses
            if random.random() < 0.8:
                return mean_interval * 0.2  # Fast burst
            else:
                return mean_interval * 4.0  # Long pause

        return mean_interval


def run_scenario(config: ScenarioConfig) -> SimulationMetrics:
    """
    Convenience function to run a single scenario.

    Args:
        config: Scenario configuration.

    Returns:
        Aggregated simulation metrics.
    """
    simulator = Simulator(config)
    return simulator.run()
