import mlflow
import mlflow.pyfunc

from src.config import MLFLOW_TRACKING_URI, REGISTERED_MODEL_NAME, MODEL_ALIAS


def test_champion_model_loads_from_mlflow_registry():
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    model_uri = f"models:/{REGISTERED_MODEL_NAME}@{MODEL_ALIAS}"
    model = mlflow.pyfunc.load_model(model_uri)

    assert model is not None
