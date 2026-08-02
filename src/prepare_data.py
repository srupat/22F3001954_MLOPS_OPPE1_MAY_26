import argparse
import shutil
from pathlib import Path

import pandas as pd

from config import RAW_DATA_DIR, PROCESSED_DATA_DIR


def infer_stock_name(file_path: Path) -> str:
    # Expected names usually begin with stock symbol
    # Example: AARTIIND__EQ__NSE__NSE__MINUTE.csv
    return file_path.stem.split("__")[0].split(".")[0]


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    original_cols = df.columns.tolist()
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    rename_map = {
        "date": "timestamp",
        "datetime": "timestamp",
        "time": "timestamp",
        "symbol": "stock_name",
        "ticker": "stock_name",
        "traded_volume": "volume",
        "volume_traded": "volume",
        "vol": "volume",
        "highest": "high",
        "high_price": "high",
        "closing_price": "close",
        "close_price": "close",
        "opening_price": "open",
        "open_price": "open",
    }

    df = df.rename(columns=rename_map)

    required = {"timestamp", "close", "volume"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            f"Missing required columns: {missing}. "
            f"Original columns were: {original_cols}. "
            f"Standardized columns are: {df.columns.tolist()}"
        )

    return df


def process_single_file(file_path: Path) -> pd.DataFrame:
    stock_name = infer_stock_name(file_path)

    df = pd.read_csv(file_path)
    df = standardize_columns(df)

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])

    if "stock_name" not in df.columns:
        df["stock_name"] = stock_name
    else:
        df["stock_name"] = df["stock_name"].fillna(stock_name).astype(str)

    numeric_cols = ["open", "high", "close", "volume"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["close", "volume"])

    # Critical requirement: do not assume source file is chronological
    df = df.sort_values(["stock_name", "timestamp"]).reset_index(drop=True)

    # Fill missing values using last available values per stock
    df = df.groupby("stock_name", group_keys=False).apply(lambda x: x.ffill())

    # Use last 10 available rows, not necessarily perfect calendar minutes
    df["rolling_avg_10"] = (
        df.groupby("stock_name")["close"]
        .transform(lambda s: s.rolling(window=10, min_periods=1).mean())
    )

    df["volume_sum_10"] = (
        df.groupby("stock_name")["volume"]
        .transform(lambda s: s.rolling(window=10, min_periods=1).sum())
    )

    # 5 available rows later per stock
    df["close_5min_future"] = df.groupby("stock_name")["close"].shift(-5)
    df = df.dropna(subset=["close_5min_future"]).copy()

    df["target"] = (df["close_5min_future"] > df["close"]).astype(int)

    df["row_id"] = (
        df["stock_name"].astype(str)
        + "_"
        + df["timestamp"].dt.strftime("%Y%m%d%H%M%S")
    )

    keep_cols = [
        "row_id",
        "timestamp",
        "stock_name",
        "open",
        "high",
        "close",
        "volume",
        "rolling_avg_10",
        "volume_sum_10",
        "close_5min_future",
        "target",
    ]

    keep_cols = [c for c in keep_cols if c in df.columns]
    return df[keep_cols]


def get_csv_files(folder: Path):
    csv_files = sorted(folder.rglob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found under {folder}")
    return csv_files


def load_iteration_data(iteration: str) -> pd.DataFrame:
    if iteration == "v0":
        folders = [RAW_DATA_DIR / "v0"]
    elif iteration == "v1":
        folders = [RAW_DATA_DIR / "v0", RAW_DATA_DIR / "v1"]
    else:
        raise ValueError("iteration must be v0 or v1")

    frames = []

    for folder in folders:
        for file_path in get_csv_files(folder):
            print(f"Processing {file_path}")
            frames.append(process_single_file(file_path))

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["stock_name", "timestamp"]).reset_index(drop=True)
    return df


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
    args = parser.parse_args()

    out_dir = PROCESSED_DATA_DIR / args.iteration
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_iteration_data(args.iteration)
    train_df, test_df = chronological_split(df)

    df.to_parquet(out_dir / "features.parquet", index=False)
    train_df.to_parquet(out_dir / "train.parquet", index=False)
    test_df.to_parquet(out_dir / "test.parquet", index=False)

    current_dir = PROCESSED_DATA_DIR / "current"
    if current_dir.exists():
        shutil.rmtree(current_dir)
    current_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy(out_dir / "features.parquet", current_dir / "features.parquet")
    shutil.copy(out_dir / "train.parquet", current_dir / "train.parquet")
    shutil.copy(out_dir / "test.parquet", current_dir / "test.parquet")

    print(f"Iteration: {args.iteration}")
    print(f"Full rows: {len(df)}")
    print(f"Train rows: {len(train_df)}")
    print(f"Test rows: {len(test_df)}")
    print(f"Stocks: {sorted(df['stock_name'].unique())}")
    print(f"Saved to {out_dir}")
    print(f"Updated current folder: {current_dir}")


if __name__ == "__main__":
    main()
