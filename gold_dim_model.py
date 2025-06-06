# Databricks notebook source
from pyspark.sql.functions import *
from pyspark.sql.types import *

# COMMAND ----------

# MAGIC %md
# MAGIC # Create Flag parameter

# COMMAND ----------

dbutils.widgets.text('incrementatl_flag','0')

# COMMAND ----------

incremental_flag = dbutils.widgets.get('incrementatl_flag')
print(incremental_flag)

# COMMAND ----------

# MAGIC %md
# MAGIC # Creating dimension model

# COMMAND ----------

# MAGIC %sql
# MAGIC select * from parquet.`abfss://silver@gkncarsdatalake.dfs.core.windows.net/carsales`

# COMMAND ----------

df_src = spark.sql('''
                   select distinct model_id, model_category 
                   from parquet.`abfss://silver@gkncarsdatalake.dfs.core.windows.net/carsales`
                   ''')

# COMMAND ----------

df_src.display()

# COMMAND ----------

# MAGIC %md
# MAGIC # Dim_model sink - Initial and Incremental

# COMMAND ----------

if spark.catalog.tableExists('cars_catalog.gold.dim_model'):
    df_sink = spark.sql('''
                    select dim_model_key, model_id, model_category 
                    from cars_catalog.gold.dim_model
                    ''')


else:
    df_sink = spark.sql('''
                    select 1 as dim_model_key, model_id, model_category 
                    from parquet.`abfss://silver@gkncarsdatalake.dfs.core.windows.net/carsales`
                    where 1=0
                    ''')

# COMMAND ----------

df_sink.display()

# COMMAND ----------

# MAGIC %md
# MAGIC # Filtering old records and new records

# COMMAND ----------

df_filter = df_src.join(df_sink,df_src['model_id'] == df_sink['model_id'],'left').select(df_src['model_id'],df_src['model_category'],df_sink['dim_model_key'])

# COMMAND ----------

df_filter.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ***df_filter_old***

# COMMAND ----------

df_filter_old = df_filter.filter(col('dim_model_key').isNotNull())
df_filter_old.display()


# COMMAND ----------

# MAGIC %md
# MAGIC ***df_filter_new***

# COMMAND ----------

df_filter_new = df_filter.filter(col('dim_model_key').isNull()).select(df_filter['model_id'],df_filter['model_category'])
df_filter_new.display()

# COMMAND ----------

# MAGIC %md
# MAGIC # create surrogate key

# COMMAND ----------

# MAGIC %md
# MAGIC ***fetch max surrogate key from existing table***

# COMMAND ----------

if incremental_flag == '0':
    max_value = 1
else:
    max_value_df = spark.sql("select max() from dim_model_key cars_catalog.gold.dim_model")
    max_value = max_value_df.collect()[0][0]



# COMMAND ----------

# MAGIC %md
# MAGIC ***create surrogate key column and add max value***

# COMMAND ----------

df_filter_new = df_filter_new.withColumn('dim_model_key',max_value+monotonically_increasing_id())
df_filter_new.display()

# COMMAND ----------

# MAGIC %md
# MAGIC # Creat Final df - df_filter_old + df_filter_new

# COMMAND ----------

df_final = df_filter_new.union(df_filter_old)

# COMMAND ----------

df_final.display()

# COMMAND ----------

from delta.tables import DeltaTable

# COMMAND ----------

# MAGIC %md
# MAGIC # SCD - Type 1(UPSERT)

# COMMAND ----------

# Incremental load
if spark.catalog.tableExists('cars_catalog.gold.dim_model'):
    delta_tbl = DeltaTable.forPath(spark, 'abfss://gold@gkncarsdatalake.dfs.core.windows.net/dim_model')
    delta_tbl.alias('target').merge(df_final.alias('source'),'target.model_id = source.model_id')\
                                    .whenMatchedUpdateAll()\
                                    .whenNotMatchedInsertAll()\
                                    .execute()


else:
    df_final.write.format('delta')\
                .mode('overwrite')\
                .option('path','abfss://gold@gkncarsdatalake.dfs.core.windows.net/dim_model')\
                .saveAsTable("cars_catalog.gold.dim_model")

# COMMAND ----------

# MAGIC %sql
# MAGIC select * from cars_catalog.gold.dim_model;