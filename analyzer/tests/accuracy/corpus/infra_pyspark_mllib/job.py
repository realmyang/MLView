"""A Spark MLlib job — a framework MLView carries no knowledge table for.

The point of this program is what MLView must **not** say. Every symbol here
has a same-named, same-shaped twin in scikit-learn:

* `pyspark.ml.feature.StandardScaler` has `.fit()` and `.transform()`;
* `pyspark.ml.Pipeline` has `.fit()`;
* `pyspark.ml.tuning.CrossValidator` has `.fit()`;
* `pyspark.ml.classification.RandomForestClassifier` has `.fit()`;
* `df.randomSplit([0.8, 0.2], seed=...)` is the split.

and none of them resolves to the sklearn rows those names live on. There is a
**real** leak in this file — `scaler.fit(frame)` at line 63 is fitted on the
whole DataFrame and `randomSplit` only runs at line 68 — and MLView cannot see
it, because a Spark `StandardScaler` is not an `sklearn.preprocessing` row. The
only defensible answer is silence plus a coverage gap naming `pyspark`, and
that is what this program asserts. A finding here would be a rule matching on a
bare attribute name, which iron law 1 forbids.
"""
from __future__ import annotations

import argparse

from pyspark.ml import Pipeline
from pyspark.ml.classification import RandomForestClassifier
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.feature import StandardScaler, StringIndexer, VectorAssembler
from pyspark.ml.tuning import CrossValidator, ParamGridBuilder
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

NUMERIC = ["tenure_months", "monthly_charge", "total_charge", "tickets"]
SEED = 31


def build_session(app: str) -> SparkSession:
    return (SparkSession.builder
            .appName(app)
            .config("spark.sql.shuffle.partitions", "200")
            .config("spark.sql.adaptive.enabled", "true")
            .getOrCreate())


def read_events(spark: SparkSession, path: str):
    frame = spark.read.parquet(path)
    frame = frame.withColumn("total_charge",
                             F.col("monthly_charge") * F.col("tenure_months"))
    frame = frame.withColumn("tickets",
                             F.coalesce(F.col("support_tickets"), F.lit(0)))
    return frame.dropna(subset=NUMERIC + ["churned"])


def featurize(frame):
    """The leak MLView cannot see: the scaler is fitted before the split."""
    indexer = StringIndexer(inputCol="churned", outputCol="label")
    frame = indexer.fit(frame).transform(frame)

    assembler = VectorAssembler(inputCols=NUMERIC, outputCol="raw_features")
    frame = assembler.transform(frame)

    scaler = StandardScaler(inputCol="raw_features", outputCol="features",
                            withMean=True, withStd=True)
    scaler_model = scaler.fit(frame)
    return scaler_model.transform(frame)


def fit_and_score(frame, folds: int):
    train_df, test_df = frame.randomSplit([0.8, 0.2], seed=SEED)

    forest = RandomForestClassifier(featuresCol="features", labelCol="label",
                                    numTrees=200, maxDepth=8, seed=SEED)
    pipeline = Pipeline(stages=[forest])
    grid = (ParamGridBuilder()
            .addGrid(forest.numTrees, [100, 200, 400])
            .addGrid(forest.maxDepth, [4, 8, 12])
            .build())
    evaluator = BinaryClassificationEvaluator(labelCol="label",
                                              metricName="areaUnderROC")
    validator = CrossValidator(estimator=pipeline, estimatorParamMaps=grid,
                               evaluator=evaluator, numFolds=folds, seed=SEED,
                               parallelism=4)

    cv_model = validator.fit(train_df)
    predictions = cv_model.transform(test_df)
    auc = evaluator.evaluate(predictions)
    return cv_model, auc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Spark churn job")
    parser.add_argument("--input", default="s3a://warehouse/events/")
    parser.add_argument("--output", default="s3a://models/churn/")
    parser.add_argument("--folds", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    spark = build_session("churn-mllib")
    frame = read_events(spark, args.input)
    features = featurize(frame)
    model, auc = fit_and_score(features, args.folds)
    print("areaUnderROC %.4f" % auc)
    model.bestModel.write().overwrite().save(args.output)
    spark.stop()


if __name__ == "__main__":
    main()
