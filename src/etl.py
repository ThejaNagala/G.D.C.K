#!/usr/bin/env python

"""
Python script to initiate and perform the ETL process
"""

import os
import pyspark
import httpagentparser
from pyspark.sql.functions import struct
from pyspark.sql.functions import *
from os.path import abspath
from pyspark.sql import SparkSession
from pyspark.sql.types import TimestampType, StringType
from geoip import ipquery


def splitCol(_dataframe, _split, _colNames):
    """Simply creates new columns when needed

    Args:
        _dataframe: The dataframe that needs to split columns
        _split: The value to split on, ex: "-", ",", "*"
        _colNames: The new names for the new columns

    Returns:

    """
    split_col = pyspark.sql.functions.split(_dataframe[_colNames[0]], _split)
    _dataframe = _dataframe.withColumn(_colNames[1], split_col.getItem(0))
    _dataframe = _dataframe.withColumn(_colNames[2], split_col.getItem(1))
    return _dataframe


def getOsBrowser(value):
    """Calls the httpagentparser and retrieves the os and browser information

    Args:
        value: Each column value of user_agent_string

    Returns: The browser and os as a string

    """
    return str(httpagentparser.simple_detect(value)[0] + "-" + httpagentparser.simple_detect(value)[1])


def load(_df):
    """Load function to print the result and to save the dataframe for api calls

    Args:
        _df: The final dataframe

    Returns: Nothing

    """

    """ Peform load process """

    print("Top 5 countries based on number of events")
    _df.groupBy("country").count().orderBy("count", ascending=False) \
        .show(5)

    print("Top 5 cities based on number of events")
    _df.groupBy("city").count().orderBy("count", ascending=False) \
        .show(5)

    print("Top 5 Browsers based on number of unique users")

    _df.groupBy("browser").agg(countDistinct("user_id")) \
        .orderBy("count(DISTINCT user_id)", ascending=False) \
        .show(5)

    print("Top 5 Operating systems based on number of unique users")
    _df.groupBy("os").agg(countDistinct("user_id")) \
        .orderBy("count(DISTINCT user_id)", ascending=False) \
        .show(5)


def transform(_df, _spark):
    """This function handles the ransformation of the dataset (biggest part)

    Args:
        _df: Initial, unhandled dataframe straight from extraction
        _spark: sparksession

    Returns: Final and structured dataframe

    """

    """ Transformation in progress... """

    print("The dataframe is being cleaned....")

    print("date and time column is becomming one timestamp...")
    _df = _df.withColumn("timestamp", concat_ws(" ", _df.date, _df.time)).drop("date").drop("time")
    _df = _df.withColumn("timestamp", _df["timestamp"].cast(TimestampType()))

    """ Getting the browser and OS from user_agent_string (amazingly fast! wow!)"""

    print("The user_agent_string is becomming os and browser...")
    agentinfo = udf(getOsBrowser, StringType())
    _df = _df.withColumn("getOsBrowser", agentinfo(_df.user_agent_string))

    """ Cleaning Os Browser result """

    _df = splitCol(_df, "-", ["getOsBrowser", "os", "browser"]) \
        .drop("getOsBrowser") \
        .drop("user_agent_string")

    """ Cleaning IP adresses """
    _df = splitCol(_df, ",", ["ip", "ip1", "ip2"]).drop('ip')

    """ Adding eventID to the dataframe, so that we can join other dataframes """
    _df = _df.withColumn("eventID", monotonically_increasing_id())

    print("Converting IP adress to city and country... ")
    countrycityinfo = udf(ipquery, StringType())

    """ Get the countries and cities from the IP columns """
    _df = _df.withColumn("ipquery", countrycityinfo(_df.ip1))

    """ Modify ip dataframe for countries and cities of the first ip column """
    _ip = splitCol(_df, "-", ["ipquery", "country", "city"]).drop("ipquery")\
        .drop("eventID").drop("timestamp").drop("user_id").drop("url")\
        .drop("os").drop("browser").drop("ip1").drop("ip2")

    """ create a monotonically increasing id """
    _ip = _ip.withColumn("id", monotonically_increasing_id())

    """ Merge countries and cities to org dataframes """

    ret_df = _df.join(_ip, _df.eventID == _ip.id)
    ret_df = ret_df.drop("ip1").drop("ip2").drop("ipquery")
    ret_df = ret_df.orderBy("eventID", ascending=True)
    ret_df = ret_df.select("eventID", "timestamp", "user_id", "url", "os", "browser", "country", "city")

    """ Remove all null values from country """

    ret_df = ret_df.filter(ret_df.country.isNotNull())

    """ Return the loaded dataframe, ready to be used for examination """

    return ret_df


def extract(_spark):
    """Extracting the tsv file into a DataFrame

    Args:
        _spark: The actual spark session

    Returns: Initial dataframe before transform

    """
    cwd = os.getcwd()
    """ Initial read of the given TSV file """
    _df = _spark.read.option("delimiter", "\t")\
        .csv(cwd + "/src/data/input_data")\
        .toDF("date", "time", "user_id", "url", "ip", "user_agent_string")

    _spark.sparkContext.setLogLevel("WARN")

    return _df


if __name__ == "__main__":
    """ Initial setup of spark project """
    warehouse_location = abspath('spark-warehouse')
    spark = SparkSession \
        .builder \
        .appName("CitiesCountriesTest") \
        .config("spark.sql.warehouse.dir", warehouse_location) \
        .enableHiveSupport() \
        .getOrCreate()

    """
    Perform extraction
    """
    print("Perform extraction")
    df = extract(spark)

    """
    Perform transformation
    """
    print("Perform transformation")
    df = transform(df, spark)

    print("Printing Transformed Dataframe Schema")
    df.printSchema()

    """
    Load the data, do some printing, make it searchable for the API, maybe a postgres
    """
    print("Perform load")
    load(df)

    print("Spark application ends")

    """ Stop spark application """
    spark.stop()
