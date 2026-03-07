import pandas as pd
import argparse

def combine_csvs(file1_path, file2_path, output_path):
    # Read both CSV files
    df1 = pd.read_csv(file1_path)
    df2 = pd.read_csv(file2_path)

    # Keep only the needed columns from file 1
    wanted_file1_cols = ["time", "Thrust_Pred_lbf", "OF_Pred", "mdot_f", "mdot_lox"]

    missing_cols = [col for col in wanted_file1_cols if col not in df1.columns]
    if missing_cols:
        raise ValueError(f"File 1 is missing required columns: {missing_cols}")

    df1_selected = df1[wanted_file1_cols].copy()

    # Rename file 2 columns based on how many it actually has
    # You listed 5 actual headers (Var1..Var5) but 6 meanings.
    # So this handles both cases safely.
    if len(df2.columns) == 5:
        df2.columns = [
            "alpha_cmd",
            "target_thrust",
            "thrust_error",
            "calc_lox_deg",
            "calc_fuel_deg",
        ]
    elif len(df2.columns) == 6:
        df2.columns = [
            "alpha_cmd",
            "target_thrust",
            "thrust_error",
            "calc_lox_deg",
            "calc_fuel_deg",
            "alpha",
        ]
    else:
        print(
            f"Warning: File 2 has {len(df2.columns)} columns, so its headers were not renamed."
        )

    # Reset index so they combine row-by-row
    df1_selected = df1_selected.reset_index(drop=True)
    df2 = df2.reset_index(drop=True)

    # Combine side by side
    combined_df = pd.concat([df1_selected, df2], axis=1)

    # Save output
    combined_df.to_csv(output_path, index=False)
    print(f"Combined CSV written to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Combine selected columns from file1 with all columns from file2.")
    parser.add_argument("file1", help="Path to file 1 CSV")
    parser.add_argument("file2", help="Path to file 2 CSV")
    parser.add_argument("output", help="Path for output CSV")

    args = parser.parse_args()

    combine_csvs(args.file1, args.file2, args.output)