from pynvml.smi import nvidia_smi
from typing import Dict, List, Union

def gpu_measure() -> Union[dict, None]:
    nvsmi = nvidia_smi.getInstance()
    if nvsmi:
        device_info = nvsmi.DeviceQuery('timestamp, power.draw, gpu_name,utilization.gpu, memory.free, memory.used, memory.total')
        return device_info
    else:
        return None
