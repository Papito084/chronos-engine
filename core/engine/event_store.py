"""
ChronosEngine - Event Journal & Event Publisher.
Provides an immutable event log for deterministic Event Sourcing, local WAL persistence,
and async publishing to Redpanda/Kafka 'market.events'.
"""

import os
import struct
import asyncio
from typing import List, Optional, Callable
from core.models.events import EngineEvent
from core.serialization import serialize_event, deserialize_event


class EventJournal:
    """
    In-Memory and File-backed Write-Ahead Log (WAL) Journal for Engine Events.
    Maintains an ordered, append-only sequence of immutable events.
    """

    def __init__(self, wal_path: Optional[str] = None) -> None:
        self.wal_path: Optional[str] = wal_path
        self._events: List[EngineEvent] = []
        self._file_handle = None

        if self.wal_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.wal_path)), exist_ok=True)
            self._file_handle = open(self.wal_path, "a+b")
            self._recover_from_wal()

    def _recover_from_wal(self) -> None:
        """Reads existing binary WAL file to recover in-memory list."""
        if not self._file_handle:
            return
        self._file_handle.seek(0)
        self._events.clear()

        while True:
            len_bytes = self._file_handle.read(4)
            if not len_bytes or len(len_bytes) < 4:
                break
            payload_len = struct.unpack(">I", len_bytes)[0]
            payload = self._file_handle.read(payload_len)
            if len(payload) < payload_len:
                break
            event = deserialize_event(payload)
            self._events.append(event)

    def append(self, event: EngineEvent) -> None:
        """Appends an event to the in-memory journal and persists to WAL if configured."""
        self._events.append(event)

        if self._file_handle:
            serialized = serialize_event(event)
            # 4-byte length prefix (big-endian) followed by payload
            header = struct.pack(">I", len(serialized))
            self._file_handle.write(header + serialized)
            self._file_handle.flush()

    def read_all(self) -> List[EngineEvent]:
        """Returns all recorded events in monotonic order."""
        return list(self._events)

    def read_from(self, from_sequence: int) -> List[EngineEvent]:
        """Returns events with sequence_number >= from_sequence."""
        return [e for e in self._events if e.sequence_number >= from_sequence]

    def get_last_sequence(self) -> int:
        """Returns highest sequence_number in journal, or 0 if empty."""
        if not self._events:
            return 0
        return self._events[-1].sequence_number

    def clear(self) -> None:
        """Resets the journal."""
        self._events.clear()
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = open(self.wal_path, "w+b")

    def close(self) -> None:
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None


class RedpandaEventPublisher:
    """
    Asynchronous event publisher to Redpanda / Kafka 'market.events'.
    Ensures partition keying by symbol for strict order preservation.
    """

    def __init__(self, bootstrap_servers: str = "localhost:9092", topic: str = "market.events") -> None:
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self._producer = None

    async def start(self) -> None:
        try:
            from aiokafka import AIOKafkaProducer
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                compression_type="zstd",
                acks="all",
            )
            await self._producer.start()
        except Exception as e:
            print(f"[RedpandaEventPublisher] Warning: Broker unavailable ({e}), running in offline mode.")
            self._producer = None

    async def publish(self, event: EngineEvent) -> None:
        if self._producer is None:
            return

        payload = serialize_event(event)
        key = getattr(event, "symbol", "GLOBAL").encode("utf-8")
        await self._producer.send_and_wait(self.topic, key=key, value=payload)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()
            self._producer = None
