"""Snapshot-based undo/redo shared by every editor tab.

Each editor keeps one `SnapshotHistory` scoped to whatever item it currently has
open (a sprite, a scene, the active palette, ...). `reset()` is called whenever
that item is (re)loaded, establishing a baseline with nothing to undo past.
`commit()` is called after each discrete, user-visible edit -- a finished brush
stroke, a changed field, an added/removed row -- not on every intermediate value
while a drag is in progress, or a single stroke would need dozens of Ctrl+Z to
undo. Equality-deduplicates so read-only tool switches or no-op edits don't
burn a history slot.
"""

from __future__ import annotations

import copy
from typing import Any


class SnapshotHistory:
    def __init__(self, limit: int = 60) -> None:
        self._limit = limit
        self._past: list[Any] = []
        self._present: Any = None
        self._future: list[Any] = []
        self._has_state = False

    def reset(self, state: Any) -> None:
        self._past.clear()
        self._future.clear()
        self._present = copy.deepcopy(state)
        self._has_state = True

    def commit(self, state: Any) -> None:
        if not self._has_state:
            self.reset(state)
            return
        if state == self._present:
            return
        self._past.append(self._present)
        if len(self._past) > self._limit:
            self._past.pop(0)
        self._present = copy.deepcopy(state)
        self._future.clear()

    def can_undo(self) -> bool:
        return bool(self._past)

    def can_redo(self) -> bool:
        return bool(self._future)

    def undo(self) -> Any | None:
        if not self._past:
            return None
        self._future.append(self._present)
        self._present = self._past.pop()
        return copy.deepcopy(self._present)

    def redo(self) -> Any | None:
        if not self._future:
            return None
        self._past.append(self._present)
        self._present = self._future.pop()
        return copy.deepcopy(self._present)
