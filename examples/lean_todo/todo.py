"""Minimal to-do list: add, list and complete tasks stored in a JSON file."""

import argparse
import json
from pathlib import Path

STORE = Path("todo.json")


def load() -> list[dict]:
    return json.loads(STORE.read_text()) if STORE.exists() else []


def save(tasks: list[dict]) -> None:
    STORE.write_text(json.dumps(tasks, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("add").add_argument("title")
    commands.add_parser("list")
    commands.add_parser("done").add_argument("number", type=int)
    args = parser.parse_args(argv)

    tasks = load()
    if args.command == "add":
        if not args.title.strip():
            parser.error("title must not be empty")
        tasks.append({"title": args.title.strip(), "done": False})
    elif args.command == "done":
        if not 1 <= args.number <= len(tasks):
            parser.error(f"no task #{args.number}")
        tasks[args.number - 1]["done"] = True
    else:
        for number, task in enumerate(tasks, start=1):
            print(f"{number}. [{'x' if task['done'] else ' '}] {task['title']}")
        return
    save(tasks)


if __name__ == "__main__":
    main()
