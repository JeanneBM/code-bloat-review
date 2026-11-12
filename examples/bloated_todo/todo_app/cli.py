"""Command line interface."""

import argparse
import sys

from .config import default_config
from .factory import TaskServiceFactory
from .formatting import format_task


def build_parser():
    parser = argparse.ArgumentParser(description="Enterprise to-do list")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("add").add_argument("title")
    commands.add_parser("list")
    commands.add_parser("done").add_argument("number", type=int)
    return parser


def handle_add(args):
    config = default_config()
    store_path = config.get_store_path()
    factory = TaskServiceFactory(store_path)
    service = factory.create()
    if service is None:
        sys.exit("could not create service")
    service.add_task(args.title)


def handle_done(args):
    config = default_config()
    store_path = config.get_store_path()
    factory = TaskServiceFactory(store_path)
    service = factory.create()
    if service is None:
        sys.exit("could not create service")
    service.complete_task(args.number)


def handle_list(args):
    config = default_config()
    store_path = config.get_store_path()
    factory = TaskServiceFactory(store_path)
    service = factory.create()
    if service is None:
        sys.exit("could not create service")
    for number, task in enumerate(service.get_all_tasks(), start=1):
        print(format_task(number, task))


# def handle_remove(args):
#     config = default_config()
#     service = TaskServiceFactory(config.get_store_path()).create()
#     service.remove_task(args.number)


HANDLERS = {"add": handle_add, "done": handle_done, "list": handle_list}


def run(argv=None):
    args = build_parser().parse_args(argv)
    HANDLERS[args.command](args)
