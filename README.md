# Stock Movement Predictor - OPPE1 MLOps

## Problem Statement

This project builds an end-to-end MLOps pipeline for predicting short-term stock movement.

The objective is to predict whether a stock will close higher 5 minutes later using minute-level stock market data.

The target variable is defined as:

```text
target = 1 if close price 5 minutes later > current close price
target = 0 otherwise
```

## Data

The data is sourced from the IITMBSMLOps OPPE1 repository.

The dataset contains NSE minute-level stock data with columns such as opening price, highest price, closing price, and traded volume.

## Data Iterations

### Iteration 1: v0 data only

Stocks used:

```text
AARTIIND
ABCAPITAL
```

### Iteration 2: v0 + v1 data

Stocks used:

```text
AARTIIND
ABCAPITAL
ABFRL
ADANIENT
ADANIGAS
```

## Features

The following features are computed:

| Feature | Description |
|---|---|
| `rolling_avg_10` | Moving average of close price over the last 10 available records |
| `volume_sum_10` | Sum of traded volume over the last 10 available records |
| `stock_name` | Stock identifier |

The data is sorted chronologically before feature computation. The pipeline does not assume that the source CSV files are already sorted.

## MLOps Components

This project uses the following MLOps tools:

```text
DVC            - Data versioning
GCS            - Remote storage for DVC and MLflow artifacts
Feast          - Feature store
MLflow         - Experiment tracking and model registry
GitHub         - Source control
GitHub Actions - CI workflow
CML            - Pull request report generation
```

## GCP Execution Environment

All work was performed on Google Cloud Platform using a Vertex AI Workbench instance.

Workbench configuration:

```text
Machine type: e2-standard-4
Memory: 16 GB RAM
```

This satisfies the course requirement of using a 16 GB cloud instance.

## Repository Structure

```text
.
|-- .github/workflows/ci.yml
|-- data/
|   |-- raw/
|   |   |-- v0.dvc
|   |   `-- v1.dvc
|   `-- processed/
|       |-- v0.dvc
|       |-- v1.dvc
|       |-- v0_sample.dvc
|       `-- v1_sample.dvc
|-- feature_repo/
|   |-- feature_store.yaml
|   `-- features.py
|-- reports/
|-- src/
|   |-- config.py
|   |-- prepare_data.py
|   |-- create_pipeline_sample.py
|   |-- train_pipeline.py
|   `-- evaluate_registered_model.py
|-- tests/
|   |-- test_feature_sanity.py
|   `-- test_model_registry.py
|-- requirements.txt
|-- pytest.ini
`-- README.md
```

## DVC

DVC is used to version both raw and processed datasets.

Tracked data:

```text
data/raw/v0
data/raw/v1
data/processed/v0
data/processed/v1
data/processed/v0_sample
data/processed/v1_sample
```

DVC remote:

```text
gs://oppe1-22f3001954-mlops/dvcstore
```

Useful DVC commands:

```bash
dvc remote list
dvc status
dvc pull
dvc push
```

## Feature Engineering

Feature engineering is implemented in:

```text
src/prepare_data.py
```

Run full feature preparation:

```bash
python src/prepare_data.py --iteration v0
python src/prepare_data.py --iteration v1
```

This creates:

```text
data/processed/v0/features.parquet
data/processed/v0/train.parquet
data/processed/v0/test.parquet

data/processed/v1/features.parquet
data/processed/v1/train.parquet
data/processed/v1/test.parquet
```

## Memory-Safe Pipeline Sample

The raw stock dataset is large minute-level data. Full raw data and full processed data are tracked with DVC.

For reliable Feast retrieval, MLflow training, and CI execution on the mandated 16 GB Workbench instance, the final end-to-end pipeline uses a chronological sample from each stock after full feature generation.

The sample is created using:

```bash
python src/create_pipeline_sample.py --iteration v0 --rows-per-stock 1000
python src/create_pipeline_sample.py --iteration v1 --rows-per-stock 1000
```

This creates:

```text
data/processed/v0_sample
data/processed/v1_sample
data/processed/current
```

`data/processed/current` is used by Feast, training, evaluation, and CI.

## Feast Feature Store

Feast configuration is present in:

```text
feature_repo/feature_store.yaml
feature_repo/features.py
```

Feast entity:

```text
stock
```

Join key:

```text
stock_name
```

Feature view:

```text
stock_rolling_features
```

Features:

```text
rolling_avg_10
volume_sum_10
```

Apply Feast definitions:

```bash
cd feature_repo
feast apply
cd ..
```

The training and evaluation scripts use Feast historical retrieval through:

```text
get_historical_features()
```

This provides point-in-time correct feature retrieval for the model pipeline.

## Training

Training is implemented in:

```text
src/train_pipeline.py
```

Final training commands:

```bash
python src/train_pipeline.py --iteration v0 --rows-per-stock 1000
python src/train_pipeline.py --iteration v1 --rows-per-stock 1000
```

Iteration 1 trains on v0 data only.

Iteration 2 trains on merged v0 + v1 data.

The script performs hyperparameter tuning over multiple model configurations and logs every run to MLflow.

## MLflow

MLflow is used for:

```text
Experiment tracking
Parameter logging
Metric logging
Model artifact logging
Model registry
Champion model aliasing
```

MLflow experiment:

```text
stock-movement-experiments
```

Registered model:

```text
stock-movement-predictor
```

Champion alias:

```text
models:/stock-movement-predictor@champion
```

MLflow tracking database:

```text
mlflow.db
```

The MLflow registry database is uploaded to GCS for CI:

```text
gs://oppe1-22f3001954-mlops/mlflow-db/mlflow.db
```

MLflow artifacts are stored in:

```text
gs://oppe1-22f3001954-mlops/mlflow-artifacts
```

Start MLflow UI:

```bash
mlflow ui \
  --backend-store-uri sqlite:///mlflow.db \
  --default-artifact-root gs://oppe1-22f3001954-mlops/mlflow-artifacts \
  --host 0.0.0.0 \
  --port 5000
```

## Evaluation

Evaluation is implemented in:

```text
src/evaluate_registered_model.py
```

Run evaluation:

```bash
python src/evaluate_registered_model.py
```

This loads the champion model from MLflow registry:

```text
models:/stock-movement-predictor@champion
```

It generates:

```text
reports/ci_metrics.json
reports/confusion_matrix.png
reports/predictions.csv
```

## Tests

Tests are present in:

```text
tests/test_feature_sanity.py
tests/test_model_registry.py
```

The tests validate:

```text
rolling_avg_10
volume_sum_10
target column
required feature columns
null checks
MLflow champion model loading
```

Run tests:

```bash
pytest tests -v
```

## CI with GitHub Actions and CML

The CI workflow is defined in:

```text
.github/workflows/ci.yml
```

The workflow runs on:

```text
push to main
pull request to main
manual workflow dispatch
```

CI steps:

```text
1. Checkout repository
2. Authenticate to GCP using Workload Identity Federation
3. Install Python dependencies
4. Pull DVC-pinned data
5. Prepare v1 sample data
6. Apply Feast feature definitions
7. Fetch MLflow registry database from GCS
8. Evaluate champion model
9. Run feature sanity tests
10. Create CML report
11. Post CML report on pull request
```

## Final End-to-End Execution Commands

Run the following from the repository root:

```bash
cd ~/oppe1/22F3001954_MLOPS_OPPE1_MAY_26
source venv/bin/activate

dvc pull

python src/prepare_data.py --iteration v0
python src/prepare_data.py --iteration v1

python src/create_pipeline_sample.py --iteration v0 --rows-per-stock 1000
python src/create_pipeline_sample.py --iteration v1 --rows-per-stock 1000

cd feature_repo
feast apply
cd ..

python src/train_pipeline.py --iteration v0 --rows-per-stock 1000
python src/train_pipeline.py --iteration v1 --rows-per-stock 1000

gcloud storage cp mlflow.db gs://oppe1-22f3001954-mlops/mlflow-db/mlflow.db

python src/evaluate_registered_model.py
pytest tests -v
```

## Notes on Dataset Size

The complete stock dataset is large. Full raw data and full processed data are versioned through DVC.

During implementation, full Feast historical retrieval on the complete dataset exceeded the memory capacity of the mandated 16 GB Workbench instance. Therefore, the final end-to-end pipeline computes features on the full data first and then uses a chronological per-stock sample for Feast retrieval, MLflow training, model registry validation, and CI.

This keeps the complete MLOps workflow reproducible and executable within the required cloud environment.

## GCP Access

The course team was granted read access to the GCP project using:

```bash
PROJECT_ID=mlops-499806

for ROLE in roles/viewer roles/container.viewer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="user:da5014_1@study.iitm.ac.in" \
    --role="$ROLE"
done
```

## Submission Checklist

```text
Private GitHub repository created
Course collaborator added
GCP read access granted
Vertex AI Workbench instance with 16 GB RAM used
Raw v0 and v1 data tracked using DVC
Processed v0 and v1 data tracked using DVC
GCS configured as DVC remote
Feast entity and feature view created
Feast historical retrieval used
Training iteration 1 completed on v0
Training iteration 2 completed on v0 + v1
MLflow tracking completed
Best model registered in MLflow registry
Champion alias assigned
Evaluation script completed
Feature sanity tests completed
GitHub Actions CI configured
CML PR report configured
```
