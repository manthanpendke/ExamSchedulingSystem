"""Deterministic student examination conflict graph."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ConflictGraph:
    adjacency: dict[int, frozenset[int]]

    def neighbors(self, exam_id: int) -> frozenset[int]:
        return self.adjacency.get(exam_id, frozenset())

    def degree(self, exam_id: int) -> int:
        return len(self.neighbors(exam_id))

    def conflicts(self, exam_a: int, exam_b: int) -> bool:
        return exam_b in self.neighbors(exam_a)

    def ordered_exams(self) -> list[int]:
        """Most constrained exams first; exam ID breaks ties."""
        return sorted(
            self.adjacency,
            key=lambda exam_id: (
                -self.degree(exam_id),
                exam_id,
            ),
        )


def build_conflict_graph(
    exam_students: dict[int, Iterable[int]],
) -> ConflictGraph:
    """
    Connect two exams when at least one student is registered in both.

    Input contains only eligible registered participants.
    Withdrawn and exempt participants must be excluded by the repository.
    """

    student_exams: dict[int, set[int]] = defaultdict(set)

    normalized: dict[int, set[int]] = {}

    for exam_id, student_ids in exam_students.items():
        normalized[exam_id] = set(student_ids)

        for student_id in normalized[exam_id]:
            student_exams[student_id].add(exam_id)

    adjacency: dict[int, set[int]] = {
        exam_id: set() for exam_id in normalized
    }

    for exam_ids in student_exams.values():
        ordered = sorted(exam_ids)

        for index, exam_a in enumerate(ordered):
            for exam_b in ordered[index + 1:]:
                adjacency[exam_a].add(exam_b)
                adjacency[exam_b].add(exam_a)

    return ConflictGraph(
        adjacency={
            exam_id: frozenset(neighbors)
            for exam_id, neighbors in adjacency.items()
        }
    )