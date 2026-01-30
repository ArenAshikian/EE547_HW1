"""
Coordinator for Distributed Merge

Alternates worker execution until both complete.

Provided to students - do not modify.
"""


class Coordinator:
    def __init__(self, worker_a, worker_b):
        self.workers = [worker_a, worker_b]

    def run(self, max_steps: int = 100000) -> dict:
        """Alternate workers until both done or max steps reached."""
        steps = 0
        active = [True, True]

        while any(active) and steps < max_steps:
            for i, worker in enumerate(self.workers):
                if active[i]:
                    active[i] = worker.step()
                    steps += 1

        return {
            "success": not any(active),
            "total_steps": steps,
            "stats_a": self.workers[0].get_stats(),
            "stats_b": self.workers[1].get_stats()
        }
