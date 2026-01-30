# test.py
#
# Durable Event Log – Test Harness
#
# - Restarts EventLogger until MessageSource completes
# - Uses append-only log
# - Measures REAL coverage (unique sequences in log)
# - Measures ordering quality via log status (OK / LATE / RETRANSMIT)
#
# Requirements:
#   message_source.py
#   event_logger.py (your EventLogger + LoggerStats)
#
# Usage:
#   python test.py

from __future__ import annotations

import tempfile
from pathlib import Path

from message_source import MessageSource
from event_logger import EventLogger


# -----------------------------
# Log analysis helpers
# -----------------------------

def unique_sequences_in_log(log_file: Path) -> set[int]:
    seqs = set()

    if not log_file.exists():
        return seqs

    with log_file.open("r", encoding="utf-8") as f:
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

            seqs.add(seq)

    return seqs


def count_statuses(log_file: Path) -> tuple[int, int, int]:
    ok = 0
    late = 0
    retrans = 0

    if not log_file.exists():
        return ok, late, retrans

    with log_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split(",", 3)
            if len(parts) < 4:
                continue

            status = parts[3]
            if status == "OK":
                ok += 1
            elif status == "LATE":
                late += 1
            elif status == "RETRANSMIT":
                retrans += 1

    return ok, late, retrans


# -----------------------------
# Test runner
# -----------------------------

def run_test(seed: int,
             total_packets: int = 500,
             reorder_window: int = 10,
             duplicate_prob: float = 0.05,
             loss_prob: float = 0.02,
             corruption_prob: float = 0.03,
             termination_prob: float = 0.002,
             buffer_size: int = 30) -> None:
    """
    Run one full experiment.
    MessageSource may crash; we restart until completion.
    """
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp)
        log_file = state_dir / "events.log"

        last_stats = None

        # No while / break: bounded for-loop with return
        for attempt in range(1, 10_000):
            source = MessageSource(
                seed=seed,
                total_packets=total_packets,
                reorder_window=reorder_window,
                duplicate_prob=duplicate_prob,
                loss_prob=loss_prob,
                corruption_prob=corruption_prob,
                termination_prob=termination_prob,
                state_dir=state_dir
            )

            logger = EventLogger(source, log_file, buffer_size=buffer_size)
            last_stats = logger.run()

            if source.is_terminated():
                seqs = unique_sequences_in_log(log_file)
                ok, late, retrans = count_statuses(log_file)

                print("=" * 72)
                print(f"Seed {seed} finished after {attempt} run(s)")
                print(f"Coverage (unique): {len(seqs)}/{source.total_packets}")
                print(f"OK: {ok}, LATE: {late}, RETRANSMIT: {retrans}")
                print(f"Inversions (last run stats): {last_stats.inversions}")
                print(f"Lost in buffer (last run stats): {last_stats.final_buffer_size}")
                print(f"Log file: {log_file}")
                return

        print("=" * 72)
        print(f"Seed {seed} did NOT finish within attempt limit.")
        if last_stats is not None:
            print(last_stats)


# -----------------------------
# Main
# -----------------------------

def main() -> None:
    # Baseline (matches assignment example)
    run_test(seed=42)

    # Stress a bit
    run_test(seed=7, termination_prob=0.005)
    run_test(seed=99, reorder_window=20, buffer_size=40)
    run_test(seed=123, loss_prob=0.05, corruption_prob=0.05)


if __name__ == "__main__":
    main()
