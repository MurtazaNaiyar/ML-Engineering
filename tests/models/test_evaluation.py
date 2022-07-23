import mlflow
from mlflow import MlflowClient
from collections import namedtuple

from mlflow.models.evaluation import (
    evaluate,
    EvaluationResult,
    ModelEvaluator,
    EvaluationArtifact,
)
from mlflow.models.evaluation.artifacts import ImageEvaluationArtifact
from mlflow.models.evaluation.base import (
    EvaluationDataset,
    _normalize_evaluators_and_evaluator_config_args as _normalize_config,
)
import hashlib
from mlflow.models.evaluation.base import _start_run_or_reuse_active_run
import sklearn
import os
import sklearn.compose
import sklearn.datasets
import sklearn.impute
import sklearn.linear_model
import sklearn.pipeline
import sklearn.preprocessing
import pytest
import numpy as np
import pandas as pd
from unittest import mock
from PIL import ImageChops, Image
import io
from mlflow.utils.file_utils import TempDir
from mlflow_test_plugin.dummy_evaluator import Array2DEvaluationArtifact
from mlflow.models.evaluation.evaluator_registry import _model_evaluation_registry
from mlflow.models.evaluation.base import _logger as _base_logger, _gen_md5_for_arraylike_obj

from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    mean_absolute_error,
    mean_squared_error,
)

from pyspark.sql import SparkSession
from pyspark.ml.linalg import Vectors
from pyspark.ml.regression import LinearRegression as SparkLinearRegression

from mlflow.tracking.artifact_utils import get_artifact_uri
import json
import uuid


def get_iris():
    iris = sklearn.datasets.load_iris()
    return iris.data, iris.target


def get_diabetes_dataset():
    data = sklearn.datasets.load_diabetes()
    return data.data, data.target


def get_diabetes_spark_dataset():
    data = sklearn.datasets.load_diabetes()
    spark = SparkSession.builder.master("local[*]").getOrCreate()
    rows = [
        (Vectors.dense(features), float(label)) for features, label in zip(data.data, data.target)
    ]
    return spark.createDataFrame(spark.sparkContext.parallelize(rows, 1), ["features", "label"])


def get_breast_cancer_dataset():
    data = sklearn.datasets.load_breast_cancer()
    return data.data, data.target


RunData = namedtuple("RunData", ["params", "metrics", "tags", "artifacts"])


def get_run_data(run_id):
    client = MlflowClient()
    data = client.get_run(run_id).data
    tags = {k: v for k, v in data.tags.items()}
    artifacts = [f.path for f in client.list_artifacts(run_id)]
    return RunData(params=data.params, metrics=data.metrics, tags=tags, artifacts=artifacts)


def get_raw_tag(run_id, tag_name):
    client = MlflowClient()
    data = client.get_run(run_id).data
    return data.tags[tag_name]


def get_local_artifact_path(run_id, artifact_path):
    return get_artifact_uri(run_id, artifact_path).replace("file://", "")


@pytest.fixture(scope="module")
def spark_session():
    session = SparkSession.builder.master("local[*]").getOrCreate()
    yield session
    session.stop()


@pytest.fixture(scope="module")
def iris_dataset():
    X, y = get_iris()
    eval_X, eval_y = X[0::3], y[0::3]
    constructor_args = {"data": eval_X, "targets": eval_y, "name": "iris_dataset"}
    ds = EvaluationDataset(**constructor_args)
    ds._constructor_args = constructor_args
    return ds


@pytest.fixture(scope="module")
def diabetes_dataset():
    X, y = get_diabetes_dataset()
    eval_X, eval_y = X[0::3], y[0::3]
    constructor_args = {"data": eval_X, "targets": eval_y, "name": "diabetes_dataset"}
    ds = EvaluationDataset(**constructor_args)
    ds._constructor_args = constructor_args
    return ds


@pytest.fixture(scope="module")
def diabetes_spark_dataset():
    spark_df = get_diabetes_spark_dataset().sample(fraction=0.3, seed=1)
    constructor_args = {"data": spark_df, "targets": "label", "name": "diabetes_spark_dataset"}
    ds = EvaluationDataset(**constructor_args)
    ds._constructor_args = constructor_args
    return ds


@pytest.fixture(scope="module")
def breast_cancer_dataset():
    X, y = get_breast_cancer_dataset()
    eval_X, eval_y = X[0::3], y[0::3]
    constructor_args = {"data": eval_X, "targets": eval_y, "name": "breast_cancer_dataset"}
    ds = EvaluationDataset(**constructor_args)
    ds._constructor_args = constructor_args
    return ds


def get_pipeline_model_dataset():
    """
    The dataset tweaks the IRIS dataset by changing its first 2 features into categorical features,
    and replace some feature values with NA values.
    The dataset is prepared for a pipeline model, see `pipeline_model_uri`.
    """
    X, y = get_iris()

    def convert_num_to_label(x):
        return f"v_{round(x)}"

    f1 = np.array(list(map(convert_num_to_label, X[:, 0])))
    f2 = np.array(list(map(convert_num_to_label, X[:, 1])))
    f3 = X[:, 2]
    f4 = X[:, 3]

    f1[0::8] = None
    f2[1::8] = None
    f3[2::8] = np.nan
    f4[3::8] = np.nan

    data = pd.DataFrame(
        {
            "f1": f1,
            "f2": f2,
            "f3": f3,
            "f4": f4,
            "y": y,
        }
    )
    return data, "y"


@pytest.fixture
def pipeline_model_uri():
    """
    Create a pipeline model that transforms and trains on the dataset returned by
    `get_pipeline_model_dataset`. The pipeline model imputes the missing values in
    input dataset, encodes categorical features, and then trains a logistic regression
    model.
    """
    data, target_col = get_pipeline_model_dataset()
    X = data.drop(target_col, axis=1)
    y = data[target_col].to_numpy()

    encoder = sklearn.preprocessing.OrdinalEncoder()
    str_imputer = sklearn.impute.SimpleImputer(missing_values=None, strategy="most_frequent")
    num_imputer = sklearn.impute.SimpleImputer(missing_values=np.nan, strategy="mean")
    preproc_pipeline = sklearn.pipeline.Pipeline(
        [
            ("imputer", str_imputer),
            ("encoder", encoder),
        ]
    )

    pipeline = sklearn.pipeline.Pipeline(
        [
            (
                "transformer",
                sklearn.compose.make_column_transformer(
                    (preproc_pipeline, ["f1", "f2"]),
                    (num_imputer, ["f3", "f4"]),
                ),
            ),
            ("clf", sklearn.linear_model.LogisticRegression()),
        ]
    )
    pipeline.fit(X, y)

    with mlflow.start_run():
        model_info = mlflow.sklearn.log_model(pipeline, "pipeline_model")
        return model_info.model_uri


@pytest.fixture
def linear_regressor_model_uri():
    X, y = get_diabetes_dataset()
    reg = sklearn.linear_model.LinearRegression()
    reg.fit(X, y)

    with mlflow.start_run() as run:
        mlflow.sklearn.log_model(reg, "reg_model")
        linear_regressor_model_uri = get_artifact_uri(run.info.run_id, "reg_model")

    return linear_regressor_model_uri


@pytest.fixture
def spark_linear_regressor_model_uri():
    spark_df = get_diabetes_spark_dataset()
    reg = SparkLinearRegression()
    spark_reg_model = reg.fit(spark_df)

    with mlflow.start_run() as run:
        mlflow.spark.log_model(spark_reg_model, "spark_reg_model")
        spark_linear_regressor_model_uri = get_artifact_uri(run.info.run_id, "spark_reg_model")

    return spark_linear_regressor_model_uri


@pytest.fixture
def multiclass_logistic_regressor_model_uri():
    X, y = get_iris()
    clf = sklearn.linear_model.LogisticRegression(max_iter=2)
    clf.fit(X, y)

    with mlflow.start_run() as run:
        mlflow.sklearn.log_model(clf, "clf_model")
        multiclass_logistic_regressor_model_uri = get_artifact_uri(run.info.run_id, "clf_model")

    return multiclass_logistic_regressor_model_uri


@pytest.fixture
def binary_logistic_regressor_model_uri():
    X, y = get_breast_cancer_dataset()
    clf = sklearn.linear_model.LogisticRegression()
    clf.fit(X, y)

    with mlflow.start_run() as run:
        mlflow.sklearn.log_model(clf, "bin_clf_model")
        binary_logistic_regressor_model_uri = get_artifact_uri(run.info.run_id, "bin_clf_model")

    return binary_logistic_regressor_model_uri


@pytest.fixture
def svm_model_uri():
    X, y = get_breast_cancer_dataset()
    clf = sklearn.svm.LinearSVC()
    clf.fit(X, y)

    with mlflow.start_run() as run:
        mlflow.sklearn.log_model(clf, "svm_model")
        svm_model_uri = get_artifact_uri(run.info.run_id, "svm_model")

    return svm_model_uri


@pytest.fixture
def iris_pandas_df_dataset():
    X, y = get_iris()
    eval_X, eval_y = X[0::3], y[0::3]
    data = pd.DataFrame(
        {
            "f1": eval_X[:, 0],
            "f2": eval_X[:, 1],
            "f3": eval_X[:, 2],
            "f4": eval_X[:, 3],
            "y": eval_y,
        }
    )
    return EvaluationDataset(data=data, targets="y", name="iris_pandas_df_dataset")


def test_classifier_evaluate(multiclass_logistic_regressor_model_uri, iris_dataset):
    y_true = iris_dataset.labels_data
    classifier_model = mlflow.pyfunc.load_model(multiclass_logistic_regressor_model_uri)
    y_pred = classifier_model.predict(iris_dataset.features_data)
    expected_accuracy_score = accuracy_score(y_true, y_pred)
    expected_metrics = {
        "accuracy_score": expected_accuracy_score,
    }
    expected_saved_metrics = {
        "accuracy_score_on_iris_dataset": expected_accuracy_score,
    }

    expected_csv_artifact = confusion_matrix(y_true, y_pred)
    cm_figure = sklearn.metrics.ConfusionMatrixDisplay.from_predictions(y_true, y_pred).figure_
    img_buf = io.BytesIO()
    cm_figure.savefig(img_buf)
    img_buf.seek(0)
    expected_image_artifact = Image.open(img_buf)

    with mlflow.start_run() as run:
        eval_result = evaluate(
            classifier_model,
            iris_dataset._constructor_args["data"],
            model_type="classifier",
            targets=iris_dataset._constructor_args["targets"],
            dataset_name=iris_dataset.name,
            evaluators="dummy_evaluator",
        )

    csv_artifact_name = "confusion_matrix_on_iris_dataset"
    saved_csv_artifact_path = get_local_artifact_path(run.info.run_id, csv_artifact_name + ".csv")

    png_artifact_name = "confusion_matrix_image_on_iris_dataset"
    saved_png_artifact_path = get_local_artifact_path(run.info.run_id, png_artifact_name) + ".png"

    _, saved_metrics, _, saved_artifacts = get_run_data(run.info.run_id)
    assert saved_metrics == expected_saved_metrics
    assert set(saved_artifacts) == {csv_artifact_name + ".csv", png_artifact_name + ".png"}

    assert eval_result.metrics == expected_metrics
    confusion_matrix_artifact = eval_result.artifacts[csv_artifact_name]
    assert np.array_equal(confusion_matrix_artifact.content, expected_csv_artifact)
    assert confusion_matrix_artifact.uri == get_artifact_uri(
        run.info.run_id, csv_artifact_name + ".csv"
    )
    assert np.array_equal(
        confusion_matrix_artifact._load(saved_csv_artifact_path), expected_csv_artifact
    )
    confusion_matrix_image_artifact = eval_result.artifacts[png_artifact_name]
    assert (
        ImageChops.difference(
            confusion_matrix_image_artifact.content, expected_image_artifact
        ).getbbox()
        is None
    )
    assert confusion_matrix_image_artifact.uri == get_artifact_uri(
        run.info.run_id, png_artifact_name + ".png"
    )
    assert (
        ImageChops.difference(
            confusion_matrix_image_artifact._load(saved_png_artifact_path),
            expected_image_artifact,
        ).getbbox()
        is None
    )

    with TempDir() as temp_dir:
        temp_dir_path = temp_dir.path()
        eval_result.save(temp_dir_path)

        with open(temp_dir.path("metrics.json"), "r") as fp:
            assert json.load(fp) == eval_result.metrics

        with open(temp_dir.path("artifacts_metadata.json"), "r") as fp:
            json_dict = json.load(fp)
            assert "confusion_matrix_on_iris_dataset" in json_dict
            assert json_dict["confusion_matrix_on_iris_dataset"] == {
                "uri": confusion_matrix_artifact.uri,
                "class_name": "mlflow_test_plugin.dummy_evaluator.Array2DEvaluationArtifact",
            }

            assert "confusion_matrix_image_on_iris_dataset" in json_dict
            assert json_dict["confusion_matrix_image_on_iris_dataset"] == {
                "uri": confusion_matrix_image_artifact.uri,
                "class_name": "mlflow.models.evaluation.artifacts.ImageEvaluationArtifact",
            }

        assert set(os.listdir(temp_dir.path("artifacts"))) == {
            "confusion_matrix_on_iris_dataset.csv",
            "confusion_matrix_image_on_iris_dataset.png",
        }

        loaded_eval_result = EvaluationResult.load(temp_dir_path)
        assert loaded_eval_result.metrics == eval_result.metrics
        loaded_confusion_matrix_artifact = loaded_eval_result.artifacts[csv_artifact_name]
        assert confusion_matrix_artifact.uri == loaded_confusion_matrix_artifact.uri
        assert np.array_equal(
            confusion_matrix_artifact.content,
            loaded_confusion_matrix_artifact.content,
        )
        loaded_confusion_matrix_image_artifact = loaded_eval_result.artifacts[png_artifact_name]
        assert confusion_matrix_image_artifact.uri == loaded_confusion_matrix_image_artifact.uri
        assert (
            ImageChops.difference(
                confusion_matrix_image_artifact.content,
                loaded_confusion_matrix_image_artifact.content,
            ).getbbox()
            is None
        )

        new_confusion_matrix_artifact = Array2DEvaluationArtifact(uri=confusion_matrix_artifact.uri)
        new_confusion_matrix_artifact._load()
        assert np.array_equal(
            confusion_matrix_artifact.content,
            new_confusion_matrix_artifact.content,
        )
        new_confusion_matrix_image_artifact = ImageEvaluationArtifact(
            uri=confusion_matrix_image_artifact.uri
        )
        new_confusion_matrix_image_artifact._load()
        assert np.array_equal(
            confusion_matrix_image_artifact.content,
            new_confusion_matrix_image_artifact.content,
        )


def test_regressor_evaluate(linear_regressor_model_uri, diabetes_dataset):
    y_true = diabetes_dataset.labels_data
    regressor_model = mlflow.pyfunc.load_model(linear_regressor_model_uri)
    y_pred = regressor_model.predict(diabetes_dataset.features_data)
    expected_mae = mean_absolute_error(y_true, y_pred)
    expected_mse = mean_squared_error(y_true, y_pred)
    expected_metrics = {
        "mean_absolute_error": expected_mae,
        "mean_squared_error": expected_mse,
    }
    expected_saved_metrics = {
        "mean_absolute_error_on_diabetes_dataset": expected_mae,
        "mean_squared_error_on_diabetes_dataset": expected_mse,
    }

    for model in [regressor_model, linear_regressor_model_uri]:
        with mlflow.start_run() as run:
            eval_result = evaluate(
                model,
                diabetes_dataset._constructor_args["data"],
                model_type="regressor",
                targets=diabetes_dataset._constructor_args["targets"],
                dataset_name=diabetes_dataset.name,
                evaluators="dummy_evaluator",
            )
        _, saved_metrics, _, _ = get_run_data(run.info.run_id)
        assert saved_metrics == expected_saved_metrics
        assert eval_result.metrics == expected_metrics


def test_pandas_df_regressor_evaluation(linear_regressor_model_uri):

    data = sklearn.datasets.load_diabetes()
    df = pd.DataFrame(data.data, columns=data.feature_names)
    df["y"] = data.target

    regressor_model = mlflow.pyfunc.load_model(linear_regressor_model_uri)

    dataset_name = "diabetes_pd"

    for model in [regressor_model, linear_regressor_model_uri]:
        with mlflow.start_run() as run:
            eval_result = evaluate(
                model,
                data=df,
                targets="y",
                model_type="regressor",
                dataset_name=dataset_name,
                evaluators=["default"],
            )
        _, saved_metrics, _, _ = get_run_data(run.info.run_id)

    augment_name = f"_on_data_{dataset_name}"
    for k, v in eval_result.metrics.items():
        assert v == saved_metrics[f"{k}{augment_name}"]


def test_dataset_name():
    X, y = get_iris()
    d1 = EvaluationDataset(data=X, targets=y, name="a1")
    assert d1.name == "a1"
    d2 = EvaluationDataset(data=X, targets=y)
    assert d2.name == d2.hash


def test_dataset_metadata():
    X, y = get_iris()
    d1 = EvaluationDataset(data=X, targets=y, name="a1", path="/path/to/a1")
    assert d1._metadata == {
        "hash": "6bdf4e119bf1a37e7907dfd9f0e68733",
        "name": "a1",
        "path": "/path/to/a1",
    }


def test_gen_md5_for_arraylike_obj():
    def get_md5(data):
        md5_gen = hashlib.md5()
        _gen_md5_for_arraylike_obj(md5_gen, data)
        return md5_gen.hexdigest()

    list0 = list(range(20))
    list1 = [100] + list0[1:]
    list2 = list0[:-1] + [100]
    list3 = list0[:10] + [100] + list0[10:]

    assert 4 == len({get_md5(list0), get_md5(list1), get_md5(list2), get_md5(list3)})

    list4 = list0[:10] + [99] + list0[10:]
    assert get_md5(list3) == get_md5(list4)


def test_dataset_hash(iris_dataset, iris_pandas_df_dataset, diabetes_spark_dataset):
    assert iris_dataset.hash == "99329a790dc483e7382c0d1d27aac3f3"
    assert iris_pandas_df_dataset.hash == "799d4f50e2e353127f94a0e5300add06"
    assert diabetes_spark_dataset.hash == "e646b03e976240bd0c79c6bcc1ae0bda"


def test_dataset_with_pandas_dataframe():
    data = pd.DataFrame({"f1": [1, 2], "f2": [3, 4], "f3": [5, 6], "label": [0, 1]})
    eval_dataset = EvaluationDataset(data=data, targets="label")

    assert list(eval_dataset.features_data.columns) == ["f1", "f2", "f3"]
    assert np.array_equal(eval_dataset.features_data.f1.to_numpy(), [1, 2])
    assert np.array_equal(eval_dataset.features_data.f2.to_numpy(), [3, 4])
    assert np.array_equal(eval_dataset.features_data.f3.to_numpy(), [5, 6])
    assert np.array_equal(eval_dataset.labels_data, [0, 1])

    eval_dataset2 = EvaluationDataset(data=data, targets="label", feature_names=["f3", "f2"])
    assert list(eval_dataset2.features_data.columns) == ["f3", "f2"]
    assert np.array_equal(eval_dataset2.features_data.f2.to_numpy(), [3, 4])
    assert np.array_equal(eval_dataset2.features_data.f3.to_numpy(), [5, 6])


def test_dataset_with_array_data():
    features = [[1, 2], [3, 4]]
    labels = [0, 1]

    for input_data in [features, np.array(features)]:
        eval_dataset1 = EvaluationDataset(data=input_data, targets=labels)
        assert np.array_equal(eval_dataset1.features_data, features)
        assert np.array_equal(eval_dataset1.labels_data, labels)
        assert list(eval_dataset1.feature_names) == ["feature_1", "feature_2"]

    assert EvaluationDataset(
        data=input_data, targets=labels, feature_names=["a", "b"]
    ).feature_names == ["a", "b"]

    with pytest.raises(ValueError, match="all element must has the same length"):
        EvaluationDataset(data=[[1, 2], [3, 4, 5]], targets=labels)


def test_dataset_autogen_feature_names():
    labels = [0]
    eval_dataset2 = EvaluationDataset(data=[list(range(9))], targets=labels)
    assert eval_dataset2.feature_names == [f"feature_{i + 1}" for i in range(9)]

    eval_dataset2 = EvaluationDataset(data=[list(range(10))], targets=labels)
    assert eval_dataset2.feature_names == [f"feature_{i + 1:02d}" for i in range(10)]

    eval_dataset2 = EvaluationDataset(data=[list(range(99))], targets=labels)
    assert eval_dataset2.feature_names == [f"feature_{i + 1:02d}" for i in range(99)]

    eval_dataset2 = EvaluationDataset(data=[list(range(100))], targets=labels)
    assert eval_dataset2.feature_names == [f"feature_{i + 1:03d}" for i in range(100)]

    with pytest.raises(
        ValueError, match="features example rows must be the same length with labels array"
    ):
        EvaluationDataset(data=[[1, 2], [3, 4]], targets=[1, 2, 3])


def test_dataset_from_spark_df(spark_session):
    spark_df = spark_session.createDataFrame([(1.0, 2.0, 3.0)] * 10, ["f1", "f2", "y"])
    with mock.patch.object(EvaluationDataset, "SPARK_DATAFRAME_LIMIT", 5):
        dataset = EvaluationDataset(spark_df, targets="y")
        assert list(dataset.features_data.columns) == ["f1", "f2"]
        assert list(dataset.features_data["f1"]) == [1.0] * 5
        assert list(dataset.features_data["f2"]) == [2.0] * 5
        assert list(dataset.labels_data) == [3.0] * 5


def test_log_dataset_tag(iris_dataset, iris_pandas_df_dataset):
    model_uuid = uuid.uuid4().hex
    with mlflow.start_run() as run:
        client = MlflowClient()
        iris_dataset._log_dataset_tag(client, run.info.run_id, model_uuid=model_uuid)
        _, _, tags, _ = get_run_data(run.info.run_id)

        logged_meta1 = {**iris_dataset._metadata, "model": model_uuid}
        logged_meta2 = {**iris_pandas_df_dataset._metadata, "model": model_uuid}

        assert json.loads(tags["mlflow.datasets"]) == [logged_meta1]

        raw_tag = get_raw_tag(run.info.run_id, "mlflow.datasets")
        assert " " not in raw_tag  # assert the tag string remove all whitespace chars.

        # Test appending dataset tag
        iris_pandas_df_dataset._log_dataset_tag(client, run.info.run_id, model_uuid=model_uuid)
        _, _, tags, _ = get_run_data(run.info.run_id)
        assert json.loads(tags["mlflow.datasets"]) == [
            logged_meta1,
            logged_meta2,
        ]

        # Test log repetitive dataset
        iris_dataset._log_dataset_tag(client, run.info.run_id, model_uuid=model_uuid)
        _, _, tags, _ = get_run_data(run.info.run_id)
        assert json.loads(tags["mlflow.datasets"]) == [
            logged_meta1,
            logged_meta2,
        ]


class FakeEvauator1(ModelEvaluator):
    def can_evaluate(self, *, model_type, evaluator_config, **kwargs):
        raise RuntimeError()

    def evaluate(self, *, model, model_type, dataset, run_id, evaluator_config, **kwargs):
        raise RuntimeError()


class FakeEvauator2(ModelEvaluator):
    def can_evaluate(self, *, model_type, evaluator_config, **kwargs):
        raise RuntimeError()

    def evaluate(self, *, model, model_type, dataset, run_id, evaluator_config, **kwargs):
        raise RuntimeError()


class FakeArtifact1(EvaluationArtifact):
    def _save(self, output_artifact_path):
        raise RuntimeError()

    def _load_content_from_file(self, local_artifact_path):
        raise RuntimeError()


class FakeArtifact2(EvaluationArtifact):
    def _save(self, output_artifact_path):
        raise RuntimeError()

    def _load_content_from_file(self, local_artifact_path):
        raise RuntimeError()


def test_evaluator_interface(multiclass_logistic_regressor_model_uri, iris_dataset):
    with mock.patch.object(
        _model_evaluation_registry, "_registry", {"test_evaluator1": FakeEvauator1}
    ):
        evaluator1_config = {"eval1_confg_a": 3, "eval1_confg_b": 4}
        evaluator1_return_value = EvaluationResult(
            metrics={"m1": 5, "m2": 6},
            artifacts={"a1": FakeArtifact1(uri="uri1"), "a2": FakeArtifact2(uri="uri2")},
        )
        with mock.patch.object(
            FakeEvauator1, "can_evaluate", return_value=False
        ) as mock_can_evaluate, mock.patch.object(
            FakeEvauator1, "evaluate", return_value=evaluator1_return_value
        ) as mock_evaluate:
            with mlflow.start_run():
                with pytest.raises(
                    ValueError,
                    match="The model could not be evaluated by any of the registered evaluators",
                ):
                    evaluate(
                        multiclass_logistic_regressor_model_uri,
                        data=iris_dataset._constructor_args["data"],
                        model_type="classifier",
                        targets=iris_dataset._constructor_args["targets"],
                        dataset_name=iris_dataset.name,
                        evaluators="test_evaluator1",
                        evaluator_config=evaluator1_config,
                    )
                mock_can_evaluate.assert_called_once_with(
                    model_type="classifier", evaluator_config=evaluator1_config
                )
                mock_evaluate.assert_not_called()
        with mock.patch.object(
            FakeEvauator1, "can_evaluate", return_value=True
        ) as mock_can_evaluate, mock.patch.object(
            FakeEvauator1, "evaluate", return_value=evaluator1_return_value
        ) as mock_evaluate:
            classifier_model = mlflow.pyfunc.load_model(multiclass_logistic_regressor_model_uri)
            with mlflow.start_run() as run:
                eval1_result = evaluate(
                    classifier_model,
                    iris_dataset._constructor_args["data"],
                    model_type="classifier",
                    targets=iris_dataset._constructor_args["targets"],
                    dataset_name=iris_dataset.name,
                    evaluators="test_evaluator1",
                    evaluator_config=evaluator1_config,
                    custom_metrics=None,
                )
                assert eval1_result.metrics == evaluator1_return_value.metrics
                assert eval1_result.artifacts == evaluator1_return_value.artifacts

                mock_can_evaluate.assert_called_once_with(
                    model_type="classifier", evaluator_config=evaluator1_config
                )
                mock_evaluate.assert_called_once_with(
                    model=classifier_model,
                    model_type="classifier",
                    dataset=iris_dataset,
                    run_id=run.info.run_id,
                    evaluator_config=evaluator1_config,
                    custom_metrics=None,
                )


def test_evaluate_with_multi_evaluators(multiclass_logistic_regressor_model_uri, iris_dataset):
    with mock.patch.object(
        _model_evaluation_registry,
        "_registry",
        {"test_evaluator1": FakeEvauator1, "test_evaluator2": FakeEvauator2},
    ):
        evaluator1_config = {"eval1_confg": 3}
        evaluator2_config = {"eval2_confg": 4}
        evaluator1_return_value = EvaluationResult(
            metrics={"m1": 5}, artifacts={"a1": FakeArtifact1(uri="uri1")}
        )
        evaluator2_return_value = EvaluationResult(
            metrics={"m2": 6}, artifacts={"a2": FakeArtifact2(uri="uri2")}
        )

        # evaluators = None is the case evaluators unspecified, it should fetch all registered
        # evaluators, and the evaluation results should equal to the case of
        # evaluators=["test_evaluator1", "test_evaluator2"]
        for evaluators in [None, ["test_evaluator1", "test_evaluator2"]]:
            with mock.patch.object(
                FakeEvauator1, "can_evaluate", return_value=True
            ) as mock_can_evaluate1, mock.patch.object(
                FakeEvauator1, "evaluate", return_value=evaluator1_return_value
            ) as mock_evaluate1, mock.patch.object(
                FakeEvauator2, "can_evaluate", return_value=True
            ) as mock_can_evaluate2, mock.patch.object(
                FakeEvauator2, "evaluate", return_value=evaluator2_return_value
            ) as mock_evaluate2:
                classifier_model = mlflow.pyfunc.load_model(multiclass_logistic_regressor_model_uri)
                with mlflow.start_run() as run:
                    eval_result = evaluate(
                        classifier_model,
                        iris_dataset._constructor_args["data"],
                        model_type="classifier",
                        targets=iris_dataset._constructor_args["targets"],
                        dataset_name=iris_dataset.name,
                        evaluators=evaluators,
                        evaluator_config={
                            "test_evaluator1": evaluator1_config,
                            "test_evaluator2": evaluator2_config,
                        },
                    )
                    assert eval_result.metrics == {
                        **evaluator1_return_value.metrics,
                        **evaluator2_return_value.metrics,
                    }
                    assert eval_result.artifacts == {
                        **evaluator1_return_value.artifacts,
                        **evaluator2_return_value.artifacts,
                    }
                    mock_can_evaluate1.assert_called_once_with(
                        model_type="classifier", evaluator_config=evaluator1_config
                    )
                    mock_evaluate1.assert_called_once_with(
                        model=classifier_model,
                        model_type="classifier",
                        dataset=iris_dataset,
                        run_id=run.info.run_id,
                        evaluator_config=evaluator1_config,
                        custom_metrics=None,
                    )
                    mock_can_evaluate2.assert_called_once_with(
                        model_type="classifier",
                        evaluator_config=evaluator2_config,
                    )
                    mock_evaluate2.assert_called_once_with(
                        model=classifier_model,
                        model_type="classifier",
                        dataset=iris_dataset,
                        run_id=run.info.run_id,
                        evaluator_config=evaluator2_config,
                        custom_metrics=None,
                    )


def test_start_run_or_reuse_active_run():
    with _start_run_or_reuse_active_run() as run_id:
        assert mlflow.active_run().info.run_id == run_id

    with mlflow.start_run() as run:
        active_run_id = run.info.run_id

        with _start_run_or_reuse_active_run() as run_id:
            assert run_id == active_run_id

        with _start_run_or_reuse_active_run() as run_id:
            assert run_id == active_run_id


def test_normalize_evaluators_and_evaluator_config_args():
    from mlflow.models.evaluation.default_evaluator import DefaultEvaluator

    with mock.patch.object(
        _model_evaluation_registry,
        "_registry",
        {"default": DefaultEvaluator},
    ):
        assert _normalize_config(None, None) == (["default"], {})
        assert _normalize_config(None, {"a": 3}) == (["default"], {"default": {"a": 3}})
        assert _normalize_config(None, {"default": {"a": 3}}) == (
            ["default"],
            {"default": {"a": 3}},
        )

    assert _normalize_config(None, None) == (["default", "dummy_evaluator"], {})
    with pytest.raises(
        ValueError, match="`evaluator_config` argument must be a dictionary mapping each evaluator"
    ):
        assert _normalize_config(None, {"a": 3}) == (["default", "dummy_evaluator"], {})

    assert _normalize_config(None, {"default": {"a": 3}}) == (
        ["default", "dummy_evaluator"],
        {"default": {"a": 3}},
    )

    with mock.patch.object(_base_logger, "warning") as patched_warning_fn:
        _normalize_config(None, None)
        patched_warning_fn.assert_called_once()
        assert "Multiple registered evaluators are found" in patched_warning_fn.call_args[0][0]

    assert _normalize_config("dummy_evaluator", {"a": 3}) == (
        ["dummy_evaluator"],
        {"dummy_evaluator": {"a": 3}},
    )

    assert _normalize_config(["default", "dummy_evaluator"], {"dummy_evaluator": {"a": 3}}) == (
        ["default", "dummy_evaluator"],
        {"dummy_evaluator": {"a": 3}},
    )

    with pytest.raises(
        ValueError, match="evaluator_config must be a dict contains mapping from evaluator name to"
    ):
        _normalize_config(["default", "dummy_evaluator"], {"abc": {"a": 3}})
