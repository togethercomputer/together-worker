from typing import Any, Dict, List, Optional, Union

import asyncio
import fcntl
import ipaddress
import json
import logging
import multiprocessing
import os
import platform
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from enum import Enum

import netifaces
from aiohttp import web
from dacite import from_dict
from together_web3.computer import (
    Instance,
    MatchEvent,
    RequestTypeLanguageModelInference,
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


# Sends coordinator_join over HTTP and returns configuration (e.g.
# dist_url for pytorch.distributed master)
def get_worker_configuration_from_coordinator(args: Dict[str, Any]) -> Dict[str, Any]:
    coordinator: TogetherWeb3 = args["coordinator"]
    i = 0
    while True:
        i += 1
        if i > 1:
            time.sleep(2)
        try:
            join = get_coordinator_join_request(args)
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


def get_coordinator_join_request(args):
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
            gpu_num=args.get("gpu_num", 0),
            gpu_type=args.get("gpu_type", ""),
            gpu_memory=args.get("gpu_mem", 0),
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


class FastInferenceInterface:
    tokenizer: Optional[Any]

    def dispatch_request(self,
                         args: List[Dict[str, Any]],
                         match_event: Optional[List[MatchEvent]]
                         ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        raise NotImplementedError

    def dispatch_shutdown(self):
        self.shutdown = True

    def worker(self):
        pass

    def __init__(self, model_name: str, args: Dict[str, Any] = {}):
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
        self.stream_tokens_pipe_r: int = -1
        self.stream_tokens_pipe_w: int = -1
        self.stream_tokens_pipe_task: Optional[asyncio.Task[None]] = None
        if args.get('stream_tokens_pipe'):
            self.stream_tokens_pipe_r, self.stream_tokens_pipe_w = os.pipe()

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
        if self.stream_tokens_pipe_r != -1:
            self.start_stream_tokens_pipe()
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

    # Primary token streaming implementation using call_soon_threadsafe().
    def stream_tokens(self, token: List[int],
                      match_event: Optional[List[MatchEvent]] = None) -> None:
        self.loop.call_soon_threadsafe(
            self._dispatch_stream_tokens,
            self.served,
            token,
            match_event if match_event else self.match_event)

    def _dispatch_stream_tokens(
            self,
            request_id: int,
            token: List[int],
            match_event: List[MatchEvent]) -> None:
        asyncio.ensure_future(
            self._handle_stream_tokens(request_id, token, match_event),
            loop=self.loop)

    async def _handle_stream_tokens(self, request_id: int, tokens: List[int], match_event: List[MatchEvent]) -> None:
        if request_id != self.served:
            return
        token = tokens[0]
        await self.send_result_back(match_event[0], {
            "choices": [{"text": self.tokenizer.decode([token]) if self.tokenizer else f"{token}"}],
            "result_type": RequestTypeLanguageModelInference,
        }, partial=True)

    # Alternative implementation of stream_tokens() using os.pipe().
    def stream_tokens_pipe(self, token: List[int]) -> None:
        os.write(
            self.stream_tokens_pipe_w,
            f'{json.dumps({ "id": self.served, "token": token })}\n'.encode())

    # We'll pass the write file-descriptor to C++ via a torch::jit::class_() method.
    def start_stream_tokens_pipe(self):
        fcntl.fcntl(self.stream_tokens_pipe_w, fcntl.F_SETFL, os.O_NONBLOCK)
        self.stream_tokens_pipe_task = asyncio.create_task(self._handle_stream_tokens_pipe())

    async def _handle_stream_tokens_pipe(self):
        reader = asyncio.StreamReader()
        read_protocol = asyncio.StreamReaderProtocol(reader)
        await self.loop.connect_read_pipe(lambda: read_protocol, os.fdopen(self.stream_tokens_pipe_r))
        while not reader.at_eof():
            line = await reader.readline()
            if not line:
                break
            streamed = json.loads(line)
            asyncio.ensure_future(
                self._handle_stream_tokens(streamed['id'], streamed['token'], self.match_event),
                loop=self.loop)

    async def _shutdown(self) -> None:
        logger.info("Shutting down")
        if self.coordinator:
            await self.coordinator.close()
        if self.stream_tokens_pipe_task:
            self.stream_tokens_pipe_task.cancel()
            await self.stream_tokens_pipe_task
            self.stream_tokens_pipe_task = None
        if self.stream_tokens_pipe_r != -1:
            os.close(self.stream_tokens_pipe_r)
            self.stream_tokens_pipe_r = -1
        if self.stream_tokens_pipe_w != -1:
            os.close(self.stream_tokens_pipe_w)
            self.stream_tokens_pipe_w = -1
        logger.info("Shutdown complete")
