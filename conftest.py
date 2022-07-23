import os
import posixpath
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--requires-ssh",
        action="store_true",
        dest="requires_ssh",
        default=False,
        help="Run tests decorated with 'requires_ssh' annotation. "
        "These tests require keys to be configured locally "
        "for SSH authentication.",
    )
    parser.addoption(
        "--ignore-flavors",
        action="store_true",
        dest="ignore_flavors",
        default=False,
        help="Ignore tests for model flavors.",
    )


def pytest_configure(config):
    # Register markers to suppress `PytestUnknownMarkWarning`
    config.addinivalue_line("markers", "requires_ssh")
    config.addinivalue_line("markers", "notrackingurimock")
    config.addinivalue_line("markers", "allow_infer_pip_requirements_fallback")


def pytest_runtest_setup(item):
    markers = [mark.name for mark in item.iter_markers()]
    if "requires_ssh" in markers and not item.config.getoption("--requires-ssh"):
        pytest.skip("use `--requires-ssh` to run this test")


@pytest.hookimpl(hookwrapper=True)
def pytest_ignore_collect(path, config):
    outcome = yield
    if not outcome.get_result() and config.getoption("ignore_flavors"):
        # If not ignored by the default hook and `--ignore-flavors` specified

        # Ignored files and directories must be included in dev/run-python-flavor-tests.sh
        model_flavors = [
            "tests/h2o",
            "tests/keras",
            "tests/pytorch",
            "tests/pyfunc",
            "tests/sagemaker",
            "tests/sklearn",
            "tests/spark",
            "tests/mleap",
            "tests/tensorflow",
            "tests/azureml",
            "tests/onnx",
            "tests/gluon",
            "tests/xgboost",
            "tests/lightgbm",
            "tests/catboost",
            "tests/statsmodels",
            "tests/spacy",
            "tests/fastai",
            "tests/models",
            "tests/shap",
            "tests/paddle",
            "tests/prophet",
            "tests/pmdarima",
            "tests/diviner",
            "tests/test_mlflow_lazily_imports_ml_packages.py",
            "tests/utils/test_model_utils.py",
            # this test is included here because it imports many big libraries like tf, keras, etc
            "tests/tracking/fluent/test_fluent_autolog.py",
            # cross flavor autologging related tests.
            "tests/autologging/test_autologging_safety_unit.py",
            "tests/autologging/test_autologging_behaviors_unit.py",
            "tests/autologging/test_autologging_behaviors_integration.py",
            "tests/autologging/test_autologging_utils.py",
            "tests/autologging/test_training_session.py",
        ]

        relpath = os.path.relpath(str(path))
        relpath = relpath.replace(os.sep, posixpath.sep)  # for Windows

        if relpath in model_flavors:
            outcome.force_result(True)
