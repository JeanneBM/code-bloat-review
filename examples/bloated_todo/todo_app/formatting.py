"""Presentation helpers."""


def format_task(number, task):
    mark = "x" if task.get_done() else " "
    return f"{number}. [{mark}] {task.get_title()}"


def format_task_verbose(number, task):
    status = "done" if task.get_done() else "open"
    return f"Task {number}: {task.get_title()} ({status})"


def format_summary(tasks):
    done = sum(1 for task in tasks if task.get_done())
    return f"{done}/{len(tasks)} done"
