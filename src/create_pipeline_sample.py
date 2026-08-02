import argparse
import shutil
from pathlib import Path

import pandas as pd

from config import PROCESSED_DATA_DIR


def chronological_split(df: pd.DataFrame, test_ratio: float = 0.2):
    train_parts = []
    test_parts = []

    for stock_name, group in df.groupby("stock_name"):
        group = group.sort_values("timestamp").reset_index(drop=True)
        split_idx = int(len(group) * (1 - test_ratio))

        train_parts.append(group.iloc[:split_idx].copy())
        test_parts.append(group.iloc[split_idx:].copy())

    train_df = pd.concat(train_parts, ignore_index=True)
    test_df = pd.concat(test_parts, ignore_index=True)

    return train_df, test_df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", choices=["v0", "v1"], required=True)
    parser.add_argument("--rows-per-stock", type=int, default=3000)
    args = parser.parse_args()

    source_path = PROCESSED_DATA_DIR / args.iteration / "features.parquet"

    if not source_path.exists():
        raise FileNotFoundError(
            f"{source_path} does not exist. Run prepare_data.py first."
        )

    df = pd.read_parquet(source_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values(["stock_name", "timestamp"]).reset_index(drop=True)

    sampled_parts = []

    for stock_name, group in df.groupby("stock_name"):
        group = group.sort_values("timestamp").tail(args.rows_per_stock).copy()
        sampled_parts.append(group)

    sample_df = pd.concat(sampled_parts, ignore_index=True)
    sample_df = sample_df.sort_values(["stock_name", "timestamp"]).reset_index(drop=True)

    train_df, test_df = chronological_split(sample_df)

    sample_dir = PROCESSED_DATA_DIR / f"{args.iteration}_sample"
    sample_dir.mkdir(parents=True, exist_ok=True)

    sample_df.to_parquet(sample_dir / "features.parquet", index=False)
    train_df.to_parquet(sample_dir / "train.parquet", index=False)
    test_df.to_parquet(sample_dir / "test.parquet", index=False)

    current_dir = PROCESSED_DATA_DIR / "current"

    if current_dir.exists():
        shutil.rmtree(current_dir)

    current_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy(sample_dir / "features.parquet", current_dir / "features.parquet")
    shutil.copy(sample_dir / "train.parquet", current_dir / "train.parquet")
    shutil.copy(sample_dir / "test.parquet", current_dir / "test.parquet")

    print(f"Created pipeline sample for iteration: {args.iteration}")
    print(f"Rows per stock: {args.rows_per_stock}")
    print(f"Sample rows: {len(sample_df)}")
    print(f"Train rows: {len(train_df)}")
    print(f"Test rows: {len(test_df)}")
    print(f"Stocks: {sorted(sample_df['stock_name'].unique())}")
    print(f"Saved sample to: {sample_dir}")
    print(f"Updated current data at: {current_dir}")


if __name__ == "__main__":
    main()
