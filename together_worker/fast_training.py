from typing import Any, Dict, List, Optional, Union

import asyncio
import fcntl
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import netifaces
from aiohttp import web
from dacite import from_dict
from together_web3.computer import (
    MatchEvent,
    RequestTypeLanguageModelInference,
    RequestTypeShutdown,
    Result,
    ResultEnvelope,
)
from together_web3.coordinator import JoinEnvelope
from together_web3.together import TogetherWeb3

from together_worker.common import ServiceDomain, get_coordinator_join_request

logger = logging.getLogger(__name__)


class FastTrainingInterface:
    def dispatch_request(self,
                         args: List[Dict[str, Any]],
                         match_event: Optional[List[MatchEvent]]
                         ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        raise NotImplementedError

    def dispatch_shutdown(self):
        self.shutdown = True

    def worker(self):
        pass

    def __init__(self, model_name: str, args: Dict[str, Any] = {}) -> None:
        args['model_name'] = model_name
        self.service_domain = args.get("service_domain", ServiceDomain.together)
        self.coordinator_join_request = get_coordinator_join_request(args)
        self.coordinator: TogetherWeb3 = args.get(
            "coordinator") if self.service_domain == ServiceDomain.together else None
        self.http_host = args.get("http_host", "localhost")
        self.http_port = args.get("http_port",
                                  5001) if self.service_domain == ServiceDomain.http else 0
        self.request_json: List[Dict[str, Any]] = []
        self.match_event: List[MatchEvent] = []
        self.rank = args.get("rank", 0)
        self.workers = args.get("workers", 1)
        self.executor = ThreadPoolExecutor(max_workers=self.workers)
        self.loop = asyncio.get_event_loop()
        self.served = 0
        self.shutdown = False
        self.tokenizer = None

    def start(self):
        if self.rank == 0:
            if self.service_domain == ServiceDomain.together:
                asyncio.ensure_future(self._run_together_server())
            else:
                asyncio.ensure_future(self._run_http_server())
            self.loop.run_forever()
        else:
            self.worker()

    async def start_with_already_running_eventloop(self):
        if self.rank == 0:
            if self.service_domain == ServiceDomain.together:
                await self._run_together_server()
            else:
                await self._run_http_server()
        else:
            self.worker()

    async def _run_http_server(self) -> None:
        logger.info("Start _run_http_server %s:%d", self.http_host, self.http_port)
        app = web.Application()
        app.add_routes([web.post('/', self.http_request)])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host=self.http_host, port=self.http_port)
        await site.start()
        try:
            while not self.shutdown:
                await asyncio.sleep(1)
        except Exception as e:
            logger.exception(f'_run_http_server failed: {e}')
        await self._shutdown()

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
        await self._shutdown()

    async def _join_local_coordinator(self):
        try:
            args = self.coordinator.coordinator.join(
                asdict(
                    JoinEnvelope(
                        join=self.coordinator_join_request,
                        signature=None)),
                await self.coordinator.get_subscription_id()
            )
            logger.info('_join_local_coordinator: %s', args)

        except Exception as e:
            logger.exception(f'_join_local_coordinator failed: {e}')

    async def http_request(self, web_request: web.Request) -> web.Response:
        wrapped_request = False
        request_json = await web_request.json()
        if not isinstance(request_json, list):
            request_json = [request_json]
            wrapped_request = True
        self.request_json = request_json
        response_json = await self.loop.run_in_executor(self.executor, self.dispatch_request, request_json, None)
        response_json = response_json if isinstance(response_json, list) else [response_json]
        self.request_json = []
        self.served += 1
        return web.Response(
            body=json.dumps({
                "data": response_json[0] if wrapped_request and len(response_json) > 0 else response_json
            }),
            content_type='application/json',
            status=response_json[0].get("status", 200))

    async def together_request(
        self,
        match_event: Union[MatchEvent, List[MatchEvent]],
        raw_event: Union[Dict[str, Any], List[Dict[str, Any]]]
    ) -> None:
        match_event = match_event if isinstance(match_event, list) else [match_event]
        raw_event = raw_event if isinstance(raw_event, list) else [raw_event]
        logger.info(f"together_request {raw_event}")
        self.match_event = match_event
        self.request_json = [event["match"]["service_bid"]["job"] for event in raw_event]
        if self.request_json[0].get("request_type") == RequestTypeShutdown:
            self.dispatch_shutdown()
        response_json = await self.loop.run_in_executor(self.executor, self.dispatch_request, self.request_json, match_event)
        response_json = response_json if isinstance(response_json, list) else [response_json]
        self.request_json = []
        self.match_event = []
        self.served += 1
        await asyncio.gather(*[self.send_result_back(match_event[i], response_json[i]) for i in range(len(response_json))])

    async def send_result_back(self, match_event: MatchEvent, result_data: Dict[str, Any], partial: bool = False) -> None:
        try:
            # logger.info(f"send_result_back {result_data}")
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

    async def _shutdown(self) -> None:
        logger.info("Shutting down")
        if self.coordinator:
            await self.coordinator.close()
        logger.info("Shutdown complete")
