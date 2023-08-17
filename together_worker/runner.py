#! python
import argparse
import importlib
import logging
import os

from together_web3.together import TogetherClientOptions, TogetherWeb3


def run_worker(worker_class=None, setup_parser=None, setup_worker=None) -> None:
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
            ''),
        help='worker name for together coordinator.')
    parser.add_argument(
        '--hf_model_name',
        type=str,
        default='',
        help='hugging face model name (used to load config).')
    parser.add_argument('--model_path', type=str, default=None,
                        help='hugging face model path (used to load config).')
    parser.add_argument('--service-domain', type=str, default=os.environ.get("SERVICE_DOMAIN", "http"),
                        help='device.')
    parser.add_argument('--http-host', type=str, default=os.environ.get("HTTP_HOST"),
                        help='http host.')
    parser.add_argument('--http-port', type=str, default=int(os.environ.get("HTTP_PORT", "5001")),
                        help='http host.')
    parser.add_argument('--worker_name', type=str, default=os.environ.get('WORKER', 'worker1'),
                        help='worker name for together coordinator.')
    parser.add_argument('--group_name', type=str, default=os.environ.get('GROUP', 'group1'),
                        help='group name for together coordinator.')
    parser.add_argument('--device', type=str, default=os.environ.get("DEVICE", "cuda"),
                        help='device.')
    parser.add_argument('--auth-token', type=str, default=os.environ.get("AUTH_TOKEN"),
                        help='Used for private repos.')

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
        "auth_token": args.auth_token,
        "coordinator": coordinator,
        "device": args.device,
        "hf_model_name": args.hf_model_name,
        "http_host": args.http_host,
        "http_port": args.http_port,
        "gpu_num": 1 if torch and torch.cuda.is_available() else 0,
        "gpu_type": torch.cuda.get_device_name() if torch and torch.cuda.is_available() else None,
        "gpu_mem": torch.cuda.get_device_properties(
            torch.cuda.current_device()).total_memory if torch and torch.cuda.is_available() else None,
        "group_name": args.group_name,
        "model_path": args.model_path,
        "service_domain": args.service_domain,
        "worker_name": args.worker_name,
    }

    if setup_worker:
        setup_worker(args, worker_args)

    worker = worker_class(model_name=args.together_model_name, args=worker_args)
    worker.start()
