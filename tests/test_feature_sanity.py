import numpy as np
import pandas as pd

from src.config import PROCESSED_DATA_DIR


def test_rolling_avg_10_matches_close_values_after_warmup():
    df = pd.read_parquet(PROCESSED_DATA_DIR / "current" / "features.parquet")
    df = df.sort_values(["stock_name", "timestamp"]).reset_index(drop=True)

    recomputed = (
        df.groupby("stock_name")["close"]
        .transform(lambda s: s.rolling(window=10, min_periods=1).mean())
    )

    df["recomputed_rolling_avg_10"] = recomputed
    df["position_in_stock"] = df.groupby("stock_name").cumcount()

    # The current dataset is a chronological sample from the full processed data.
    # For the first 9 rows of each stock, the stored rolling features may depend
    # on earlier rows that are outside the sample. After warmup, the recomputed
    # values within the sample should match.
    check_df = df[df["position_in_stock"] >= 9].copy()

    assert np.allclose(
        check_df["rolling_avg_10"],
        check_df["recomputed_rolling_avg_10"],
        rtol=1e-5,
        atol=1e-5,
    )


def test_volume_sum_10_matches_volume_values_after_warmup():
    df = pd.read_parquet(PROCESSED_DATA_DIR / "current" / "features.parquet")
    df = df.sort_values(["stock_name", "timestamp"]).reset_index(drop=True)

    recomputed = (
        df.groupby("stock_name")["volume"]
        .transform(lambda s: s.rolling(window=10, min_periods=1).sum())
    )

    df["recomputed_volume_sum_10"] = recomputed
    df["position_in_stock"] = df.groupby("stock_name").cumcount()

    # Same warmup logic as rolling average:
    # first 9 sampled rows may depend on context outside the sample.
    check_df = df[df["position_in_stock"] >= 9].copy()

    assert np.allclose(
        check_df["volume_sum_10"],
        check_df["recomputed_volume_sum_10"],
        rtol=1e-5,
        atol=1e-5,
    )


def test_target_is_binary():
    df = pd.read_parquet(PROCESSED_DATA_DIR / "current" / "features.parquet")
    assert set(df["target"].unique()).issubset({0, 1})


def test_no_nulls_in_model_features():
    df = pd.read_parquet(PROCESSED_DATA_DIR / "current" / "features.parquet")

    required_cols = [
        "rolling_avg_10",
        "volume_sum_10",
        "stock_name",
        "target",
    ]

    assert df[required_cols].isnull().sum().sum() == 0


def test_required_feature_columns_exist():
    df = pd.read_parquet(PROCESSED_DATA_DIR / "current" / "features.parquet")

    required_cols = {
        "timestamp",
        "stock_name",
        "close",
        "volume",
        "rolling_avg_10",
        "volume_sum_10",
        "target",
    }

    assert required_cols.issubset(set(df.columns))
