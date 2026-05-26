import json
from datetime import datetime
from pathlib import Path

from taste_graph_ai.config import EVENT_LOG_FILE


class EventLog:
    """Append-only event store for audit trail."""

    def __init__(self, path: Path = EVENT_LOG_FILE):
        self.path = Path(path)

    def append(self, event_type: str, data: dict) -> None:
        entry = {
            "ts": datetime.now().isoformat(),
            "type": event_type,
            "data": data,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        events = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def read_by_type(self, event_type: str) -> list[dict]:
        return [e for e in self.read_all() if e.get("type") == event_type]
