
"""Domain models used by the exam scheduling engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class StudentAccommodation:
    accommodation_type: str
    extension_percentage: Optional[Decimal]
    requires_separate_room: bool
    effective_from: date
    effective_to: Optional[date]
    status: str

    def is_active_on(self, exam_date: date) -> bool:
        return (
            self.status == "ACTIVE"
            and self.effective_from <= exam_date
            and (
                self.effective_to is None
                or exam_date <= self.effective_to
            )
        )


@dataclass(frozen=True)
class StudentParticipant:
    exam_enrollment_id: int
    student_id: int
    student_code: str
    seat_number: str
    accommodations: tuple[StudentAccommodation, ...] = ()
    enrollment_effective_from: Optional[date] = None
    enrollment_effective_to: Optional[date] = None

    def is_enrolled_on(self, exam_date: date) -> bool:
        """Check whether the student's enrollment covers the exam date."""
        if self.enrollment_effective_from is not None:
            if exam_date < self.enrollment_effective_from:
                return False

        if (
            self.enrollment_effective_to is not None
            and exam_date > self.enrollment_effective_to
        ):
            return False

        return True

    def active_accommodations_on(
        self,
        exam_date: date,
    ) -> tuple[StudentAccommodation, ...]:
        return tuple(
            accommodation
            for accommodation in self.accommodations
            if accommodation.is_active_on(exam_date)
        )


@dataclass(frozen=True)
class EquipmentRequirement:
    equipment_id: int
    quantity_required: int
    mandatory: bool = True


@dataclass(frozen=True)
class Exam:
    exam_id: int
    exam_code: str
    course_id: int
    window_start: datetime
    window_end: datetime
    base_duration_minutes: int
    accessibility_required: bool
    participants: tuple[StudentParticipant, ...]
    equipment_requirements: tuple[EquipmentRequirement, ...] = ()

    @property
    def participant_count(self) -> int:
        return len(self.participants)

    def participants_on(
        self,
        exam_date: date,
    ) -> tuple[StudentParticipant, ...]:
        """Return participants whose enrollment is valid on the given date."""
        return tuple(
            participant
            for participant in self.participants
            if participant.is_enrolled_on(exam_date)
        )


@dataclass(frozen=True)
class RoomEquipment:
    equipment_id: int
    quantity: int
    effective_from: date
    effective_to: Optional[date]


@dataclass(frozen=True)
class RoomCapacityPeriod:
    capacity: int
    effective_from: date
    effective_to: Optional[date]


@dataclass(frozen=True)
class RoomClosure:
    start: datetime
    end: datetime
    status: str


@dataclass(frozen=True)
class Room:
    room_id: int
    room_code: str
    is_active: bool
    is_accessible: bool
    capacity_periods: tuple[RoomCapacityPeriod, ...]
    equipment: tuple[RoomEquipment, ...]
    closures: tuple[RoomClosure, ...] = ()


@dataclass(frozen=True)
class InvigilatorAvailability:
    start: datetime
    end: datetime
    status: str


@dataclass(frozen=True)
class Invigilator:
    invigilator_id: int
    invigilator_code: str
    max_daily_hours: Decimal
    status: str
    availability: tuple[InvigilatorAvailability, ...]


@dataclass(frozen=True)
class ScheduledInterval:
    exam_id: int
    start: datetime
    end: datetime
    student_ids: frozenset[int]
    room_id: int
    invigilator_ids: frozenset[int] = frozenset()


@dataclass
class SchedulingDiagnostics:
    eligible_exams: int = 0
    scheduled_exams: int = 0
    unassigned_exams: int = 0
    exceptions_by_reason: dict[str, int] = field(default_factory=dict)

    def record_exception(self, reason_code: str) -> None:
        self.exceptions_by_reason[reason_code] = (
            self.exceptions_by_reason.get(reason_code, 0) + 1
        )
