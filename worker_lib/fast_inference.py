from typing import Any, Dict, Optional

import asyncio
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from enum import Enum

from dacite import from_dict
from together_web3.computer import (
    ImageModelInferenceResult,
    Instance,
    Job,
    LanguageModelInferenceChoice,
    LanguageModelInferenceResult,
    MatchEvent,
    RequestTypeImageModelInference,
    RequestTypeLanguageModelInference,
    RequestTypeShutdown,
    ResourceTypeInstance,
    Result,
    ResultEnvelope,
)
from together_web3.coordinator import Join, JoinEnvelope
from together_web3.together import TogetherClientOptions, TogetherWeb3

logger = logging.getLogger(__name__)


class ServiceDomain(Enum):
    http = "http"
    together = "together"


class FastInferenceInterface:
    def dispatch_request(self, args: Dict[str, Any], match_event: MatchEvent) -> Dict[str, Any]:
        raise NotImplementedError

    def __init__(self, model_name: str, args: Dict[str, Any] = {}):
        self.model_name = model_name
        self.service_domain = args.get("service_domain", ServiceDomain.together)
        self.coordinator: TogetherWeb3 = args.get(
            "coordinator") if self.service_domain == ServiceDomain.together else None
        self.executor = ThreadPoolExecutor(max_workers=args.get("workers", 1))
        self.shutdown = False

    def start(self):
        loop = asyncio.get_event_loop()
        asyncio.ensure_future(self._run_together_server())
        loop.run_forever()

    def worker(self):
        pass

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
                group_name="group1",
                worker_name="worker1",
                host_name="",
                host_ip="",
                interface_ip=[],
                instance=Instance(
                    arch="",
                    os="",
                    cpu_num=0,
                    gpu_num=0,
                    gpu_type="",
                    gpu_memory=0,
                    resource_type=ResourceTypeInstance,
                    tags={}
                ),
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

    async def together_request(self, match_event: MatchEvent, raw_event: Dict[str, Any]) -> None:
        logger.info(f"together_request {raw_event}")
        loop = asyncio.get_event_loop()
        request_json = [raw_event["match"]["service_bid"]["job"]]
        if request_json[0]["request_type"] == RequestTypeShutdown:
            pass
        response_json = await loop.run_in_executor(self.executor, self.dispatch_request, request_json, match_event)
        await self.send_result_back(match_event, response_json)

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
