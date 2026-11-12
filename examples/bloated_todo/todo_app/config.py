"""Configuration handling."""

import os

DEFAULT_STORE = "todo.json"


class Config:
    def __init__(self, store_path):
        self._store_path = store_path

    def get_store_path(self):
        return self._store_path

    def set_store_path(self, store_path):
        self._store_path = store_path


def load_config(environ):
    return Config(environ.get("TODO_STORE", DEFAULT_STORE))


def get_config(environ):
    return load_config(environ)


def default_config():
    return get_config(os.environ)
