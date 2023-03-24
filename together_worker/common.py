from typing import Any, Dict, List

import ipaddress
import logging
import multiprocessing
import platform
import socket
import time
from dataclasses import asdict
from enum import Enum

import netifaces
from pynvml import (
    nvmlDeviceGetCount,
    nvmlDeviceGetHandleByIndex,
    nvmlDeviceGetMemoryInfo,
    nvmlDeviceGetName,
)
from together_web3.computer import Instance, ResourceTypeInstance
from together_web3.coordinator import Join, JoinEnvelope
from together_web3.together import TogetherWeb3

logger = logging.getLogger(__name__)


def get_host_ip():
    try:
        host_ip = socket.gethostbyname(platform.node())
    except BaseException:
        host_ip = ""
    return host_ip


def get_non_loopback_ipv4_addresses():
    addresses = []
    for interface in netifaces.interfaces():
        if netifaces.AF_INET in netifaces.ifaddresses(interface):
            for address_info in netifaces.ifaddresses(interface)[netifaces.AF_INET]:
                address_object = ipaddress.IPv4Address(address_info['addr'])
                if not address_object.is_loopback:
                    addresses.append(address_info['addr'])
    return addresses


# Sends coordinator_join over HTTP and returns configuration (e.g.
# dist_url for pytorch.distributed master)
def get_worker_configuration_from_coordinator(
        args: Dict[str, Any], nvidia_enabled: bool) -> Dict[str, Any]:
    coordinator: TogetherWeb3 = args["coordinator"]
    i = 0
    while True:
        i += 1
        if i > 1:
            time.sleep(2)
        try:
            join = get_coordinator_join_request(args, nvidia_enabled)
            coordinator_args = coordinator.coordinator.join(
                asdict(JoinEnvelope(join=join, signature=None)),
            )
            logger.info(f"Joining {join.group_name} on coordinator "
                        + f"{coordinator.http_url} as {join.worker_name}: %s", coordinator_args)
            for key in coordinator_args:
                args[key] = coordinator_args[key]
            return args
        except Exception as e:
            logger.exception(f'get_worker_configuration_from_coordinator failed: {e}')


def get_coordinator_join_request(args, nvidia_enabled):
    gpu_num = nvmlDeviceGetCount() if nvidia_enabled else 0
    # assume: on a single node, all gpus are of the same type
    if gpu_num > 0:
        handle = nvmlDeviceGetHandleByIndex(0)
        gpu_type = nvmlDeviceGetName(handle)
        mem_info = nvmlDeviceGetMemoryInfo(handle)
        gpu_mem = mem_info.total
    else:
        gpu_type = ""
        gpu_mem = 0
    join = Join(
        group_name=args.get("group_name", "group1"),
        worker_name=args.get("worker_name", "worker1"),
        host_name=platform.node(),
        host_ip=get_host_ip(),
        interface_ip=get_non_loopback_ipv4_addresses(),
        instance=Instance(
            arch=platform.machine(),
            os=platform.system(),
            cpu_num=multiprocessing.cpu_count(),
            gpu_num=args.get("gpu_num", gpu_mem),
            gpu_type=args.get("gpu_type", gpu_type),
            gpu_memory=args.get("gpu_mem", gpu_mem),
            resource_type=ResourceTypeInstance,
            tags={}),
        config={
            "model": args.get("model_name")
        },
    )
    return join


def parse_request_prompts(request_json: List[Dict[str, Any]]) -> List[str]:
    prompts = []
    for x in request_json:
        prompt = x["prompt"]
        if isinstance(prompt, list):
            prompts.extend(prompt)
        else:
            prompts.append(prompt)
    return prompts


class ServiceDomain(Enum):
    http = "http"
    together = "together"
