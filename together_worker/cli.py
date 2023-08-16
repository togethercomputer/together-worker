from start import start_worker


def setup_parser(parser):
    parser.add_argument('--example-message', type=str, default=" to you also.")


def setup_worker(args, worker_args):
    worker_args["message"] = args.example_message


def main():
    start_worker()


if __name__ == "__main__":
    main()
