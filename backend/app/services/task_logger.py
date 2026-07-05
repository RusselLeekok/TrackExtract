from pathlib import Path

from app.services.storage import unique_path


class TaskLogger:
    def __init__(self, task_id: int):
        self.path: Path = unique_path("logs", "log", f"task_{task_id}")

    def write(self, message: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")

    def command(self, args: list[str]) -> None:
        self.write("$ " + " ".join(args))

