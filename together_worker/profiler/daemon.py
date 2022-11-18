import os
import sched
import time

from client import bucket, org, write_api
from gpu_profiler import gpu_measure
from influxdb_client import Point

s = sched.scheduler(time.time, time.sleep)
worker_name = os.environ.get("WORKER_NAME", "")


def do_something(sc):
    gpu_stat = gpu_measure()
    if gpu_stat is not None:
        # for what we can get:
        # https://github.com/gpuopenanalytics/pynvml/blob/master/help_query_gpu.txt
        for stat in gpu_stat['gpu']:
            point = (
                Point("GPU Stats") .tag(
                    "worker",
                    worker_name) .field(
                    "gpu_name",
                    stat['product_name']).field(
                    "gpu_util",
                    stat['utilization']['gpu_util']).field(
                    "gpu_power",
                    stat['power_readings']['power_draw']).field(
                        "gpu_mem_free",
                        stat['fb_memory_usage']['free']).field(
                            "gpu_mem_used",
                    stat['fb_memory_usage']['used']))
            write_api.write(bucket=bucket, org=org, record=point)
    sc.enter(10, 1, do_something, (sc,))


s.enter(10, 1, do_something, (s,))
s.run()
