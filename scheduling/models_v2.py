
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True)
class ExamBatch:
    """Students allocated to one exam sitting."""

    exam_id: int
    course_id: int
    student_ids: tuple[int, ...]
    extended_student_ids: tuple[int, ...] = ()

    def __post_init__(self):
        if self.exam_id <= 0 or self.course_id <= 0:
            raise ValueError("ExamID and CourseID must be positive.")

        if len(self.student_ids) != len(set(self.student_ids)):
            raise ValueError("Duplicate students in an exam batch.")

        if not set(self.extended_student_ids).issubset(set(self.student_ids)):
            raise ValueError(
                "Extended-time students must belong to the exam batch."
            )

    @property
    def normal_student_count(self) -> int:
        return len(self.student_ids) - len(self.extended_student_ids)

    @property
    def extended_student_count(self) -> int:
        return len(self.extended_student_ids)


@dataclass(frozen=True)
class RoomBooking:
    """A proposed sitting in a physical room."""

    exam_id: int
    course_id: int
    room_id: int
    start_time: datetime
    batch: ExamBatch
    standard_duration_minutes: int = 90
    extended_duration_minutes: int = 120

    def __post_init__(self):
        if self.exam_id != self.batch.exam_id:
            raise ValueError("Booking and batch ExamID do not match.")

        if self.course_id != self.batch.course_id:
            raise ValueError("Booking and batch CourseID do not match.")

        if self.room_id <= 0:
            raise ValueError("RoomID must be positive.")

        if self.standard_duration_minutes <= 0:
            raise ValueError("Standard duration must be positive.")

        if self.extended_duration_minutes < self.standard_duration_minutes:
            raise ValueError(
                "Extended duration cannot be shorter than standard duration."
            )

    @property
    def standard_end(self) -> datetime:
        return self.start_time + timedelta(
            minutes=self.standard_duration_minutes
        )

    @property
    def extended_end(self) -> datetime:
        return self.start_time + timedelta(
            minutes=self.extended_duration_minutes
        )

    @property
    def latest_end(self) -> datetime:
        if self.batch.extended_student_count:
            return self.extended_end
        return self.standard_end


@dataclass(frozen=True)
class OccupancyInterval:
    room_id: int
    exam_id: int
    course_id: int
    student_id: int
    start_time: datetime
    end_time: datetime


@dataclass
class ConstraintViolation:
    code: str
    severity: str
    message: str
    exam_ids: list[int] = field(default_factory=list)
    room_id: int | None = None
    details: dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    passed: bool
    violations: list[ConstraintViolation]

    @property
    def violation_count(self) -> int:
        return len(self.violations)
