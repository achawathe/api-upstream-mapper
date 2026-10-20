"""Bounded local action history. Callers supply metadata, never response bodies or values."""

import json
import logging
import threading
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

MAX_LOG_BYTES = 2 * 1024 * 1024


class ActivityLog:
    def __init__(self, root: Path, max_bytes: int = MAX_LOG_BYTES):
        self.path = root / "activity.jsonl"
        self.backup = root / "activity.previous.jsonl"
        self.max_bytes = max_bytes
        self.lock = threading.RLock()

    def record(self, action: str, outcome: str = "success", **details) -> None:
        event = {
            "id": uuid.uuid4().hex,
            "time": datetime.now(UTC).isoformat(),
            "action": action,
            "outcome": outcome,
            "details": details,
        }
        try:
            line = json.dumps(event, ensure_ascii=True) + "\n"
            with self.lock:
                if self.path.exists() and self.path.stat().st_size + len(line) > self.max_bytes:
                    self.path.replace(self.backup)
                if self.path.exists() and self.path.stat().st_size:
                    with self.path.open("rb") as previous:
                        previous.seek(-1, 2)
                        if previous.read(1) != b"\n":
                            line = "\n" + line
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(line)
        except OSError:
            # Logging failure must not turn an already completed action into a failed request.
            logging.getLogger(__name__).warning("Could not save the local activity log")

    @contextmanager
    def action(self, name: str, **details):
        started = perf_counter()
        try:
            yield
        except Exception as error:
            self.record(
                name,
                "failed",
                **details,
                error_type=type(error).__name__,
                elapsed_ms=round((perf_counter() - started) * 1000, 1),
            )
            raise
        else:
            self.record(name, **details, elapsed_ms=round((perf_counter() - started) * 1000, 1))

    def recent(self, limit: int = 200) -> list[dict]:
        events = deque(maxlen=max(1, min(limit, 1000)))
        with self.lock:
            for path in (self.backup, self.path):
                if not path.exists():
                    continue
                with path.open(encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            event = json.loads(line)
                            if isinstance(event, dict):
                                events.append(event)
                        except ValueError:
                            continue  # Recover the readable history after an interrupted write.
        return list(reversed(events))
