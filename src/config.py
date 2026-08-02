from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

RAW_DATA_DIR = ROOT_DIR / "data" / "raw"
PROCESSED_DATA_DIR = ROOT_DIR / "data" / "processed"
REPORTS_DIR = ROOT_DIR / "reports"
FEATURE_REPO_DIR = ROOT_DIR / "feature_repo"

MLFLOW_DB_PATH = ROOT_DIR / "mlflow.db"
MLFLOW_TRACKING_URI = f"sqlite:///{MLFLOW_DB_PATH}"
MLFLOW_ARTIFACT_ROOT = "gs://oppe1-22f3001954-mlops/mlflow-artifacts"

EXPERIMENT_NAME = "stock-movement-experiments"
REGISTERED_MODEL_NAME = "stock-movement-predictor"
MODEL_ALIAS = "champion"

TIMESTAMP_COLUMN = "timestamp"
ENTITY_COLUMN = "stock_name"
TARGET_COLUMN = "target"

NUMERIC_FEATURES = ["rolling_avg_10", "volume_sum_10"]
CATEGORICAL_FEATURES = ["stock_name"]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
