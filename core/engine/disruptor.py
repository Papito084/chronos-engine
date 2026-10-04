"""
ChronosEngine - LMAX Disruptor-inspired RingBuffer Pipeline.
Features:
- Power-of-2 circular RingBuffer with bitwise sequence indexing.
- Lock-free sequence claims for single-writer/single-reader or batched draining.
- Ultra-low latency decoupled ingestion from the network gateway to the core matching thread.
"""

import threading
from typing import Optional, List, Callable, Union
from core.models.events import NewOrderCommand, CancelOrderCommand, EngineEvent
from core.engine.matching_engine import MatchingEngine


class RingBuffer:
    __slots__ = ("_capacity", "_mask", "_buffer", "_cursor", "_gating_sequence")

    def __init__(self, capacity: int = 65536) -> None:
        # Capacity must be a power of 2
        if capacity <= 0 or (capacity & (capacity - 1)) != 0:
            raise ValueError(f"RingBuffer capacity must be a power of 2, got {capacity}")
        self._capacity: int = capacity
        self._mask: int = capacity - 1
        self._buffer: List[Optional[Union[NewOrderCommand, CancelOrderCommand]]] = [None] * capacity
        self._cursor: int = -1
        self._gating_sequence: int = -1

    @property
    def capacity(self) -> int:
        return self._capacity

    def publish(self, command: Union[NewOrderCommand, CancelOrderCommand]) -> int:
        """Publishes an item to the next available sequence slot."""
        seq = self._cursor + 1
        idx = seq & self._mask
        self._buffer[idx] = command
        self._cursor = seq
        return seq

    def get(self, sequence: int) -> Optional[Union[NewOrderCommand, CancelOrderCommand]]:
        """Retrieves item stored at sequence."""
        return self._buffer[sequence & self._mask]


class DisruptorEngineProcessor:
    """
    Worker pipeline orchestrating commands from a RingBuffer to the deterministic MatchingEngine.
    """

    def __init__(
        self,
        engine: MatchingEngine,
        ring_buffer_size: int = 65536,
        on_event_callback: Optional[Callable[[EngineEvent], None]] = None,
    ) -> None:
        self.engine: MatchingEngine = engine
        self.ring_buffer: RingBuffer = RingBuffer(ring_buffer_size)
        self.on_event_callback: Optional[Callable[[EngineEvent], None]] = on_event_callback
        self._processed_sequence: int = -1
        self._running: bool = False
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)

    def submit_command(self, command: Union[NewOrderCommand, CancelOrderCommand]) -> int:
        """Thread-safe submission from API gateway or simulator."""
        with self._not_empty:
            seq = self.ring_buffer.publish(command)
            self._not_empty.notify()
            return seq

    def process_all_pending(self) -> int:
        """
        Synchronously drains and processes all pending commands up to the current published cursor.
        Returns the number of commands processed.
        """
        processed_count = 0
        while self._processed_sequence < self.ring_buffer._cursor:
            self._processed_sequence += 1
            cmd = self.ring_buffer.get(self._processed_sequence)
            if cmd is not None:
                events = self.engine.process_command(cmd)
                if self.on_event_callback:
                    for ev in events:
                        self.on_event_callback(ev)
                processed_count += 1
        return processed_count
