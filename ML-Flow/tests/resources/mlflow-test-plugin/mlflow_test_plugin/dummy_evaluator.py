from mlflow import MlflowClient
from mlflow.models.evaluation import (
    ModelEvaluator,
    EvaluationArtifact,
    EvaluationResult,
)
from mlflow.models.evaluation.artifacts import ImageEvaluationArtifact
from mlflow.tracking.artifact_utils import get_artifact_uri
from mlflow.entities import Metric
from sklearn import metrics as sk_metrics
import time
import pandas as pd
import io
from PIL import Image


class Array2DEvaluationArtifact(EvaluationArtifact):
    def _save(self, output_artifact_path):
        pd.DataFrame(self._content).to_csv(output_artifact_path, index=False)

    def _load_content_from_file(self, local_artifact_path):
        pdf = pd.read_csv(local_artifact_path)
        return pdf.to_numpy()


class DummyEvaluator(ModelEvaluator):
    # pylint: disable=unused-argument
    def can_evaluate(self, *, model_type, evaluator_config, **kwargs):
        return model_type in ["classifier", "regressor"]

    def _log_metrics(self, run_id, metrics, dataset_name):
        """
        Helper method to log metrics into specified run.
        """
        client = MlflowClient()
        timestamp = int(time.time() * 1000)
        client.log_batch(
            run_id,
            metrics=[
                Metric(key=f"{key}_on_{dataset_name}", value=value, timestamp=timestamp, step=0)
                for key, value in metrics.items()
            ],
        )

    # pylint: disable=unused-argument
    def evaluate(
        self, *, model, model_type, dataset, run_id, evaluator_config, **kwargs
    ) -> EvaluationResult:
        client = MlflowClient()
        X = dataset.features_data
        y = dataset.labels_data
        y_pred = model.predict(X)
        if model_type == "classifier":
            accuracy_score = sk_metrics.accuracy_score(y, y_pred)

            metrics = {"accuracy_score": accuracy_score}
            self._log_metrics(run_id, metrics, dataset.name)
            confusion_matrix = sk_metrics.confusion_matrix(y, y_pred)
            confusion_matrix_artifact_name = f"confusion_matrix_on_{dataset.name}"
            confusion_matrix_artifact = Array2DEvaluationArtifact(
                uri=get_artifact_uri(run_id, confusion_matrix_artifact_name + ".csv"),
                content=confusion_matrix,
            )
            confusion_matrix_csv_buff = io.StringIO()
            confusion_matrix_artifact._save(confusion_matrix_csv_buff)
            client.log_text(
                run_id,
                confusion_matrix_csv_buff.getvalue(),
                confusion_matrix_artifact_name + ".csv",
            )

            confusion_matrix_figure = sk_metrics.ConfusionMatrixDisplay.from_predictions(
                y, y_pred
            ).figure_
            img_buf = io.BytesIO()
            confusion_matrix_figure.savefig(img_buf)
            img_buf.seek(0)
            confusion_matrix_image = Image.open(img_buf)

            confusion_matrix_image_artifact_name = f"confusion_matrix_image_on_{dataset.name}"
            confusion_matrix_image_artifact = ImageEvaluationArtifact(
                uri=get_artifact_uri(run_id, confusion_matrix_image_artifact_name + ".png"),
                content=confusion_matrix_image,
            )
            confusion_matrix_image_artifact._save(confusion_matrix_image_artifact_name + ".png")
            client.log_image(
                run_id, confusion_matrix_image, confusion_matrix_image_artifact_name + ".png"
            )

            artifacts = {
                confusion_matrix_artifact_name: confusion_matrix_artifact,
                confusion_matrix_image_artifact_name: confusion_matrix_image_artifact,
            }
        elif model_type == "regressor":
            mean_absolute_error = sk_metrics.mean_absolute_error(y, y_pred)
            mean_squared_error = sk_metrics.mean_squared_error(y, y_pred)
            metrics = {
                "mean_absolute_error": mean_absolute_error,
                "mean_squared_error": mean_squared_error,
            }
            self._log_metrics(run_id, metrics, dataset.name)
            artifacts = {}
        else:
            raise ValueError(f"Unsupported model type {model_type}")

        return EvaluationResult(metrics=metrics, artifacts=artifacts)
