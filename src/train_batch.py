import argparse
import gc
import json
import shutil
import subprocess
from pathlib import Path

import mlflow
import mlflow.pyfunc
import numpy as np
import pandas as pd
from feast import FeatureStore
from mlflow.tracking import MlflowClient
from sklearn.base import BaseEstimator
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

from config import (
    FEATURE_REPO_DIR,
    PROCESSED_DATA_DIR,
    REPORTS_DIR,
    MLFLOW_TRACKING_URI,
    EXPERIMENT_NAME,
    REGISTERED_MODEL_NAME,
    MODEL_ALIAS,
    NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    TARGET_COLUMN,
)


FEATURE_REFS = [
    "stock_rolling_features:rolling_avg_10",
    "stock_rolling_features:volume_sum_10",
]


class StockMovementPyFuncModel(mlflow.pyfunc.PythonModel):
    def __init__(self, scaler, model, stock_categories):
        self.scaler = scaler
        self.model = model
        self.stock_categories = list(stock_categories)
        self.stock_to_idx = {stock: idx for idx, stock in enumerate(self.stock_categories)}

    def _transform(self, df: pd.DataFrame):
        df = df.copy()

        numeric = df[NUMERIC_FEATURES].astype(float).values
        numeric_scaled = self.scaler.transform(numeric)

        one_hot = np.zeros((len(df), len(self.stock_categories)), dtype=float)

        for row_idx, stock_name in enumerate(df["stock_name"].astype(str).values):
            col_idx = self.stock_to_idx.get(stock_name)
            if col_idx is not None:
                one_hot[row_idx, col_idx] = 1.0

        return np.hstack([numeric_scaled, one_hot])

    def predict(self, context, model_input):
        X = self._transform(model_input)
        return self.model.predict(X)


def run_cmd(cmd: str):
    print(f"Running: {cmd}")
    subprocess.run(cmd, shell=True, check=True)


def prepare_iteration(iteration: str):
    run_cmd(f"python src/prepare_data.py --iteration {iteration}")
    run_cmd("cd feature_repo && feast apply")

    print(
        "Skipping full Feast materialization. "
        "Training uses batch-wise get_historical_features from the offline store."
    )


def clean_batch_dir(split: str):
    batch_dir = PROCESSED_DATA_DIR / "current" / f"feast_{split}_batches"

    if batch_dir.exists():
        shutil.rmtree(batch_dir)

    batch_dir.mkdir(parents=True, exist_ok=True)
    return batch_dir


def build_feast_batches(split: str, batch_size: int):
    """
    Retrieve Feast historical features in batches and save each batch to parquet.
    This avoids loading the full historical feature dataset into memory.
    """
    store = FeatureStore(repo_path=str(FEATURE_REPO_DIR))

    base_path = PROCESSED_DATA_DIR / "current" / f"{split}.parquet"
    base_df = pd.read_parquet(base_path)
    base_df = base_df.sort_values(["stock_name", "timestamp"]).reset_index(drop=True)

    batch_dir = clean_batch_dir(split)

    total_rows = len(base_df)
    batch_count = 0

    print(f"Building Feast {split} batches")
    print(f"Total rows: {total_rows}")
    print(f"Batch size: {batch_size}")

    for start in range(0, total_rows, batch_size):
        end = min(start + batch_size, total_rows)

        chunk = base_df.iloc[start:end][["stock_name", "timestamp", "target", "row_id"]].copy()

        print(f"Retrieving Feast batch {batch_count}: rows {start} to {end}")

        feature_df = store.get_historical_features(
            entity_df=chunk,
            features=FEATURE_REFS,
        ).to_df()

        feature_df = feature_df.dropna(
            subset=["rolling_avg_10", "volume_sum_10", "stock_name", "target"]
        )

        output_path = batch_dir / f"part_{batch_count:05d}.parquet"
        feature_df.to_parquet(output_path, index=False)

        print(f"Saved {output_path}, rows={len(feature_df)}")

        batch_count += 1

        del chunk
        del feature_df
        gc.collect()

    print(f"Completed Feast batch creation for {split}. Parts: {batch_count}")

    return batch_dir


def list_batch_files(split: str):
    batch_dir = PROCESSED_DATA_DIR / "current" / f"feast_{split}_batches"
    files = sorted(batch_dir.glob("*.parquet"))

    if not files:
        raise FileNotFoundError(f"No batch files found in {batch_dir}")

    return files


def get_stock_categories():
    df = pd.read_parquet(PROCESSED_DATA_DIR / "current" / "features.parquet")
    return sorted(df["stock_name"].astype(str).unique())


def transform_batch(df: pd.DataFrame, scaler: StandardScaler, stock_categories):
    numeric = df[NUMERIC_FEATURES].astype(float).values
    numeric_scaled = scaler.transform(numeric)

    stock_to_idx = {stock: idx for idx, stock in enumerate(stock_categories)}

    one_hot = np.zeros((len(df), len(stock_categories)), dtype=float)

    for row_idx, stock_name in enumerate(df["stock_name"].astype(str).values):
        col_idx = stock_to_idx.get(stock_name)
        if col_idx is not None:
            one_hot[row_idx, col_idx] = 1.0

    return np.hstack([numeric_scaled, one_hot])


def fit_scaler(train_files):
    scaler = StandardScaler()

    for file_path in train_files:
        df = pd.read_parquet(file_path)
        numeric = df[NUMERIC_FEATURES].astype(float).values
        scaler.partial_fit(numeric)

        del df
        gc.collect()

    return scaler


def train_incremental_model(train_files, params, scaler, stock_categories):
    model = SGDClassifier(
        loss=params["loss"],
        alpha=params["alpha"],
        penalty=params["penalty"],
        max_iter=1,
        tol=None,
        random_state=42,
        class_weight="balanced",
    )

    classes = np.array([0, 1])

    for epoch in range(params["epochs"]):
        print(f"Epoch {epoch + 1}/{params['epochs']}")

        for file_path in train_files:
            df = pd.read_parquet(file_path)

            X = transform_batch(df, scaler, stock_categories)
            y = df[TARGET_COLUMN].astype(int).values

            model.partial_fit(X, y, classes=classes)

            del df
            del X
            del y
            gc.collect()

    return model


def evaluate_batchwise(model, test_files, scaler, stock_categories):
    y_true_all = []
    y_pred_all = []
    y_score_all = []

    for file_path in test_files:
        df = pd.read_parquet(file_path)

        X = transform_batch(df, scaler, stock_categories)
        y_true = df[TARGET_COLUMN].astype(int).values
        y_pred = model.predict(X)

        y_true_all.extend(y_true.tolist())
        y_pred_all.extend(y_pred.tolist())

        if hasattr(model, "decision_function"):
            scores = model.decision_function(X)
            y_score_all.extend(scores.tolist())

        del df
        del X
        del y_true
        del y_pred
        gc.collect()

    y_true_all = np.array(y_true_all)
    y_pred_all = np.array(y_pred_all)

    metrics = {
        "accuracy": accuracy_score(y_true_all, y_pred_all),
        "precision": precision_score(y_true_all, y_pred_all, zero_division=0),
        "recall": recall_score(y_true_all, y_pred_all, zero_division=0),
        "f1": f1_score(y_true_all, y_pred_all, zero_division=0),
    }

    if len(set(y_true_all.tolist())) == 2 and len(y_score_all) == len(y_true_all):
        metrics["roc_auc"] = roc_auc_score(y_true_all, np.array(y_score_all))
    else:
        metrics["roc_auc"] = 0.0

    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", choices=["v0", "v1"], required=True)
    parser.add_argument("--batch-size", type=int, default=20000)
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    prepare_iteration(args.iteration)

    build_feast_batches("train", args.batch_size)
    build_feast_batches("test", args.batch_size)

    train_files = list_batch_files("train")
    test_files = list_batch_files("test")

    stock_categories = get_stock_categories()

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    param_grid = [
        {
            "model_type": "sgd_classifier",
            "loss": "log_loss",
            "alpha": 0.0001,
            "penalty": "l2",
            "epochs": 2,
        },
        {
            "model_type": "sgd_classifier",
            "loss": "log_loss",
            "alpha": 0.001,
            "penalty": "l2",
            "epochs": 2,
        },
        {
            "model_type": "sgd_classifier",
            "loss": "modified_huber",
            "alpha": 0.0001,
            "penalty": "l2",
            "epochs": 2,
        },
    ]

    best_score = -1
    best_run_id = None
    best_model_uri = None
    best_metrics = None
    best_params = None
    all_results = []

    for params in param_grid:
        run_name = f"{args.iteration}_{params['model_type']}_{params['loss']}_{params['alpha']}"

        with mlflow.start_run(run_name=run_name) as run:
            print(f"Training run: {run_name}")

            scaler = fit_scaler(train_files)
            model = train_incremental_model(train_files, params, scaler, stock_categories)

            metrics = evaluate_batchwise(model, test_files, scaler, stock_categories)

            mlflow.log_param("iteration", args.iteration)
            mlflow.log_param("batch_size", args.batch_size)
            mlflow.log_param("num_train_batches", len(train_files))
            mlflow.log_param("num_test_batches", len(test_files))
            mlflow.log_param("stock_categories", ",".join(stock_categories))
            mlflow.log_params(params)
            mlflow.log_metrics(metrics)

            mlflow.set_tag("dataset", "StockAnalytica")
            mlflow.set_tag("task", "stock_movement_prediction")
            mlflow.set_tag("training_mode", "batchwise_partial_fit")

            pyfunc_model = StockMovementPyFuncModel(
                scaler=scaler,
                model=model,
                stock_categories=stock_categories,
            )

            input_example = pd.DataFrame(
                [
                    {
                        "rolling_avg_10": 100.0,
                        "volume_sum_10": 10000.0,
                        "stock_name": stock_categories[0],
                    }
                ]
            )

            mlflow.pyfunc.log_model(
                artifact_path="model",
                python_model=pyfunc_model,
                input_example=input_example,
                pip_requirements=[
                    "mlflow",
                    "pandas",
                    "numpy",
                    "scikit-learn",
                ],
            )

            run_id = run.info.run_id
            model_uri = f"runs:/{run_id}/model"

            result = {
                "iteration": args.iteration,
                "run_id": run_id,
                "model_uri": model_uri,
                "params": params,
                "metrics": metrics,
            }

            all_results.append(result)

            print(json.dumps(result, indent=2))

            if metrics["f1"] > best_score:
                best_score = metrics["f1"]
                best_run_id = run_id
                best_model_uri = model_uri
                best_metrics = metrics
                best_params = params

    model_version = mlflow.register_model(
        model_uri=best_model_uri,
        name=REGISTERED_MODEL_NAME,
    )

    client = MlflowClient()
    client.set_registered_model_alias(
        name=REGISTERED_MODEL_NAME,
        alias=MODEL_ALIAS,
        version=model_version.version,
    )

    client.set_model_version_tag(
        name=REGISTERED_MODEL_NAME,
        version=model_version.version,
        key="iteration",
        value=args.iteration,
    )

    client.set_model_version_tag(
        name=REGISTERED_MODEL_NAME,
        version=model_version.version,
        key="training_mode",
        value="batchwise_partial_fit",
    )

    summary = {
        "iteration": args.iteration,
        "registered_model_name": REGISTERED_MODEL_NAME,
        "champion_alias": MODEL_ALIAS,
        "champion_version": model_version.version,
        "best_run_id": best_run_id,
        "best_model_uri": best_model_uri,
        "best_params": best_params,
        "best_metrics": best_metrics,
        "all_results": all_results,
    }

    summary_path = REPORTS_DIR / f"training_summary_{args.iteration}.json"

    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=4)

    print(f"Saved summary to {summary_path}")

    run_cmd("gcloud storage cp mlflow.db gs://oppe1-22f3001954-mlops/mlflow-db/mlflow.db")


if __name__ == "__main__":
    main()
