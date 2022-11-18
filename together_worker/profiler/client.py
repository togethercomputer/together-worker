import os

import influxdb_client
from influxdb_client.client.write_api import ASYNCHRONOUS

token = os.environ.get("INFLUXDB_TOKEN", "")
org = os.environ.get("INFLUXDB_ORG", "")
url = os.environ.get("INFLUXDB_URL", "")

client = influxdb_client.InfluxDBClient(url=url, token=token, org=org)
bucket = os.environ.get("INFLUXDB_BUCKET", "")

write_api = client.write_api(write_options=ASYNCHRONOUS)
