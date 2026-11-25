# Databricks notebook source
# MAGIC %md
# MAGIC # Load the synthetic cohort data
# MAGIC
# MAGIC Writes the four tables the MCP server reads (`master_patient`,
# MAGIC `chronic_conditions`, `ed_episodes`, `program_members`) into
# MAGIC `<catalog>.<schema>`, replacing any that are already there. The data is
# MAGIC made up, with a planted programme effect (rate ratio 0.70) and a planted
# MAGIC selection bias, from `backend/app/seed/synthetic.py`.
# MAGIC
# MAGIC Run it from the Git folder, on serverless compute or any cluster. Set the
# MAGIC widgets first. If the catalog or schema differs from `workspace.cohort`,
# MAGIC change the table names in `backend/config/mapping.yaml` to match.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "cohort")
dbutils.widgets.text("patients", "2000")
dbutils.widgets.text("seed", "7")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
patients = int(dbutils.widgets.get("patients"))
seed = int(dbutils.widgets.get("seed"))

for name in (catalog, schema):
    if not name.replace("_", "").isalnum():
        raise ValueError(f"Not a plain identifier: {name!r}")

# COMMAND ----------

import os
import sys

# The notebook runs in its own folder; the generator is in ../backend.
sys.path.insert(0, os.path.abspath(os.path.join(os.getcwd(), "..", "backend")))

from pyspark.sql import functions as F  # noqa: E402

from app.seed import synthetic  # noqa: E402

tables = synthetic.generate(patients=patients, seed=seed)
DATE_COLUMNS = {"date_of_birth", "attendance_date", "enrollment_date"}

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")

for table, frame in tables.items():
    df = spark.createDataFrame(frame)
    for column in DATE_COLUMNS & set(frame.columns):
        df = df.withColumn(column, F.to_date(column))
    (
        df.write.mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(f"{catalog}.{schema}.{table}")
    )
    print(f"{catalog}.{schema}.{table}: {len(frame)} rows")
