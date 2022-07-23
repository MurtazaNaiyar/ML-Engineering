#!/usr/bin/env bash
# Test Spark autologging against the Spark 3.0 preview. This script is temporary and should be
# removed once Spark 3.0 is released in favor of simply updating all tests to run against Spark 3.0
set -ex

# Build Java package
pushd mlflow/java/spark
mvn package -DskipTests -q
popd

# Install PySpark 3.0 preview & run tests. For faster local iteration, you can also simply download
# the .tgz used below (http://mirror.cogentco.com/pub/apache/spark/spark-3.0.0-preview/spark-3.0.0-preview-bin-hadoop2.7.tgz),
# extract it, and set SPARK_HOME to the path of the extracted folder while invoking pytest as
# shown below
version=spark-3.0.0-preview-bin-hadoop2.7
wget --no-verbose "https://archive.apache.org/dist/spark/spark-3.0.0-preview/${version}.tgz" -O /tmp/spark.tgz
tar -xf /tmp/spark.tgz --directory /tmp
pip install -e /tmp/$version/python
export SPARK_HOME=/tmp/$version
