import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


CANONICAL_ALIASES = {
    "predicted_thrust": "predicted_thrust",
    "thrust_pred": "predicted_thrust",
    "thrust_pred_lbf": "predicted_thrust",
    "predicted_thrust_lbf": "predicted_thrust",

    "target_thrust": "target_thrust",

    "predicted_of": "predicted_of",
    "of_pred": "predicted_of",
    "predicted_of_ratio": "predicted_of",

    "mdot_fuel": "mdot_fuel",
    "mdot_f": "mdot_fuel",

    "mdot_lox": "mdot_lox",

    "thrust_error": "thrust_error",

    "change_alpha_cmd": "change_alpha_cmd",
    "delta_alpha_cmd": "change_alpha_cmd",

    "clamped_change_alpha_cmd": "clamped_change_alpha_cmd",

    "alpha_cmd": "alpha_cmd",
    "alpha": "alpha",

    "thrust_from_alpha": "thrust_from_alpha",

    "fuel_valve_setpoint": "fuel_valve_setpoint",
    "fuel_target": "fuel_valve_setpoint",
    "calc_fuel_deg": "fuel_valve_setpoint",
    "fuel_deg": "fuel_valve_setpoint",

    "fuel_valve_driver": "fuel_valve_driver",
    "fuel_driver": "fuel_valve_driver",

    "fuel_valve_encoder_pos": "fuel_valve_encoder_pos",
    "fuel_encoder_pos": "fuel_valve_encoder_pos",

    "lox_valve_setpoint": "lox_valve_setpoint",
    "lox_target": "lox_valve_setpoint",
    "calc_lox_deg": "lox_valve_setpoint",
    "lox_deg": "lox_valve_setpoint",

    "lox_valve_driver": "lox_valve_driver",
    "lox_driver": "lox_valve_driver",

    "lox_valve_encoder_pos": "lox_valve_encoder_pos",
    "lox_encoder_pos": "lox_valve_encoder_pos",
}

LONG_FILE_SENSORS = [
    "predicted_thrust",
    "target_thrust",
    "predicted_of",
    "mdot_fuel",
    "mdot_lox",
    "thrust_error",
    "change_alpha_cmd",
    "clamped_change_alpha_cmd",
    "alpha",
    "thrust_from_alpha",
    "fuel_valve_setpoint",
    "fuel_valve_driver",
    "fuel_valve_encoder_pos",
    "lox_valve_setpoint",
    "lox_valve_driver",
    "lox_valve_encoder_pos",
]

PLOT_GROUPS = {
    "01_thrust_comparison": ["predicted_thrust", "target_thrust", "thrust_from_alpha"],
    "02_thrust_error": ["thrust_error"],
    "03_mixture_and_mass_flow": ["predicted_of", "mdot_fuel", "mdot_lox"],
    "04_alpha_commands": ["change_alpha_cmd", "clamped_change_alpha_cmd", "alpha_cmd", "alpha"],
    "05_fuel_valve": ["fuel_valve_setpoint", "fuel_valve_driver", "fuel_valve_encoder_pos"],
    "06_lox_valve": ["lox_valve_setpoint", "lox_valve_driver", "lox_valve_encoder_pos"],
}

PREFIXES_TO_STRIP = (
    "gnc_",
    "atlas_",
    "edge_",
    "hitl_",
    "raw_",
)


def normalize_name(name: str) -> str:
    text = str(name).strip().lower()
    text = text.replace(" ", "_").replace("-", "_")
    while "__" in text:
        text = text.replace("__", "_")
    for prefix in PREFIXES_TO_STRIP:
        if text.startswith(prefix):
            text = text[len(prefix):]
    return CANONICAL_ALIASES.get(text, text)



def convert_to_relative_seconds(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    numeric = numeric.dropna()
    if numeric.empty:
        raise ValueError("Time column could not be converted to numeric values.")

    start = numeric.iloc[0]
    shifted = pd.to_numeric(series, errors="coerce") - start

    abs_max = max(abs(float(numeric.iloc[-1])), abs(float(numeric.iloc[0])))
    if abs_max >= 1e17:
        scale = 1e9   # nanoseconds -> seconds
    elif abs_max >= 1e14:
        scale = 1e6   # microseconds -> seconds
    elif abs_max >= 1e11:
        scale = 1e3   # milliseconds -> seconds
    else:
        scale = 1.0   # already seconds (or close enough)

    return shifted / scale



def load_long_format_csv(path: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    df = pd.read_csv(path)
    required = {"time", "sensor", "value"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Long-format file {path} is missing required columns: {sorted(missing)}"
        )

    df = df.copy()
    df["sensor_canonical"] = df["sensor"].map(normalize_name)
    df = df[df["sensor_canonical"].isin(LONG_FILE_SENSORS)].copy()
    if df.empty:
        raise ValueError(
            "No requested sensors were found in the long-format CSV. "
            "Check the alias map near CANONICAL_ALIASES if your sensor names differ."
        )

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["time_s"] = convert_to_relative_seconds(df["time"])
    df = df.dropna(subset=["time_s", "value"]).sort_values(["time_s", "sensor_canonical"])

    pivot = (
        df.pivot_table(
            index="time_s",
            columns="sensor_canonical",
            values="value",
            aggfunc="last",
        )
        .sort_index()
        .reset_index()
    )

    labels = {col: col for col in pivot.columns if col != "time_s"}
    return pivot, labels



def load_wide_format_csv(path: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    df = pd.read_csv(path)
    cleaned_columns = {col: str(col).strip() for col in df.columns}
    df = df.rename(columns=cleaned_columns)

    if "time" not in df.columns:
        raise ValueError(f"Wide-format file {path} must have a 'time' column.")

    rename_map = {}
    labels = {}
    for original in df.columns:
        if original == "time":
            continue
        canonical = normalize_name(original)
        rename_map[original] = canonical
        labels[canonical] = original

    df = df.rename(columns=rename_map).copy()
    df["time_s"] = convert_to_relative_seconds(df["time"])

    value_columns = [col for col in df.columns if col not in {"time", "time_s"}]
    for col in value_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    keep = ["time_s"] + value_columns
    df = df[keep].dropna(subset=["time_s"]).sort_values("time_s")
    return df, labels



def plot_group(
    long_df: pd.DataFrame,
    wide_df: pd.DataFrame,
    long_labels: dict[str, str],
    wide_labels: dict[str, str],
    columns: list[str],
    title: str,
    out_path: Path,
) -> bool:
    plt.figure(figsize=(12, 6))
    plotted = False

    for col in columns:
        if col in long_df.columns:
            plt.plot(
                long_df["time_s"],
                long_df[col],
                label=f"rupin: {long_labels.get(col, col)}",
                linewidth=1.5,
            )
            plotted = True
        if col in wide_df.columns:
            plt.plot(
                wide_df["time_s"],
                wide_df[col],
                linestyle="--",
                label=f"hitl: {wide_labels.get(col, col)}",
                linewidth=1.5,
            )
            plotted = True

    if not plotted:
        plt.close()
        return False

    plt.xlabel("Time from start [s]")
    plt.ylabel("Value")
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()
    return True



def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare a long-format sensor CSV against a wide-format CSV and create grouped plots."
        )
    )
    parser.add_argument("long_csv", type=Path, help="Path to the long-format CSV (time,sensor,value,...)")
    parser.add_argument("wide_csv", type=Path, help="Path to the wide-format CSV (one row per timestamp)")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("comparison_plots"),
        help="Directory where plot PNG files will be written",
    )
    args = parser.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)

    long_df, long_labels = load_long_format_csv(args.long_csv)
    wide_df, wide_labels = load_wide_format_csv(args.wide_csv)

    created = []
    for stem, columns in PLOT_GROUPS.items():
        title = stem.replace("_", " ").split("_", 1)[-1].title()
        out_path = args.outdir / f"{stem}.png"
        if plot_group(long_df, wide_df, long_labels, wide_labels, columns, title, out_path):
            created.append(out_path)

    summary = pd.DataFrame(
        {
            "long_format_columns_found": [", ".join(sorted(c for c in long_df.columns if c != "time_s"))],
            "wide_format_columns_found": [", ".join(sorted(c for c in wide_df.columns if c != "time_s"))],
            "plots_created": [", ".join(p.name for p in created)],
        }
    )
    summary.to_csv(args.outdir / "plot_summary.csv", index=False)

    print("Created plots:")
    for path in created:
        print(f"  - {path}")
    print(f"\nSummary written to: {args.outdir / 'plot_summary.csv'}")


if __name__ == "__main__":
    main()
