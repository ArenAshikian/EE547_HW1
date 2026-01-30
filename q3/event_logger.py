from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from message_source import MessageSource, Packet


@dataclass
class LoggerStats:
    packets_received: int = 0      # Total packets from source
    packets_written: int = 0       # Packets written to log
    duplicates_discarded: int = 0  # Duplicate packets ignored
    corrupted_packets: int = 0     # Packets with bad checksum
    retransmit_requests: int = 0   # Times request_retransmit called
    retransmits_received: int = 0  # Successful retransmits
    inversions: int = 0            # Out-of-order writes (LATE status)
    gaps: int = 0                  # Missing sequences in final log
    buffer_flushes: int = 0        # Times buffer was flushed
    final_buffer_size: int = 0     # Packets in buffer at termination (lost)


class EventLogger:
    def __init__(self,
                 source: MessageSource,
                 log_file: Path,
                 buffer_size: int = 30):
        """
        Initialize event logger.

        Args:
            source: Message source to receive from
            log_file: Path to append-only log file
            buffer_size: Max packets to buffer before forced flush
        """
        self.source = source
        self.log_file = log_file
        self.buffer_size = buffer_size

        # Template state variables
        self.buffer: list[Packet] = []
        self.seen_sequences: set[int] = set()
        self.last_written_seq: int = -1
        self.pending_retransmits: set[int] = set()

        # Extra state
        self.stats = LoggerStats()
        self.expected_seq: int = 0
        self.gap_wait: int = 0
        self.gap_patience: int = max(5, buffer_size // 2)

        # On restart, rebuild state from the existing append-only log
        self._recover_from_log()

    def run(self) -> LoggerStats:
        """
        Main processing loop.

        Continuously receive packets until termination.
        Handle each packet appropriately:
        - Verify checksum (request retransmit if corrupted)
        - Detect duplicates (discard if already seen)
        - Buffer or write based on your strategy
        - Periodically flush buffer

        Returns:
            Statistics about logging performance.
        """
        while True:
            try:
                packet = self.source.receive()
            except SystemExit:
                self._finalize()
                return self.stats

            if packet is None:
                self._finalize()
                return self.stats

            self.stats.packets_received += 1
            self._handle_packet(packet)

            if self._should_flush():
                self._flush_buffer()

    def _handle_packet(self, packet: Packet) -> None:
        """Process a single packet."""
        if not self.source.verify_checksum(packet):
            self.stats.corrupted_packets += 1
            self._request_retransmit(packet.sequence)
            return

        if packet.sequence in self.seen_sequences:
            self.stats.duplicates_discarded += 1
            return

        for p in self.buffer:
            if p.sequence == packet.sequence:
                self.stats.duplicates_discarded += 1
                return

        if packet.sequence in self.pending_retransmits:
            self.stats.retransmits_received += 1

        self.buffer.append(packet)

        have_expected = False
        for p in self.buffer:
            if p.sequence == self.expected_seq:
                have_expected = True

        if have_expected:
            self.gap_wait = 0
        else:
            self.gap_wait += 1
            if self.gap_wait >= self.gap_patience:
                self._request_retransmit(self.expected_seq)
                self.gap_wait = 0

    def _should_flush(self) -> bool:
        """Determine if buffer should be flushed."""
        for p in self.buffer:
            if p.sequence == self.expected_seq:
                return True

        if len(self.buffer) >= self.buffer_size:
            return True

        return False

    def _flush_buffer(self) -> None:
        """Write buffered packets to log."""
        if not self.buffer:
            return

        self.buffer.sort(key=lambda p: p.sequence)
        wrote_any = False

        # Write as much contiguous data as we can from expected_seq
        while self.buffer and self.buffer[0].sequence == self.expected_seq:
            pkt = self.buffer.pop(0)
            self._append_packet(pkt)
            wrote_any = True

            self.expected_seq = self.last_written_seq + 1
            self.gap_wait = 0

        self._finish_flush(wrote_any)

    def _finalize(self) -> None:
        """Called after termination. Flush remaining buffer."""
        if self._should_flush():
            self._flush_buffer()

        if self.buffer:
            self.buffer.sort(key=lambda p: p.sequence)
            for pkt in self.buffer:
                self._append_packet(pkt)
            self.buffer = []
            self.stats.buffer_flushes += 1

        self.stats.final_buffer_size = 0
        self.stats.gaps = self._compute_gaps()

    def _finish_flush(self, wrote_any: bool) -> None:
        if wrote_any:
            self.stats.buffer_flushes += 1

        # If we're stuck on a gap and buffer is full, force one write for coverage
        if len(self.buffer) >= self.buffer_size:
            self.buffer.sort(key=lambda p: p.sequence)
            if self.buffer:
                pkt = self.buffer.pop(0)
                self._append_packet(pkt)
                self.stats.buffer_flushes += 1
                self.expected_seq = self.last_written_seq + 1

    def _recover_from_log(self) -> None:
        if not self.log_file.exists():
            self.expected_seq = 0
            return

        max_seq = -1

        try:
            with self.log_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    parts = line.split(",", 3)
                    if len(parts) < 4:
                        continue

                    try:
                        seq = int(parts[0])
                    except ValueError:
                        continue

                    self.seen_sequences.add(seq)
                    if seq > max_seq:
                        max_seq = seq
        except OSError:
            self.seen_sequences = set()
            max_seq = -1

        self.last_written_seq = max_seq
        self.expected_seq = self.last_written_seq + 1
        self.gap_wait = 0

    def _request_retransmit(self, seq: int) -> None:
        if seq < 0:
            return
        if seq in self.seen_sequences:
            return
        if seq in self.pending_retransmits:
            return

        self.source.request_retransmit(seq)
        self.pending_retransmits.add(seq)
        self.stats.retransmit_requests += 1

    def _append_packet(self, pkt: Packet) -> None:
        seq = pkt.sequence
        status = "OK"

        if seq in self.pending_retransmits:
            status = "RETRANSMIT"
        else:
            if seq < self.last_written_seq:
                status = "LATE"

        if seq < self.last_written_seq:
            self.stats.inversions += 1

        line = f"{seq},{pkt.timestamp},{pkt.payload.hex()},{status}\n"

        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()

        self.seen_sequences.add(seq)
        if seq > self.last_written_seq:
            self.last_written_seq = seq

        if seq in self.pending_retransmits:
            self.pending_retransmits.remove(seq)

        self.stats.packets_written += 1

    def _compute_gaps(self) -> int:
        if self.last_written_seq < 0:
            return 0

        upper = self.last_written_seq
        total_packets = getattr(self.source, "total_packets", None)
        if isinstance(total_packets, int) and total_packets > 0:
            upper = max(upper, total_packets - 1)

        gaps = 0
        for s in range(0, upper + 1):
            if s not in self.seen_sequences:
                gaps += 1
        return gaps
