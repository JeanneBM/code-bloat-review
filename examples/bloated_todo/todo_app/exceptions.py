"""Domain exception hierarchy."""


class TodoError(Exception):
    """Base class for all to-do errors."""


class TaskNotFoundError(TodoError):
    """Raised when a task does not exist."""


class ValidationError(TodoError):
    """Raised when input is invalid."""


class StorageError(TodoError):
    """Raised when the store cannot be read or written."""

    def __init__(self, message):
        super().__init__(message)
