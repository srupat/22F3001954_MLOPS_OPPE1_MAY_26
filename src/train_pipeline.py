import argparse
import json
import subprocess

import mlflow
import mlflow.sklearn
import pandas as pd
from feast import FeatureStore
from mlflow.models.signature import infer_signature
from mlflow.tracking import MlflowClient
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from config import (
    FEATURE_REPO_DIR,
    PROCESSED_DATA_DIR,
    REPORTS_DIR,
    MLFLOW_TRACKING_URI,
    MLFLOW_ARTIFACT_ROOT,
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


def run_cmd(cmd: str):
    print(f"Running: {cmd}")
    subprocess.run(cmd, shell=True, check=True)


def prepare_iteration(iteration: str, rows_per_stock: int):
    run_cmd(f"python src/prepare_data.py --iteration {iteration}")
    run_cmd(
        f"python src/create_pipeline_sample.py "
        f"--iteration {iteration} "
        f"--rows-per-stock {rows_per_stock}"
    )
    run_cmd("cd feature_repo && feast apply")


def get_feast_dataset(split: str) -> pd.DataFrame:
    store = FeatureStore(repo_path=str(FEATURE_REPO_DIR))

    base_df = pd.read_parquet(PROCESSED_DATA_DIR / "current" / f"{split}.parquet")
    entity_df = base_df[["stock_name", "timestamp", "target", "row_id"]].copy()

    print(f"Retrieving Feast features for {split}: {len(entity_df)} rows")

    df = store.get_historical_features(
        entity_df=entity_df,
        features=FEATURE_REFS,
    ).to_df()

    df = df.dropna(subset=["rolling_avg_10", "volume_sum_10", "stock_name", "target"])

    print(f"Retrieved {split} dataset from Feast: {len(df)} rows")

    return df


def build_model(params):
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", "passthrough", NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ]
    )

    if params["model_type"] == "random_forest":
        estimator = RandomForestClassifier(
            n_estimators=params["n_estimators"],
            max_depth=params["max_depth"],
            min_samples_split=params["min_samples_split"],
            random_state=42,
            class_weight="balanced",
        )
    elif params["model_type"] == "gradient_boosting":
        estimator = GradientBoostingClassifier(
            n_estimators=params["n_estimators"],
            learning_rate=params["learning_rate"],
            max_depth=params["max_depth"],
            random_state=42,
        )
    else:
        raise ValueError(f"Unsupported model_type: {params['model_type']}")

    return Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("model", estimator),
        ]
    )


def evaluate(model, X, y):
    pred = model.predict(X)

    metrics = {
        "accuracy": accuracy_score(y, pred),
        "precision": precision_score(y, pred, zero_division=0),
        "recall": recall_score(y, pred, zero_division=0),
        "f1": f1_score(y, pred, zero_division=0),
    }

    try:
        proba = model.predict_proba(X)[:, 1]
        metrics["roc_auc"] = roc_auc_score(y, proba)
    except Exception:
        metrics["roc_auc"] = 0.0

    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", choices=["v0", "v1"], required=True)
    parser.add_argument("--rows-per-stock", type=int, default=3000)
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    prepare_iteration(args.iteration, args.rows_per_stock)

    train_df = get_feast_dataset("train")
    test_df = get_feast_dataset("test")

    X_train = train_df[FEATURE_COLUMNS]
    y_train = train_df[TARGET_COLUMN].astype(int)

    X_test = test_df[FEATURE_COLUMNS]
    y_test = test_df[TARGET_COLUMN].astype(int)

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    client = MlflowClient()
    experiment = client.get_experiment_by_name(EXPERIMENT_NAME)

    if experiment is None:
        client.create_experiment(
            name=EXPERIMENT_NAME,
            artifact_location=MLFLOW_ARTIFACT_ROOT,
        )
    else:
        print(f"Using existing MLflow experiment: {experiment.name}")
        print(f"Artifact location: {experiment.artifact_location}")

    mlflow.set_experiment(EXPERIMENT_NAME)

    param_grid = [
        {
            "model_type": "random_forest",
            "n_estimators": 50,
            "max_depth": 4,
            "min_samples_split": 2,
            "learning_rate": 0.1,
        },
        {
            "model_type": "random_forest",
            "n_estimators": 100,
            "max_depth": 6,
            "min_samples_split": 5,
            "learning_rate": 0.1,
        },
        {
            "model_type": "gradient_boosting",
            "n_estimators": 50,
            "max_depth": 2,
            "min_samples_split": 2,
            "learning_rate": 0.05,
        },
    ]

    best_score = -1.0
    best_model_uri = None
    best_run_id = None
    best_params = None
    best_metrics = None
    all_results = []

    for params in param_grid:
        run_name = f"{args.iteration}_{params['model_type']}_{params['n_estimators']}_{params['max_depth']}"

        with mlflow.start_run(run_name=run_name) as run:
            model = build_model(params)
            model.fit(X_train, y_train)

            metrics = evaluate(model, X_test, y_test)

            mlflow.log_param("iteration", args.iteration)
            mlflow.log_param("rows_per_stock", args.rows_per_stock)
            mlflow.log_params(params)
            mlflow.log_metrics(metrics)

            mlflow.set_tag("dataset", "StockAnalytica")
            mlflow.set_tag("task", "stock_movement_prediction")
            mlflow.set_tag("training_mode", "pipeline_sample")

            signature = infer_signature(X_test.head(20), model.predict(X_test.head(20)))

            mlflow.sklearn.log_model(
                sk_model=model,
                artifact_path="model",
                signature=signature,
                input_example=X_test.head(5),
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

            print(json.dumps(result, indent=2))
            all_results.append(result)

            if metrics["f1"] > best_score:
                best_score = metrics["f1"]
                best_model_uri = model_uri
                best_run_id = run_id
                best_params = params
                best_metrics = metrics

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

    summary = {
        "iteration": args.iteration,
        "rows_per_stock": args.rows_per_stock,
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
