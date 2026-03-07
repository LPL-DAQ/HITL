#!/usr/bin/env python3
"""
Compare two telemetry CSV files with different layouts and generate plots.

Supported inputs
----------------
1) Event / long format:
   time,sensor,value,event,system,source
   1772875760948537,gnc_ptf401,0.0,,atlas,gnc
   1772875760948537,gnc_pto401,0.0,,atlas,gnc
   ...

2) Wide / row-per-timestamp format:
   time,data_queue_size,fuel_valve_setpoint,fuel_valve_internal_pos,...
   0.000,0,81,81.12,80.22,...
   0.001,0,81,80.97,80.22,...
   ...

What the script does
--------------------
- Loads both CSVs with pandas.
- Converts the long/event CSV into a wide dataframe by pivoting on sensor names.
- Renames the wide CSV columns into a canonical naming scheme so the two files can be compared.
- Normalizes time for both files to "seconds from start".
- Generates comparison plots with time on the x-axis.
- Writes a summary CSV with basic error statistics for common signals.

Example
-------
python compare_telemetry_csvs.py event_style.csv row_style.csv --outdir plots
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# Edit this mapping if your row-per-timestamp CSV uses slightly different names.
WIDE_TO_CANONICAL = {
    # Shared time-series / queue info
    "data_queue_size": "gnc_data_queue_size",
    # Fuel valve / motor positions
    "fuel_valve_setpoint": "gnc_fuel_target",
    "fuel_valve_internal_pos": "gnc_fuel_driver",
    "fuel_valve_driver": "gnc_fuel_driver",
    "fuel_valve_encoder_pos": "gnc_fuel_encoder",
    # Lox valve / motor positions
    "lox_valve_setpoint": "gnc_lox_target",
    "lox_valve_internal_pos": "gnc_lox_driver",
    "lox_valve_driver": "gnc_lox_driver",
    "lox_valve_encoder_pos": "gnc_lox_encoder",
    # PTs
    "pt102": "gnc_pt102",
    "pt103": "gnc_pt103",
    "pt202": "gnc_pt202",
    "pt203": "gnc_pt203",
    "ptf401": "gnc_ptf401",
    "pto401": "gnc_pto401",
    "ptc401": "gnc_ptc401",
    "ptc402": "gnc_ptc402",
    # Optional / sometimes present extras
    "predicted_thrust": "gnc_predicted_thrust",
    "target_thrust": "gnc_target_thrust",
    "predicted_of": "gnc_predicted_of",
    "mdot_fuel": "gnc_mdot_fuel",
    "mdot_lox": "gnc_mdot_lox",
    "thrust_error": "gnc_thrust_error",
    "change_alpha_cmd": "gnc_change_alpha_cmd",
    "clamped_change_alpha_cmd": "gnc_clamped_change_alpha_cmd",
    "alpha": "gnc_alpha",
    "thrust_from_alpha": "gnc_thrust_from_alpha",
}

PT_SIGNALS = [
    "gnc_pt102",
    "gnc_pt103",
    "gnc_pt202",
    "gnc_pt203",
    "gnc_ptf401",
    "gnc_pto401",
    "gnc_ptc401",
    "gnc_ptc402",
]

MOTOR_SIGNALS = [
    "gnc_fuel_target",
    "gnc_fuel_driver",
    "gnc_fuel_encoder",
    "gnc_lox_target",
    "gnc_lox_driver",
    "gnc_lox_encoder",
]

PREFERRED_EXTRA_GROUPS = {
    "queue_size": ["gnc_data_queue_size"],
    "thrust_model": [
        "gnc_predicted_thrust",
        "gnc_target_thrust",
        "gnc_thrust_error",
        "gnc_thrust_from_alpha",
    ],
    "mixture_and_flow": ["gnc_predicted_of", "gnc_mdot_fuel", "gnc_mdot_lox", "gnc_alpha"],
    "control_cmds": ["gnc_change_alpha_cmd", "gnc_clamped_change_alpha_cmd"],
}

TIME_COL = "time_s"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two differently structured telemetry CSV files.")
    parser.add_argument("csv_a", type=Path, help="First CSV file path")
    parser.add_argument("csv_b", type=Path, help="Second CSV file path")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("comparison_plots"),
        help="Directory where PNG plots and summary CSV will be written",
    )
    return parser.parse_args()


def infer_time_divisor(raw_time: pd.Series) -> float:
    """Guess the time unit scale and convert to seconds.

    Heuristic:
    - ~1e15 epoch-ish values are usually microseconds.
    - ~1e18 are usually nanoseconds.
    - ~1e12 are usually milliseconds.
    - Otherwise assume the input is already in seconds.
    """
    t = pd.to_numeric(raw_time, errors="coerce").dropna()
    if t.empty:
        return 1.0

    first_abs = float(abs(t.iloc[0]))
    span = float(abs(t.iloc[-1] - t.iloc[0]))

    if first_abs >= 1e17 or span >= 1e12:
        return 1e9   # ns -> s
    if first_abs >= 1e14 or span >= 1e9:
        return 1e6   # us -> s
    if first_abs >= 1e11 or span >= 1e6:
        return 1e3   # ms -> s
    return 1.0       # already seconds


def normalize_time_to_seconds(df: pd.DataFrame, raw_time_col: str = "time") -> pd.DataFrame:
    out = df.copy()
    raw_t = pd.to_numeric(out[raw_time_col], errors="coerce")
    divisor = infer_time_divisor(raw_t)
    out[TIME_COL] = (raw_t - raw_t.iloc[0]) / divisor
    out = out.sort_values(TIME_COL).reset_index(drop=True)
    return out


def make_unique_columns(columns: Sequence[str]) -> list[str]:
    counts: dict[str, int] = {}
    out: list[str] = []
    for col in columns:
        base = col.strip()
        if base not in counts:
            counts[base] = 0
            out.append(base)
        else:
            counts[base] += 1
            out.append(f"{base}_{counts[base]}")
    return out


def ensure_numeric_except_time(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if col == TIME_COL:
            continue
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def load_long_event_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = make_unique_columns(df.columns)
    required = {"time", "sensor", "value"}
    if not required.issubset(df.columns):
        raise ValueError(f"{path} does not look like the long/event format. Missing: {required - set(df.columns)}")

    temp = df[["time", "sensor", "value"]].copy()
    temp["sensor"] = temp["sensor"].astype(str).str.strip()
    temp["value"] = pd.to_numeric(temp["value"], errors="coerce")

    # Pivot to one row per timestamp, one column per sensor.
    wide = (
        temp.pivot_table(index="time", columns="sensor", values="value", aggfunc="last")
        .reset_index()
        .rename_axis(columns=None)
    )
    wide = normalize_time_to_seconds(wide, raw_time_col="time")
    wide = ensure_numeric_except_time(wide)
    return wide


def load_wide_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = make_unique_columns(df.columns)
    if "time" not in df.columns:
        raise ValueError(f"{path} does not have a 'time' column.")

    renamed = {}
    for col in df.columns:
        key = col.strip()
        renamed[col] = WIDE_TO_CANONICAL.get(key, key)

    out = df.rename(columns=renamed)
    out = normalize_time_to_seconds(out, raw_time_col="time")
    out = ensure_numeric_except_time(out)
    return out


def detect_and_load(path: Path) -> pd.DataFrame:
    preview = pd.read_csv(path, nrows=5)
    cols = {c.strip() for c in preview.columns}
    if {"time", "sensor", "value"}.issubset(cols):
        return load_long_event_csv(path)
    if "time" in cols:
        return load_wide_csv(path)
    raise ValueError(
        f"Could not identify CSV format for {path}. Expected either a long format with columns "
        "time/sensor/value or a wide format with a time column."
    )


def available_signals(df: pd.DataFrame) -> set[str]:
    return {c for c in df.columns if c not in {"time", TIME_COL}}


def common_signals(df_a: pd.DataFrame, df_b: pd.DataFrame) -> list[str]:
    common = sorted(available_signals(df_a) & available_signals(df_b))
    return [c for c in common if pd.api.types.is_numeric_dtype(df_a[c]) and pd.api.types.is_numeric_dtype(df_b[c])]


def infer_match_tolerance_seconds(df: pd.DataFrame) -> float:
    t = pd.to_numeric(df[TIME_COL], errors="coerce").dropna().sort_values()
    diffs = t.diff().dropna()
    diffs = diffs[diffs > 0]
    if diffs.empty:
        return 0.02
    dt = float(diffs.median())
    return max(0.5 * dt, 1e-6)


def comparison_stats(df_a: pd.DataFrame, df_b: pd.DataFrame, signals: Iterable[str]) -> pd.DataFrame:
    rows = []
    tol = max(infer_match_tolerance_seconds(df_a), infer_match_tolerance_seconds(df_b))

    for signal in signals:
        a = df_a[[TIME_COL, signal]].dropna().sort_values(TIME_COL)
        b = df_b[[TIME_COL, signal]].dropna().sort_values(TIME_COL)
        if a.empty or b.empty:
            continue

        merged = pd.merge_asof(
            a,
            b,
            on=TIME_COL,
            direction="nearest",
            tolerance=tol,
            suffixes=("_a", "_b"),
        ).dropna()

        if merged.empty:
            rows.append(
                {
                    "signal": signal,
                    "matched_points": 0,
                    "mean_abs_error": np.nan,
                    "max_abs_error": np.nan,
                    "rmse": np.nan,
                    "time_tolerance_s": tol,
                }
            )
            continue

        err = merged[f"{signal}_a"] - merged[f"{signal}_b"]
        rows.append(
            {
                "signal": signal,
                "matched_points": int(len(merged)),
                "mean_abs_error": float(err.abs().mean()),
                "max_abs_error": float(err.abs().max()),
                "rmse": float(np.sqrt(np.mean(np.square(err)))),
                "time_tolerance_s": tol,
            }
        )

    return pd.DataFrame(rows).sort_values(["matched_points", "signal"], ascending=[False, True])


def plot_signal_group(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    signals: Sequence[str],
    title: str,
    output_path: Path,
    label_a: str,
    label_b: str,
) -> bool:
    usable = [s for s in signals if s in df_a.columns or s in df_b.columns]
    if not usable:
        return False

    colors = plt.rcParams["axes.prop_cycle"].by_key().get("color", []) or [None]
    fig, ax = plt.subplots(figsize=(14, 7))

    for idx, signal in enumerate(usable):
        color = colors[idx % len(colors)] if colors[0] is not None else None
        plotted_any = False

        if signal in df_a.columns and df_a[signal].notna().any():
            ax.plot(
                df_a[TIME_COL],
                df_a[signal],
                linestyle="-",
                linewidth=1.5,
                color=color,
                label=f"{label_a} | {signal}",
            )
            plotted_any = True

        if signal in df_b.columns and df_b[signal].notna().any():
            ax.plot(
                df_b[TIME_COL],
                df_b[signal],
                linestyle="--",
                linewidth=1.5,
                color=color,
                label=f"{label_b} | {signal}",
            )
            plotted_any = True

        if not plotted_any:
            continue

    ax.set_title(title)
    ax.set_xlabel("Time from start (s)")
    ax.set_ylabel("Value")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return True


def plot_single_signal(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    signal: str,
    output_path: Path,
    label_a: str,
    label_b: str,
) -> bool:
    if signal not in df_a.columns and signal not in df_b.columns:
        return False

    fig, ax = plt.subplots(figsize=(12, 6))
    plotted = False

    if signal in df_a.columns and df_a[signal].notna().any():
        ax.plot(df_a[TIME_COL], df_a[signal], label=f"{label_a} | {signal}", linewidth=1.6)
        plotted = True
    if signal in df_b.columns and df_b[signal].notna().any():
        ax.plot(df_b[TIME_COL], df_b[signal], label=f"{label_b} | {signal}", linewidth=1.6, linestyle="--")
        plotted = True

    if not plotted:
        plt.close(fig)
        return False

    ax.set_title(f"Comparison: {signal}")
    ax.set_xlabel("Time from start (s)")
    ax.set_ylabel(signal)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return True


def write_column_report(df_a: pd.DataFrame, df_b: pd.DataFrame, outdir: Path, label_a: str, label_b: str) -> None:
    cols_a = sorted(available_signals(df_a))
    cols_b = sorted(available_signals(df_b))
    common = sorted(set(cols_a) & set(cols_b))
    only_a = sorted(set(cols_a) - set(cols_b))
    only_b = sorted(set(cols_b) - set(cols_a))

    report_path = outdir / "column_report.txt"
    report_path.write_text(
        "\n".join(
            [
                f"{label_a} columns: {len(cols_a)}",
                *cols_a,
                "",
                f"{label_b} columns: {len(cols_b)}",
                *cols_b,
                "",
                f"Common columns: {len(common)}",
                *common,
                "",
                f"Only in {label_a}: {len(only_a)}",
                *only_a,
                "",
                f"Only in {label_b}: {len(only_b)}",
                *only_b,
            ]
        )
    )


def main() -> None:
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    df_a = detect_and_load(args.csv_a)
    df_b = detect_and_load(args.csv_b)

    label_a = args.csv_a.stem
    label_b = args.csv_b.stem

    plotted_signals: set[str] = set()

    # Required groups from your request.
    if plot_signal_group(
        df_a,
        df_b,
        PT_SIGNALS,
        title="PT Comparison",
        output_path=args.outdir / "01_pts_comparison.png",
        label_a=label_a,
        label_b=label_b,
    ):
        plotted_signals.update(s for s in PT_SIGNALS if s in df_a.columns or s in df_b.columns)

    if plot_signal_group(
        df_a,
        df_b,
        MOTOR_SIGNALS,
        title="Motor Position Comparison",
        output_path=args.outdir / "02_motor_positions_comparison.png",
        label_a=label_a,
        label_b=label_b,
    ):
        plotted_signals.update(s for s in MOTOR_SIGNALS if s in df_a.columns or s in df_b.columns)

    # Extra groups at my discretion, only if those signals exist.
    group_idx = 3
    for group_name, signals in PREFERRED_EXTRA_GROUPS.items():
        made = plot_signal_group(
            df_a,
            df_b,
            signals,
            title=group_name.replace("_", " ").title() + " Comparison",
            output_path=args.outdir / f"{group_idx:02d}_{group_name}_comparison.png",
            label_a=label_a,
            label_b=label_b,
        )
        if made:
            plotted_signals.update(s for s in signals if s in df_a.columns or s in df_b.columns)
            group_idx += 1

    # Any remaining common signals get their own plot so nothing useful is missed.
    common = common_signals(df_a, df_b)
    leftovers = [s for s in common if s not in plotted_signals]
    for signal in leftovers:
        made = plot_single_signal(
            df_a,
            df_b,
            signal,
            args.outdir / f"{group_idx:02d}_{signal}_comparison.png",
            label_a,
            label_b,
        )
        if made:
            group_idx += 1

    stats = comparison_stats(df_a, df_b, common)
    if not stats.empty:
        stats.to_csv(args.outdir / "comparison_summary.csv", index=False)

    write_column_report(df_a, df_b, args.outdir, label_a, label_b)

    print(f"Loaded {args.csv_a} -> shape {df_a.shape}")
    print(f"Loaded {args.csv_b} -> shape {df_b.shape}")
    print(f"Wrote outputs to: {args.outdir.resolve()}")
    if not stats.empty:
        print(f"Saved summary stats: {(args.outdir / 'comparison_summary.csv').resolve()}")


if __name__ == "__main__":
    main()
