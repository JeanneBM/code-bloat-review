"""Business logic."""

import logging

from .exceptions import TaskNotFoundError, ValidationError
from .models import Task


class TaskService:
    """Application service coordinating task use cases."""

    def __init__(self, repository):
        self.repository = repository

    def get_all_tasks(self):
        return self.repository.load_all()

    def save_all_tasks(self, tasks):
        return self.repository.save_all(tasks)

    def add_task(self, title):
        if not title or not title.strip():
            raise ValidationError("title must not be empty")
        tasks = self.get_all_tasks()
        tasks.append(Task(title=title.strip()))
        self.save_all_tasks(tasks)

    def complete_task(self, number):
        tasks = self.get_all_tasks()
        if not 1 <= number <= len(tasks):
            raise TaskNotFoundError(f"no task #{number}")
        tasks[number - 1].set_done(True)
        self.save_all_tasks(tasks)
