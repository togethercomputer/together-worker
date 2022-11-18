from typing import Any, Dict, Optional, cast

from pynvml.smi import nvidia_smi


def gpu_measure() -> Optional[Dict[str, Any]]:
    nvsmi = nvidia_smi.getInstance()
    if nvsmi:
        device_info = nvsmi.DeviceQuery(
            'timestamp, power.draw, gpu_name,utilization.gpu, memory.free, memory.used, memory.total')
        return cast(Dict[str, Any], device_info)
    else:
        return None
