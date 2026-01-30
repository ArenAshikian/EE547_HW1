# EE 547  Homework #1: Coordination Under Uncertainty  
**Spring 2026**

**Assigned:** January 14  
**Due:** Tuesday, January 27 at 23:59  


# Overview

This assignment explores foundational ideas in distributed systems, focusing on coordination, uncertainty, and durability. The problems emphasize algorithmic reasoning rather than infrastructure: no Docker, servers, or cloud services are required. All communication and persistence are simulated using local files and controlled interfaces.

The homework consists of three independent problems:

1. **Distributed Merge** — coordination via file-based message passing  
2. **Robust HTTP Client** — handling unreliable networks with retries and backoff  
3. **Durable Event Log** — persistence under reordering, duplication, corruption, and termination

Each problem is implemented separately and includes its own README explaining design choices.

---

# Requirements

- Python 3.11 or newer
- Use **only Python standard library modules** unless explicitly stated
- All submitted code must be your own work
- No shared memory or direct inter-process communication unless specified
- Programs must handle failures gracefully (no crashes)

---
# Repository Structure

README.md
q1/
├── merge_worker.py
└── README.md

q2/
├── http_client.py
└── README.md

q3/
├── event_logger.py
└── README.md
