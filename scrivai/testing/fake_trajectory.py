"""FakeTrajectoryStore — in-memory SQLite TrajectoryStore for tests.

Behaves identically to the production TrajectoryStore (inherits the same schema
and record_* implementations) but uses an isolated :memory: SQLite instance.

Reference: docs/superpowers/specs/2026-04-16-scrivai-m0.25-design.md §4.4.
"""

from __future__ import annotations

from scrivai.trajectory.store import TrajectoryStore


class FakeTrajectoryStore(TrajectoryStore):
    """Runs the real schema against an :memory: SQLite database.

    Usage::

        store = FakeTrajectoryStore()
        store.start_run(...)
    """

    def __init__(self) -> None:
        super().__init__(db_path=":memory:")
