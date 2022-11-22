from typing import Any, Dict, List, Union

import asyncio
import ipaddress
import logging
import multiprocessing
import platform
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from enum import Enum

import netifaces
from dacite import from_dict
from together_web3.computer import (
    Instance,
    MatchEvent,
    RequestTypeShutdown,
    ResourceTypeInstance,
    Result,
    ResultEnvelope,
)
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


class ServiceDomain(Enum):
    http = "http"
    together = "together"


class FastInferenceInterface:
    def dispatch_request(self, args: List[Dict[str, Any]], match_event: List[MatchEvent]
                         ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        raise NotImplementedError

    def dispatch_shutdown(self):
        self.shutdown = True

    def worker(self):
        pass

    def __init__(self, model_name: str, args: Dict[str, Any] = {}):
        self.model_name = model_name
        self.group_name = args.get("group_name", "group1")
        self.worker_name = args.get("worker_name", "worker1")
        self.gpu_type = args.get("gpu_type", "")
        self.gpu_num = args.get("gpu_num", 0)
        self.gpu_mem = args.get("gpu_mem", 0)
        self.service_domain = args.get("service_domain", ServiceDomain.together)
        self.coordinator: TogetherWeb3 = args.get(
            "coordinator") if self.service_domain == ServiceDomain.together else None
        self.executor = ThreadPoolExecutor(max_workers=args.get("workers", 1))
        self.shutdown = False

    def start(self):
        loop = asyncio.get_event_loop()
        asyncio.ensure_future(self._run_together_server())
        loop.run_forever()

    async def _run_together_server(self) -> None:
        self.coordinator._on_connect.append(self._join_local_coordinator)
        self.coordinator._on_match_event.append(self.together_request)
        self.coordinator.subscribe_events("coordinator")
        logger.info("Start _run_together_server")
        try:
            while not self.shutdown:
                await asyncio.sleep(1)
        except Exception as e:
            logger.exception(f'_run_together_server failed: {e}')
        self._shutdown()

    async def _join_local_coordinator(self):
        try:
            logger.info("_join_local_coordinator")
            join = Join(
                group_name=self.group_name,
                worker_name=self.worker_name,
                host_name=platform.node(),
                host_ip=get_host_ip(),
                interface_ip=get_non_loopback_ipv4_addresses(),
                instance=Instance(
                    arch=platform.machine(),
                    os=platform.system(),
                    cpu_num=multiprocessing.cpu_count(),
                    gpu_num=self.gpu_num,
                    gpu_type=self.gpu_type,
                    gpu_memory=self.gpu_mem,
                    resource_type=ResourceTypeInstance,
                    tags={}),
                config={
                    "model": self.model_name,
                },
            )
            args = self.coordinator.coordinator.join(
                asdict(JoinEnvelope(join=join, signature=None)),
                await self.coordinator.get_subscription_id()
            )

        except Exception as e:
            logger.exception(f'_join_local_coordinator failed: {e}')

    async def together_request(
        self,
        match_event: Union[MatchEvent, List[MatchEvent]],
        raw_event: Union[Dict[str, Any], List[Dict[str, Any]]]
    ) -> None:
        match_event = match_event if isinstance(match_event, list) else [match_event]
        raw_event = raw_event if isinstance(raw_event, list) else [raw_event]
        logger.info(f"together_request {raw_event}")
        loop = asyncio.get_event_loop()
        request_json = [event["match"]["service_bid"]["job"] for event in raw_event]
        if request_json[0]["request_type"] == RequestTypeShutdown:
            self.dispatch_shutdown()
        response_json = await loop.run_in_executor(self.executor, self.dispatch_request, request_json, match_event)
        response_json = response_json if isinstance(response_json, list) else [response_json]
        await asyncio.gather(*[self.send_result_back(match_event[i], response_json[i]) for i in range(len(response_json))])

    async def send_result_back(self, match_event: MatchEvent, result_data: Dict[str, Any], partial: bool = False) -> None:
        try:
            #logger.info(f"send_result_back {result_data}")
            result = {
                "ask_address": match_event.match.ask_address,
                "bid_address": match_event.match.bid_address,
                "ask_offer_id": match_event.match.ask_offer_id,
                "bid_offer_id": match_event.match.bid_offer_id,
                "match_id": match_event.match_id,
                "data": result_data,
            }
            if partial:
                result["partial"] = True
            await self.coordinator.update_result(ResultEnvelope(
                result=from_dict(
                    data_class=Result,
                    data=result,
                ),
                signature=None,
            ))
        except Exception as e:
            logger.error(f"send_result_back error: {e}")

    def _shutdown(self) -> None:
        logger.info("Shutting down")


# if __name__ == "__main__":
#    fip = FastInferenceInterface(model_name="opt66b")
#    fip.start()
