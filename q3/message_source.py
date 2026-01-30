"""
Message Source for Durable Event Log Testing

Generates packets with realistic network behavior:
- Reordering within a window
- Duplicate delivery
- Packet loss
- Checksum corruption

At random points, calls sys.exit(1) to simulate process termination.
State is persisted to allow resume on restart.

Provided to students - do not modify.
"""

import hashlib
import json
import os
import random
import sys
import zlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


# Default configuration
DEFAULT_TOTAL_PACKETS = 1000
DEFAULT_REORDER_WINDOW = 10
DEFAULT_DUPLICATE_PROB = 0.05
DEFAULT_LOSS_PROB = 0.02
DEFAULT_CORRUPTION_PROB = 0.03
DEFAULT_TERMINATION_PROB = 0.005  # Per-packet probability of termination


@dataclass
class Packet:
    """A single packet from the message source."""
    sequence: int       # Global sequence number (ground truth order)
    timestamp: float    # Generation timestamp
    payload: bytes      # Arbitrary payload data
    checksum: int       # CRC32 checksum of payload

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "payload": self.payload.hex(),
            "checksum": self.checksum
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Packet":
        return cls(
            sequence=d["sequence"],
            timestamp=d["timestamp"],
            payload=bytes.fromhex(d["payload"]),
            checksum=d["checksum"]
        )


class MessageSource:
    """
    Simulates unreliable message delivery with process termination.

    On first init with a seed, generates all packets and saves to file.
    On subsequent inits with same seed, loads packets and resumes.
    At random points, calls sys.exit(1) to simulate crash.
    """

    def __init__(self,
                 seed: int,
                 total_packets: int = DEFAULT_TOTAL_PACKETS,
                 reorder_window: int = DEFAULT_REORDER_WINDOW,
                 duplicate_prob: float = DEFAULT_DUPLICATE_PROB,
                 loss_prob: float = DEFAULT_LOSS_PROB,
                 corruption_prob: float = DEFAULT_CORRUPTION_PROB,
                 termination_prob: float = DEFAULT_TERMINATION_PROB,
                 state_dir: Optional[Path] = None):
        """
        Initialize message source.

        Args:
            seed: Random seed for reproducibility
            total_packets: Number of packets to generate
            reorder_window: Max positions a packet can be delayed
            duplicate_prob: Probability of duplicate delivery
            loss_prob: Probability of packet never arriving
            corruption_prob: Probability of corrupted checksum
            termination_prob: Per-packet probability of process termination
            state_dir: Directory for state files (default: /tmp)
        """
        self.seed = seed
        self.total_packets = total_packets
        self.reorder_window = reorder_window
        self.duplicate_prob = duplicate_prob
        self.loss_prob = loss_prob
        self.corruption_prob = corruption_prob
        self.termination_prob = termination_prob

        # State file paths
        if state_dir is None:
            state_dir = Path("/tmp")
        self._packets_file = state_dir / f".ms_{seed}_packets.json"
        self._position_file = state_dir / f".ms_{seed}_position.txt"
        self._retransmit_file = state_dir / f".ms_{seed}_retransmit.json"

        # Random generator for runtime decisions
        self.rng = random.Random(seed)

        # Load or generate packets
        self._delivery_queue: list[tuple[int, Packet, bool]] = []  # (priority, packet, corrupted)
        self._position = 0
        self._terminated = False
        self._pending_retransmits: list[int] = []
        self._generated_sequences: set[int] = set()

        self._initialize()

    def _initialize(self) -> None:
        """Load existing state or generate new packets."""
        if self._packets_file.exists():
            # Resume from existing state
            self._load_state()
        else:
            # Generate new packet sequence
            self._generate_packets()
            self._save_packets()
            self._save_position()

    def _generate_packets(self) -> None:
        """Generate all packets with network effects applied."""
        gen_rng = random.Random(self.seed)

        # Generate ground truth packets
        ground_truth = []
        for seq in range(self.total_packets):
            payload = f"packet_{seq:06d}_{gen_rng.randint(0, 999999)}".encode()
            checksum = zlib.crc32(payload)
            packet = Packet(
                sequence=seq,
                timestamp=seq * 0.001 + gen_rng.uniform(0, 0.0001),
                payload=payload,
                checksum=checksum
            )
            ground_truth.append(packet)
            self._generated_sequences.add(seq)

        # Apply network effects to create delivery queue
        delivery = []
        for packet in ground_truth:
            # Loss: packet never delivered
            if gen_rng.random() < self.loss_prob:
                continue

            # Reordering: add random delay
            delay = gen_rng.randint(0, self.reorder_window)
            priority = packet.sequence + delay

            # Corruption: bad checksum
            corrupted = gen_rng.random() < self.corruption_prob

            delivery.append((priority, packet, corrupted))

            # Duplication: add another copy
            if gen_rng.random() < self.duplicate_prob:
                dup_delay = gen_rng.randint(1, self.reorder_window * 2)
                delivery.append((priority + dup_delay, packet, corrupted))

        # Sort by priority (delivery order)
        delivery.sort(key=lambda x: x[0])
        self._delivery_queue = delivery

    def _save_packets(self) -> None:
        """Save generated packets to file."""
        data = {
            "seed": self.seed,
            "total_packets": self.total_packets,
            "generated_sequences": list(self._generated_sequences),
            "delivery_queue": [
                {"priority": p, "packet": pkt.to_dict(), "corrupted": c}
                for p, pkt, c in self._delivery_queue
            ]
        }
        with open(self._packets_file, 'w') as f:
            json.dump(data, f)

    def _load_state(self) -> None:
        """Load packets and position from files."""
        # Load packets
        with open(self._packets_file) as f:
            data = json.load(f)

        self._generated_sequences = set(data["generated_sequences"])
        self._delivery_queue = [
            (item["priority"], Packet.from_dict(item["packet"]), item["corrupted"])
            for item in data["delivery_queue"]
        ]

        # Load position
        if self._position_file.exists():
            with open(self._position_file) as f:
                self._position = int(f.read().strip())
        else:
            self._position = 0

        # Load pending retransmits
        if self._retransmit_file.exists():
            with open(self._retransmit_file) as f:
                self._pending_retransmits = json.load(f)
        else:
            self._pending_retransmits = []

    def _save_position(self) -> None:
        """Save current position."""
        with open(self._position_file, 'w') as f:
            f.write(str(self._position))

        with open(self._retransmit_file, 'w') as f:
            json.dump(self._pending_retransmits, f)

    def _cleanup(self) -> None:
        """Remove state files after completion."""
        for f in [self._packets_file, self._position_file, self._retransmit_file]:
            if f.exists():
                f.unlink()

    def receive(self) -> Optional[Packet]:
        """
        Receive next packet.

        Returns:
            Packet if available, None if all packets delivered.

        May call sys.exit(1) to simulate process termination.
        """
        if self._terminated:
            return None

        # Check for pending retransmits first
        if self._pending_retransmits:
            seq = self._pending_retransmits.pop(0)
            # Find the packet in original queue
            for _, pkt, _ in self._delivery_queue:
                if pkt.sequence == seq:
                    self._save_position()
                    # Retransmits might also be corrupted
                    if self.rng.random() < self.corruption_prob:
                        pkt = Packet(pkt.sequence, pkt.timestamp, pkt.payload,
                                    pkt.checksum ^ 0xDEADBEEF)
                    return pkt
            # Packet not found (was lost), just continue
            self._save_position()

        # Check if done
        if self._position >= len(self._delivery_queue):
            self._terminated = True
            self._cleanup()
            return None

        # Random termination check
        if self.rng.random() < self.termination_prob:
            self._save_position()
            sys.exit(1)

        # Get next packet from delivery queue
        priority, packet, corrupted = self._delivery_queue[self._position]
        self._position += 1
        self._save_position()

        # Apply corruption if flagged
        if corrupted:
            packet = Packet(
                sequence=packet.sequence,
                timestamp=packet.timestamp,
                payload=packet.payload,
                checksum=packet.checksum ^ 0xDEADBEEF  # Corrupt checksum
            )

        return packet

    def request_retransmit(self, sequence: int) -> None:
        """
        Request retransmission of a packet.

        The packet will be re-queued for delivery.
        """
        if sequence not in self._pending_retransmits:
            self._pending_retransmits.append(sequence)
            self._save_position()

    def verify_checksum(self, packet: Packet) -> bool:
        """Check if packet checksum is valid."""
        return zlib.crc32(packet.payload) == packet.checksum

    def get_ground_truth(self) -> list[int]:
        """
        Get list of all sequence numbers that were generated.
        Only meaningful after completion.
        """
        return sorted(self._generated_sequences)

    def is_terminated(self) -> bool:
        """Check if source has terminated (all packets delivered)."""
        return self._terminated

    def get_position(self) -> int:
        """Get current position in delivery queue."""
        return self._position

    def get_total_deliveries(self) -> int:
        """Get total number of packets to deliver (including duplicates)."""
        return len(self._delivery_queue)


def run_demo():
    """Demo showing termination and restart behavior."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)

        print("Creating message source (seed=42, 100 packets)...")
        source = MessageSource(
            seed=42,
            total_packets=100,
            termination_prob=0.0,  # Disable termination for demo
            state_dir=state_dir
        )

        print(f"Total deliveries: {source.get_total_deliveries()}")

        # Receive some packets
        received = []
        corrupted = 0
        while not source.is_terminated():
            packet = source.receive()
            if packet is None:
                break
            if not source.verify_checksum(packet):
                corrupted += 1
                source.request_retransmit(packet.sequence)
            else:
                received.append(packet.sequence)

        print(f"Received: {len(received)} packets")
        print(f"Corrupted: {corrupted}")
        print(f"Unique sequences: {len(set(received))}")

        # Check for duplicates
        from collections import Counter
        counts = Counter(received)
        dups = [seq for seq, count in counts.items() if count > 1]
        print(f"Duplicates: {len(dups)}")

        # Check ordering
        inversions = sum(1 for i in range(len(received)-1)
                        if received[i] > received[i+1])
        print(f"Inversions: {inversions}")


if __name__ == "__main__":
    run_demo()
