"""Shared utilities."""

import re
import time


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def chunk(items, size):
    return [items[i : i + size] for i in range(0, len(items), size)]


def retry(times=3, delay=0.1):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(times):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    if attempt == times - 1:
                        raise
                    time.sleep(delay)

        return wrapper

    return decorator
