"""
Visualization utilities for simulation results.

Generates charts comparing strategies, presets, and process counts.
"""

from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from simulations.src.metrics import SimulationMetrics


def setup_style() -> None:
    """Set up matplotlib/seaborn style for consistent visuals."""
    sns.set_theme(style="whitegrid", palette="husl")
    plt.rcParams["figure.figsize"] = (12, 6)
    plt.rcParams["figure.dpi"] = 100
    plt.rcParams["font.size"] = 10


def metrics_to_dataframe(metrics_list: Sequence[SimulationMetrics]) -> pd.DataFrame:
    """Convert list of metrics to DataFrame."""
    return pd.DataFrame([m.to_dict() for m in metrics_list])


def plot_strategy_comparison(
    df: pd.DataFrame,
    output_path: Path,
    title: str = "Rate Limiting Strategy Comparison",
) -> None:
    """
    Create comparison chart for different strategies.

    Args:
        df: DataFrame with metrics from different strategies.
        output_path: Path to save the chart.
        title: Chart title.
    """
    setup_style()

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # Success Rate
    ax1 = axes[0, 0]
    sns.barplot(data=df, x="strategy", y="success_rate", ax=ax1)
    ax1.set_title("Success Rate (%)")
    ax1.set_xlabel("Strategy")
    ax1.set_ylabel("Success Rate (%)")
    ax1.set_ylim(0, 105)

    # 429 Rate
    ax2 = axes[0, 1]
    sns.barplot(data=df, x="strategy", y="rate_429", ax=ax2)
    ax2.set_title("429 Response Rate (%)")
    ax2.set_xlabel("Strategy")
    ax2.set_ylabel("429 Rate (%)")

    # Latency P95
    ax3 = axes[1, 0]
    sns.barplot(data=df, x="strategy", y="latency_p95", ax=ax3)
    ax3.set_title("Latency P95 (seconds)")
    ax3.set_xlabel("Strategy")
    ax3.set_ylabel("Latency (s)")

    # Throughput
    ax4 = axes[1, 1]
    sns.barplot(data=df, x="strategy", y="throughput_per_minute", ax=ax4)
    ax4.set_title("Throughput (requests/minute)")
    ax4.set_xlabel("Strategy")
    ax4.set_ylabel("Requests/min")

    fig.suptitle(title, fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(output_path, bbox_inches="tight")
    plt.close()


def plot_preset_comparison(
    df: pd.DataFrame,
    output_path: Path,
    title: str = "Adaptive Preset Comparison",
) -> None:
    """
    Create comparison chart for different presets.

    Args:
        df: DataFrame with metrics from different presets.
        output_path: Path to save the chart.
        title: Chart title.
    """
    setup_style()

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # Success Rate
    ax1 = axes[0, 0]
    sns.barplot(data=df, x="scenario", y="success_rate", ax=ax1)
    ax1.set_title("Success Rate (%)")
    ax1.set_xlabel("Preset")
    ax1.set_ylabel("Success Rate (%)")
    ax1.set_ylim(0, 105)
    ax1.tick_params(axis='x', rotation=45)

    # 429 Rate
    ax2 = axes[0, 1]
    sns.barplot(data=df, x="scenario", y="rate_429", ax=ax2)
    ax2.set_title("429 Response Rate (%)")
    ax2.set_xlabel("Preset")
    ax2.set_ylabel("429 Rate (%)")
    ax2.tick_params(axis='x', rotation=45)

    # Latency P95
    ax3 = axes[1, 0]
    sns.barplot(data=df, x="scenario", y="latency_p95", ax=ax3)
    ax3.set_title("Latency P95 (seconds)")
    ax3.set_xlabel("Preset")
    ax3.set_ylabel("Latency (s)")
    ax3.tick_params(axis='x', rotation=45)

    # RPS Amplification
    ax4 = axes[1, 1]
    sns.barplot(data=df, x="scenario", y="rps_amplification", ax=ax4)
    ax4.set_title("RPS Amplification (retry overhead)")
    ax4.set_xlabel("Preset")
    ax4.set_ylabel("Amplification")
    ax4.tick_params(axis='x', rotation=45)

    fig.suptitle(title, fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(output_path, bbox_inches="tight")
    plt.close()


def plot_process_scaling(
    df: pd.DataFrame,
    output_path: Path,
    title: str = "Impact of Process Count",
) -> None:
    """
    Create chart showing impact of number of processes.

    Args:
        df: DataFrame with metrics from different process counts.
        output_path: Path to save the chart.
        title: Chart title.
    """
    setup_style()

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # Success Rate vs Processes
    ax1 = axes[0, 0]
    sns.lineplot(data=df, x="processes", y="success_rate", marker="o", ax=ax1)
    ax1.set_title("Success Rate vs Process Count")
    ax1.set_xlabel("Number of Processes")
    ax1.set_ylabel("Success Rate (%)")
    ax1.set_ylim(0, 105)

    # 429 Rate vs Processes
    ax2 = axes[0, 1]
    sns.lineplot(data=df, x="processes", y="rate_429", marker="o", ax=ax2)
    ax2.set_title("429 Rate vs Process Count")
    ax2.set_xlabel("Number of Processes")
    ax2.set_ylabel("429 Rate (%)")

    # Latency P95 vs Processes
    ax3 = axes[1, 0]
    sns.lineplot(data=df, x="processes", y="latency_p95", marker="o", ax=ax3)
    ax3.set_title("Latency P95 vs Process Count")
    ax3.set_xlabel("Number of Processes")
    ax3.set_ylabel("Latency (s)")

    # Throughput vs Processes
    ax4 = axes[1, 1]
    sns.lineplot(data=df, x="processes", y="throughput_per_minute", marker="o", ax=ax4)
    ax4.set_title("Throughput vs Process Count")
    ax4.set_xlabel("Number of Processes")
    ax4.set_ylabel("Requests/min")

    fig.suptitle(title, fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(output_path, bbox_inches="tight")
    plt.close()


def plot_time_series(
    metrics: SimulationMetrics,
    output_path: Path,
    title: str | None = None,
) -> None:
    """
    Plot time series data for a single scenario.

    Args:
        metrics: Metrics with time series data.
        output_path: Path to save the chart.
        title: Optional title override.
    """
    setup_style()

    fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)

    title = title or f"{metrics.scenario_name} - Time Series"

    # Success Rate over Time
    ax1 = axes[0]
    if metrics.success_rate_over_time:
        times = [p.time for p in metrics.success_rate_over_time]
        values = [p.value for p in metrics.success_rate_over_time]
        ax1.plot(times, values, marker=".", markersize=3)
    ax1.set_title("Success Rate Over Time")
    ax1.set_ylabel("Success Rate (%)")
    ax1.set_ylim(0, 105)

    # Effective Rate over Time (for AIMD)
    ax2 = axes[1]
    if metrics.effective_rate_over_time:
        times = [p.time for p in metrics.effective_rate_over_time]
        values = [p.value for p in metrics.effective_rate_over_time]
        ax2.plot(times, values, marker=".", markersize=2, alpha=0.7)
    ax2.set_title("Effective Rate Over Time (AIMD Adaptation)")
    ax2.set_ylabel("Effective Rate")

    # Latency over Time
    ax3 = axes[2]
    if metrics.latency_over_time:
        times = [p.time for p in metrics.latency_over_time]
        values = [p.value for p in metrics.latency_over_time]
        ax3.plot(times, values, marker=".", markersize=3)
    ax3.set_title("Mean Latency Over Time")
    ax3.set_xlabel("Time (seconds)")
    ax3.set_ylabel("Latency (s)")

    fig.suptitle(title, fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(output_path, bbox_inches="tight")
    plt.close()


def plot_summary_heatmap(
    df: pd.DataFrame,
    output_path: Path,
    title: str = "Success Rate Heatmap",
) -> None:
    """
    Create heatmap of success rates.

    Args:
        df: DataFrame with scenario results.
        output_path: Path to save the chart.
        title: Chart title.
    """
    setup_style()

    # Pivot for heatmap (strategy vs processes)
    if "strategy" in df.columns and "processes" in df.columns:
        pivot = df.pivot_table(
            values="success_rate",
            index="strategy",
            columns="processes",
            aggfunc="mean",
        )

        plt.figure(figsize=(10, 6))
        sns.heatmap(
            pivot,
            annot=True,
            fmt=".1f",
            cmap="RdYlGn",
            vmin=0,
            vmax=100,
            cbar_kws={"label": "Success Rate (%)"},
        )
        plt.title(title)
        plt.xlabel("Number of Processes")
        plt.ylabel("Strategy")
        plt.tight_layout()
        plt.savefig(output_path, bbox_inches="tight")
        plt.close()
