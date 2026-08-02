from datetime import timedelta
from pathlib import Path

from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float32


ROOT_DIR = Path(__file__).resolve().parents[1]
FEATURE_PATH = ROOT_DIR / "data" / "processed" / "current" / "features.parquet"


stock = Entity(
    name="stock",
    join_keys=["stock_name"],
    description="Stock identifier",
)


stock_feature_source = FileSource(
    name="stock_feature_source",
    path=str(FEATURE_PATH),
    timestamp_field="timestamp",
)


stock_rolling_features = FeatureView(
    name="stock_rolling_features",
    entities=[stock],
    ttl=timedelta(days=3650),
    schema=[
        Field(name="rolling_avg_10", dtype=Float32),
        Field(name="volume_sum_10", dtype=Float32),
    ],
    source=stock_feature_source,
    online=True,
    tags={
        "dataset": "StockAnalytica",
        "task": "stock_movement_prediction",
    },
)
