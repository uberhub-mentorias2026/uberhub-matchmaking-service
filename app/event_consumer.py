import asyncio
import json
import logging
from pathlib import Path

from app.indexer import upsert_mentor_event
from app.schemas import EventIngestionResult, MentorProfileEvent

logger = logging.getLogger("matchmaking.consumer")


class MentorEventConsumer:
    """Consumer assíncrono desacoplado do transporte para atualização contínua do índice."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[MentorProfileEvent] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def publish(self, event: MentorProfileEvent) -> None:
        await self._queue.put(event)

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _worker_loop(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                result = await asyncio.to_thread(upsert_mentor_event, event)
                logger.info(
                    "Event %s (mentor=%s, v=%s) -> %s",
                    result.event_id,
                    result.mentor_id,
                    result.version,
                    result.status,
                )
            except Exception:
                logger.exception("Erro ao processar evento %s", event.event_id)
            finally:
                self._queue.task_done()


def consume_jsonl_file(file_path: Path) -> list[EventIngestionResult]:
    results: list[EventIngestionResult] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = MentorProfileEvent(**json.loads(line))
        results.append(upsert_mentor_event(event))
    return results


event_consumer = MentorEventConsumer()
