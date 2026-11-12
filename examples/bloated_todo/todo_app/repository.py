"""Persistence layer."""

import json
from abc import ABC, abstractmethod
from pathlib import Path

from .exceptions import StorageError
from .models import Task


class AbstractTaskRepository(ABC):
    """Interface for task storage backends."""

    @abstractmethod
    def load_all(self):
        """Return all tasks."""

    @abstractmethod
    def save_all(self, tasks):
        """Persist all tasks."""


class JsonTaskRepository(AbstractTaskRepository):
    """Stores tasks in a JSON file."""

    def __init__(self, path):
        self.path = Path(path)

    def load_all(self):
        try:
            if not self.path.exists():
                return []
            with self.path.open() as handle:
                return [Task.from_dict(item) for item in json.load(handle)]
        except StorageError:
            raise

    def save_all(self, tasks):
        try:
            with self.path.open("w") as handle:
                json.dump([task.to_dict() for task in tasks], handle, indent=2)
        except StorageError:
            raise

    def backup(self, suffix=".bak"):
        target = self.path.with_suffix(suffix)
        target.write_text(self.path.read_text())
        return target
