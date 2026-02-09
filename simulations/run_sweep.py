#!/usr/bin/env python3
"""
Run sweep test and generate line charts like Marc Brooker's blog.

Inspirado em: https://brooker.co.za/blog/2022/02/28/retries.html

Usage:
    python run_sweep.py                  # Default: RQC workload
    python run_sweep.py --workload rqc   # Explicit: RQC workload
    python run_sweep.py --workload agent # Agent workload
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Literal

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from simulations.src.simulator import run_scenario
from simulations.src.metrics import SimulationMetrics


WorkloadType = Literal["rqc", "agent"]


def load_scenarios(workload: WorkloadType):
    """
    Load scenarios based on workload type.

    Returns:
        Tuple of (SCENARIOS, STRATEGIES, CONTENTION_LEVELS)
    """
    if workload == "agent":
        from simulations.scenarios.agent_sweep_test import (
            SCENARIOS,
            STRATEGIES,
            CONTENTION_LEVELS,
        )
    else:
        from simulations.scenarios.rqc_sweep_test import (
            SCENARIOS,
            STRATEGIES,
            CONTENTION_LEVELS,
        )
    return SCENARIOS, STRATEGIES, CONTENTION_LEVELS


def create_run_directory(base_dir: Path, workload: WorkloadType) -> Path:
    """
    Create a timestamped directory for this run and update the 'latest' symlink.

    Args:
        base_dir: Base results directory (e.g., simulations/results/)
        workload: Workload type (rqc or agent)

    Returns:
        Path to the created run directory (e.g., simulations/results/rqc/2024-02-01_12-30-45/)
    """
    # Create workload-specific subdirectory
    workload_dir = base_dir / workload
    workload_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = workload_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    # Create/update symlink "latest" pointing to this run
    latest = workload_dir / "latest"
    if latest.is_symlink():
        latest.unlink()
    elif latest.exists():
        # Handle case where "latest" is a regular file/directory
        latest.unlink() if latest.is_file() else None
    latest.symlink_to(run_dir.name)

    return run_dir


def run_sweep(scenarios, strategies, contention_levels) -> dict[str, dict[int, SimulationMetrics]]:
    """
    Run all sweep scenarios and organize results by strategy and contention level.

    Returns:
        Dict[strategy_name, Dict[num_processes, metrics]]
    """
    results = defaultdict(dict)

    total = len(scenarios)
    for i, scenario in enumerate(scenarios, 1):
        # Parse scenario name: "Nproc-strategy"
        parts = scenario.name.split("-", 1)
        num_processes = int(parts[0].replace("proc", ""))
        strategy = parts[1]

        print(f"  [{i:2d}/{total}] {scenario.name}...", end=" ", flush=True)

        metrics = run_scenario(scenario)
        results[strategy][num_processes] = metrics

        print(f"Success: {metrics.success_rate:.1f}%, 429: {metrics.rate_429:.1f}%")

    return dict(results)


def create_line_charts(
    results: dict[str, dict[int, SimulationMetrics]],
    output_dir: Path,
    strategies: dict,
    contention_levels: list[int],
    workload: WorkloadType,
) -> None:
    """
    Create essential charts comparing strategies across contention levels.

    Generates 5 charts:
    1. graph_01_success_rate_vs_server_load.png - Main: Client Success Rate + Server Load
    2. graph_02_success_rate_vs_rejection_rate.png - Client Success Rate + Server Rejection Rate
    3. graph_03_failure_breakdown.png - Why requests failed (client perspective)
    4. graph_04_efficiency_score.png - Efficiency score (success per unit of load)
    5. graph_05_success_rate_vs_latency.png - Success Rate vs Latency trade-off
    """
    # Prepare data
    data = []
    for strategy, levels in results.items():
        for num_proc, metrics in levels.items():
            data.append({
                "Strategy": strategy,
                "Processes": num_proc,
                "Success Rate (%)": metrics.success_rate,
                "Failure Rate (%)": metrics.failure_rate,
                "Token Timeout (%)": metrics.failure_rate_token_timeout,
                "Server 429 (%)": metrics.failure_rate_server_429,
                "Server Error (%)": metrics.failure_rate_server_error,
                "Server Rejection Rate (%)": metrics.server_rejection_rate,
                "Total Attempts": metrics.total_attempts,
                "RPS Amplification": metrics.rps_amplification,
            })

    df = pd.DataFrame(data)

    # Color palette for strategies
    colors = {
        "none": "#e74c3c",         # Red
        "token_bucket": "#3498db", # Blue
        "optimistic": "#f39c12",   # Orange
        "balanced": "#9b59b6",     # Purple
        "conservative": "#2ecc71", # Green
        "congestion_aware": "#00bcd4",   # Cyan (congestion_aware)
    }

    # Line styles
    markers = {
        "none": "o",
        "token_bucket": "s",
        "optimistic": "^",
        "balanced": "D",
        "conservative": "v",
        "congestion_aware": "*",
    }

    # Workload label for titles
    workload_label = "Agent::chat()" if workload == "agent" else "RQC"

    # ==========================================================================
    # Chart 1: Client Success Rate vs Server Load (MAIN CHART)
    # ==========================================================================
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Left: Client Success Rate
    ax1 = axes[0]
    for strategy in strategies.keys():
        strategy_data = df[df["Strategy"] == strategy].sort_values("Processes")
        ax1.plot(
            strategy_data["Processes"],
            strategy_data["Success Rate (%)"],
            marker=markers[strategy],
            color=colors[strategy],
            linewidth=2,
            markersize=8,
            label=strategy.replace("_", " ").title(),
        )

    ax1.set_xlabel("Number of Processes", fontsize=11)
    ax1.set_ylabel("Success Rate (%)", fontsize=11)
    ax1.set_title("Client Success Rate\n(Higher is better)", fontsize=12, fontweight="bold")
    ax1.set_xticks(contention_levels)
    ax1.set_ylim(0, 105)
    ax1.axhline(y=90, color="green", linestyle="--", alpha=0.3)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="lower left", fontsize=9)

    # Right: Server Load (Total Attempts)
    ax2 = axes[1]
    for strategy in strategies.keys():
        strategy_data = df[df["Strategy"] == strategy].sort_values("Processes")

        total_attempts = []
        for proc in strategy_data["Processes"].values:
            total_attempts.append(results[strategy][proc].total_attempts)

        ax2.plot(
            strategy_data["Processes"],
            total_attempts,
            marker=markers[strategy],
            color=colors[strategy],
            linewidth=2,
            markersize=8,
            label=strategy.replace("_", " ").title(),
        )

    ax2.set_xlabel("Number of Processes", fontsize=11)
    ax2.set_ylabel("Total Attempts (requests to server)", fontsize=11)
    ax2.set_title("Server Load\n(Lower is better)", fontsize=12, fontweight="bold")
    ax2.set_xticks(contention_levels)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc="upper left", fontsize=9)

    fig.suptitle(
        f"[{workload_label}] Client Success vs Server Load\n"
        "(Ideal: high success rate with low server load)",
        fontsize=13,
        fontweight="bold",
        y=1.02,
    )

    plt.tight_layout()
    plt.savefig(output_dir / "graph_01_success_rate_vs_server_load.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: graph_01_success_rate_vs_server_load.png")

    # ==========================================================================
    # Chart 2: Success Rate + Server Rejection Rate (normalized view)
    # ==========================================================================
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Left: Success Rate
    ax1 = axes[0]
    for strategy in strategies.keys():
        strategy_data = df[df["Strategy"] == strategy].sort_values("Processes")
        ax1.plot(
            strategy_data["Processes"],
            strategy_data["Success Rate (%)"],
            marker=markers[strategy],
            color=colors[strategy],
            linewidth=2,
            markersize=8,
            label=strategy.replace("_", " ").title(),
        )

    ax1.set_xlabel("Number of Processes", fontsize=11)
    ax1.set_ylabel("Success Rate (%)", fontsize=11)
    ax1.set_title("Client Success Rate\n(Higher is better)", fontsize=12, fontweight="bold")
    ax1.set_xticks(contention_levels)
    ax1.set_ylim(0, 105)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="lower left", fontsize=9)

    # Right: Server Rejection Rate (normalized metric)
    ax2 = axes[1]
    for strategy in strategies.keys():
        strategy_data = df[df["Strategy"] == strategy].sort_values("Processes")

        rejection_rates = []
        for proc in strategy_data["Processes"].values:
            rejection_rates.append(results[strategy][proc].server_rejection_rate)

        ax2.plot(
            strategy_data["Processes"],
            rejection_rates,
            marker=markers[strategy],
            color=colors[strategy],
            linewidth=2,
            markersize=8,
            label=strategy.replace("_", " ").title(),
        )

    ax2.set_xlabel("Number of Processes", fontsize=11)
    ax2.set_ylabel("Server Rejection Rate (%)", fontsize=11)
    ax2.set_title("Server Rejection Rate\n(429s ÷ Total Attempts - Lower is better)", fontsize=12, fontweight="bold")
    ax2.set_xticks(contention_levels)
    ax2.set_ylim(0, 100)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc="upper left", fontsize=9)

    fig.suptitle(
        f"[{workload_label}] Rate Limiting Strategies: Client Success vs Server Rejection\n"
        "(Server quota: 100 req/min, varying client count)",
        fontsize=13,
        fontweight="bold",
        y=1.02,
    )

    plt.tight_layout()
    plt.savefig(output_dir / "graph_02_success_rate_vs_rejection_rate.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: graph_02_success_rate_vs_rejection_rate.png")

    # ==========================================================================
    # Chart 3: Failure Breakdown (why did requests fail?)
    # ==========================================================================
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Left: Token Timeout Rate (client-side failures)
    ax1 = axes[0]
    for strategy in strategies.keys():
        strategy_data = df[df["Strategy"] == strategy].sort_values("Processes")
        ax1.plot(
            strategy_data["Processes"],
            strategy_data["Token Timeout (%)"],
            marker=markers[strategy],
            color=colors[strategy],
            linewidth=2,
            markersize=8,
            label=strategy.replace("_", " ").title(),
        )

    ax1.set_xlabel("Number of Processes", fontsize=11)
    ax1.set_ylabel("Failure Rate (%)", fontsize=11)
    ax1.set_title(
        "Failed: Token Timeout\n(Never reached server)",
        fontsize=12,
        fontweight="bold",
    )
    ax1.set_xticks(contention_levels)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper left", fontsize=9)

    # Right: Server 429 Rate (server-side failures)
    ax2 = axes[1]
    for strategy in strategies.keys():
        strategy_data = df[df["Strategy"] == strategy].sort_values("Processes")
        ax2.plot(
            strategy_data["Processes"],
            strategy_data["Server 429 (%)"],
            marker=markers[strategy],
            color=colors[strategy],
            linewidth=2,
            markersize=8,
            label=strategy.replace("_", " ").title(),
        )

    ax2.set_xlabel("Number of Processes", fontsize=11)
    ax2.set_ylabel("Failure Rate (%)", fontsize=11)
    ax2.set_title(
        "Failed: Server 429\n(Rejected after all retries)",
        fontsize=12,
        fontweight="bold",
    )
    ax2.set_xticks(contention_levels)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc="upper left", fontsize=9)

    fig.suptitle(
        f"[{workload_label}] Failure Breakdown: Why Did Requests Fail? (Client Perspective)",
        fontsize=13,
        fontweight="bold",
        y=1.02,
    )

    plt.tight_layout()
    plt.savefig(output_dir / "graph_03_failure_breakdown.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: graph_03_failure_breakdown.png")

    # ==========================================================================
    # Chart 4: Efficiency Score (success per unit of server load)
    # ==========================================================================
    fig, ax = plt.subplots(figsize=(10, 6))

    for strategy in strategies.keys():
        strategy_data = df[df["Strategy"] == strategy].sort_values("Processes")

        efficiency = (
            strategy_data["Success Rate (%)"].values /
            strategy_data["RPS Amplification"].values
        )

        ax.plot(
            strategy_data["Processes"],
            efficiency,
            marker=markers[strategy],
            color=colors[strategy],
            linewidth=2,
            markersize=8,
            label=strategy.replace("_", " ").title(),
        )

    ax.set_xlabel("Number of Processes (contention level)", fontsize=12)
    ax.set_ylabel("Efficiency (Success % / RPS Amplification)", fontsize=12)
    ax.set_title(
        f"[{workload_label}] Efficiency: Success Rate per Unit of Server Load\n"
        "(Higher is better - more success with less server impact)",
        fontsize=14,
        fontweight="bold",
    )
    ax.set_xticks(contention_levels)
    ax.axhline(y=100, color="green", linestyle="--", alpha=0.3, label="Ideal (100)")
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_dir / "graph_04_efficiency_score.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: graph_04_efficiency_score.png")

    # ==========================================================================
    # Chart 5: Success Rate vs Latency (trade-off chart)
    # ==========================================================================
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Left: Client Success Rate ("what you get")
    ax1 = axes[0]
    for strategy in strategies.keys():
        strategy_data = df[df["Strategy"] == strategy].sort_values("Processes")
        ax1.plot(
            strategy_data["Processes"],
            strategy_data["Success Rate (%)"],
            marker=markers[strategy],
            color=colors[strategy],
            linewidth=2,
            markersize=8,
            label=strategy.replace("_", " ").title(),
        )

    ax1.set_xlabel("Number of Processes", fontsize=11)
    ax1.set_ylabel("Success Rate (%)", fontsize=11)
    ax1.set_title("Client Success Rate\n(What you get - Higher is better)", fontsize=12, fontweight="bold")
    ax1.set_xticks(contention_levels)
    ax1.set_ylim(0, 105)
    ax1.axhline(y=90, color="green", linestyle="--", alpha=0.3)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="lower left", fontsize=9)

    # Right: Latency P95 ("what you pay")
    ax2 = axes[1]
    for strategy in strategies.keys():
        strategy_data = df[df["Strategy"] == strategy].sort_values("Processes")

        latency_p95 = []
        for proc in strategy_data["Processes"].values:
            latency_p95.append(results[strategy][proc].latency_p95)

        ax2.plot(
            strategy_data["Processes"],
            latency_p95,
            marker=markers[strategy],
            color=colors[strategy],
            linewidth=2,
            markersize=8,
            label=strategy.replace("_", " ").title(),
        )

    ax2.set_xlabel("Number of Processes", fontsize=11)
    ax2.set_ylabel("Latency P95 (seconds)", fontsize=11)
    ax2.set_title("Client Latency P95\n(What you pay - Lower is better)", fontsize=12, fontweight="bold")
    ax2.set_xticks(contention_levels)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc="upper left", fontsize=9)

    fig.suptitle(
        f"[{workload_label}] Trade-off: Success Rate vs Latency\n"
        "(High success may come at the cost of higher latency)",
        fontsize=13,
        fontweight="bold",
        y=1.02,
    )

    plt.tight_layout()
    plt.savefig(output_dir / "graph_05_success_rate_vs_latency.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: graph_05_success_rate_vs_latency.png")


def print_summary_table(
    results: dict[str, dict[int, SimulationMetrics]],
    strategies: dict,
    contention_levels: list[int],
) -> None:
    """Print summary table."""
    print("\n" + "=" * 90)
    print("  TABELA RESUMO")
    print("=" * 90)

    # Header
    header = f"{'Strategy':<15}"
    for n in contention_levels:
        header += f" {n}proc"
    print(header)
    print("-" * 90)

    # Success Rate
    print("\nSuccess Rate (%):")
    for strategy in strategies.keys():
        row = f"  {strategy:<13}"
        for n in contention_levels:
            if n in results[strategy]:
                row += f" {results[strategy][n].success_rate:5.1f}"
            else:
                row += "   N/A"
        print(row)

    # 429 Rate (per original request - can exceed 100%)
    print("\n429 Rate (%) [per original request]:")
    for strategy in strategies.keys():
        row = f"  {strategy:<13}"
        for n in contention_levels:
            if n in results[strategy]:
                row += f" {results[strategy][n].rate_429:5.1f}"
            else:
                row += "   N/A"
        print(row)

    # Server Rejection Rate (per attempt - always 0-100%)
    print("\nServer Rejection Rate (%) [429s / total_attempts]:")
    for strategy in strategies.keys():
        row = f"  {strategy:<13}"
        for n in contention_levels:
            if n in results[strategy]:
                row += f" {results[strategy][n].server_rejection_rate:5.1f}"
            else:
                row += "   N/A"
        print(row)

    # Total Attempts (original + retries)
    print("\nTotal Attempts:")
    for strategy in strategies.keys():
        row = f"  {strategy:<13}"
        for n in contention_levels:
            if n in results[strategy]:
                row += f" {results[strategy][n].total_attempts:5d}"
            else:
                row += "   N/A"
        print(row)

    # Wait Time (rate limiter token wait)
    print("\nWait Time Mean (s):")
    for strategy in strategies.keys():
        row = f"  {strategy:<13}"
        for n in contention_levels:
            if n in results[strategy]:
                row += f" {results[strategy][n].wait_time_mean:5.2f}"
            else:
                row += "   N/A"
        print(row)

    # Token Timeouts
    print("\nToken Timeouts:")
    for strategy in strategies.keys():
        row = f"  {strategy:<13}"
        for n in contention_levels:
            if n in results[strategy]:
                row += f" {results[strategy][n].token_timeouts:5d}"
            else:
                row += "   N/A"
        print(row)

    print("\n" + "-" * 90)
    print("  FAILURE BREAKDOWN (Client Perspective)")
    print("-" * 90)

    # Failures: Token Timeout
    print("\nFailed - Token Timeout (%):")
    for strategy in strategies.keys():
        row = f"  {strategy:<13}"
        for n in contention_levels:
            if n in results[strategy]:
                row += f" {results[strategy][n].failure_rate_token_timeout:5.1f}"
            else:
                row += "   N/A"
        print(row)

    # Failures: Server 429
    print("\nFailed - Server 429 (%):")
    for strategy in strategies.keys():
        row = f"  {strategy:<13}"
        for n in contention_levels:
            if n in results[strategy]:
                row += f" {results[strategy][n].failure_rate_server_429:5.1f}"
            else:
                row += "   N/A"
        print(row)

    # Failures: Server Error
    print("\nFailed - Server Error (%):")
    for strategy in strategies.keys():
        row = f"  {strategy:<13}"
        for n in contention_levels:
            if n in results[strategy]:
                row += f" {results[strategy][n].failure_rate_server_error:5.1f}"
            else:
                row += "   N/A"
        print(row)

    # Total Failure Rate
    print("\nTotal Failure Rate (%):")
    for strategy in strategies.keys():
        row = f"  {strategy:<13}"
        for n in contention_levels:
            if n in results[strategy]:
                row += f" {results[strategy][n].failure_rate:5.1f}"
            else:
                row += "   N/A"
        print(row)

    print("\n" + "=" * 90)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run rate limiting sweep tests for stkai SDK.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python run_sweep.py                  # Run RQC workload (default)
    python run_sweep.py --workload rqc   # Run RQC workload (explicit)
    python run_sweep.py --workload agent # Run Agent workload

Workload differences:
    RQC:   ~200ms POST latency, 8 workers/process, 1000 requests/process
    Agent: ~15s POST latency, 2 workers/process, 60 requests/process
        """,
    )
    parser.add_argument(
        "--workload",
        type=str,
        choices=["rqc", "agent"],
        default="rqc",
        help="Workload type to simulate (default: rqc)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workload: WorkloadType = args.workload

    # Load scenarios for the specified workload
    scenarios, strategies, contention_levels = load_scenarios(workload)

    workload_label = "Agent::chat()" if workload == "agent" else "RQC"

    print("=" * 70)
    print(f"  SWEEP TEST: {workload_label} Workload")
    print("  Inspired by: https://brooker.co.za/blog/2022/02/28/retries.html")
    print("=" * 70)
    print(f"\n  Workload: {workload}")
    print(f"  Strategies: {', '.join(strategies.keys())}")
    print(f"  Contention levels: {contention_levels} processes")
    print(f"  Total scenarios: {len(scenarios)}")
    print()

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    # Create timestamped run directory under workload-specific subdirectory
    run_dir = create_run_directory(results_dir, workload)
    print(f"  Output directory: {workload}/{run_dir.name}/")
    print()

    print("Running simulations...")
    results = run_sweep(scenarios, strategies, contention_levels)

    print("\nGenerating charts...")
    create_line_charts(results, run_dir, strategies, contention_levels, workload)

    print_summary_table(results, strategies, contention_levels)

    print("\n" + "=" * 70)
    print("  Sweep test complete!")
    print(f"  Charts saved to: {run_dir}")
    print(f"  Latest symlink: {results_dir / workload / 'latest'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
