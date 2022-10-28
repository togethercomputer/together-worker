import influxdb_client, os, time
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import ASYNCHRONOUS

token = os.environ.get("INFLUXDB_TOKEN","")
org = os.environ.get("INFLUXDB_ORG","")
url = os.environ.get("INFLUXDB_URL","")

client = influxdb_client.InfluxDBClient(url=url, token=token, org=org)