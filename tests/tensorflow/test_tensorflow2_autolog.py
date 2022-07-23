# pep8: disable=E501

import collections
import os
import pickle
from unittest.mock import patch
import json
import functools

import numpy as np
import pandas as pd
import pytest
import tensorflow as tf
from tensorflow import estimator as tf_estimator
from packaging.version import Version
from tensorflow.keras import layers
import yaml

import mlflow
from mlflow import MlflowClient
import mlflow.keras
import mlflow.tensorflow
from mlflow.models import Model
from mlflow.models.utils import _read_example
from mlflow.tensorflow._autolog import _TensorBoard, __MLflowTfKeras2Callback
from mlflow.utils.autologging_utils import (
    AUTOLOGGING_INTEGRATIONS,
    BatchMetricsLogger,
    autologging_is_disabled,
)

np.random.seed(1337)

SavedModelInfo = collections.namedtuple(
    "SavedModelInfo",
    ["path", "meta_graph_tags", "signature_def_key", "inference_df", "expected_results_df"],
)


@pytest.fixture(autouse=True)
def clear_session():
    yield
    tf.keras.backend.clear_session()


@pytest.fixture
def random_train_data():
    return np.random.random((150, 4))


@pytest.fixture
def random_one_hot_labels():
    n, n_class = (150, 3)
    classes = np.random.randint(0, n_class, n)
    labels = np.zeros((n, n_class))
    labels[np.arange(n), classes] = 1
    return labels


@pytest.fixture
def random_train_dict_mapping(random_train_data):
    def _generate_features(pos):
        return [v[pos] for v in random_train_data]

    features = {
        "a": np.array(_generate_features(0)),
        "b": np.array(_generate_features(1)),
        "c": np.array(_generate_features(2)),
        "d": np.array(_generate_features(3)),
    }
    return features


def _create_model_for_dict_mapping():
    model = tf.keras.Sequential()
    model.add(
        layers.DenseFeatures(
            [
                tf.feature_column.numeric_column("a"),
                tf.feature_column.numeric_column("b"),
                tf.feature_column.numeric_column("c"),
                tf.feature_column.numeric_column("d"),
            ]
        )
    )
    model.add(layers.Dense(16, activation="relu", input_shape=(4,)))
    model.add(layers.Dense(3, activation="softmax"))

    model.compile(
        optimizer=tf.keras.optimizers.Adam(), loss="categorical_crossentropy", metrics=["accuracy"]
    )
    return model


@pytest.fixture
def fashion_mnist_tf_dataset():
    train, _ = tf.keras.datasets.fashion_mnist.load_data()
    images, labels = train
    images = images / 255.0
    labels = labels.astype(np.int32)
    fmnist_train_ds = tf.data.Dataset.from_tensor_slices((images, labels))
    fmnist_train_ds = fmnist_train_ds.shuffle(5000).batch(32)
    return fmnist_train_ds


def _create_fashion_mnist_model():
    model = tf.keras.Sequential([tf.keras.layers.Flatten(), tf.keras.layers.Dense(10)])
    model.compile(
        optimizer=tf.keras.optimizers.Adam(),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        metrics=["accuracy"],
    )
    return model


@pytest.fixture
def keras_data_gen_sequence(random_train_data, random_one_hot_labels):
    class DataGenerator(tf.keras.utils.Sequence):
        def __len__(self):
            return 128

        def __getitem__(self, index):
            x = random_train_data
            y = random_one_hot_labels
            return x, y

    return DataGenerator()


@pytest.fixture(autouse=True)
def clear_fluent_autologging_import_hooks():
    """
    Clears import hooks for MLflow fluent autologging (`mlflow.autolog()`) between tests
    to ensure that interactions between fluent autologging and TensorFlow / tf.keras can
    be tested successfully
    """
    mlflow.utils.import_hooks._post_import_hooks.pop("tensorflow", None)
    mlflow.utils.import_hooks._post_import_hooks.pop("keras", None)


@pytest.fixture(autouse=True)
def clear_autologging_config():
    """
    Clears TensorFlow autologging config, simulating a fresh state where autologging has not
    been previously enabled with any particular configuration
    """
    AUTOLOGGING_INTEGRATIONS.pop(mlflow.tensorflow.FLAVOR_NAME, None)


def create_tf_keras_model():
    model = tf.keras.Sequential()
    model.add(layers.Dense(16, activation="relu", input_shape=(4,)))
    model.add(layers.Dense(3, activation="softmax"))

    model.compile(
        optimizer=tf.keras.optimizers.Adam(), loss="categorical_crossentropy", metrics=["accuracy"]
    )
    return model


def test_tf_keras_autolog_ends_auto_created_run(random_train_data, random_one_hot_labels):
    mlflow.tensorflow.autolog()

    data = random_train_data
    labels = random_one_hot_labels

    model = create_tf_keras_model()
    model.fit(data, labels, epochs=10)

    assert mlflow.active_run() is None


@pytest.mark.parametrize("log_models", [True, False])
def test_tf_keras_autolog_log_models_configuration(
    random_train_data, random_one_hot_labels, log_models
):
    # pylint: disable=unused-argument
    mlflow.tensorflow.autolog(log_models=log_models)

    data = random_train_data
    labels = random_one_hot_labels

    model = create_tf_keras_model()

    model.fit(data, labels, epochs=10)

    client = MlflowClient()
    run_id = client.list_run_infos(experiment_id="0")[0].run_id
    artifacts = client.list_artifacts(run_id)
    artifacts = map(lambda x: x.path, artifacts)
    assert ("model" in artifacts) == log_models


def test_tf_keras_autolog_persists_manually_created_run(random_train_data, random_one_hot_labels):
    mlflow.tensorflow.autolog()
    with mlflow.start_run() as run:
        data = random_train_data
        labels = random_one_hot_labels

        model = create_tf_keras_model()
        model.fit(data, labels, epochs=10)

        assert mlflow.active_run()
        assert mlflow.active_run().info.run_id == run.info.run_id


@pytest.fixture
def tf_keras_random_data_run(random_train_data, random_one_hot_labels, initial_epoch):
    # pylint: disable=unused-argument
    mlflow.tensorflow.autolog()

    data = random_train_data
    labels = random_one_hot_labels

    model = create_tf_keras_model()
    history = model.fit(
        data, labels, epochs=initial_epoch + 10, steps_per_epoch=1, initial_epoch=initial_epoch
    )

    client = MlflowClient()
    return client.get_run(client.list_run_infos(experiment_id="0")[0].run_id), history


@pytest.mark.parametrize("initial_epoch", [0, 10])
def test_tf_keras_autolog_logs_expected_data(tf_keras_random_data_run):
    run, history = tf_keras_random_data_run
    data = run.data
    assert "accuracy" in data.metrics
    assert "loss" in data.metrics
    # Testing explicitly passed parameters are logged correctly
    assert "epochs" in data.params
    assert data.params["epochs"] == str(history.epoch[-1] + 1)
    assert "steps_per_epoch" in data.params
    assert data.params["steps_per_epoch"] == "1"
    # Testing default parameters are logged correctly
    assert "initial_epoch" in data.params
    assert data.params["initial_epoch"] == str(history.epoch[0])
    # Testing unwanted parameters are not logged
    assert "callbacks" not in data.params
    assert "validation_data" not in data.params
    # Testing optimizer parameters are logged
    assert "opt_name" in data.params
    assert data.params["opt_name"] == "Adam"
    assert "opt_learning_rate" in data.params
    assert "opt_decay" in data.params
    assert "opt_beta_1" in data.params
    assert "opt_beta_2" in data.params
    assert "opt_epsilon" in data.params
    assert "opt_amsgrad" in data.params
    assert data.params["opt_amsgrad"] == "False"
    client = MlflowClient()
    all_epoch_acc = client.get_metric_history(run.info.run_id, "accuracy")
    num_of_epochs = len(history.history["loss"])
    assert len(all_epoch_acc) == num_of_epochs == 10
    artifacts = client.list_artifacts(run.info.run_id)
    artifacts = map(lambda x: x.path, artifacts)
    assert "model_summary.txt" in artifacts


def __example_tf_dataset(batch_size):
    a = tf.data.Dataset.range(1)
    b = tf.data.Dataset.range(1)
    ds = tf.data.Dataset.zip((a, b))
    return ds.batch(batch_size)


class __ExampleSequence(tf.keras.utils.Sequence):
    def __init__(self, batch_size):
        self.batch_size = batch_size

    def __len__(self):
        return 10

    def __getitem__(self, idx):
        return np.array([idx] * self.batch_size), np.array([-idx] * self.batch_size)


def __generator(data, target, batch_size):
    data_batches = np.split(data, data.shape[0] // batch_size)
    target_batches = np.split(target, target.shape[0] // batch_size)
    for data_batch, target_batch in zip(data_batches, target_batches):
        yield data_batch, target_batch


class __GeneratorClass:
    def __init__(self, data, target, batch_size):
        self.data = data
        self.target = target
        self.batch_size = batch_size
        self.ptr = 0

    def __next__(self):
        if self.ptr >= len(self.data):
            raise StopIteration
        idx = self.ptr % len(self.data)
        self.ptr += 1
        return self.data[idx : idx + self.batch_size], self.target[idx : idx + self.batch_size]

    def __iter__(self):
        return self


@pytest.mark.parametrize(
    "generate_data",
    [
        __example_tf_dataset,
        __ExampleSequence,
        functools.partial(__generator, np.array([[1]] * 10), np.array([[1]] * 10)),
        functools.partial(__GeneratorClass, np.array([[1]] * 10), np.array([[1]] * 10)),
    ],
)
@pytest.mark.parametrize("batch_size", [5, 10])
def test_tf_keras_autolog_implicit_batch_size_works(generate_data, batch_size):
    mlflow.autolog()
    model = tf.keras.Sequential()
    model.add(tf.keras.layers.Dense(1, input_shape=(1,)))
    model.compile(loss="mse")

    # 'x' passed as arg
    model.fit(generate_data(batch_size), verbose=0)
    assert mlflow.last_active_run().data.params["batch_size"] == str(batch_size)

    # 'x' passed as kwarg
    model.fit(x=generate_data(batch_size), verbose=0)
    assert mlflow.last_active_run().data.params["batch_size"] == str(batch_size)


@pytest.mark.skipif(
    Version(tf.__version__) < Version("2.1.4"),
    reason="Does not support passing of generator classes as `x` in `fit`",
)
@pytest.mark.parametrize("generator", [__generator, __GeneratorClass])
@pytest.mark.parametrize("batch_size", [2, 3, 6])
def test_tf_keras_autolog_implicit_batch_size_for_generator_dataset_without_side_effects(
    generator,
    batch_size,
):
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import Dense

    data = np.array([[1, 2, 3], [3, 2, 1], [2, 2, 2], [10, 20, 30], [30, 20, 10], [20, 20, 20]])
    target = np.array([[1], [3], [2], [11], [13], [12]])

    model = Sequential()
    model.add(
        Dense(
            5, input_dim=3, activation="relu", kernel_initializer="zeros", bias_initializer="zeros"
        )
    )
    model.add(Dense(1, kernel_initializer="zeros", bias_initializer="zeros"))
    model.compile(loss="mae", optimizer="adam", metrics=["mse"])

    mlflow.autolog()
    actual_mse = model.fit(generator(data, target, batch_size), verbose=0).history["mse"][-1]

    mlflow.autolog(disable=True)
    expected_mse = model.fit(generator(data, target, batch_size), verbose=0).history["mse"][-1]

    np.testing.assert_allclose(actual_mse, expected_mse, atol=1)
    assert mlflow.last_active_run().data.params["batch_size"] == str(batch_size)


def test_tf_keras_autolog_succeeds_for_tf_datasets_lacking_batch_size_info():
    X_train = np.random.rand(100, 100)
    y_train = np.random.randint(0, 10, 100)

    train_ds = tf.data.Dataset.from_tensor_slices((X_train, y_train))
    train_ds = train_ds.batch(50)
    train_ds = train_ds.cache().prefetch(buffer_size=5)
    assert not hasattr(train_ds, "_batch_size")

    model = tf.keras.Sequential()
    model.add(
        tf.keras.Input(
            100,
        )
    )
    model.add(tf.keras.layers.Dense(256, activation="relu"))
    model.add(tf.keras.layers.Dropout(rate=0.4))
    model.add(tf.keras.layers.Dense(10, activation="sigmoid"))
    model.compile(
        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False),
        optimizer="Adam",
        metrics=["accuracy"],
    )

    mlflow.tensorflow.autolog()
    model.fit(train_ds, epochs=100)

    assert mlflow.last_active_run().data.params["batch_size"] == "None"


def test_tf_keras_autolog_records_metrics_for_last_epoch(random_train_data, random_one_hot_labels):
    every_n_iter = 5
    num_training_epochs = 17
    mlflow.tensorflow.autolog(every_n_iter=every_n_iter)

    model = create_tf_keras_model()
    with mlflow.start_run() as run:
        model.fit(
            random_train_data,
            random_one_hot_labels,
            epochs=num_training_epochs,
            initial_epoch=0,
        )

    client = MlflowClient()
    run_metrics = client.get_run(run.info.run_id).data.metrics
    assert "accuracy" in run_metrics
    all_epoch_acc = client.get_metric_history(run.info.run_id, "accuracy")
    assert set([metric.step for metric in all_epoch_acc]) == set([0, 5, 10, 15])


def test_tf_keras_autolog_logs_metrics_for_single_epoch_training(
    random_train_data, random_one_hot_labels
):
    """
    tf.Keras exhibits inconsistent epoch indexing behavior in comparison with other
    TF2 APIs (e.g., tf.Estimator). tf.Keras uses zero-indexing for epochs,
    while other APIs use one-indexing. Accordingly, this test verifies that metrics are
    produced in the boundary case where a model is trained for a single epoch, ensuring
    that we don't miss the zero index in the tf.Keras case.
    """
    mlflow.tensorflow.autolog(every_n_iter=5)

    model = create_tf_keras_model()
    with mlflow.start_run() as run:
        model.fit(random_train_data, random_one_hot_labels, epochs=1)

    client = MlflowClient()
    run_metrics = client.get_run(run.info.run_id).data.metrics
    assert "accuracy" in run_metrics
    assert "loss" in run_metrics


def test_tf_keras_autolog_names_positional_parameters_correctly(
    random_train_data, random_one_hot_labels
):
    mlflow.tensorflow.autolog(every_n_iter=5)

    data = random_train_data
    labels = random_one_hot_labels

    model = create_tf_keras_model()

    with mlflow.start_run():
        # Pass `batch_size` as a positional argument for testing purposes
        model.fit(data, labels, 8, epochs=10, steps_per_epoch=1)
        run_id = mlflow.active_run().info.run_id

    client = MlflowClient()
    run_info = client.get_run(run_id)
    assert run_info.data.params.get("batch_size") == "8"


@pytest.mark.parametrize("initial_epoch", [0, 10])
def test_tf_keras_autolog_model_can_load_from_artifact(tf_keras_random_data_run, random_train_data):
    run, _ = tf_keras_random_data_run

    client = MlflowClient()
    artifacts = client.list_artifacts(run.info.run_id)
    artifacts = map(lambda x: x.path, artifacts)
    assert "model" in artifacts
    assert "tensorboard_logs" in artifacts
    model = mlflow.keras.load_model("runs:/" + run.info.run_id + "/model")
    model.predict(random_train_data)


def get_tf_keras_random_data_run_with_callback(
    random_train_data,
    random_one_hot_labels,
    callback,
    restore_weights,
    patience,
    initial_epoch,
    log_models,
):
    # pylint: disable=unused-argument
    mlflow.tensorflow.autolog(every_n_iter=1, log_models=log_models)

    data = random_train_data
    labels = random_one_hot_labels

    model = create_tf_keras_model()
    if callback == "early":
        # min_delta is set as such to guarantee early stopping
        callback = tf.keras.callbacks.EarlyStopping(
            monitor="loss",
            patience=patience,
            min_delta=99999999,
            restore_best_weights=restore_weights,
            verbose=1,
        )
    else:

        class CustomCallback(tf.keras.callbacks.Callback):
            def on_train_end(self, logs=None):
                pass

        callback = CustomCallback()

    history = model.fit(
        data, labels, epochs=initial_epoch + 10, callbacks=[callback], initial_epoch=initial_epoch
    )

    client = MlflowClient()
    return client.get_run(client.list_run_infos(experiment_id="0")[0].run_id), history, callback


@pytest.fixture
def tf_keras_random_data_run_with_callback(
    random_train_data,
    random_one_hot_labels,
    callback,
    restore_weights,
    patience,
    initial_epoch,
    log_models,
):
    return get_tf_keras_random_data_run_with_callback(
        random_train_data,
        random_one_hot_labels,
        callback,
        restore_weights,
        patience,
        initial_epoch,
        log_models=log_models,
    )


@pytest.mark.parametrize("log_models", [True, False])
@pytest.mark.parametrize("restore_weights", [True])
@pytest.mark.parametrize("callback", ["early"])
@pytest.mark.parametrize("patience", [0, 1, 5])
@pytest.mark.parametrize("initial_epoch", [0, 10])
def test_tf_keras_autolog_early_stop_logs(tf_keras_random_data_run_with_callback, initial_epoch):
    run, history, callback = tf_keras_random_data_run_with_callback
    metrics = run.data.metrics
    params = run.data.params
    assert "patience" in params
    assert params["patience"] == str(callback.patience)
    assert "monitor" in params
    assert params["monitor"] == "loss"
    assert "verbose" not in params
    assert "mode" not in params
    assert "stopped_epoch" in metrics
    assert "restored_epoch" in metrics
    restored_epoch = int(metrics["restored_epoch"])
    # In this test, the best epoch is always the first epoch because the early stopping callback
    # never observes a loss improvement due to an extremely large `min_delta` value
    assert restored_epoch == initial_epoch
    assert "loss" in history.history
    client = MlflowClient()
    metric_history = client.get_metric_history(run.info.run_id, "loss")
    # Check that MLflow has logged the metrics of the "best" model, in addition to per-epoch metrics
    loss = history.history["loss"]
    assert len(metric_history) == len(loss) + 1
    steps, values = map(list, zip(*[(m.step, m.value) for m in metric_history]))
    # Check that MLflow has logged the correct steps
    assert steps == [*history.epoch, callback.stopped_epoch + 1]
    # Check that MLflow has logged the correct metric values
    np.testing.assert_allclose(values, [*loss, callback.best])

    artifacts = [f.path for f in client.list_artifacts(run.info.run_id)]
    assert "tensorboard_logs" in artifacts


@pytest.mark.parametrize("restore_weights", [True])
@pytest.mark.parametrize("callback", ["early"])
@pytest.mark.parametrize("patience", [0, 1, 5])
@pytest.mark.parametrize("initial_epoch", [0, 10])
def test_tf_keras_autolog_batch_metrics_logger_logs_expected_metrics(
    callback,
    restore_weights,
    patience,
    initial_epoch,
    random_train_data,
    random_one_hot_labels,
):
    patched_metrics_data = []

    # Mock patching BatchMetricsLogger.record_metrics()
    # to ensure that expected metrics are being logged.
    original = BatchMetricsLogger.record_metrics

    with patch(
        "mlflow.utils.autologging_utils.BatchMetricsLogger.record_metrics", autospec=True
    ) as record_metrics_mock:

        def record_metrics_side_effect(self, metrics, step=None):
            patched_metrics_data.extend(metrics.items())
            original(self, metrics, step)

        record_metrics_mock.side_effect = record_metrics_side_effect
        run, _, callback = get_tf_keras_random_data_run_with_callback(
            random_train_data,
            random_one_hot_labels,
            callback,
            restore_weights,
            patience,
            initial_epoch,
            log_models=False,
        )
    patched_metrics_data = dict(patched_metrics_data)
    original_metrics = run.data.metrics

    for metric_name in original_metrics:
        assert metric_name in patched_metrics_data

    restored_epoch = int(patched_metrics_data["restored_epoch"])
    assert restored_epoch == initial_epoch


@pytest.mark.parametrize("log_models", [False])
@pytest.mark.parametrize("restore_weights", [True])
@pytest.mark.parametrize("callback", ["early"])
@pytest.mark.parametrize("patience", [11])
@pytest.mark.parametrize("initial_epoch", [0, 10])
def test_tf_keras_autolog_early_stop_no_stop_does_not_log(tf_keras_random_data_run_with_callback):
    run, history, callback = tf_keras_random_data_run_with_callback
    metrics = run.data.metrics
    params = run.data.params
    assert "patience" in params
    assert params["patience"] == str(callback.patience)
    assert "monitor" in params
    assert params["monitor"] == "loss"
    assert "verbose" not in params
    assert "mode" not in params
    assert "stopped_epoch" not in metrics
    assert "restored_epoch" not in metrics
    assert "loss" in history.history
    num_of_epochs = len(history.history["loss"])
    client = MlflowClient()
    metric_history = client.get_metric_history(run.info.run_id, "loss")
    # Check the test epoch numbers are correct
    assert num_of_epochs == 10
    assert len(metric_history) == num_of_epochs


@pytest.mark.parametrize("log_models", [False])
@pytest.mark.parametrize("restore_weights", [False])
@pytest.mark.parametrize("callback", ["early"])
@pytest.mark.parametrize("patience", [5])
@pytest.mark.parametrize("initial_epoch", [0, 10])
def test_tf_keras_autolog_early_stop_no_restore_doesnt_log(tf_keras_random_data_run_with_callback):
    run, history, callback = tf_keras_random_data_run_with_callback
    metrics = run.data.metrics
    params = run.data.params
    assert "patience" in params
    assert params["patience"] == str(callback.patience)
    assert "monitor" in params
    assert params["monitor"] == "loss"
    assert "verbose" not in params
    assert "mode" not in params
    assert "stopped_epoch" in metrics
    assert "restored_epoch" not in metrics
    assert "loss" in history.history
    num_of_epochs = len(history.history["loss"])
    client = MlflowClient()
    metric_history = client.get_metric_history(run.info.run_id, "loss")
    # Check the test epoch numbers are correct
    assert num_of_epochs == callback.patience + 1
    assert len(metric_history) == num_of_epochs


@pytest.mark.parametrize("log_models", [False])
@pytest.mark.parametrize("restore_weights", [False])
@pytest.mark.parametrize("callback", ["not-early"])
@pytest.mark.parametrize("patience", [5])
@pytest.mark.parametrize("initial_epoch", [0, 10])
def test_tf_keras_autolog_non_early_stop_callback_no_log(tf_keras_random_data_run_with_callback):
    run, history = tf_keras_random_data_run_with_callback[:-1]
    metrics = run.data.metrics
    params = run.data.params
    assert "patience" not in params
    assert "monitor" not in params
    assert "verbose" not in params
    assert "mode" not in params
    assert "stopped_epoch" not in metrics
    assert "restored_epoch" not in metrics
    assert "loss" in history.history
    num_of_epochs = len(history.history["loss"])
    client = MlflowClient()
    metric_history = client.get_metric_history(run.info.run_id, "loss")
    # Check the test epoch numbers are correct
    assert num_of_epochs == 10
    assert len(metric_history) == num_of_epochs


@pytest.mark.parametrize("positional", [True, False])
def test_tf_keras_autolog_does_not_mutate_original_callbacks_list(
    tmpdir, random_train_data, random_one_hot_labels, positional
):
    """
    TensorFlow autologging passes new callbacks to the `fit()` / `fit_generator()` function. If
    preexisting user-defined callbacks already exist, these new callbacks are added to the
    user-specified ones. This test verifies that the new callbacks are added to the without
    permanently mutating the original list of callbacks.
    """
    mlflow.tensorflow.autolog()

    tensorboard_callback = tf.keras.callbacks.TensorBoard(log_dir=tmpdir)
    callbacks = [tensorboard_callback]

    model = create_tf_keras_model()
    data = random_train_data
    labels = random_one_hot_labels

    if positional:
        model.fit(data, labels, None, 10, 1, callbacks)
    else:
        model.fit(data, labels, epochs=10, callbacks=callbacks)

    assert len(callbacks) == 1
    assert callbacks == [tensorboard_callback]


def test_tf_keras_autolog_does_not_delete_logging_directory_for_tensorboard_callback(
    tmpdir, random_train_data, random_one_hot_labels
):
    tensorboard_callback_logging_dir_path = str(tmpdir.mkdir("tb_logs"))
    tensorboard_callback = tf.keras.callbacks.TensorBoard(
        tensorboard_callback_logging_dir_path, histogram_freq=0
    )

    mlflow.tensorflow.autolog()

    data = random_train_data
    labels = random_one_hot_labels

    model = create_tf_keras_model()
    model.fit(data, labels, epochs=10, callbacks=[tensorboard_callback])

    assert os.path.exists(tensorboard_callback_logging_dir_path)


def test_tf_keras_autolog_logs_to_and_deletes_temporary_directory_when_tensorboard_callback_absent(
    tmpdir, random_train_data, random_one_hot_labels
):
    from unittest import mock
    from mlflow.tensorflow import _TensorBoardLogDir

    mlflow.tensorflow.autolog()

    mock_log_dir_inst = _TensorBoardLogDir(location=str(tmpdir.mkdir("tb_logging")), is_temp=True)
    with mock.patch("mlflow.tensorflow._TensorBoardLogDir", autospec=True) as mock_log_dir_class:
        mock_log_dir_class.return_value = mock_log_dir_inst

        data = random_train_data
        labels = random_one_hot_labels

        model = create_tf_keras_model()
        model.fit(data, labels, epochs=10)

        assert not os.path.exists(mock_log_dir_inst.location)


def create_tf_estimator_model(directory, export, training_steps=100, use_v1_estimator=False):
    CSV_COLUMN_NAMES = ["SepalLength", "SepalWidth", "PetalLength", "PetalWidth", "Species"]

    train = pd.read_csv(
        os.path.join(os.path.dirname(__file__), "iris_training.csv"),
        names=CSV_COLUMN_NAMES,
        header=0,
    )

    train_y = train.pop("Species")

    def input_fn(features, labels, training=True, batch_size=256):
        """An input function for training or evaluating"""
        # Convert the inputs to a Dataset.
        dataset = tf.data.Dataset.from_tensor_slices((dict(features), labels))

        # Shuffle and repeat if you are in training mode.
        if training:
            dataset = dataset.shuffle(1000).repeat()

        return dataset.batch(batch_size)

    my_feature_columns = [tf.feature_column.numeric_column(key=key) for key in train.keys()]

    feature_spec = {
        feature: tf.Variable([], dtype=tf.float64, name=feature)
        for feature in CSV_COLUMN_NAMES
        if feature != "Species"
    }

    receiver_fn = tf_estimator.export.build_raw_serving_input_receiver_fn(feature_spec)

    run_config = tf_estimator.RunConfig(
        # Emit loss metrics to TensorBoard every step
        save_summary_steps=1,
    )

    # If flag set to true, then use the v1 classifier that extends Estimator
    # If flag set to false, then use the v2 classifier that extends EstimatorV2
    if use_v1_estimator:
        classifier = tf.compat.v1.estimator.DNNClassifier(
            feature_columns=my_feature_columns,
            # Two hidden layers of 10 nodes each.
            hidden_units=[30, 10],
            # The model must choose between 3 classes.
            n_classes=3,
            model_dir=directory,
            config=run_config,
        )
    else:
        classifier = tf_estimator.DNNClassifier(
            feature_columns=my_feature_columns,
            # Two hidden layers of 10 nodes each.
            hidden_units=[30, 10],
            # The model must choose between 3 classes.
            n_classes=3,
            model_dir=directory,
            config=run_config,
        )

    classifier.train(input_fn=lambda: input_fn(train, train_y, training=True), steps=training_steps)
    if export:
        classifier.export_saved_model(directory, receiver_fn)


@pytest.fixture
def iris_dataset_spec():
    return [
        {
            "name": "SepalLength",
            "type": "tensor",
            "tensor-spec": {"dtype": "float64", "shape": [-1]},
        },
        {
            "name": "SepalWidth",
            "type": "tensor",
            "tensor-spec": {"dtype": "float64", "shape": [-1]},
        },
        {
            "name": "PetalLength",
            "type": "tensor",
            "tensor-spec": {"dtype": "float64", "shape": [-1]},
        },
        {
            "name": "PetalWidth",
            "type": "tensor",
            "tensor-spec": {"dtype": "float64", "shape": [-1]},
        },
    ]


@pytest.fixture
def tf_iris_estimator_prediction_schema():
    return [
        {
            "name": "logits",
            "type": "tensor",
            "tensor-spec": {"dtype": "float32", "shape": [-1]},
        },
        {
            "name": "probabilities",
            "type": "tensor",
            "tensor-spec": {"dtype": "float32", "shape": [-1]},
        },
        {
            "name": "class_ids",
            "type": "tensor",
            "tensor-spec": {"dtype": "int64", "shape": [-1]},
        },
        {
            "name": "classes",
            "type": "tensor",
            "tensor-spec": {"dtype": "object", "shape": [-1]},
        },
        {
            "name": "all_class_ids",
            "type": "tensor",
            "tensor-spec": {"dtype": "int32", "shape": [-1]},
        },
        {
            "name": "all_classes",
            "type": "tensor",
            "tensor-spec": {"dtype": "object", "shape": [-1]},
        },
    ]


def train_tf_titanic_estimator(directory, input_data_type):
    def train_input_fn():
        titanic_file = tf.keras.utils.get_file(
            "titanic_train.csv", "https://storage.googleapis.com/tf-datasets/titanic/train.csv"
        )
        input_data = {
            k: tf.convert_to_tensor(list(v.values()))
            for k, v in pd.read_csv(
                titanic_file,
                header=0,
            )
            .to_dict()
            .items()
        }
        labels = input_data.pop("survived")
        if input_data_type == "tuple_dict":
            return input_data, labels
        elif input_data_type == "dataset":
            titanic = tf.data.experimental.make_csv_dataset(
                titanic_file, batch_size=32, label_name="survived"
            )
            titanic_batches = titanic.cache().repeat().shuffle(500).prefetch(tf.data.AUTOTUNE)
            return titanic_batches

    age = tf.feature_column.numeric_column("age")
    cls = tf.feature_column.categorical_column_with_vocabulary_list(
        "class", ["First", "Second", "Third"]
    )
    embark = tf.feature_column.categorical_column_with_hash_bucket("embark_town", 32)

    estimator = tf.estimator.LinearClassifier(
        model_dir=directory, feature_columns=[embark, cls, age], n_classes=2
    )

    estimator = estimator.train(input_fn=train_input_fn, steps=100)

    feature_spec = {
        "sex": tf.Variable([], dtype=tf.string, name="sex"),
        "age": tf.Variable([], dtype=tf.float32, name="age"),
        "n_siblings_spouses": tf.Variable([], dtype=tf.int32, name="n_siblings_spouses"),
        "parch": tf.Variable([], dtype=tf.int32, name="parch"),
        "fare": tf.Variable([], dtype=tf.float32, name="fare"),
        "class": tf.Variable([], dtype=tf.string, name="class"),
        "deck": tf.Variable([], dtype=tf.string, name="deck"),
        "embark_town": tf.Variable([], dtype=tf.string, name="embark_town"),
        "alone": tf.Variable([], dtype=tf.string, name="alone"),
    }

    receiver_fn = tf.estimator.export.build_raw_serving_input_receiver_fn(feature_spec)
    estimator.export_saved_model(directory, receiver_fn)

    return estimator


@pytest.fixture
def titanic_dataset_spec():
    return [
        {"name": "sex", "tensor-spec": {"dtype": "object", "shape": [-1]}, "type": "tensor"},
        {"name": "age", "tensor-spec": {"dtype": "float32", "shape": [-1]}, "type": "tensor"},
        {
            "name": "n_siblings_spouses",
            "tensor-spec": {"dtype": "int32", "shape": [-1]},
            "type": "tensor",
        },
        {"name": "parch", "tensor-spec": {"dtype": "int32", "shape": [-1]}, "type": "tensor"},
        {"name": "fare", "tensor-spec": {"dtype": "float32", "shape": [-1]}, "type": "tensor"},
        {"name": "class", "tensor-spec": {"dtype": "object", "shape": [-1]}, "type": "tensor"},
        {"name": "deck", "tensor-spec": {"dtype": "object", "shape": [-1]}, "type": "tensor"},
        {
            "name": "embark_town",
            "tensor-spec": {"dtype": "object", "shape": [-1]},
            "type": "tensor",
        },
        {"name": "alone", "tensor-spec": {"dtype": "object", "shape": [-1]}, "type": "tensor"},
    ]


@pytest.fixture
def tf_titanic_estimator_prediction_schema():
    return [
        {"name": "logits", "tensor-spec": {"dtype": "float32", "shape": [-1]}, "type": "tensor"},
        {"name": "logistic", "tensor-spec": {"dtype": "float32", "shape": [-1]}, "type": "tensor"},
        {
            "name": "probabilities",
            "tensor-spec": {"dtype": "float32", "shape": [-1]},
            "type": "tensor",
        },
        {"name": "class_ids", "tensor-spec": {"dtype": "int64", "shape": [-1]}, "type": "tensor"},
        {"name": "classes", "tensor-spec": {"dtype": "object", "shape": [-1]}, "type": "tensor"},
        {
            "name": "all_class_ids",
            "tensor-spec": {"dtype": "int32", "shape": [-1]},
            "type": "tensor",
        },
        {
            "name": "all_classes",
            "tensor-spec": {"dtype": "object", "shape": [-1]},
            "type": "tensor",
        },
    ]


def test_tf_signature_with_dataset(tmpdir, iris_dataset_spec, tf_iris_estimator_prediction_schema):
    directory = tmpdir.mkdir("tf_signature_with_dataset")
    mlflow.tensorflow.autolog(log_input_examples=True, log_model_signatures=True)
    with mlflow.start_run() as run:
        create_tf_estimator_model(str(directory), True)
        _assert_autolog_infers_model_signature_correctly(
            run, iris_dataset_spec, tf_iris_estimator_prediction_schema
        )


def test_tf_input_example_with_dataset(tmpdir):
    mlflow.tensorflow.autolog(log_input_examples=True, log_model_signatures=True)
    directory = tmpdir.mkdir("tf_input_example_with_dataset")
    with mlflow.start_run() as run:
        create_tf_estimator_model(directory=str(directory), export=True, use_v1_estimator=False)
        model_path = os.path.join(run.info.artifact_uri, "model")
        model_conf = Model.load(os.path.join(model_path, "MLmodel"))
        input_example = _read_example(model_conf, model_path)
        pyfunc_model = mlflow.pyfunc.load_model(os.path.join(run.info.artifact_uri, "model"))
        pyfunc_model.predict(input_example)


def _assert_tf_signature(
    tmpdir, data_type, titanic_dataset_spec, tf_titanic_estimator_prediction_schema
):
    directory = tmpdir.mkdir("tf_signature")
    mlflow.tensorflow.autolog(log_input_examples=True, log_model_signatures=True)
    with mlflow.start_run() as run:
        train_tf_titanic_estimator(directory=str(directory), input_data_type=data_type)
        _assert_autolog_infers_model_signature_correctly(
            run, titanic_dataset_spec, tf_titanic_estimator_prediction_schema
        )


def test_tf_input_example_with_tuple_dict(tmpdir):
    mlflow.tensorflow.autolog(log_input_examples=True, log_model_signatures=True)
    directory = tmpdir.mkdir("tf_input_example_with_tuple_dict")
    with mlflow.start_run() as run:
        train_tf_titanic_estimator(directory=str(directory), input_data_type="tuple_dict")
        model_path = os.path.join(run.info.artifact_uri, "model")
        model_conf = Model.load(os.path.join(model_path, "MLmodel"))
        input_example = _read_example(model_conf, model_path)
        pyfunc_model = mlflow.pyfunc.load_model(os.path.join(run.info.artifact_uri, "model"))
        pyfunc_model.predict(input_example)


@pytest.mark.skipif(
    Version(tf.__version__) >= Version("2.1.0"),
    reason="`fit_generator()` is deprecated in TF >= 2.1.0 and simply wraps `fit()`",
)
def test_fit_generator_signature_autologging(keras_data_gen_sequence):
    mlflow.tensorflow.autolog(log_input_examples=True, log_model_signatures=True)
    model = create_tf_keras_model()

    with mlflow.start_run() as run:
        model.fit_generator(keras_data_gen_sequence)
        _assert_autolog_infers_model_signature_correctly(
            run,
            [{"type": "tensor", "tensor-spec": {"dtype": "float64", "shape": [-1, 4]}}],
            [{"type": "tensor", "tensor-spec": {"dtype": "float32", "shape": [-1, 3]}}],
        )


@pytest.mark.skipif(
    Version(tf.__version__) >= Version("2.1.0"),
    reason="`fit_generator()` is deprecated in TF >= 2.1.0 and simply wraps `fit()`",
)
def test_fit_generator_input_example_autologging(keras_data_gen_sequence):
    mlflow.tensorflow.autolog(log_input_examples=True, log_model_signatures=True)
    model = create_tf_keras_model()

    with mlflow.start_run() as run:
        model.fit_generator(keras_data_gen_sequence)
        _assert_keras_autolog_input_example_load_and_predict_with_nparray(
            run, keras_data_gen_sequence[:][0]
        )


def test_tf_signature_with_tuple_dict(
    tmpdir, titanic_dataset_spec, tf_titanic_estimator_prediction_schema
):
    _assert_tf_signature(
        tmpdir, "tuple_dict", titanic_dataset_spec, tf_titanic_estimator_prediction_schema
    )


@pytest.mark.parametrize("export", [True, False])
def test_tf_estimator_autolog_ends_auto_created_run(tmpdir, export):
    directory = tmpdir.mkdir("test")
    mlflow.tensorflow.autolog()
    create_tf_estimator_model(str(directory), export)
    assert mlflow.active_run() is None


@pytest.mark.parametrize("export", [True, False])
def test_tf_estimator_autolog_persists_manually_created_run(tmpdir, export):
    directory = tmpdir.mkdir("test")
    with mlflow.start_run() as run:
        create_tf_estimator_model(str(directory), export)
        assert mlflow.active_run()
        assert mlflow.active_run().info.run_id == run.info.run_id


@pytest.fixture
def tf_estimator_random_data_run(tmpdir, export):
    # pylint: disable=unused-argument
    directory = tmpdir.mkdir("test")
    mlflow.tensorflow.autolog()
    create_tf_estimator_model(str(directory), export)
    client = MlflowClient()
    return client.get_run(client.list_run_infos(experiment_id="0")[0].run_id)


@pytest.mark.parametrize("export", [True, False])
@pytest.mark.parametrize("use_v1_estimator", [True, False])
def test_tf_estimator_autolog_logs_metrics(tmpdir, export, use_v1_estimator):
    directory = tmpdir.mkdir("test")
    mlflow.tensorflow.autolog(every_n_iter=5)

    with mlflow.start_run():
        create_tf_estimator_model(
            str(directory), export, use_v1_estimator=use_v1_estimator, training_steps=17
        )
        run_id = mlflow.active_run().info.run_id

    client = MlflowClient()
    run = client.get_run(run_id)

    assert "loss" in run.data.metrics
    assert "steps" in run.data.params
    metrics = client.get_metric_history(run_id, "loss")
    assert set([metric.step for metric in metrics]) == set([1, 6, 11, 16])


@pytest.mark.parametrize("export", [True])
def test_tf_estimator_v1_autolog_can_load_from_artifact(tmpdir, export):
    directory = tmpdir.mkdir("test")
    mlflow.tensorflow.autolog()

    create_tf_estimator_model(str(directory), export, use_v1_estimator=True)
    client = MlflowClient()
    tf_estimator_v1_run = client.get_run(client.list_run_infos(experiment_id="0")[0].run_id)
    artifacts = client.list_artifacts(tf_estimator_v1_run.info.run_id)
    artifacts = map(lambda x: x.path, artifacts)
    assert "model" in artifacts
    mlflow.tensorflow.load_model("runs:/" + tf_estimator_v1_run.info.run_id + "/model")


@pytest.mark.parametrize("export", [True, False])
def test_tf_estimator_autolog_logs_tensorboard_logs(tf_estimator_random_data_run):
    client = MlflowClient()
    artifacts = client.list_artifacts(tf_estimator_random_data_run.info.run_id)
    assert any("tensorboard_logs" in a.path and a.is_dir for a in artifacts)


def test_tf_estimator_autolog_logs_metrics_in_exclusive_mode(tmpdir):
    mlflow.tensorflow.autolog(exclusive=True)

    create_tf_estimator_model(tmpdir, export=False)
    client = MlflowClient()
    tf_estimator_run = client.get_run(client.list_run_infos(experiment_id="0")[0].run_id)

    assert "loss" in tf_estimator_run.data.metrics
    assert "steps" in tf_estimator_run.data.params
    metrics = client.get_metric_history(tf_estimator_run.info.run_id, "loss")
    assert len(metrics) == 100


def test_tf_estimator_autolog_logs_metics_for_single_epoch_training(tmpdir):
    """
    Epoch indexing behavior is consistent across TensorFlow 2: tf.Keras uses
    zero-indexing for epochs, while other APIs (e.g., tf.Estimator) use one-indexing.
    This test verifies that metrics are produced for tf.Estimator training sessions
    in the boundary casewhere a model is trained for a single epoch, ensuring that
    we capture metrics from the first epoch at index 1.
    """
    mlflow.tensorflow.autolog()
    with mlflow.start_run() as run:
        create_tf_estimator_model(str(tmpdir), export=False, training_steps=1)
    client = MlflowClient()
    metrics = client.get_metric_history(run.info.run_id, "loss")
    assert len(metrics) == 1
    assert metrics[0].step == 1


@pytest.mark.parametrize("export", [True])
def test_tf_estimator_autolog_model_can_load_from_artifact(tf_estimator_random_data_run):
    client = MlflowClient()
    artifacts = client.list_artifacts(tf_estimator_random_data_run.info.run_id)
    artifacts = map(lambda x: x.path, artifacts)
    assert "model" in artifacts
    mlflow.tensorflow.load_model("runs:/" + tf_estimator_random_data_run.info.run_id + "/model")


def test_flush_queue_is_thread_safe():
    """
    Autologging augments TensorBoard event logging hooks with MLflow `log_metric` API
    calls. To prevent these API calls from blocking TensorBoard event logs, `log_metric`
    API calls are scheduled via `_flush_queue` on a background thread. Accordingly, this test
    verifies that `_flush_queue` is thread safe.
    """
    from threading import Thread
    from mlflow.entities import Metric
    from mlflow.tensorflow import _flush_queue, _metric_queue_lock

    client = MlflowClient()
    run = client.create_run(experiment_id="0")
    metric_queue_item = (run.info.run_id, Metric("foo", 0.1, 100, 1))
    mlflow.tensorflow._metric_queue.append(metric_queue_item)

    # Verify that, if another thread holds a lock on the metric queue leveraged by
    # _flush_queue, _flush_queue terminates and does not modify the queue
    _metric_queue_lock.acquire()
    flush_thread1 = Thread(target=_flush_queue)
    flush_thread1.start()
    flush_thread1.join()
    assert len(mlflow.tensorflow._metric_queue) == 1
    assert mlflow.tensorflow._metric_queue[0] == metric_queue_item
    _metric_queue_lock.release()

    # Verify that, if no other thread holds a lock on the metric queue leveraged by
    # _flush_queue, _flush_queue flushes the queue as expected
    flush_thread2 = Thread(target=_flush_queue)
    flush_thread2.start()
    flush_thread2.join()
    assert len(mlflow.tensorflow._metric_queue) == 0


def get_text_vec_model(train_samples):
    # Taken from: https://github.com/mlflow/mlflow/issues/3910

    # pylint: disable=no-name-in-module
    from tensorflow.keras.layers.experimental.preprocessing import TextVectorization

    VOCAB_SIZE = 10
    SEQUENCE_LENGTH = 16
    EMBEDDING_DIM = 16

    vectorizer_layer = TextVectorization(
        input_shape=(1,),
        max_tokens=VOCAB_SIZE,
        output_mode="int",
        output_sequence_length=SEQUENCE_LENGTH,
    )
    vectorizer_layer.adapt(train_samples)
    model = tf.keras.Sequential(
        [
            vectorizer_layer,
            tf.keras.layers.Embedding(
                VOCAB_SIZE,
                EMBEDDING_DIM,
                name="embedding",
                mask_zero=True,
                input_shape=(1,),
            ),
            tf.keras.layers.GlobalAveragePooling1D(),
            tf.keras.layers.Dense(16, activation="relu"),
            tf.keras.layers.Dense(1, activation="tanh"),
        ]
    )
    model.compile(optimizer="adam", loss="mse", metrics="mae")
    return model


@pytest.mark.skipif(
    Version(tf.__version__) < Version("2.3.0"),
    reason=(
        "Deserializing a model with `TextVectorization` and `Embedding`"
        "fails in tensorflow < 2.3.0. See this issue:"
        "https://github.com/tensorflow/tensorflow/issues/38250"
    ),
)
def test_autolog_text_vec_model(tmpdir):
    """
    Verifies autolog successfully saves a model that can't be saved in the H5 format
    """
    mlflow.tensorflow.autolog()

    train_samples = np.array(["this is an example", "another example"])
    train_labels = np.array([0.4, 0.2])
    model = get_text_vec_model(train_samples)

    # Saving in the H5 format should fail
    with pytest.raises(NotImplementedError, match="is not supported in h5"):
        model.save(tmpdir.join("model.h5").strpath, save_format="h5")

    with mlflow.start_run() as run:
        model.fit(train_samples, train_labels, epochs=1)

    loaded_model = mlflow.keras.load_model("runs:/" + run.info.run_id + "/model")
    np.testing.assert_array_equal(loaded_model.predict(train_samples), model.predict(train_samples))


@pytest.mark.parametrize("log_models", [True, False])
def test_fit_generator(random_train_data, random_one_hot_labels, log_models):
    mlflow.tensorflow.autolog(log_models=log_models)
    model = create_tf_keras_model()

    def generator():
        while True:
            yield random_train_data, random_one_hot_labels

    with mlflow.start_run() as run:
        model.fit_generator(generator(), epochs=10, steps_per_epoch=1)

    client = MlflowClient()
    run = client.get_run(run.info.run_id)
    params = run.data.params
    metrics = run.data.metrics
    artifacts = [f.path for f in client.list_artifacts(run.info.run_id)]
    assert "epochs" in params
    assert params["epochs"] == "10"
    assert "steps_per_epoch" in params
    assert params["steps_per_epoch"] == "1"
    assert "accuracy" in metrics
    assert "loss" in metrics
    assert "tensorboard_logs" in artifacts


def test_tf_keras_model_autolog_registering_model(random_train_data, random_one_hot_labels):
    registered_model_name = "test_autolog_registered_model"
    mlflow.tensorflow.autolog(registered_model_name=registered_model_name)
    with mlflow.start_run():
        model = create_tf_keras_model()
        model.fit(random_train_data, random_one_hot_labels, epochs=10)

        registered_model = MlflowClient().get_registered_model(registered_model_name)
        assert registered_model.name == registered_model_name


def test_fluent_autolog_with_tf_keras_logs_expected_content(
    random_train_data, random_one_hot_labels
):
    """
    Guards against previously-exhibited issues where using the fluent `mlflow.autolog()` API with
    `tf.keras` Models did not work due to conflicting patches set by both the
    `mlflow.tensorflow.autolog()` and the `mlflow.keras.autolog()` APIs.
    """
    mlflow.autolog()

    model = create_tf_keras_model()

    with mlflow.start_run() as run:
        model.fit(random_train_data, random_one_hot_labels, epochs=10)

    client = MlflowClient()
    run_data = client.get_run(run.info.run_id).data
    assert "accuracy" in run_data.metrics
    assert "epochs" in run_data.params

    artifacts = client.list_artifacts(run.info.run_id)
    artifacts = map(lambda x: x.path, artifacts)
    assert "model" in artifacts


def test_callback_is_picklable():
    cb = __MLflowTfKeras2Callback(
        metrics_logger=BatchMetricsLogger(run_id="1234"), log_every_n_steps=5
    )
    pickle.dumps(cb)

    tb = _TensorBoard()
    pickle.dumps(tb)


@pytest.mark.skipif(
    Version(tf.__version__) < Version("2.1.0"), reason="This test requires tensorflow >= 2.1.0"
)
def test_tf_keras_autolog_distributed_training(random_train_data, random_one_hot_labels):
    # Ref: https://www.tensorflow.org/tutorials/distribute/keras
    mlflow.tensorflow.autolog()

    with tf.distribute.MirroredStrategy().scope():
        model = create_tf_keras_model()
    fit_params = {"epochs": 10, "batch_size": 10}
    with mlflow.start_run() as run:
        model.fit(random_train_data, random_one_hot_labels, **fit_params)
    client = MlflowClient()
    assert client.get_run(run.info.run_id).data.params.keys() >= fit_params.keys()


@pytest.mark.skipif(
    Version(tf.__version__) < Version("2.6.0"),
    reason=("TensorFlow only has a hard dependency on Keras in version >= 2.6.0"),
)
def test_fluent_autolog_with_tf_keras_preserves_v2_model_reference():
    """
    Verifies that, in TensorFlow >= 2.6.0, `tensorflow.keras.Model` refers to the correct class in
    the correct module after `mlflow.autolog()` is called, guarding against previously identified
    compatibility issues between recent versions of TensorFlow and MLflow's internal utility for
    setting up autologging import hooks.
    """
    mlflow.autolog()

    import tensorflow.keras
    from keras.api._v2.keras import Model as ModelV2

    assert tensorflow.keras.Model is ModelV2


def test_import_tensorflow_with_fluent_autolog_enables_tf_autologging():
    mlflow.autolog()

    import tensorflow  # pylint: disable=unused-variable,unused-import,reimported

    assert not autologging_is_disabled(mlflow.tensorflow.FLAVOR_NAME)

    # NB: In Tensorflow >= 2.6, we redirect keras autologging to tensorflow autologging
    # so the original keras autologging is disabled
    if Version(tf.__version__) >= Version("2.6"):
        import keras  # pylint: disable=unused-variable,unused-import

        assert autologging_is_disabled(mlflow.keras.FLAVOR_NAME)


def test_import_tf_keras_with_fluent_autolog_enables_tf_autologging():
    mlflow.autolog()

    import tensorflow.keras  # pylint: disable=unused-variable,unused-import

    assert not autologging_is_disabled(mlflow.tensorflow.FLAVOR_NAME)

    # NB: In Tensorflow >= 2.6, we redirect keras autologging to tensorflow autologging
    # so the original keras autologging is disabled
    if Version(tf.__version__) >= Version("2.6"):
        # NB: For TF >= 2.6, import tensorflow.keras will trigger importing keras
        assert autologging_is_disabled(mlflow.keras.FLAVOR_NAME)


@pytest.mark.skipif(
    Version(tf.__version__) < Version("2.6.0"),
    reason=("TensorFlow autologging is not used for vanilla Keras models in Keras < 2.6.0"),
)
def test_import_keras_with_fluent_autolog_enables_tensorflow_autologging():
    mlflow.autolog()

    import keras  # pylint: disable=unused-variable,unused-import

    assert not autologging_is_disabled(mlflow.tensorflow.FLAVOR_NAME)
    assert autologging_is_disabled(mlflow.keras.FLAVOR_NAME)


def _assert_autolog_infers_model_signature_correctly(run, input_sig_spec, output_sig_spec):
    artifacts_dir = run.info.artifact_uri.replace("file://", "")
    client = MlflowClient()
    artifacts = [x.path for x in client.list_artifacts(run.info.run_id, "model")]
    ml_model_filename = "MLmodel"
    assert str(os.path.join("model", ml_model_filename)) in artifacts
    ml_model_path = os.path.join(artifacts_dir, "model", ml_model_filename)
    with open(ml_model_path, "r") as f:
        data = yaml.load(f, Loader=yaml.FullLoader)
        assert data is not None
        assert "signature" in data
        signature = data["signature"]
        assert signature is not None
        assert "inputs" in signature
        assert "outputs" in signature
        assert json.loads(signature["inputs"]) == input_sig_spec
        assert json.loads(signature["outputs"]) == output_sig_spec


def _assert_keras_autolog_input_example_load_and_predict_with_nparray(run, random_train_data):
    model_path = os.path.join(run.info.artifact_uri, "model")
    model_conf = Model.load(os.path.join(model_path, "MLmodel"))
    input_example = _read_example(model_conf, model_path)
    np.testing.assert_array_almost_equal(input_example, random_train_data[:5])
    pyfunc_model = mlflow.pyfunc.load_model(os.path.join(run.info.artifact_uri, "model"))
    pyfunc_model.predict(input_example)


def test_keras_autolog_input_example_load_and_predict_with_nparray(
    random_train_data, random_one_hot_labels
):
    mlflow.tensorflow.autolog(log_input_examples=True, log_model_signatures=True)
    initial_model = create_tf_keras_model()
    with mlflow.start_run() as run:
        initial_model.fit(random_train_data, random_one_hot_labels)
        _assert_keras_autolog_input_example_load_and_predict_with_nparray(run, random_train_data)


def test_keras_autolog_infers_model_signature_correctly_with_nparray(
    random_train_data, random_one_hot_labels
):
    mlflow.tensorflow.autolog(log_model_signatures=True)
    initial_model = create_tf_keras_model()
    with mlflow.start_run() as run:
        initial_model.fit(random_train_data, random_one_hot_labels)
        _assert_autolog_infers_model_signature_correctly(
            run,
            [{"type": "tensor", "tensor-spec": {"dtype": "float64", "shape": [-1, 4]}}],
            [{"type": "tensor", "tensor-spec": {"dtype": "float32", "shape": [-1, 3]}}],
        )


@pytest.mark.skipif(
    Version(tf.__version__) < Version("2.1.0"),
    reason="tf.data.Dataset inputs are unsupported for input example logging in TensorFlow < 2.1.0",
)
def test_keras_autolog_input_example_load_and_predict_with_tf_dataset(fashion_mnist_tf_dataset):
    mlflow.tensorflow.autolog(log_input_examples=True, log_model_signatures=True)
    fashion_mnist_model = _create_fashion_mnist_model()
    with mlflow.start_run() as run:
        fashion_mnist_model.fit(fashion_mnist_tf_dataset)
        model_path = os.path.join(run.info.artifact_uri, "model")
        model_conf = Model.load(os.path.join(model_path, "MLmodel"))
        input_example = _read_example(model_conf, model_path)
        pyfunc_model = mlflow.pyfunc.load_model(os.path.join(run.info.artifact_uri, "model"))
        pyfunc_model.predict(input_example)


@pytest.mark.skipif(
    Version(tf.__version__) < Version("2.1.0"),
    reason="tf.data.Dataset inputs are unsupported for signature logging in TensorFlow < 2.1.0",
)
def test_keras_autolog_infers_model_signature_correctly_with_tf_dataset(fashion_mnist_tf_dataset):
    mlflow.tensorflow.autolog(log_model_signatures=True)
    fashion_mnist_model = _create_fashion_mnist_model()
    with mlflow.start_run() as run:
        fashion_mnist_model.fit(fashion_mnist_tf_dataset)
        _assert_autolog_infers_model_signature_correctly(
            run,
            [{"type": "tensor", "tensor-spec": {"dtype": "float64", "shape": [-1, 28, 28]}}],
            [{"type": "tensor", "tensor-spec": {"dtype": "float32", "shape": [-1, 10]}}],
        )


def test_keras_autolog_input_example_load_and_predict_with_dict(
    random_train_dict_mapping, random_one_hot_labels
):
    mlflow.tensorflow.autolog(log_input_examples=True, log_model_signatures=True)
    model = _create_model_for_dict_mapping()
    with mlflow.start_run() as run:
        model.fit(random_train_dict_mapping, random_one_hot_labels)
        model_path = os.path.join(run.info.artifact_uri, "model")
        model_conf = Model.load(os.path.join(model_path, "MLmodel"))
        input_example = _read_example(model_conf, model_path)
        for k, v in random_train_dict_mapping.items():
            np.testing.assert_array_almost_equal(input_example[k], np.take(v, range(0, 5)))
        pyfunc_model = mlflow.pyfunc.load_model(os.path.join(run.info.artifact_uri, "model"))
        pyfunc_model.predict(input_example)


def test_keras_autolog_infers_model_signature_correctly_with_dict(
    random_train_dict_mapping, random_one_hot_labels
):
    mlflow.tensorflow.autolog(log_model_signatures=True)
    model = _create_model_for_dict_mapping()
    with mlflow.start_run() as run:
        model.fit(random_train_dict_mapping, random_one_hot_labels)
        _assert_autolog_infers_model_signature_correctly(
            run,
            [
                {"name": "a", "type": "tensor", "tensor-spec": {"dtype": "float64", "shape": [-1]}},
                {"name": "b", "type": "tensor", "tensor-spec": {"dtype": "float64", "shape": [-1]}},
                {"name": "c", "type": "tensor", "tensor-spec": {"dtype": "float64", "shape": [-1]}},
                {"name": "d", "type": "tensor", "tensor-spec": {"dtype": "float64", "shape": [-1]}},
            ],
            [{"type": "tensor", "tensor-spec": {"dtype": "float32", "shape": [-1, 3]}}],
        )


def test_keras_autolog_input_example_load_and_predict_with_keras_sequence(keras_data_gen_sequence):
    mlflow.tensorflow.autolog(log_input_examples=True, log_model_signatures=True)
    model = create_tf_keras_model()
    with mlflow.start_run() as run:
        model.fit(keras_data_gen_sequence)
        _assert_keras_autolog_input_example_load_and_predict_with_nparray(
            run, keras_data_gen_sequence[:][0][:5]
        )


def test_keras_autolog_infers_model_signature_correctly_with_keras_sequence(
    keras_data_gen_sequence,
):
    mlflow.tensorflow.autolog(log_model_signatures=True)
    initial_model = create_tf_keras_model()
    with mlflow.start_run() as run:
        initial_model.fit(keras_data_gen_sequence)
        _assert_autolog_infers_model_signature_correctly(
            run,
            [{"type": "tensor", "tensor-spec": {"dtype": "float64", "shape": [-1, 4]}}],
            [{"type": "tensor", "tensor-spec": {"dtype": "float32", "shape": [-1, 3]}}],
        )


def test_keras_autolog_does_not_log_model_signature_when_mlflow_autolog_called(
    keras_data_gen_sequence,
):
    mlflow.autolog()
    initial_model = create_tf_keras_model()
    initial_model.fit(keras_data_gen_sequence)

    mlmodel_path = mlflow.artifacts.download_artifacts(
        f"runs:/{mlflow.last_active_run().info.run_id}/model/MLmodel"
    )
    mlmodel_contents = yaml.safe_load(open(mlmodel_path, "r"))
    assert "signature" not in mlmodel_contents, mlmodel_contents.keys()


def test_extract_tf_keras_input_example_unsupported_type_returns_None():
    from mlflow.tensorflow._autolog import extract_tf_keras_input_example

    extracted_data = extract_tf_keras_input_example([1, 2, 4, 5])
    assert extracted_data is None, (
        "Keras input data extraction function should have "
        "returned None as input type is not supported."
    )


def test_extract_input_example_from_tf_input_fn_unsupported_type_returns_None():
    from mlflow.tensorflow._autolog import extract_tf_keras_input_example

    extracted_data = extract_tf_keras_input_example(lambda: [1, 2, 4, 5])
    assert extracted_data is None, (
        "Tensorflow's input_fn training data extraction should have"
        " returned None as input type is not supported."
    )
