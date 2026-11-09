
"""Hard-constraint calculations for examination scheduling."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING
from typing import Iterable, Optional

from scheduling.models import (
    Exam,
    Invigilator,
    Room,
    ScheduledInterval,
    StudentAccommodation,
)


def intervals_overlap(
    start_a: datetime,
    end_a: datetime,
    start_b: datetime,
    end_b: datetime,
) -> bool:
    """Half-open interval overlap: touching endpoints are not conflicts."""
    if end_a <= start_a or end_b <= start_b:
        raise ValueError("Intervals must have positive duration.")

    return start_a < end_b and start_b < end_a


def effective_duration_minutes(
    base_duration: int,
    accommodations: Iterable[StudentAccommodation],
    exam_date: date,
) -> int:
    """Apply the highest active extended-time percentage."""
    if base_duration <= 0:
        raise ValueError("Base examination duration must be positive.")

    maximum_percentage = Decimal("0")

    for accommodation in accommodations:
        if not accommodation.is_active_on(exam_date):
            continue

        if accommodation.accommodation_type == "EXTENDED_TIME":
            percentage = accommodation.extension_percentage

            if percentage is None or percentage <= 0:
                raise ValueError(
                    "Active extended-time accommodation has no "
                    "valid extension percentage."
                )

            maximum_percentage = max(maximum_percentage, percentage)

    duration = (
        Decimal(base_duration)
        * (Decimal("1") + maximum_percentage / Decimal("100"))
    )

    return int(
        duration.quantize(
            Decimal("1"),
            rounding=ROUND_CEILING,
        )
    )


def active_accommodations(
    exam: Exam,
    exam_date: date,
) -> dict[int, tuple[StudentAccommodation, ...]]:
    """Return active accommodations for participants enrolled on exam_date."""
    result = {}

    for participant in exam.participants_on(exam_date):
        applicable = participant.active_accommodations_on(exam_date)

        if applicable:
            result[participant.student_id] = applicable

    return result


def exam_duration_minutes(exam: Exam, start_time: datetime) -> int:
    """Calculate duration using only participants enrolled on the exam date."""
    exam_date = start_time.date()

    accommodations = (
        accommodation
        for participant in exam.participants_on(exam_date)
        for accommodation in participant.accommodations
    )

    return effective_duration_minutes(
        exam.base_duration_minutes,
        accommodations,
        exam_date,
    )


def room_capacity_on(room: Room, exam_date: date) -> int | None:
    """Return the applicable room capacity, or None if not defined."""
    applicable = [
        period
        for period in room.capacity_periods
        if period.effective_from <= exam_date
        and (
            period.effective_to is None
            or exam_date <= period.effective_to
        )
    ]

    if not applicable:
        return None

    if len(applicable) != 1:
        raise ValueError(
            f"Room {room.room_code} has overlapping capacity periods."
        )

    capacity = applicable[0].capacity
    return capacity if capacity > 0 else None


def room_is_closed(
    room: Room,
    start: datetime,
    end: datetime,
) -> bool:
    return any(
        closure.status == "ACTIVE"
        and intervals_overlap(
            start,
            end,
            closure.start,
            closure.end,
        )
        for closure in room.closures
    )


def room_has_required_equipment(
    room: Room,
    exam: Exam,
    exam_date: date,
) -> bool:
    """Check mandatory normalized equipment requirements."""
    available: dict[int, int] = {}

    for equipment in room.equipment:
        if (
            equipment.effective_from <= exam_date
            and (
                equipment.effective_to is None
                or exam_date <= equipment.effective_to
            )
        ):
            available[equipment.equipment_id] = (
                available.get(equipment.equipment_id, 0)
                + equipment.quantity
            )

    for requirement in exam.equipment_requirements:
        if not requirement.mandatory:
            continue

        if available.get(requirement.equipment_id, 0) < (
            requirement.quantity_required
        ):
            return False

    return True


def unsupported_accommodation_students(
    exam: Exam,
    exam_date: date,
) -> frozenset[int]:
    """Find participants with accommodation types lacking a verified mapping."""
    unsupported = set()

    for student_id, accommodations in active_accommodations(
        exam,
        exam_date,
    ).items():
        if any(
            accommodation.accommodation_type == "SPECIAL_EQUIPMENT"
            for accommodation in accommodations
        ):
            unsupported.add(student_id)

    return frozenset(unsupported)


def room_is_eligible(
    room: Room,
    exam: Exam,
    start: datetime,
    end: datetime,
    allocated_student_count: int,
    allocated_student_ids: Optional[Iterable[int]] = None,
) -> tuple[bool, str | None]:
    """Return room eligibility and a supported blocking reason.

    allocated_student_ids should identify the actual students assigned
    to this room. When omitted, all date-eligible exam participants are
    considered for accommodation checks.
    """
    if end <= start:
        return False, "NO_VALID_TIMESLOT"

    if not room.is_active:
        return False, "NO_ROOM_CAPACITY"

    capacity = room_capacity_on(room, start.date())

    if capacity is None or allocated_student_count > capacity:
        return False, "NO_ROOM_CAPACITY"

    if allocated_student_count <= 0:
        return False, "NO_ELIGIBLE_STUDENTS"

    if room_is_closed(room, start, end):
        return False, "ROOM_CLOSED"

    participants = exam.participants_on(start.date())

    if allocated_student_ids is None:
        selected_student_ids = {
            participant.student_id for participant in participants
        }
    else:
        selected_student_ids = set(allocated_student_ids)

    participant_ids = {
        participant.student_id for participant in participants
    }

    if not selected_student_ids.issubset(participant_ids):
        return False, "NO_ELIGIBLE_STUDENTS"

    if len(selected_student_ids) != allocated_student_count:
        return False, "NO_ELIGIBLE_STUDENTS"

    selected_accommodations = [
        accommodation
        for participant in participants
        if participant.student_id in selected_student_ids
        for accommodation in participant.active_accommodations_on(
            start.date()
        )
    ]

    if any(
        accommodation.accommodation_type == "SPECIAL_EQUIPMENT"
        for accommodation in selected_accommodations
    ):
        return False, "ACCOMMODATION_CONFLICT"

    if exam.accessibility_required and not room.is_accessible:
        return False, "ACCOMMODATION_CONFLICT"

    if any(
        accommodation.accommodation_type == "ACCESSIBLE_ROOM"
        for accommodation in selected_accommodations
    ) and not room.is_accessible:
        return False, "ACCOMMODATION_CONFLICT"

    if not room_has_required_equipment(room, exam, start.date()):
        return False, "NO_EQUIPMENT"

    return True, None


def separate_room_students(
    exam: Exam,
    exam_date: date,
) -> frozenset[int]:
    """Return enrolled students requiring a separate room."""
    separate = set()

    for participant in exam.participants_on(exam_date):
        for accommodation in participant.active_accommodations_on(
            exam_date
        ):
            if (
                accommodation.accommodation_type == "SEPARATE_ROOM"
                or accommodation.requires_separate_room
            ):
                separate.add(participant.student_id)

    return frozenset(separate)


def invigilator_is_available(
    invigilator: Invigilator,
    start: datetime,
    end: datetime,
) -> bool:
    """Require full AVAILABLE coverage with no overlapping UNAVAILABLE slot."""
    if invigilator.status != "ACTIVE" or end <= start:
        return False

    if any(
        slot.status == "UNAVAILABLE"
        and intervals_overlap(start, end, slot.start, slot.end)
        for slot in invigilator.availability
    ):
        return False

    return any(
        slot.status == "AVAILABLE"
        and slot.start <= start
        and slot.end >= end
        for slot in invigilator.availability
    )


def invigilator_workload_allows(
    invigilator: Invigilator,
    start: datetime,
    end: datetime,
    existing_intervals: Iterable[ScheduledInterval],
) -> bool:
    """Check daily workload and reject overlapping assignments."""
    if end <= start:
        return False

    assigned_minutes = 0

    for interval in existing_intervals:
        if invigilator.invigilator_id not in interval.invigilator_ids:
            continue

        if intervals_overlap(
            start,
            end,
            interval.start,
            interval.end,
        ):
            return False

        if interval.start.date() == start.date():
            assigned_minutes += int(
                (interval.end - interval.start).total_seconds() / 60
            )

    assigned_minutes += int(
        (end - start).total_seconds() / 60
    )

    maximum_minutes = int(
        invigilator.max_daily_hours * Decimal("60")
    )

    return assigned_minutes <= maximum_minutes


def student_conflict_exists(
    student_ids: Iterable[int],
    start: datetime,
    end: datetime,
    existing_intervals: Iterable[ScheduledInterval],
) -> bool:
    """Check whether any selected student has an overlapping assignment."""
    if end <= start:
        return True

    target_students = set(student_ids)

    for interval in existing_intervals:
        if not target_students.intersection(interval.student_ids):
            continue

        if intervals_overlap(
            start,
            end,
            interval.start,
            interval.end,
        ):
            return True

    return False
