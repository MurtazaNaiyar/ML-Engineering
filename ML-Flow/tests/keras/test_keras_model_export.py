from packaging.version import Version
import h5py
import os
import pytest
import shutil
import importlib
import random
import json

import tensorflow as tf

# pylint: disable=no-name-in-module
from tensorflow.keras.models import Sequential as TfSequential
from tensorflow.keras.layers import Dense as TfDense
from tensorflow.keras.optimizers import SGD as TfSGD
import sklearn.datasets as datasets
import pandas as pd
import numpy as np
import yaml
from unittest import mock

import mlflow
import mlflow.keras
import mlflow.pyfunc.scoring_server as pyfunc_scoring_server
from mlflow import pyfunc
from mlflow.exceptions import MlflowException
from mlflow.models import Model, infer_signature
from mlflow.models.utils import _read_example
from mlflow.store.artifact.s3_artifact_repo import S3ArtifactRepository
from mlflow.tracking.artifact_utils import _download_artifact_from_uri
from mlflow.utils.environment import _mlflow_conda_env
from mlflow.utils.file_utils import TempDir
from mlflow.utils.model_utils import _get_flavor_configuration
from tests.helper_functions import pyfunc_serve_and_score_model
from tests.helper_functions import (
    _compare_conda_env_requirements,
    _assert_pip_requirements,
    _is_available_on_pypi,
    _is_importable,
    _compare_logged_code_paths,
)
from tests.helper_functions import PROTOBUF_REQUIREMENT
from tests.pyfunc.test_spark import score_model_as_udf
from mlflow.tracking._model_registry import DEFAULT_AWAIT_MAX_SLEEP_SECONDS


import keras

# pylint: disable=no-name-in-module,reimported
keras_version = Version(keras.__version__)
if keras_version >= Version("2.6.0"):
    from tensorflow import keras
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import Layer, Dense
    from tensorflow.keras import backend as K
    from tensorflow.keras.optimizers import SGD
else:
    from keras.models import Sequential
    from keras.layers import Layer, Dense
    from keras import backend as K
    from keras.optimizers import SGD


EXTRA_PYFUNC_SERVING_TEST_ARGS = (
    [] if _is_available_on_pypi("keras") else ["--env-manager", "local"]
)
extra_pip_requirements = [PROTOBUF_REQUIREMENT] if keras_version < Version("2.6.0") else []


@pytest.fixture(scope="module", autouse=True)
def fix_random_seed():
    SEED = 0
    os.environ["PYTHONHASHSEED"] = str(SEED)
    random.seed(SEED)
    np.random.seed(SEED)

    if Version(tf.__version__) >= Version("2.0.0"):
        tf.random.set_seed(SEED)
    else:
        tf.set_random_seed(SEED)


@pytest.fixture(scope="module")
def data():
    return datasets.load_iris(as_frame=True, return_X_y=True)


def get_model(data):
    x, y = data
    model = Sequential()
    model.add(Dense(3, input_dim=4))
    model.add(Dense(1))
    # Use a small learning rate to prevent exploding gradients which may produce
    # infinite prediction values
    lr = 0.001
    kwargs = (
        # `lr` was renamed to `learning_rate` in keras 2.3.0:
        # https://github.com/keras-team/keras/releases/tag/2.3.0
        {"lr": lr}
        if keras_version < Version("2.3.0")
        else {"learning_rate": lr}
    )
    model.compile(loss="mean_squared_error", optimizer=SGD(**kwargs))
    model.fit(x.values, y.values)
    return model


@pytest.fixture(scope="module")
def model(data):
    return get_model(data)


def get_tf_keras_model(data):
    x, y = data
    model = TfSequential()
    model.add(TfDense(3, input_dim=4))
    model.add(TfDense(1))
    model.compile(loss="mean_squared_error", optimizer=TfSGD(learning_rate=0.001))
    model.fit(x.values, y.values)
    return model


@pytest.fixture(scope="module")
def tf_keras_model(data):
    return get_tf_keras_model(data)


@pytest.fixture(scope="module")
def predicted(model, data):
    return model.predict(data[0].values)


@pytest.fixture(scope="module")
def custom_layer():
    class MyDense(Layer):
        def __init__(self, output_dim, **kwargs):
            self.output_dim = output_dim
            super().__init__(**kwargs)

        def build(self, input_shape):
            # pylint: disable=attribute-defined-outside-init
            self.kernel = self.add_weight(
                name="kernel",
                shape=(input_shape[1], self.output_dim),
                initializer="uniform",
                trainable=True,
            )
            super().build(input_shape)

        def call(self, inputs):  # pylint: disable=arguments-differ
            return K.dot(inputs, self.kernel)

        def compute_output_shape(self, input_shape):
            return (input_shape[0], self.output_dim)

        def get_config(self):
            return {"output_dim": self.output_dim}

    return MyDense


@pytest.fixture(scope="module")
def custom_model(data, custom_layer):
    x, y = data
    model = Sequential()
    model.add(Dense(6, input_dim=4))
    model.add(custom_layer(1))
    model.compile(loss="mean_squared_error", optimizer="SGD")
    model.fit(x.values, y.values, epochs=1)
    return model


@pytest.fixture(scope="module")
def custom_predicted(custom_model, data):
    return custom_model.predict(data[0].values)


@pytest.fixture
def model_path(tmpdir):
    return os.path.join(tmpdir.strpath, "model")


@pytest.fixture
def keras_custom_env(tmpdir):
    conda_env = os.path.join(str(tmpdir), "conda_env.yml")
    _mlflow_conda_env(conda_env, additional_pip_deps=["keras", "tensorflow", "pytest"])
    return conda_env


@pytest.mark.allow_infer_pip_requirements_fallback
def test_that_keras_module_arg_works(model_path):
    class MyModel:
        def __init__(self, x):
            self._x = x

        def __eq__(self, other):
            return self._x == other._x

        def save(self, path, **kwargs):
            # pylint: disable=unused-argument
            with h5py.File(path, "w") as f:
                f.create_dataset(name="x", data=self._x)

    class FakeKerasModule:
        __name__ = "some.test.keras.module"
        __version__ = "42.42.42"

        @staticmethod
        def load_model(file, **kwargs):
            # pylint: disable=unused-argument

            # `Dataset.value` was removed in `h5py == 3.0.0`
            if Version(h5py.__version__) >= Version("3.0.0"):
                return MyModel(file.get("x")[()].decode("utf-8"))
            else:
                return MyModel(file.get("x").value)

    original_import = importlib.import_module

    def _import_module(name, **kwargs):
        if name.startswith(FakeKerasModule.__name__):
            return FakeKerasModule
        else:
            return original_import(name, **kwargs)

    with mock.patch("importlib.import_module") as import_module_mock:
        import_module_mock.side_effect = _import_module
        x = MyModel("x123")
        path0 = os.path.join(model_path, "0")
        with pytest.raises(MlflowException, match="Unable to infer keras module from the model"):
            mlflow.keras.save_model(x, path0)
        mlflow.keras.save_model(x, path0, keras_module=FakeKerasModule, save_format="h5")
        y = mlflow.keras.load_model(path0)
        assert x == y
        path1 = os.path.join(model_path, "1")
        mlflow.keras.save_model(x, path1, keras_module=FakeKerasModule.__name__, save_format="h5")
        z = mlflow.keras.load_model(path1)
        assert x == z
        # Tests model log
        with mlflow.start_run() as active_run:
            with pytest.raises(
                MlflowException, match="Unable to infer keras module from the model"
            ):
                mlflow.keras.log_model(x, "model0")
            mlflow.keras.log_model(x, "model0", keras_module=FakeKerasModule, save_format="h5")
            a = mlflow.keras.load_model("runs:/{}/model0".format(active_run.info.run_id))
            assert x == a
            mlflow.keras.log_model(
                x, "model1", keras_module=FakeKerasModule.__name__, save_format="h5"
            )
            b = mlflow.keras.load_model("runs:/{}/model1".format(active_run.info.run_id))
            assert x == b


@pytest.mark.parametrize(
    "build_model,save_format",
    [
        (get_model, None),
        (get_tf_keras_model, None),
        (get_tf_keras_model, "h5"),
        (get_tf_keras_model, "tf"),
    ],
)
def test_model_save_load(build_model, save_format, model_path, data):
    x, _ = data
    keras_model = build_model(data)
    if build_model == get_tf_keras_model:
        model_path = os.path.join(model_path, "tf")
    else:
        model_path = os.path.join(model_path, "plain")
    expected = keras_model.predict(x.values)
    kwargs = {"save_format": save_format} if save_format else {}
    mlflow.keras.save_model(keras_model, model_path, **kwargs)
    # Loading Keras model
    model_loaded = mlflow.keras.load_model(model_path)
    # When saving as SavedModel, we actually convert the model
    # to a slightly different format, so we cannot assume it is
    # exactly the same.
    if save_format != "tf":
        assert type(keras_model) == type(model_loaded)
    np.testing.assert_allclose(model_loaded.predict(x.values), expected, rtol=1e-5)
    # Loading pyfunc model
    pyfunc_loaded = mlflow.pyfunc.load_model(model_path)
    np.testing.assert_allclose(pyfunc_loaded.predict(x).values, expected, rtol=1e-5)


def test_pyfunc_serve_and_score(data):
    x, _ = data
    model = get_model(data)
    with mlflow.start_run():
        model_info = mlflow.keras.log_model(
            model,
            "model",
            extra_pip_requirements=[PROTOBUF_REQUIREMENT],
        )
    expected = model.predict(x.values)
    scoring_response = pyfunc_serve_and_score_model(
        model_uri=model_info.model_uri,
        data=pd.DataFrame(x),
        content_type=pyfunc_scoring_server.CONTENT_TYPE_JSON_SPLIT_ORIENTED,
        extra_args=EXTRA_PYFUNC_SERVING_TEST_ARGS,
    )
    actual_scoring_response = pd.read_json(
        scoring_response.content.decode("utf-8"), orient="records", encoding="utf8"
    ).values.astype(np.float32)
    np.testing.assert_allclose(actual_scoring_response, expected, rtol=1e-5)


def test_score_model_as_spark_udf(data):
    x, _ = data
    model = get_model(data)
    with mlflow.start_run():
        model_info = mlflow.keras.log_model(model, "model")
    expected = model.predict(x.values)
    spark_udf_preds = score_model_as_udf(
        model_uri=model_info.model_uri, pandas_df=pd.DataFrame(x), result_type="float"
    )
    np.testing.assert_allclose(
        np.array(spark_udf_preds), expected.reshape(len(spark_udf_preds)), rtol=1e-5
    )


def test_signature_and_examples_are_saved_correctly(model, data):
    signature_ = infer_signature(*data)
    example_ = data[0].head(3)
    for signature in (None, signature_):
        for example in (None, example_):
            with TempDir() as tmp:
                path = tmp.path("model")
                mlflow.keras.save_model(
                    model, path=path, signature=signature, input_example=example
                )
                mlflow_model = Model.load(path)
                assert signature == mlflow_model.signature
                if example is None:
                    assert mlflow_model.saved_input_example_info is None
                else:
                    assert all((_read_example(mlflow_model, path) == example).all())


def test_custom_model_save_load(custom_model, custom_layer, data, custom_predicted, model_path):
    x, _ = data
    custom_objects = {"MyDense": custom_layer}
    mlflow.keras.save_model(custom_model, model_path, custom_objects=custom_objects)
    # Loading Keras model
    model_loaded = mlflow.keras.load_model(model_path)
    assert all(model_loaded.predict(x.values) == custom_predicted)
    # Loading pyfunc model
    pyfunc_loaded = mlflow.pyfunc.load_model(model_path)
    assert all(pyfunc_loaded.predict(x).values == custom_predicted)


@pytest.mark.allow_infer_pip_requirements_fallback
def test_custom_model_save_respects_user_custom_objects(custom_model, custom_layer, model_path):
    class DifferentCustomLayer:
        def __init__(self):
            pass

        def __call__(self):
            pass

    incorrect_custom_objects = {"MyDense": DifferentCustomLayer()}
    correct_custom_objects = {"MyDense": custom_layer}
    mlflow.keras.save_model(custom_model, model_path, custom_objects=incorrect_custom_objects)
    model_loaded = mlflow.keras.load_model(model_path, custom_objects=correct_custom_objects)
    assert model_loaded is not None
    with pytest.raises(TypeError, match=r".+"):
        model_loaded = mlflow.keras.load_model(model_path)


def test_model_load_from_remote_uri_succeeds(model, model_path, mock_s3_bucket, data, predicted):
    x, _ = data
    mlflow.keras.save_model(model, model_path)

    artifact_root = "s3://{bucket_name}".format(bucket_name=mock_s3_bucket)
    artifact_path = "model"
    artifact_repo = S3ArtifactRepository(artifact_root)
    artifact_repo.log_artifacts(model_path, artifact_path=artifact_path)

    model_uri = artifact_root + "/" + artifact_path
    model_loaded = mlflow.keras.load_model(model_uri=model_uri)
    assert all(model_loaded.predict(x.values) == predicted)


def test_model_log(model, data, predicted):
    x, _ = data
    # should_start_run tests whether or not calling log_model() automatically starts a run.
    for should_start_run in [False, True]:
        try:
            if should_start_run:
                mlflow.start_run()
            artifact_path = "keras_model"
            model_info = mlflow.keras.log_model(model, artifact_path=artifact_path)
            model_uri = "runs:/{run_id}/{artifact_path}".format(
                run_id=mlflow.active_run().info.run_id, artifact_path=artifact_path
            )
            assert model_info.model_uri == model_uri

            # Load model
            model_loaded = mlflow.keras.load_model(model_uri=model_uri)
            assert all(model_loaded.predict(x.values) == predicted)

            # Loading pyfunc model
            pyfunc_loaded = mlflow.pyfunc.load_model(model_uri=model_uri)
            assert all(pyfunc_loaded.predict(x).values == predicted)
        finally:
            mlflow.end_run()


def test_log_model_calls_register_model(model):
    artifact_path = "model"
    register_model_patch = mock.patch("mlflow.register_model")
    with mlflow.start_run(), register_model_patch:
        mlflow.keras.log_model(
            model, artifact_path=artifact_path, registered_model_name="AdsModel1"
        )
        model_uri = "runs:/{run_id}/{artifact_path}".format(
            run_id=mlflow.active_run().info.run_id, artifact_path=artifact_path
        )
        mlflow.register_model.assert_called_once_with(
            model_uri, "AdsModel1", await_registration_for=DEFAULT_AWAIT_MAX_SLEEP_SECONDS
        )


def test_log_model_no_registered_model_name(model):
    artifact_path = "model"
    register_model_patch = mock.patch("mlflow.register_model")
    with mlflow.start_run(), register_model_patch:
        mlflow.keras.log_model(model, artifact_path=artifact_path)
        mlflow.register_model.assert_not_called()


def test_model_save_persists_specified_conda_env_in_mlflow_model_directory(
    model, model_path, keras_custom_env
):
    mlflow.keras.save_model(keras_model=model, path=model_path, conda_env=keras_custom_env)

    pyfunc_conf = _get_flavor_configuration(model_path=model_path, flavor_name=pyfunc.FLAVOR_NAME)
    saved_conda_env_path = os.path.join(model_path, pyfunc_conf[pyfunc.ENV])
    assert os.path.exists(saved_conda_env_path)
    assert saved_conda_env_path != keras_custom_env

    with open(keras_custom_env, "r") as f:
        keras_custom_env_parsed = yaml.safe_load(f)
    with open(saved_conda_env_path, "r") as f:
        saved_conda_env_parsed = yaml.safe_load(f)
    assert saved_conda_env_parsed == keras_custom_env_parsed


def test_model_save_accepts_conda_env_as_dict(model, model_path):
    conda_env = dict(mlflow.keras.get_default_conda_env())
    conda_env["dependencies"].append("pytest")
    mlflow.keras.save_model(keras_model=model, path=model_path, conda_env=conda_env)

    pyfunc_conf = _get_flavor_configuration(model_path=model_path, flavor_name=pyfunc.FLAVOR_NAME)
    saved_conda_env_path = os.path.join(model_path, pyfunc_conf[pyfunc.ENV])
    assert os.path.exists(saved_conda_env_path)

    with open(saved_conda_env_path, "r") as f:
        saved_conda_env_parsed = yaml.safe_load(f)
    assert saved_conda_env_parsed == conda_env


def test_model_save_persists_requirements_in_mlflow_model_directory(
    model, model_path, keras_custom_env
):
    mlflow.keras.save_model(keras_model=model, path=model_path, conda_env=keras_custom_env)

    saved_pip_req_path = os.path.join(model_path, "requirements.txt")
    _compare_conda_env_requirements(keras_custom_env, saved_pip_req_path)


def test_log_model_with_pip_requirements(model, tmpdir):
    # Path to a requirements file
    req_file = tmpdir.join("requirements.txt")
    req_file.write("a")
    with mlflow.start_run():
        mlflow.keras.log_model(model, "model", pip_requirements=req_file.strpath)
        _assert_pip_requirements(mlflow.get_artifact_uri("model"), ["mlflow", "a"], strict=True)

    # List of requirements
    with mlflow.start_run():
        mlflow.keras.log_model(model, "model", pip_requirements=[f"-r {req_file.strpath}", "b"])
        _assert_pip_requirements(
            mlflow.get_artifact_uri("model"), ["mlflow", "a", "b"], strict=True
        )

    # Constraints file
    with mlflow.start_run():
        mlflow.keras.log_model(model, "model", pip_requirements=[f"-c {req_file.strpath}", "b"])
        _assert_pip_requirements(
            mlflow.get_artifact_uri("model"),
            ["mlflow", "b", "-c constraints.txt"],
            ["a"],
            strict=True,
        )


def test_log_model_with_extra_pip_requirements(model, tmpdir):
    default_reqs = mlflow.keras.get_default_pip_requirements()
    # Path to a requirements file
    req_file = tmpdir.join("requirements.txt")
    req_file.write("a")
    with mlflow.start_run():
        mlflow.keras.log_model(model, "model", extra_pip_requirements=req_file.strpath)
        _assert_pip_requirements(mlflow.get_artifact_uri("model"), ["mlflow", *default_reqs, "a"])

    # List of requirements
    with mlflow.start_run():
        mlflow.keras.log_model(
            model,
            "model",
            extra_pip_requirements=[f"-r {req_file.strpath}", "b"],
        )
        _assert_pip_requirements(
            mlflow.get_artifact_uri("model"), ["mlflow", *default_reqs, "a", "b"]
        )

    # Constraints file
    with mlflow.start_run():
        mlflow.keras.log_model(
            model,
            "model",
            extra_pip_requirements=[f"-c {req_file.strpath}", "b"],
        )
        _assert_pip_requirements(
            mlflow.get_artifact_uri("model"),
            ["mlflow", *default_reqs, "b", "-c constraints.txt"],
            ["a"],
        )


def test_model_log_persists_requirements_in_mlflow_model_directory(model, keras_custom_env):
    artifact_path = "model"
    with mlflow.start_run():
        mlflow.keras.log_model(
            keras_model=model, artifact_path=artifact_path, conda_env=keras_custom_env
        )
        model_path = _download_artifact_from_uri(
            "runs:/{run_id}/{artifact_path}".format(
                run_id=mlflow.active_run().info.run_id, artifact_path=artifact_path
            )
        )

    saved_pip_req_path = os.path.join(model_path, "requirements.txt")
    _compare_conda_env_requirements(keras_custom_env, saved_pip_req_path)


def test_model_log_persists_specified_conda_env_in_mlflow_model_directory(model, keras_custom_env):
    artifact_path = "model"
    with mlflow.start_run():
        mlflow.keras.log_model(
            keras_model=model, artifact_path=artifact_path, conda_env=keras_custom_env
        )
        model_path = _download_artifact_from_uri(
            "runs:/{run_id}/{artifact_path}".format(
                run_id=mlflow.active_run().info.run_id, artifact_path=artifact_path
            )
        )

    pyfunc_conf = _get_flavor_configuration(model_path=model_path, flavor_name=pyfunc.FLAVOR_NAME)
    saved_conda_env_path = os.path.join(model_path, pyfunc_conf[pyfunc.ENV])
    assert os.path.exists(saved_conda_env_path)
    assert saved_conda_env_path != keras_custom_env

    with open(keras_custom_env, "r") as f:
        keras_custom_env_parsed = yaml.safe_load(f)
    with open(saved_conda_env_path, "r") as f:
        saved_conda_env_parsed = yaml.safe_load(f)
    assert saved_conda_env_parsed == keras_custom_env_parsed


def test_model_save_without_specified_conda_env_uses_default_env_with_expected_dependencies(
    model, model_path
):
    mlflow.keras.save_model(keras_model=model, path=model_path)
    _assert_pip_requirements(model_path, mlflow.keras.get_default_pip_requirements())


def test_model_log_without_specified_conda_env_uses_default_env_with_expected_dependencies(model):
    artifact_path = "model"
    with mlflow.start_run():
        mlflow.keras.log_model(keras_model=model, artifact_path=artifact_path)
        model_uri = mlflow.get_artifact_uri(artifact_path)
    _assert_pip_requirements(model_uri, mlflow.keras.get_default_pip_requirements())


def test_model_load_succeeds_with_missing_data_key_when_data_exists_at_default_path(
    tf_keras_model, model_path, data
):
    """
    This is a backwards compatibility test to ensure that models saved in MLflow version <= 0.8.0
    can be loaded successfully. These models are missing the `data` flavor configuration key.
    """
    mlflow.keras.save_model(keras_model=tf_keras_model, path=model_path, save_format="h5")
    shutil.move(os.path.join(model_path, "data", "model.h5"), os.path.join(model_path, "model.h5"))
    model_conf_path = os.path.join(model_path, "MLmodel")
    model_conf = Model.load(model_conf_path)
    flavor_conf = model_conf.flavors.get(mlflow.keras.FLAVOR_NAME, None)
    assert flavor_conf is not None
    del flavor_conf["data"]
    model_conf.save(model_conf_path)

    model_loaded = mlflow.keras.load_model(model_path)
    assert all(model_loaded.predict(data[0].values) == tf_keras_model.predict(data[0].values))


@pytest.mark.allow_infer_pip_requirements_fallback
def test_save_model_with_tf_save_format(model_path):
    """Ensures that Keras models can be saved with SavedModel format.

    Using SavedModel format (save_format="tf") requires that the file extension
    is _not_ "h5".
    """
    keras_model = mock.Mock(spec=tf.keras.Model)
    mlflow.keras.save_model(keras_model=keras_model, path=model_path, save_format="tf")
    _, args, kwargs = keras_model.save.mock_calls[0]
    # Ensure that save_format propagated through
    assert kwargs["save_format"] == "tf"
    # Ensure that the saved model does not have h5 extension
    assert not args[0].endswith(".h5")


def test_save_and_load_model_with_tf_save_format(tf_keras_model, model_path):
    """Ensures that keras models saved with save_format="tf" can be loaded."""
    mlflow.keras.save_model(keras_model=tf_keras_model, path=model_path, save_format="tf")
    model_conf_path = os.path.join(model_path, "MLmodel")
    model_conf = Model.load(model_conf_path)
    flavor_conf = model_conf.flavors.get(mlflow.keras.FLAVOR_NAME, None)
    assert flavor_conf is not None
    assert flavor_conf.get("save_format") == "tf"
    assert not os.path.exists(
        os.path.join(model_path, "data", "model.h5")
    ), "TF model was saved with HDF5 format; expected SavedModel"
    assert os.path.isdir(
        os.path.join(model_path, "data", "model")
    ), "Expected directory containing saved_model.pb"

    model_loaded = mlflow.keras.load_model(model_path)
    assert tf_keras_model.to_json() == model_loaded.to_json()


def test_load_without_save_format(tf_keras_model, model_path):
    """Ensures that keras models without save_format can still be loaded."""
    mlflow.keras.save_model(tf_keras_model, model_path, save_format="h5")
    model_conf_path = os.path.join(model_path, "MLmodel")
    model_conf = Model.load(model_conf_path)
    flavor_conf = model_conf.flavors.get(mlflow.keras.FLAVOR_NAME)
    assert flavor_conf is not None
    del flavor_conf["save_format"]
    model_conf.save(model_conf_path)

    model_loaded = mlflow.keras.load_model(model_path)
    assert tf_keras_model.to_json() == model_loaded.to_json()


@pytest.mark.skipif(
    not _is_importable("transformers"),
    reason="This test requires transformers, which is incompatible with Keras < 2.3.0",
)
def test_pyfunc_serve_and_score_transformers():
    from transformers import BertConfig, TFBertModel  # pylint: disable=import-error

    bert = TFBertModel(
        BertConfig(
            vocab_size=16,
            hidden_size=2,
            num_hidden_layers=2,
            num_attention_heads=2,
            intermediate_size=2,
        )
    )
    dummy_inputs = bert.dummy_inputs["input_ids"].numpy()
    input_ids = tf.keras.layers.Input(shape=(dummy_inputs.shape[1],), dtype=tf.int32)
    model = tf.keras.Model(inputs=[input_ids], outputs=[bert(input_ids).last_hidden_state])
    model.compile()

    with mlflow.start_run():
        mlflow.keras.log_model(
            model,
            artifact_path="model",
            keras_module=tf.keras,
            extra_pip_requirements=extra_pip_requirements,
        )
        model_uri = mlflow.get_artifact_uri("model")

    data = json.dumps({"inputs": dummy_inputs.tolist()})
    resp = pyfunc_serve_and_score_model(model_uri, data, pyfunc_scoring_server.CONTENT_TYPE_JSON)
    np.testing.assert_array_equal(json.loads(resp.content), model.predict(dummy_inputs))


def test_log_model_with_code_paths(model):
    artifact_path = "model"
    with mlflow.start_run(), mock.patch(
        "mlflow.keras._add_code_from_conf_to_system_path"
    ) as add_mock:
        mlflow.keras.log_model(model, artifact_path, code_paths=[__file__])
        model_uri = mlflow.get_artifact_uri(artifact_path)
        _compare_logged_code_paths(__file__, model_uri, mlflow.keras.FLAVOR_NAME)
        mlflow.keras.load_model(model_uri)
        add_mock.assert_called()
