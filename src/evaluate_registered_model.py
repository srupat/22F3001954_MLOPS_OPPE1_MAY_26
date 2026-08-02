import json

import matplotlib.pyplot as plt
import mlflow
import mlflow.pyfunc
import pandas as pd
from feast import FeatureStore
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    ConfusionMatrixDisplay,
)

from config import (
    FEATURE_REPO_DIR,
    PROCESSED_DATA_DIR,
    REPORTS_DIR,
    MLFLOW_TRACKING_URI,
    REGISTERED_MODEL_NAME,
    MODEL_ALIAS,
    FEATURE_COLUMNS,
    TARGET_COLUMN,
)


FEATURE_REFS = [
    "stock_rolling_features:rolling_avg_10",
    "stock_rolling_features:volume_sum_10",
]


def get_test_dataset():
    store = FeatureStore(repo_path=str(FEATURE_REPO_DIR))

    base_df = pd.read_parquet(PROCESSED_DATA_DIR / "current" / "test.parquet")
    entity_df = base_df[["stock_name", "timestamp", "target", "row_id"]].copy()

    print(f"Retrieving Feast test features: {len(entity_df)} rows")

    test_df = store.get_historical_features(
        entity_df=entity_df,
        features=FEATURE_REFS,
    ).to_df()

    test_df = test_df.dropna(
        subset=["rolling_avg_10", "volume_sum_10", "stock_name", "target"]
    )

    return test_df


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    model_uri = f"models:/{REGISTERED_MODEL_NAME}@{MODEL_ALIAS}"
    print(f"Loading model from MLflow registry: {model_uri}")

    model = mlflow.pyfunc.load_model(model_uri)

    test_df = get_test_dataset()

    X_test = test_df[FEATURE_COLUMNS]
    y_true = test_df[TARGET_COLUMN].astype(int)

    y_pred = model.predict(X_test)

    metrics = {
        "model_uri": model_uri,
        "num_test_rows": int(len(test_df)),
        "accuracy": accuracy_score(y_true, y_pred),
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
    }

    with open(REPORTS_DIR / "ci_metrics.json", "w") as f:
        json.dump(metrics, f, indent=4)

    cm = confusion_matrix(y_true, y_pred)
    disp = ConfusionMatrixDisplay(confusion_matrix=cm)
    disp.plot()
    plt.title("Stock Movement Prediction - Confusion Matrix")
    plt.savefig(REPORTS_DIR / "confusion_matrix.png", bbox_inches="tight")
    plt.close()

    pred_df = test_df[["row_id", "timestamp", "stock_name", "target"]].copy()
    pred_df["prediction"] = y_pred
    pred_df.to_csv(REPORTS_DIR / "predictions.csv", index=False)

    print(json.dumps(metrics, indent=4))


if __name__ == "__main__":
    main()
