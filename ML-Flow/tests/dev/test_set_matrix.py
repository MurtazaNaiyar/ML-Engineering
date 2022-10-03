import json
import re
from unittest import mock
import tempfile
from contextlib import contextmanager
import functools
from pathlib import Path

import pytest

from dev.set_matrix import generate_matrix


class MockResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return json.dumps(self.body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    @classmethod
    def from_versions(cls, versions):
        return cls(
            {"releases": {v: [{"filename": v + ".whl", "upload_time": v}] for v in versions}}
        )


def mock_pypi_api(mock_responses):
    def urlopen_patch(url, *args, **kwargs):  # pylint: disable=unused-argument
        package_name = re.search(r"https://pypi.python.org/pypi/(.+)/json", url).group(1)
        return mock_responses[package_name]

    def decorotor(test_func):
        @functools.wraps(test_func)
        def wrapper(*args, **kwargs):
            with mock.patch("urllib.request.urlopen", new=urlopen_patch):
                return test_func(*args, **kwargs)

        return wrapper

    return decorotor


@contextmanager
def mock_ml_package_versions_yml(src_base, src_ref):
    with tempfile.TemporaryDirectory() as tmp_dir:
        yml_base = Path(tmp_dir).joinpath("base.yml")
        yml_ref = Path(tmp_dir).joinpath("ref.yml")
        yml_base.write_text(src_base)
        yml_ref.write_text(src_ref)
        yield ["--versions-yaml", str(yml_base), "--ref-versions-yaml", str(yml_ref)]


MOCK_YAML_SOURCE = """
foo:
  package_info:
    pip_release: foo
    install_dev: "pip install git+https://github.com/foo/foo.git"

  autologging:
    minimum: "1.0.0"
    maximum: "1.2.0"
    run: pytest tests/foo

bar:
  package_info:
    pip_release: bar
    install_dev: "pip install git+https://github.com/bar/bar.git"

  autologging:
    minimum: "1.3"
    maximum: "1.4"
    run: pytest/tests bar
"""

MOCK_PYPI_API_RESPONSES = {
    "foo": MockResponse.from_versions(["1.0.0", "1.1.0", "1.1.1", "1.2.0"]),
    "bar": MockResponse.from_versions(["1.3", "1.4"]),
}


@pytest.mark.parametrize(
    "flavors, expected",
    [
        ("foo", {"foo"}),
        ("foo,bar", {"foo", "bar"}),
        ("foo, bar", {"foo", "bar"}),  # Contains a space after a comma
        ("", {"foo", "bar"}),
        (None, {"foo", "bar"}),
    ],
)
@mock_pypi_api(MOCK_PYPI_API_RESPONSES)
def test_flavors(flavors, expected):
    with mock_ml_package_versions_yml(MOCK_YAML_SOURCE, "{}") as path_args:
        flavors_args = [] if flavors is None else ["--flavors", flavors]
        matrix = generate_matrix([*path_args, *flavors_args])
        flavors = set(x["flavor"] for x in matrix)
        assert flavors == expected


@pytest.mark.parametrize(
    "versions, expected",
    [
        ("1.0.0", {"1.0.0"}),
        ("1.0.0,1.1.1", {"1.0.0", "1.1.1"}),
        ("1.3, 1.4", {"1.3", "1.4"}),  # Contains a space after a comma
        ("", {"1.0.0", "1.1.1", "1.2.0", "1.3", "1.4", "dev"}),
        (None, {"1.0.0", "1.1.1", "1.2.0", "1.3", "1.4", "dev"}),
    ],
)
@mock_pypi_api(MOCK_PYPI_API_RESPONSES)
def test_versions(versions, expected):
    with mock_ml_package_versions_yml(MOCK_YAML_SOURCE, "{}") as path_args:
        versions_args = [] if versions is None else ["--versions", versions]
        matrix = generate_matrix([*path_args, *versions_args])
        versions = set(x["version"] for x in matrix)
        assert versions == expected


@mock_pypi_api(MOCK_PYPI_API_RESPONSES)
def test_flavors_and_versions():
    with mock_ml_package_versions_yml(MOCK_YAML_SOURCE, "{}") as path_args:
        matrix = generate_matrix([*path_args, "--flavors", "foo,bar", "--versions", "dev"])
        flavors = set(x["flavor"] for x in matrix)
        versions = set(x["version"] for x in matrix)
        assert set(flavors) == {"foo", "bar"}
        assert set(versions) == {"dev"}
