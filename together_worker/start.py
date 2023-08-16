#! python
import argparse
import importlib
import logging
import os

from together_web3.together import TogetherClientOptions, TogetherWeb3


def start_worker(worker_class=None, setup_parser=None, setup_worker=None) -> None:
    parser = argparse.ArgumentParser(
        description="Together Worker Python Library",
        prog="together-worker",
    )

    if not worker_class:
        parser.add_argument(
            "module",
            type=str,
            help="The module to load. E.g. examples.predict"
        )
        parser.add_argument(
            "name",
            type=str,
            help="Class name"
        )

    parser.add_argument(
        "--log",
        default="DEBUG",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        type=str,
        help="Set logging level. Defaults to DEBUG.",
        required=False,
    )
    parser.add_argument(
        '--together_model_name',
        type=str,
        default=os.environ.get(
            'SERVICE',
            'my-service'),
        help='worker name for together coordinator.')

    if setup_parser:
        setup_parser(parser)

    args = parser.parse_args()
    logging.basicConfig(level=args.log)

    if not worker_class:
        worker_module = importlib.import_module(args.module)
        worker_class = getattr(worker_module, args.name)

    try:
        torch = importlib.import_module("torch")
    except ImportError:
        torch = None

    coord_url = os.environ.get("COORD_URL", "127.0.0.1")
    coord_http_port = os.environ.get("COORD_HTTP_PORT", "8092")
    coord_ws_port = os.environ.get("COORD_WS_PORT", "8093")
    coordinator = TogetherWeb3(
        TogetherClientOptions(reconnect=True),
        http_url=f"http://{coord_url}:{coord_http_port}",
        websocket_url=f"ws://{coord_url}:{coord_ws_port}/websocket"
    )

    worker_args = {
        "auth_token": os.environ.get("AUTH_TOKEN"),
        "coordinator": coordinator,
        "device": os.environ.get(
            "DEVICE",
            "cuda"),
        "http_host": os.environ.get("HTTP_HOST"),
        "http_port": int(
            os.environ.get(
                "HTTP_PORT",
                "5001")),
        "gpu_num": 1 if torch and torch.cuda.is_available() else 0,
        "gpu_type": torch.cuda.get_device_name() if torch and torch.cuda.is_available() else None,
        "gpu_mem": torch.cuda.get_device_properties(
            torch.cuda.current_device()).total_memory if torch and torch.cuda.is_available() else None,
        "group_name": os.environ.get(
            "GROUP",
            "group1"),
        "service_domain": os.environ.get(
            "SERVICE_DOMAIN",
            "http"),
        "worker_name": os.environ.get(
            "WORKER",
            "worker1"),
    }

    if setup_worker:
        setup_worker(args, worker_args)

    worker = worker_class(model_name=args.together_model_name, args=worker_args)
    worker.start()
