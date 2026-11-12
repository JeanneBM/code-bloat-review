"""Domain model."""

from dataclasses import dataclass


@dataclass
class Task:
    title: str
    done: bool = False

    def get_title(self):
        return self.title

    def set_title(self, title):
        self.title = title

    def get_done(self):
        return self.done

    def set_done(self, done):
        self.done = done

    def to_dict(self):
        return {"title": self.get_title(), "done": self.get_done()}

    @classmethod
    def from_dict(cls, data):
        return cls(title=data["title"], done=data["done"])
