import matplotlib.pyplot as plt
from unittest import mock
import numpy as np
import json
import pandas as pd
import pytest
from contextlib import nullcontext as does_not_raise

from mlflow.exceptions import MlflowException
from mlflow.models.evaluation import evaluate
from mlflow.models.evaluation.artifacts import (
    CsvEvaluationArtifact,
    ImageEvaluationArtifact,
    JsonEvaluationArtifact,
    NumpyEvaluationArtifact,
    ParquetEvaluationArtifact,
    TextEvaluationArtifact,
    PickleEvaluationArtifact,
)
from mlflow.models.evaluation.default_evaluator import (
    _get_classifier_global_metrics,
    _infer_model_type_by_labels,
    _extract_raw_model,
    _extract_predict_fn,
    _get_regressor_metrics,
    _get_binary_sum_up_label_pred_prob,
    _get_classifier_per_class_metrics,
    _gen_classifier_curve,
    _evaluate_custom_metric,
    _compute_df_mode_or_mean,
    _CustomMetric,
)
import mlflow
from sklearn.linear_model import LogisticRegression, LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer
from sklearn.datasets import load_iris

from tempfile import TemporaryDirectory
from os.path import join as path_join
from PIL import Image, ImageChops
import io

# pylint: disable=unused-import
from tests.models.test_evaluation import (
    get_run_data,
    linear_regressor_model_uri,
    diabetes_dataset,
    multiclass_logistic_regressor_model_uri,
    iris_dataset,
    binary_logistic_regressor_model_uri,
    breast_cancer_dataset,
    spark_linear_regressor_model_uri,
    diabetes_spark_dataset,
    svm_model_uri,
    pipeline_model_uri,
    get_pipeline_model_dataset,
)
from mlflow.models.utils import plot_lines


def assert_dict_equal(d1, d2, rtol):
    for k in d1:
        assert k in d2
        assert np.isclose(d1[k], d2[k], rtol=rtol)


def test_regressor_evaluation(linear_regressor_model_uri, diabetes_dataset):
    with mlflow.start_run() as run:
        result = evaluate(
            linear_regressor_model_uri,
            diabetes_dataset._constructor_args["data"],
            model_type="regressor",
            targets=diabetes_dataset._constructor_args["targets"],
            dataset_name=diabetes_dataset.name,
            evaluators="default",
        )

    _, metrics, tags, artifacts = get_run_data(run.info.run_id)

    model = mlflow.pyfunc.load_model(linear_regressor_model_uri)

    y = diabetes_dataset.labels_data
    y_pred = model.predict(diabetes_dataset.features_data)

    expected_metrics = _get_regressor_metrics(y, y_pred)
    expected_metrics["score"] = model._model_impl.score(
        diabetes_dataset.features_data, diabetes_dataset.labels_data
    )
    for metric_key in expected_metrics:
        assert np.isclose(
            expected_metrics[metric_key],
            metrics[metric_key + "_on_data_diabetes_dataset"],
            rtol=1e-3,
        )
        assert np.isclose(expected_metrics[metric_key], result.metrics[metric_key], rtol=1e-3)

    assert json.loads(tags["mlflow.datasets"]) == [
        {**diabetes_dataset._metadata, "model": model.metadata.model_uuid}
    ]

    assert set(artifacts) == {
        "shap_beeswarm_plot_on_data_diabetes_dataset.png",
        "shap_feature_importance_plot_on_data_diabetes_dataset.png",
        "shap_summary_plot_on_data_diabetes_dataset.png",
    }
    assert result.artifacts.keys() == {
        "shap_beeswarm_plot",
        "shap_feature_importance_plot",
        "shap_summary_plot",
    }


def test_regressor_evaluation_with_int_targets(
    linear_regressor_model_uri, diabetes_dataset, tmp_path
):
    with mlflow.start_run():
        result = evaluate(
            linear_regressor_model_uri,
            diabetes_dataset._constructor_args["data"],
            model_type="regressor",
            targets=diabetes_dataset._constructor_args["targets"].astype(np.int64),
            dataset_name=diabetes_dataset.name,
            evaluators="default",
        )
        result.save(tmp_path)


def test_multi_classifier_evaluation(multiclass_logistic_regressor_model_uri, iris_dataset):
    with mlflow.start_run() as run:
        result = evaluate(
            multiclass_logistic_regressor_model_uri,
            iris_dataset._constructor_args["data"],
            model_type="classifier",
            targets=iris_dataset._constructor_args["targets"],
            dataset_name=iris_dataset.name,
            evaluators="default",
        )

    _, metrics, tags, artifacts = get_run_data(run.info.run_id)

    model = mlflow.pyfunc.load_model(multiclass_logistic_regressor_model_uri)

    _, raw_model = _extract_raw_model(model)
    predict_fn, predict_proba_fn = _extract_predict_fn(model, raw_model)
    y = iris_dataset.labels_data
    y_pred = predict_fn(iris_dataset.features_data)
    y_probs = predict_proba_fn(iris_dataset.features_data)

    expected_metrics = _get_classifier_global_metrics(False, y, y_pred, y_probs, labels=None)
    expected_metrics["score"] = model._model_impl.score(
        iris_dataset.features_data, iris_dataset.labels_data
    )
    for metric_key in expected_metrics:
        assert np.isclose(
            expected_metrics[metric_key], metrics[metric_key + "_on_data_iris_dataset"], rtol=1e-3
        )
        assert np.isclose(expected_metrics[metric_key], result.metrics[metric_key], rtol=1e-3)

    assert json.loads(tags["mlflow.datasets"]) == [
        {**iris_dataset._metadata, "model": model.metadata.model_uuid}
    ]

    assert set(artifacts) == {
        "shap_beeswarm_plot_on_data_iris_dataset.png",
        "per_class_metrics_on_data_iris_dataset.csv",
        "roc_curve_plot_on_data_iris_dataset.png",
        "precision_recall_curve_plot_on_data_iris_dataset.png",
        "shap_feature_importance_plot_on_data_iris_dataset.png",
        "explainer_on_data_iris_dataset",
        "confusion_matrix_on_data_iris_dataset.png",
        "shap_summary_plot_on_data_iris_dataset.png",
    }
    assert result.artifacts.keys() == {
        "per_class_metrics",
        "roc_curve_plot",
        "precision_recall_curve_plot",
        "confusion_matrix",
        "shap_beeswarm_plot",
        "shap_summary_plot",
        "shap_feature_importance_plot",
    }


def test_bin_classifier_evaluation(binary_logistic_regressor_model_uri, breast_cancer_dataset):
    with mlflow.start_run() as run:
        result = evaluate(
            binary_logistic_regressor_model_uri,
            breast_cancer_dataset._constructor_args["data"],
            model_type="classifier",
            targets=breast_cancer_dataset._constructor_args["targets"],
            dataset_name=breast_cancer_dataset.name,
            evaluators="default",
        )

    _, metrics, tags, artifacts = get_run_data(run.info.run_id)

    model = mlflow.pyfunc.load_model(binary_logistic_regressor_model_uri)

    _, raw_model = _extract_raw_model(model)
    predict_fn, predict_proba_fn = _extract_predict_fn(model, raw_model)
    y = breast_cancer_dataset.labels_data
    y_pred = predict_fn(breast_cancer_dataset.features_data)
    y_probs = predict_proba_fn(breast_cancer_dataset.features_data)

    expected_metrics = _get_classifier_global_metrics(True, y, y_pred, y_probs, labels=None)
    expected_metrics["score"] = model._model_impl.score(
        breast_cancer_dataset.features_data, breast_cancer_dataset.labels_data
    )
    for metric_key in expected_metrics:
        assert np.isclose(
            expected_metrics[metric_key],
            metrics[metric_key + "_on_data_breast_cancer_dataset"],
            rtol=1e-3,
        )
        assert np.isclose(expected_metrics[metric_key], result.metrics[metric_key], rtol=1e-3)

    assert json.loads(tags["mlflow.datasets"]) == [
        {**breast_cancer_dataset._metadata, "model": model.metadata.model_uuid}
    ]

    assert set(artifacts) == {
        "shap_feature_importance_plot_on_data_breast_cancer_dataset.png",
        "lift_curve_plot_on_data_breast_cancer_dataset.png",
        "shap_beeswarm_plot_on_data_breast_cancer_dataset.png",
        "precision_recall_curve_plot_on_data_breast_cancer_dataset.png",
        "confusion_matrix_on_data_breast_cancer_dataset.png",
        "shap_summary_plot_on_data_breast_cancer_dataset.png",
        "roc_curve_plot_on_data_breast_cancer_dataset.png",
    }
    assert result.artifacts.keys() == {
        "roc_curve_plot",
        "precision_recall_curve_plot",
        "lift_curve_plot",
        "confusion_matrix",
        "shap_beeswarm_plot",
        "shap_summary_plot",
        "shap_feature_importance_plot",
    }


def test_spark_regressor_model_evaluation(spark_linear_regressor_model_uri, diabetes_spark_dataset):
    with mlflow.start_run() as run:
        result = evaluate(
            spark_linear_regressor_model_uri,
            diabetes_spark_dataset._constructor_args["data"],
            model_type="regressor",
            targets=diabetes_spark_dataset._constructor_args["targets"],
            dataset_name=diabetes_spark_dataset.name,
            evaluators="default",
            evaluator_config={"log_model_explainability": True},
        )

    _, metrics, tags, artifacts = get_run_data(run.info.run_id)

    model = mlflow.pyfunc.load_model(spark_linear_regressor_model_uri)

    X = diabetes_spark_dataset.features_data
    y = diabetes_spark_dataset.labels_data
    y_pred = model.predict(X)

    expected_metrics = _get_regressor_metrics(y, y_pred)

    for metric_key in expected_metrics:
        assert np.isclose(
            expected_metrics[metric_key],
            metrics[metric_key + "_on_data_diabetes_spark_dataset"],
            rtol=1e-3,
        )
        assert np.isclose(expected_metrics[metric_key], result.metrics[metric_key], rtol=1e-3)

    model = mlflow.pyfunc.load_model(spark_linear_regressor_model_uri)

    assert json.loads(tags["mlflow.datasets"]) == [
        {**diabetes_spark_dataset._metadata, "model": model.metadata.model_uuid}
    ]

    assert set(artifacts) == set()
    assert result.artifacts == {}


def test_svm_classifier_evaluation(svm_model_uri, breast_cancer_dataset):
    with mlflow.start_run() as run:
        result = evaluate(
            svm_model_uri,
            breast_cancer_dataset._constructor_args["data"],
            model_type="classifier",
            targets=breast_cancer_dataset._constructor_args["targets"],
            dataset_name=breast_cancer_dataset.name,
            evaluators="default",
        )

    _, metrics, tags, artifacts = get_run_data(run.info.run_id)

    model = mlflow.pyfunc.load_model(svm_model_uri)

    _, raw_model = _extract_raw_model(model)
    predict_fn, _ = _extract_predict_fn(model, raw_model)
    y = breast_cancer_dataset.labels_data
    y_pred = predict_fn(breast_cancer_dataset.features_data)

    expected_metrics = _get_classifier_global_metrics(True, y, y_pred, None, labels=None)
    expected_metrics["score"] = model._model_impl.score(
        breast_cancer_dataset.features_data, breast_cancer_dataset.labels_data
    )
    for metric_key in expected_metrics:
        assert np.isclose(
            expected_metrics[metric_key],
            metrics[metric_key + "_on_data_breast_cancer_dataset"],
            rtol=1e-3,
        )
        assert np.isclose(expected_metrics[metric_key], result.metrics[metric_key], rtol=1e-3)

    assert json.loads(tags["mlflow.datasets"]) == [
        {**breast_cancer_dataset._metadata, "model": model.metadata.model_uuid}
    ]

    assert set(artifacts) == {
        "confusion_matrix_on_data_breast_cancer_dataset.png",
        "shap_feature_importance_plot_on_data_breast_cancer_dataset.png",
        "shap_beeswarm_plot_on_data_breast_cancer_dataset.png",
        "shap_summary_plot_on_data_breast_cancer_dataset.png",
    }
    assert result.artifacts.keys() == {
        "confusion_matrix",
        "shap_beeswarm_plot",
        "shap_summary_plot",
        "shap_feature_importance_plot",
    }


def test_pipeline_model_kernel_explainer_on_categorical_features(pipeline_model_uri):
    from mlflow.models.evaluation._shap_patch import _PatchedKernelExplainer

    data, target_col = get_pipeline_model_dataset()
    with mlflow.start_run() as run:
        evaluate(
            pipeline_model_uri,
            data[0::3],
            model_type="classifier",
            targets=target_col,
            dataset_name="pipeline_model_dataset",
            evaluators="default",
            evaluator_config={"explainability_algorithm": "kernel"},
        )
    run_data = get_run_data(run.info.run_id)
    assert {
        "shap_beeswarm_plot_on_data_pipeline_model_dataset.png",
        "shap_feature_importance_plot_on_data_pipeline_model_dataset.png",
        "shap_summary_plot_on_data_pipeline_model_dataset.png",
        "explainer_on_data_pipeline_model_dataset",
    }.issubset(run_data.artifacts)

    explainer = mlflow.shap.load_explainer(
        f"runs:/{run.info.run_id}/explainer_on_data_pipeline_model_dataset"
    )
    assert isinstance(explainer, _PatchedKernelExplainer)


def test_compute_df_mode_or_mean():
    df = pd.DataFrame(
        {
            "a": [2.0, 2.0, 5.0],
            "b": [3, 3, 5],
            "c": [2.0, 2.0, 6.5],
            "d": [True, False, True],
            "e": ["abc", "b", "abc"],
            "f": [1.5, 2.5, np.nan],
            "g": ["ab", "ab", None],
            "h": pd.Series([2.0, 2.0, 6.5], dtype="category"),
        }
    )
    result = _compute_df_mode_or_mean(df)
    assert result == {
        "a": 2,
        "b": 3,
        "c": 3.5,
        "d": True,
        "e": "abc",
        "f": 2.0,
        "g": "ab",
        "h": 2.0,
    }

    # Test on dataframe that all columns are continuous.
    df2 = pd.DataFrame(
        {
            "c": [2.0, 2.0, 6.5],
            "f": [1.5, 2.5, np.nan],
        }
    )
    assert _compute_df_mode_or_mean(df2) == {"c": 3.5, "f": 2.0}

    # Test on dataframe that all columns are not continuous.
    df2 = pd.DataFrame(
        {
            "d": [True, False, True],
            "g": ["ab", "ab", None],
        }
    )
    assert _compute_df_mode_or_mean(df2) == {"d": True, "g": "ab"}


def test_infer_model_type_by_labels():
    assert _infer_model_type_by_labels(["a", "b"]) == "classifier"
    assert _infer_model_type_by_labels([True, False]) == "classifier"
    assert _infer_model_type_by_labels([1, 2.5]) == "regressor"
    assert _infer_model_type_by_labels(pd.Series(["a", "b"], dtype="category")) == "classifier"
    assert _infer_model_type_by_labels(pd.Series([1.5, 2.5], dtype="category")) == "classifier"
    assert _infer_model_type_by_labels([1, 2, 3]) is None


def test_extract_raw_model_and_predict_fn(
    binary_logistic_regressor_model_uri, breast_cancer_dataset
):
    model = mlflow.pyfunc.load_model(binary_logistic_regressor_model_uri)

    model_loader_module, raw_model = _extract_raw_model(model)
    predict_fn, predict_proba_fn = _extract_predict_fn(model, raw_model)

    assert model_loader_module == "mlflow.sklearn"
    assert isinstance(raw_model, LogisticRegression)
    assert np.allclose(
        predict_fn(breast_cancer_dataset.features_data),
        raw_model.predict(breast_cancer_dataset.features_data),
    )
    assert np.allclose(
        predict_proba_fn(breast_cancer_dataset.features_data),
        raw_model.predict_proba(breast_cancer_dataset.features_data),
    )


def test_get_regressor_metrics():
    y = [1.1, 2.1, -3.5]
    y_pred = [1.5, 2.0, -3.0]

    metrics = _get_regressor_metrics(y, y_pred)
    expected_metrics = {
        "example_count": 3,
        "mean_absolute_error": 0.3333333333333333,
        "mean_squared_error": 0.13999999999999999,
        "root_mean_squared_error": 0.3741657386773941,
        "sum_on_label": -0.2999999999999998,
        "mean_on_label": -0.09999999999999994,
        "r2_score": 0.976457399103139,
        "max_error": 0.5,
        "mean_absolute_percentage_error": 0.18470418470418468,
    }
    assert_dict_equal(metrics, expected_metrics, rtol=1e-3)


def test_get_binary_sum_up_label_pred_prob():
    y = [0, 1, 2]
    y_pred = [0, 2, 1]
    y_probs = [[0.7, 0.1, 0.2], [0.2, 0.3, 0.5], [0.25, 0.4, 0.35]]

    results = []
    for idx, label in enumerate([0, 1, 2]):
        y_bin, y_pred_bin, y_prob_bin = _get_binary_sum_up_label_pred_prob(
            idx, label, y, y_pred, y_probs
        )
        results.append((list(y_bin), list(y_pred_bin), list(y_prob_bin)))

    assert results == [
        ([1, 0, 0], [1, 0, 0], [0.7, 0.2, 0.25]),
        ([0, 1, 0], [0, 0, 1], [0.1, 0.3, 0.4]),
        ([0, 0, 1], [0, 1, 0], [0.2, 0.5, 0.35]),
    ]


def test_get_classifier_per_class_metrics():
    y = [0, 1, 0, 1, 0, 1, 0, 1, 1, 0]
    y_pred = [0, 1, 1, 0, 1, 1, 0, 1, 1, 0]

    expected_metrics = {
        "true_negatives": 3,
        "false_positives": 2,
        "false_negatives": 1,
        "true_positives": 4,
        "recall": 0.8,
        "precision": 0.6666666666666666,
        "f1_score": 0.7272727272727272,
    }
    metrics = _get_classifier_per_class_metrics(y, y_pred)
    assert_dict_equal(metrics, expected_metrics, rtol=1e-3)


def test_multiclass_get_classifier_global_metrics():
    y = [0, 1, 2, 1, 2]
    y_pred = [0, 2, 1, 1, 0]
    y_probs = [
        [0.7, 0.1, 0.2],
        [0.2, 0.3, 0.5],
        [0.25, 0.4, 0.35],
        [0.3, 0.4, 0.3],
        [0.8, 0.1, 0.1],
    ]

    metrics = _get_classifier_global_metrics(
        is_binomial=False, y=y, y_pred=y_pred, y_probs=y_probs, labels=[0, 1, 2]
    )
    expected_metrics = {
        "accuracy": 0.4,
        "example_count": 5,
        "f1_score_micro": 0.4,
        "f1_score_macro": 0.38888888888888884,
        "log_loss": 1.1658691395263094,
    }
    assert_dict_equal(metrics, expected_metrics, 1e-3)


def test_binary_get_classifier_global_metrics():
    y = [0, 1, 0, 1, 0, 1, 0, 1, 1, 0]
    y_pred = [0, 1, 1, 0, 1, 1, 0, 1, 1, 0]
    y_prob = [0.1, 0.9, 0.8, 0.2, 0.7, 0.8, 0.3, 0.6, 0.65, 0.4]
    y_probs = [[1 - p, p] for p in y_prob]
    metrics = _get_classifier_global_metrics(
        is_binomial=True, y=y, y_pred=y_pred, y_probs=y_probs, labels=[0, 1]
    )
    expected_metrics = {"accuracy": 0.7, "example_count": 10, "log_loss": 0.6665822319387167}
    assert_dict_equal(metrics, expected_metrics, 1e-3)


def test_gen_binary_precision_recall_curve():
    y = [0, 1, 0, 1, 0, 1, 0, 1, 1, 0]
    y_prob = [0.1, 0.9, 0.8, 0.2, 0.7, 0.8, 0.3, 0.6, 0.65, 0.4]

    results = _gen_classifier_curve(
        is_binomial=True, y=y, y_probs=y_prob, labels=[0, 1], curve_type="pr"
    )
    assert np.allclose(
        results.plot_fn_args["data_series"][0][1],
        np.array([1.0, 0.8, 0.8, 0.8, 0.6, 0.4, 0.4, 0.2, 0.0]),
        rtol=1e-3,
    )
    assert np.allclose(
        results.plot_fn_args["data_series"][0][2],
        np.array([0.55555556, 0.5, 0.57142857, 0.66666667, 0.6, 0.5, 0.66666667, 1.0, 1.0]),
        rtol=1e-3,
    )
    assert results.plot_fn_args["xlabel"] == "recall"
    assert results.plot_fn_args["ylabel"] == "precision"
    assert results.plot_fn_args["line_kwargs"] == {"drawstyle": "steps-post", "linewidth": 1}
    assert np.isclose(results.auc, 0.7088888888888889, rtol=1e-3)


def test_gen_binary_roc_curve():
    y = [0, 1, 0, 1, 0, 1, 0, 1, 1, 0]
    y_prob = [0.1, 0.9, 0.8, 0.2, 0.7, 0.8, 0.3, 0.6, 0.65, 0.4]

    results = _gen_classifier_curve(
        is_binomial=True, y=y, y_probs=y_prob, labels=[0, 1], curve_type="roc"
    )
    assert np.allclose(
        results.plot_fn_args["data_series"][0][1],
        np.array([0.0, 0.0, 0.2, 0.4, 0.4, 0.8, 0.8, 1.0]),
        rtol=1e-3,
    )
    assert np.allclose(
        results.plot_fn_args["data_series"][0][2],
        np.array([0.0, 0.2, 0.4, 0.4, 0.8, 0.8, 1.0, 1.0]),
        rtol=1e-3,
    )
    assert results.plot_fn_args["xlabel"] == "False Positive Rate"
    assert results.plot_fn_args["ylabel"] == "True Positive Rate"
    assert results.plot_fn_args["line_kwargs"] == {"drawstyle": "steps-post", "linewidth": 1}
    assert np.isclose(results.auc, 0.66, rtol=1e-3)


def test_gen_multiclass_precision_recall_curve():
    y = [0, 1, 2, 1, 2]
    y_probs = [
        [0.7, 0.1, 0.2],
        [0.2, 0.3, 0.5],
        [0.25, 0.4, 0.35],
        [0.3, 0.4, 0.3],
        [0.8, 0.1, 0.1],
    ]

    results = _gen_classifier_curve(
        is_binomial=False, y=y, y_probs=y_probs, labels=[0, 1, 2], curve_type="pr"
    )
    expected_x_data_list = [[1.0, 0.0, 0.0], [1.0, 0.5, 0.0], [1.0, 0.5, 0.5, 0.5, 0.0, 0.0]]
    expected_y_data_list = [
        [0.5, 0.0, 1.0],
        [0.66666667, 0.5, 1.0],
        [0.4, 0.25, 0.33333333, 0.5, 0.0, 1.0],
    ]
    line_labels = ["label=0,AP=0.500", "label=1,AP=0.722", "label=2,AP=0.414"]
    for index, (name, x_data, y_data) in enumerate(results.plot_fn_args["data_series"]):
        assert name == line_labels[index]
        assert np.allclose(x_data, expected_x_data_list[index], rtol=1e-3)
        assert np.allclose(y_data, expected_y_data_list[index], rtol=1e-3)

    assert results.plot_fn_args["xlabel"] == "recall"
    assert results.plot_fn_args["ylabel"] == "precision"
    assert results.plot_fn_args["line_kwargs"] == {"drawstyle": "steps-post", "linewidth": 1}

    expected_auc = [0.25, 0.6666666666666666, 0.2875]
    assert np.allclose(results.auc, expected_auc, rtol=1e-3)


def test_gen_multiclass_roc_curve():
    y = [0, 1, 2, 1, 2]
    y_probs = [
        [0.7, 0.1, 0.2],
        [0.2, 0.3, 0.5],
        [0.25, 0.4, 0.35],
        [0.3, 0.4, 0.3],
        [0.8, 0.1, 0.1],
    ]

    results = _gen_classifier_curve(
        is_binomial=False, y=y, y_probs=y_probs, labels=[0, 1, 2], curve_type="roc"
    )

    expected_x_data_list = [
        [0.0, 0.25, 0.25, 1.0],
        [0.0, 0.33333333, 0.33333333, 1.0],
        [0.0, 0.33333333, 0.33333333, 1.0, 1.0],
    ]
    expected_y_data_list = [[0.0, 0.0, 1.0, 1.0], [0.0, 0.5, 1.0, 1.0], [0.0, 0.0, 0.5, 0.5, 1.0]]
    line_labels = ["label=0,AUC=0.750", "label=1,AUC=0.750", "label=2,AUC=0.333"]
    for index, (name, x_data, y_data) in enumerate(results.plot_fn_args["data_series"]):
        assert name == line_labels[index]
        assert np.allclose(x_data, expected_x_data_list[index], rtol=1e-3)
        assert np.allclose(y_data, expected_y_data_list[index], rtol=1e-3)

    assert results.plot_fn_args["xlabel"] == "False Positive Rate"
    assert results.plot_fn_args["ylabel"] == "True Positive Rate"
    assert results.plot_fn_args["line_kwargs"] == {"drawstyle": "steps-post", "linewidth": 1}

    expected_auc = [0.75, 0.75, 0.3333]
    assert np.allclose(results.auc, expected_auc, rtol=1e-3)


def test_evaluate_custom_metric_incorrect_return_formats():
    eval_df = pd.DataFrame({"prediction": [1.2, 1.9, 3.2], "target": [1, 2, 3]})
    metrics = _get_regressor_metrics(eval_df["target"], eval_df["prediction"])

    def dummy_fn(*_):
        pass

    with pytest.raises(
        MlflowException,
        match=f"'{dummy_fn.__name__}' (.*) returned None",
    ):
        _evaluate_custom_metric(_CustomMetric(dummy_fn, "dummy_fn", 0, ""), eval_df, metrics)

    def incorrect_return_type_1(*_):
        return 3

    def incorrect_return_type_2(*_):
        return "stuff", 3

    for test_fn in (
        incorrect_return_type_1,
        incorrect_return_type_2,
    ):
        with pytest.raises(
            MlflowException,
            match=f"'{test_fn.__name__}' (.*) did not return in an expected format",
        ):
            _evaluate_custom_metric(
                _CustomMetric(test_fn, test_fn.__name__, 0, ""), eval_df, metrics
            )

    def non_str_metric_name(*_):
        return {123: 123, "a": 32.1, "b": 3}

    def non_numerical_metric_value(*_):
        return {"stuff": 12, "non_numerical_metric": "123"}

    for test_fn in (
        non_str_metric_name,
        non_numerical_metric_value,
    ):
        with pytest.raises(
            MlflowException,
            match=f"'{test_fn.__name__}' (.*) did not return metrics as a dictionary of "
            "string metric names with numerical values",
        ):
            _evaluate_custom_metric(
                _CustomMetric(test_fn, test_fn.__name__, 0, ""), eval_df, metrics
            )

    def non_str_artifact_name(*_):
        return {"a": 32.1, "b": 3}, {1: [1, 2, 3]}

    with pytest.raises(
        MlflowException,
        match=f"'{non_str_artifact_name.__name__}' (.*) did not return artifacts as a "
        "dictionary of string artifact names with their corresponding objects",
    ):
        _evaluate_custom_metric(
            _CustomMetric(non_str_artifact_name, non_str_artifact_name.__name__, 0, ""),
            eval_df,
            metrics,
        )


@pytest.mark.parametrize(
    "fn, expectation",
    [
        (lambda eval_df, _: {"pred_sum": sum(eval_df["prediction"])}, does_not_raise()),
        (lambda eval_df, builtin_metrics: ({"test": 1.1}, {"a_list": [1, 2, 3]}), does_not_raise()),
        (
            lambda _, __: 3,
            pytest.raises(
                MlflowException,
                match="'<lambda>' (.*) did not return in an expected format",
            ),
        ),
    ],
)
def test_evaluate_custom_metric_lambda(fn, expectation):
    eval_df = pd.DataFrame({"prediction": [1.2, 1.9, 3.2], "target": [1, 2, 3]})
    metrics = _get_regressor_metrics(eval_df["target"], eval_df["prediction"])
    with expectation:
        _evaluate_custom_metric(_CustomMetric(fn, "<lambda>", 0, ""), eval_df, metrics)


def test_evaluate_custom_metric_success():
    eval_df = pd.DataFrame({"prediction": [1.2, 1.9, 3.2], "target": [1, 2, 3]})
    metrics = _get_regressor_metrics(eval_df["target"], eval_df["prediction"])

    def example_custom_metric(_, given_metrics):
        return {
            "example_count_times_1_point_5": given_metrics["example_count"] * 1.5,
            "sum_on_label_minus_5": given_metrics["sum_on_label"] - 5,
            "example_np_metric_1": np.float32(123.2),
            "example_np_metric_2": np.ulonglong(10000000),
        }

    res_metrics, res_artifacts = _evaluate_custom_metric(
        _CustomMetric(example_custom_metric, "", 0, ""), eval_df, metrics
    )
    assert res_metrics == {
        "example_count_times_1_point_5": metrics["example_count"] * 1.5,
        "sum_on_label_minus_5": metrics["sum_on_label"] - 5,
        "example_np_metric_1": np.float32(123.2),
        "example_np_metric_2": np.ulonglong(10000000),
    }
    assert res_artifacts is None

    def example_custom_metric_with_artifacts(given_df, given_metrics):
        return (
            {
                "example_count_times_1_point_5": given_metrics["example_count"] * 1.5,
                "sum_on_label_minus_5": given_metrics["sum_on_label"] - 5,
                "example_np_metric_1": np.float32(123.2),
                "example_np_metric_2": np.ulonglong(10000000),
            },
            {
                "pred_target_abs_diff": np.abs(given_df["prediction"] - given_df["target"]),
                "example_dictionary_artifact": {"a": 1, "b": 2},
            },
        )

    res_metrics_2, res_artifacts_2 = _evaluate_custom_metric(
        _CustomMetric(example_custom_metric_with_artifacts, "", 0, ""), eval_df, metrics
    )
    assert res_metrics_2 == {
        "example_count_times_1_point_5": metrics["example_count"] * 1.5,
        "sum_on_label_minus_5": metrics["sum_on_label"] - 5,
        "example_np_metric_1": np.float32(123.2),
        "example_np_metric_2": np.ulonglong(10000000),
    }

    # pylint: disable=unsupported-membership-test
    assert isinstance(res_artifacts_2, dict)
    assert "pred_target_abs_diff" in res_artifacts_2
    pd.testing.assert_series_equal(
        res_artifacts_2["pred_target_abs_diff"], np.abs(eval_df["prediction"] - eval_df["target"])
    )

    assert "example_dictionary_artifact" in res_artifacts_2
    assert res_artifacts_2["example_dictionary_artifact"] == {"a": 1, "b": 2}


def _get_results_for_custom_metrics_tests(model_uri, dataset, custom_metrics):
    with mlflow.start_run() as run:
        result = evaluate(
            model_uri,
            dataset._constructor_args["data"],
            model_type="classifier",
            targets=dataset._constructor_args["targets"],
            dataset_name=dataset.name,
            evaluators="default",
            custom_metrics=custom_metrics,
        )
    _, metrics, _, artifacts = get_run_data(run.info.run_id)
    return result, metrics, artifacts


def test_custom_metric_produced_multiple_artifacts_with_same_name_throw_exception(
    binary_logistic_regressor_model_uri, breast_cancer_dataset
):
    def example_custom_metric_1(_, __):
        return {}, {"test_json_artifact": {"a": 2, "b": [1, 2]}}

    def example_custom_metric_2(_, __):
        return {}, {"test_json_artifact": {"a": 3, "b": [1, 2]}}

    with pytest.raises(
        MlflowException,
        match="cannot be logged because there already exists an artifact with the same name",
    ):
        _get_results_for_custom_metrics_tests(
            binary_logistic_regressor_model_uri,
            breast_cancer_dataset,
            [example_custom_metric_1, example_custom_metric_2],
        )


def test_custom_metric_mixed(binary_logistic_regressor_model_uri, breast_cancer_dataset):
    def example_custom_metric(eval_df, given_metrics, tmp_path):
        example_metrics = {
            "true_count": given_metrics["true_negatives"] + given_metrics["true_positives"],
            "positive_count": np.sum(eval_df["prediction"]),
        }
        df = pd.DataFrame({"a": [1, 2, 3]})
        df.to_csv(path_join(tmp_path, "user_logged_df.csv"), index=False)
        np_array = np.array([1, 2, 3, 4, 5])
        np.save(path_join(tmp_path, "arr.npy"), np_array)

        example_artifacts = {
            "test_json_artifact": {"a": 3, "b": [1, 2]},
            "test_npy_artifact": path_join(tmp_path, "arr.npy"),
        }
        return example_metrics, example_artifacts

    result, metrics, artifacts = _get_results_for_custom_metrics_tests(
        binary_logistic_regressor_model_uri, breast_cancer_dataset, [example_custom_metric]
    )

    model = mlflow.pyfunc.load_model(binary_logistic_regressor_model_uri)

    _, raw_model = _extract_raw_model(model)
    predict_fn, _ = _extract_predict_fn(model, raw_model)
    y = breast_cancer_dataset.labels_data
    y_pred = predict_fn(breast_cancer_dataset.features_data)

    expected_metrics = _get_classifier_per_class_metrics(y, y_pred)

    assert "true_count_on_data_breast_cancer_dataset" in metrics
    assert np.isclose(
        metrics["true_count_on_data_breast_cancer_dataset"],
        expected_metrics["true_negatives"] + expected_metrics["true_positives"],
        rtol=1e-3,
    )
    assert "true_count" in result.metrics
    assert np.isclose(
        result.metrics["true_count"],
        expected_metrics["true_negatives"] + expected_metrics["true_positives"],
        rtol=1e-3,
    )

    assert "positive_count_on_data_breast_cancer_dataset" in metrics
    assert np.isclose(
        metrics["positive_count_on_data_breast_cancer_dataset"], np.sum(y_pred), rtol=1e-3
    )
    assert "positive_count" in result.metrics
    assert np.isclose(result.metrics["positive_count"], np.sum(y_pred), rtol=1e-3)

    assert "test_json_artifact" in result.artifacts
    assert "test_json_artifact_on_data_breast_cancer_dataset.json" in artifacts
    assert isinstance(result.artifacts["test_json_artifact"], JsonEvaluationArtifact)
    assert result.artifacts["test_json_artifact"].content == {"a": 3, "b": [1, 2]}

    assert "test_npy_artifact" in result.artifacts
    assert "test_npy_artifact_on_data_breast_cancer_dataset.npy" in artifacts
    assert isinstance(result.artifacts["test_npy_artifact"], NumpyEvaluationArtifact)
    assert np.array_equal(result.artifacts["test_npy_artifact"].content, np.array([1, 2, 3, 4, 5]))


def test_custom_metric_logs_artifacts_from_paths(
    binary_logistic_regressor_model_uri, breast_cancer_dataset
):
    fig_x = 8.0
    fig_y = 5.0
    fig_dpi = 100.0
    img_formats = ("png", "jpeg", "jpg")

    def example_custom_metric(_, __, tmp_path):
        example_artifacts = {}

        # images
        for ext in img_formats:
            fig = plt.figure(figsize=(fig_x, fig_y), dpi=fig_dpi)
            plt.plot([1, 2, 3])
            fig.savefig(path_join(tmp_path, f"test.{ext}"), format=ext)
            plt.clf()
            example_artifacts[f"test_{ext}_artifact"] = path_join(tmp_path, f"test.{ext}")

        # json
        with open(path_join(tmp_path, "test.json"), "w") as f:
            json.dump([1, 2, 3], f)
        example_artifacts["test_json_artifact"] = path_join(tmp_path, "test.json")

        # numpy
        np_array = np.array([1, 2, 3, 4, 5])
        np.save(path_join(tmp_path, "test.npy"), np_array)
        example_artifacts["test_npy_artifact"] = path_join(tmp_path, "test.npy")

        # csv
        df = pd.DataFrame({"a": [1, 2, 3]})
        df.to_csv(path_join(tmp_path, "test.csv"), index=False)
        example_artifacts["test_csv_artifact"] = path_join(tmp_path, "test.csv")

        # parquet
        df = pd.DataFrame({"test": [1, 2, 3]})
        df.to_parquet(path_join(tmp_path, "test.parquet"))
        example_artifacts["test_parquet_artifact"] = path_join(tmp_path, "test.parquet")

        # text
        with open(path_join(tmp_path, "test.txt"), "w") as f:
            f.write("hello world")
        example_artifacts["test_text_artifact"] = path_join(tmp_path, "test.txt")

        return {}, example_artifacts

    result, _, artifacts = _get_results_for_custom_metrics_tests(
        binary_logistic_regressor_model_uri, breast_cancer_dataset, [example_custom_metric]
    )

    with TemporaryDirectory() as tmp_dir:
        for img_ext in img_formats:
            assert f"test_{img_ext}_artifact" in result.artifacts
            assert f"test_{img_ext}_artifact_on_data_breast_cancer_dataset.{img_ext}" in artifacts
            assert isinstance(result.artifacts[f"test_{img_ext}_artifact"], ImageEvaluationArtifact)

            fig = plt.figure(figsize=(fig_x, fig_y), dpi=fig_dpi)
            plt.plot([1, 2, 3])
            fig.savefig(path_join(tmp_dir, f"test.{img_ext}"), format=img_ext)
            plt.clf()

            saved_img = Image.open(path_join(tmp_dir, f"test.{img_ext}"))
            result_img = result.artifacts[f"test_{img_ext}_artifact"].content

            for img in (saved_img, result_img):
                img_ext_qualified = "jpeg" if img_ext == "jpg" else img_ext
                assert img.format.lower() == img_ext_qualified
                assert img.size == (fig_x * fig_dpi, fig_y * fig_dpi)
                assert (fig_dpi, fig_dpi) == pytest.approx(img.info.get("dpi"), 0.001)

    assert "test_json_artifact" in result.artifacts
    assert "test_json_artifact_on_data_breast_cancer_dataset.json" in artifacts
    assert isinstance(result.artifacts["test_json_artifact"], JsonEvaluationArtifact)
    assert result.artifacts["test_json_artifact"].content == [1, 2, 3]

    assert "test_npy_artifact" in result.artifacts
    assert "test_npy_artifact_on_data_breast_cancer_dataset.npy" in artifacts
    assert isinstance(result.artifacts["test_npy_artifact"], NumpyEvaluationArtifact)
    assert np.array_equal(result.artifacts["test_npy_artifact"].content, np.array([1, 2, 3, 4, 5]))

    assert "test_csv_artifact" in result.artifacts
    assert "test_csv_artifact_on_data_breast_cancer_dataset.csv" in artifacts
    assert isinstance(result.artifacts["test_csv_artifact"], CsvEvaluationArtifact)
    pd.testing.assert_frame_equal(
        result.artifacts["test_csv_artifact"].content, pd.DataFrame({"a": [1, 2, 3]})
    )

    assert "test_parquet_artifact" in result.artifacts
    assert "test_parquet_artifact_on_data_breast_cancer_dataset.parquet" in artifacts
    assert isinstance(result.artifacts["test_parquet_artifact"], ParquetEvaluationArtifact)
    pd.testing.assert_frame_equal(
        result.artifacts["test_parquet_artifact"].content, pd.DataFrame({"test": [1, 2, 3]})
    )

    assert "test_text_artifact" in result.artifacts
    assert "test_text_artifact_on_data_breast_cancer_dataset.txt" in artifacts
    assert isinstance(result.artifacts["test_text_artifact"], TextEvaluationArtifact)
    assert result.artifacts["test_text_artifact"].content == "hello world"


class _ExampleToBePickledObject:
    def __init__(self):
        self.a = [1, 2, 3]
        self.b = "hello"

    def __eq__(self, o: object) -> bool:
        return self.a == o.a and self.b == self.b


def test_custom_metric_logs_artifacts_from_objects(
    binary_logistic_regressor_model_uri, breast_cancer_dataset
):
    fig = plt.figure()
    plt.plot([1, 2, 3])
    buf = io.BytesIO()
    fig.savefig(buf)
    buf.seek(0)
    img = Image.open(buf)

    def example_custom_metric(_, __):
        return {}, {
            "test_image_artifact": fig,
            "test_json_artifact": {
                "list": [1, 2, 3],
                "numpy_int": np.int64(0),
                "numpy_float": np.float64(0.5),
            },
            "test_npy_artifact": np.array([1, 2, 3, 4, 5]),
            "test_csv_artifact": pd.DataFrame({"a": [1, 2, 3]}),
            "test_json_text_artifact": '{"a": [1, 2, 3], "c": 3.4}',
            "test_pickled_artifact": _ExampleToBePickledObject(),
        }

    result, _, artifacts = _get_results_for_custom_metrics_tests(
        binary_logistic_regressor_model_uri, breast_cancer_dataset, [example_custom_metric]
    )

    assert "test_image_artifact" in result.artifacts
    assert "test_image_artifact_on_data_breast_cancer_dataset.png" in artifacts
    assert isinstance(result.artifacts["test_image_artifact"], ImageEvaluationArtifact)
    img_diff = ImageChops.difference(result.artifacts["test_image_artifact"].content, img).getbbox()
    assert img_diff is None

    assert "test_json_artifact" in result.artifacts
    assert "test_json_artifact_on_data_breast_cancer_dataset.json" in artifacts
    assert isinstance(result.artifacts["test_json_artifact"], JsonEvaluationArtifact)
    assert result.artifacts["test_json_artifact"].content == {
        "list": [1, 2, 3],
        "numpy_int": 0,
        "numpy_float": 0.5,
    }

    assert "test_npy_artifact" in result.artifacts
    assert "test_npy_artifact_on_data_breast_cancer_dataset.npy" in artifacts
    assert isinstance(result.artifacts["test_npy_artifact"], NumpyEvaluationArtifact)
    assert np.array_equal(result.artifacts["test_npy_artifact"].content, np.array([1, 2, 3, 4, 5]))

    assert "test_csv_artifact" in result.artifacts
    assert "test_csv_artifact_on_data_breast_cancer_dataset.csv" in artifacts
    assert isinstance(result.artifacts["test_csv_artifact"], CsvEvaluationArtifact)
    pd.testing.assert_frame_equal(
        result.artifacts["test_csv_artifact"].content, pd.DataFrame({"a": [1, 2, 3]})
    )

    assert "test_json_text_artifact" in result.artifacts
    assert "test_json_text_artifact_on_data_breast_cancer_dataset.json" in artifacts
    assert isinstance(result.artifacts["test_json_text_artifact"], JsonEvaluationArtifact)
    assert result.artifacts["test_json_text_artifact"].content == {"a": [1, 2, 3], "c": 3.4}

    assert "test_pickled_artifact" in result.artifacts
    assert "test_pickled_artifact_on_data_breast_cancer_dataset.pickle" in artifacts
    assert isinstance(result.artifacts["test_pickled_artifact"], PickleEvaluationArtifact)
    assert result.artifacts["test_pickled_artifact"].content == _ExampleToBePickledObject()


def test_evaluate_sklearn_model_score_skip_when_not_scorable(
    linear_regressor_model_uri, diabetes_dataset
):
    with mock.patch(
        "sklearn.linear_model.LinearRegression.score",
        side_effect=RuntimeError("LinearRegression.score failed"),
    ) as mock_score:
        with mlflow.start_run():
            result = evaluate(
                linear_regressor_model_uri,
                diabetes_dataset._constructor_args["data"],
                model_type="regressor",
                targets=diabetes_dataset._constructor_args["targets"],
                dataset_name=diabetes_dataset.name,
                evaluators="default",
            )
        mock_score.assert_called_once()
        assert "score" not in result.metrics


@pytest.mark.parametrize(
    "model",
    [LogisticRegression(), LinearRegression()],
)
def test_autologging_is_disabled_during_evaluate(model):
    mlflow.sklearn.autolog()
    try:
        X, y = load_iris(as_frame=True, return_X_y=True)
        with mlflow.start_run() as run:
            model.fit(X, y)
            model_info = mlflow.sklearn.log_model(model, "model")
            result = evaluate(
                model_info.model_uri,
                X.assign(target=y),
                model_type="classifier" if isinstance(model, LogisticRegression) else "regressor",
                targets="target",
                dataset_name="iris",
                evaluators="default",
            )

        run_data = get_run_data(run.info.run_id)
        duplicate_metrics = []
        for evaluate_metric_key in result.metrics.keys():
            matched_keys = [k for k in run_data.metrics.keys() if k.startswith(evaluate_metric_key)]
            if len(matched_keys) > 1:
                duplicate_metrics += matched_keys
        assert duplicate_metrics == []
    finally:
        mlflow.sklearn.autolog(disable=True)


def test_truncation_works_for_long_feature_names(linear_regressor_model_uri, diabetes_dataset):
    evaluate(
        linear_regressor_model_uri,
        diabetes_dataset._constructor_args["data"],
        model_type="regressor",
        targets=diabetes_dataset._constructor_args["targets"],
        dataset_name=diabetes_dataset.name,
        feature_names=[
            "f1",
            "f2",
            "f3longnamelongnamelongname",
            "f4",
            "f5",
            "f6",
            "f7longlonglonglong",
            "f8",
            "f9",
            "f10",
        ],
        evaluators="default",
    )


def test_evaluation_works_with_model_pipelines_that_modify_input_data():
    iris = load_iris()
    X = pd.DataFrame(iris.data, columns=["0", "1", "2", "3"])
    y = pd.Series(iris.target)

    def add_feature(df):
        df["newfeature"] = 1
        return df

    # Define a transformer that modifies input data by adding an extra feature column
    add_feature_transformer = FunctionTransformer(add_feature, validate=False)
    model_pipeline = Pipeline(
        steps=[("add_feature", add_feature_transformer), ("predict", LogisticRegression())]
    )
    model_pipeline.fit(X, y)

    with mlflow.start_run() as run:
        pipeline_model_uri = mlflow.sklearn.log_model(model_pipeline, "model").model_uri

        evaluation_data = pd.DataFrame(load_iris().data, columns=["0", "1", "2", "3"])
        evaluation_data["labels"] = load_iris().target

        evaluate(
            pipeline_model_uri,
            evaluation_data,
            dataset_name="iris",
            model_type="regressor",
            targets="labels",
            evaluators="default",
            evaluator_config={
                "log_model_explainability": True,
                # Use the kernel explainability algorithm, which fails if there is a mismatch
                # between the number of features in the input dataset and the number of features
                # expected by the model
                "explainability_algorithm": "kernel",
            },
        )

        _, _, _, artifacts = get_run_data(run.info.run_id)
        assert set(artifacts) >= {
            "shap_beeswarm_plot_on_data_iris.png",
            "shap_feature_importance_plot_on_data_iris.png",
            "shap_summary_plot_on_data_iris.png",
        }
