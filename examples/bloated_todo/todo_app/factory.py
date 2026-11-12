"""Object construction."""

from .repository import JsonTaskRepository
from .service import TaskService


class TaskServiceFactory:
    """Builds a fully wired TaskService."""

    def __init__(self, store_path):
        self.store_path = store_path

    def create(self):
        return TaskService(JsonTaskRepository(self.store_path))
