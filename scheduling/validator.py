"""Independent, read-only validation of examination schedules.

This validator independently checks the generated schedule against the
domain models. It does not import scheduling.constraints and never
connects to SQL Server.

Default operating hours: 08:00–18:00.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING
from typing import Iterable


# ---------------------------------------------------------------------
# VALIDATION MODELS
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    exam_id: int | None = None
    room_id: int | None = None
    invigilator_id: int | None = None
    student_id: int | None = None


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    checks: Counter = field(default_factory=Counter)

    @property
    def passed(self) -> bool:
        return not self.issues

    def add(
        self,
        code: str,
        message: str,
        *,
        exam_id: int | None = None,
        room_id: int | None = None,
        invigilator_id: int | None = None,
        student_id: int | None = None,
    ) -> None:
        self.issues.append(
            ValidationIssue(
                code=code,
                message=message,
                exam_id=exam_id,
                room_id=room_id,
                invigilator_id=invigilator_id,
                student_id=student_id,
            )
        )


# ---------------------------------------------------------------------
# INDEPENDENT RULE CALCULATIONS
# ---------------------------------------------------------------------

def _overlap(
    a_start: datetime,
    a_end: datetime,
    b_start: datetime,
    b_end: datetime,
) -> bool:
    if a_end <= a_start or b_end <= b_start:
        return True

    return a_start < b_end and b_start < a_end


def _active_accommodations(
    participant,
    exam_date: date,
) -> list:
    return [
        item
        for item in participant.accommodations
        if item.status == "ACTIVE"
        and item.effective_from <= exam_date
        and (
            item.effective_to is None
            or exam_date <= item.effective_to
        )
    ]


def _expected_duration(
    exam,
    participants,
    exam_date: date,
) -> int:
    percentages = []

    if exam.base_duration_minutes <= 0:
        raise ValueError(
            f"Exam {exam.exam_code} has a non-positive duration."
        )

    for participant in participants:
        for accommodation in _active_accommodations(
            participant,
            exam_date,
        ):
            if accommodation.accommodation_type != "EXTENDED_TIME":
                continue

            percentage = accommodation.extension_percentage

            if percentage is None or percentage <= 0:
                raise ValueError(
                    f"Student {participant.student_id} has an "
                    "invalid extended-time percentage."
                )

            percentages.append(Decimal(percentage))

    maximum_percentage = max(
        percentages,
        default=Decimal("0"),
    )

    duration = (
        Decimal(exam.base_duration_minutes)
        * (
            Decimal("1")
            + maximum_percentage / Decimal("100")
        )
    )

    return int(
        duration.quantize(
            Decimal("1"),
            rounding=ROUND_CEILING,
        )
    )


def _room_capacity(
    room,
    exam_date: date,
) -> int | None:
    periods = [
        period
        for period in room.capacity_periods
        if period.effective_from <= exam_date
        and (
            period.effective_to is None
            or exam_date <= period.effective_to
        )
    ]

    if len(periods) != 1:
        return None

    capacity = periods[0].capacity

    if capacity <= 0:
        return None

    return capacity


def _room_has_equipment(
    room,
    exam,
    exam_date: date,
) -> bool:
    quantities = defaultdict(int)

    for item in room.equipment:
        if (
            item.effective_from <= exam_date
            and (
                item.effective_to is None
                or exam_date <= item.effective_to
            )
        ):
            quantities[item.equipment_id] += item.quantity

    for requirement in exam.equipment_requirements:
        if not requirement.mandatory:
            continue

        if (
            quantities[requirement.equipment_id]
            < requirement.quantity_required
        ):
            return False

    return True


def _room_is_closed(
    room,
    start: datetime,
    end: datetime,
) -> bool:
    return any(
        closure.status == "ACTIVE"
        and _overlap(
            start,
            end,
            closure.start,
            closure.end,
        )
        for closure in room.closures
    )


def _invigilator_available(
    invigilator,
    start: datetime,
    end: datetime,
) -> bool:
    if invigilator.status != "ACTIVE":
        return False

    if any(
        slot.status == "UNAVAILABLE"
        and _overlap(
            start,
            end,
            slot.start,
            slot.end,
        )
        for slot in invigilator.availability
    ):
        return False

    return any(
        slot.status == "AVAILABLE"
        and slot.start <= start
        and slot.end >= end
        for slot in invigilator.availability
    )


def _needs_separate_room(
    participant,
    exam_date: date,
) -> bool:
    return any(
        accommodation.accommodation_type == "SEPARATE_ROOM"
        or accommodation.requires_separate_room
        for accommodation in _active_accommodations(
            participant,
            exam_date,
        )
    )


def _requires_accessible_room(
    participant,
    exam_date: date,
) -> bool:
    return any(
        accommodation.accommodation_type == "ACCESSIBLE_ROOM"
        for accommodation in _active_accommodations(
            participant,
            exam_date,
        )
    )


# ---------------------------------------------------------------------
# MAIN VALIDATOR
# ---------------------------------------------------------------------

def validate_schedule(
    exams: Iterable,
    rooms: Iterable,
    invigilators: Iterable,
    result,
    relief_rooms_per_invigilator: int = 4,
    *,
    operating_start: time = time(8, 0),
    operating_end: time = time(18, 0),
) -> ValidationReport:
    """Independently validate a proposed in-memory schedule.

    The function is read-only.

    Args:
        exams: Source Exam model objects.
        rooms: Source Room model objects.
        invigilators: Source Invigilator model objects.
        result: ScheduleResult from scheduling.engine.
        relief_rooms_per_invigilator: Retained for API compatibility.
        operating_start: Earliest permitted daily start.
        operating_end: Latest permitted daily finish.

    Returns:
        ValidationReport containing all detected violations.
    """

    del relief_rooms_per_invigilator

    report = ValidationReport()

    if operating_end <= operating_start:
        raise ValueError(
            "Operating end time must be later than operating start time."
        )

    exams = list(exams)
    rooms = list(rooms)
    invigilators = list(invigilators)

    exams_by_id = {
        item.exam_id: item
        for item in exams
    }

    rooms_by_id = {
        item.room_id: item
        for item in rooms
    }

    staff_by_id = {
        item.invigilator_id: item
        for item in invigilators
    }

    if len(exams_by_id) != len(exams):
        report.add(
            "DUPLICATE_SOURCE_EXAM_ID",
            "Source data contains duplicate exam IDs.",
        )

    if len(rooms_by_id) != len(rooms):
        report.add(
            "DUPLICATE_SOURCE_ROOM_ID",
            "Source data contains duplicate room IDs.",
        )

    if len(staff_by_id) != len(invigilators):
        report.add(
            "DUPLICATE_SOURCE_INVIGILATOR_ID",
            "Source data contains duplicate invigilator IDs.",
        )

    scheduled = list(result.scheduled_exams)
    exceptions = list(result.exceptions)

    scheduled_ids = [
        item.exam_id
        for item in scheduled
    ]

    exception_ids = [
        item.exam_id
        for item in exceptions
    ]

    scheduled_counts = Counter(scheduled_ids)
    exception_counts = Counter(exception_ids)

    for exam_id, count in scheduled_counts.items():
        if count > 1:
            report.add(
                "DUPLICATE_SCHEDULED_EXAM",
                f"Exam {exam_id} appears {count} times.",
                exam_id=exam_id,
            )

    for exam_id, count in exception_counts.items():
        if count > 1:
            report.add(
                "DUPLICATE_EXCEPTION",
                f"Exam {exam_id} has {count} exceptions.",
                exam_id=exam_id,
            )

    for exam_id in sorted(
        set(scheduled_ids) & set(exception_ids)
    ):
        report.add(
            "SCHEDULED_AND_EXCEPTION",
            f"Exam {exam_id} is both scheduled and unassigned.",
            exam_id=exam_id,
        )

    for exam_id in sorted(
        set(scheduled_ids) - set(exams_by_id)
    ):
        report.add(
            "UNKNOWN_SCHEDULED_EXAM",
            f"Scheduled exam {exam_id} is not in source data.",
            exam_id=exam_id,
        )

    for exam_id in sorted(
        set(exception_ids) - set(exams_by_id)
    ):
        report.add(
            "UNKNOWN_EXCEPTION_EXAM",
            f"Exception exam {exam_id} is not in source data.",
            exam_id=exam_id,
        )

    # Cross-exam booking indexes.
    student_bookings = defaultdict(list)
    staff_bookings = defaultdict(list)
    room_bookings = defaultdict(list)

    # -----------------------------------------------------------------
    # EXAM-LEVEL VALIDATION
    # -----------------------------------------------------------------

    for item in scheduled:
        exam = exams_by_id.get(item.exam_id)

        if exam is None:
            continue

        report.checks["scheduled_exams_examined"] += 1

        if item.start < exam.window_start:
            report.add(
                "EXAM_BEFORE_WINDOW",
                "Exam starts before its permitted window.",
                exam_id=item.exam_id,
            )

        if item.end > exam.window_end:
            report.add(
                "EXAM_AFTER_WINDOW",
                "Exam ends after its permitted window.",
                exam_id=item.exam_id,
            )

        if item.end <= item.start:
            report.add(
                "INVALID_EXAM_INTERVAL",
                "Exam interval has non-positive duration.",
                exam_id=item.exam_id,
            )
            continue

        if item.start.date() != item.end.date():
            report.add(
                "CROSSES_MIDNIGHT",
                "Exam crosses midnight.",
                exam_id=item.exam_id,
            )

        # Operating-hours validation.
        if item.start.time() < operating_start:
            report.add(
                "OUTSIDE_OPERATING_HOURS",
                (
                    f"Exam starts at {item.start.time()}, "
                    f"before {operating_start}."
                ),
                exam_id=item.exam_id,
            )

        if item.end.time() > operating_end:
            report.add(
                "OUTSIDE_OPERATING_HOURS",
                (
                    f"Exam ends at {item.end.time()}, "
                    f"after {operating_end}."
                ),
                exam_id=item.exam_id,
            )

        exam_date = item.start.date()

        participants = list(
            exam.participants_on(exam_date)
        )

        participant_by_id = {
            participant.student_id: participant
            for participant in participants
        }

        expected_students = set(participant_by_id)

        if len(expected_students) != len(participants):
            report.add(
                "DUPLICATE_SOURCE_PARTICIPANT",
                "Exam contains duplicate source participants.",
                exam_id=item.exam_id,
            )

        # Duration validation.
        try:
            expected_duration = _expected_duration(
                exam,
                participants,
                exam_date,
            )

            expected_end = (
                item.start
                + timedelta(minutes=expected_duration)
            )

            if expected_end != item.end:
                report.add(
                    "INCORRECT_EXAM_DURATION",
                    (
                        f"Expected end {expected_end.isoformat()}, "
                        f"actual end {item.end.isoformat()}."
                    ),
                    exam_id=item.exam_id,
                )

        except (
            ValueError,
            TypeError,
            ArithmeticError,
        ) as exc:
            report.add(
                "INVALID_ACCOMMODATION_DURATION",
                str(exc),
                exam_id=item.exam_id,
            )

        allocations = list(item.room_allocations)

        if not allocations:
            report.add(
                "NO_ROOM_ALLOCATIONS",
                "Scheduled exam has no room allocations.",
                exam_id=item.exam_id,
            )

        allocated_students = []
        exam_room_ids = []

        # -------------------------------------------------------------
        # ROOM ALLOCATION VALIDATION
        # -------------------------------------------------------------

        for allocation in allocations:
            report.checks["room_allocations_examined"] += 1

            room = rooms_by_id.get(allocation.room_id)

            exam_room_ids.append(allocation.room_id)

            allocated_students.extend(
                allocation.student_ids
            )

            if allocation.exam_id != item.exam_id:
                report.add(
                    "ROOM_ALLOCATION_EXAM_MISMATCH",
                    "Room allocation references a different exam.",
                    exam_id=item.exam_id,
                    room_id=allocation.room_id,
                )

            if (
                allocation.start != item.start
                or allocation.end != item.end
            ):
                report.add(
                    "ROOM_INTERVAL_MISMATCH",
                    "Room allocation interval differs from exam interval.",
                    exam_id=item.exam_id,
                    room_id=allocation.room_id,
                )

            if room is None:
                report.add(
                    "UNKNOWN_ROOM",
                    f"Room {allocation.room_id} was not loaded.",
                    exam_id=item.exam_id,
                    room_id=allocation.room_id,
                )
                continue

            if not room.is_active:
                report.add(
                    "INACTIVE_ROOM",
                    f"Room {room.room_code} is inactive.",
                    exam_id=item.exam_id,
                    room_id=room.room_id,
                )

            capacity = _room_capacity(
                room,
                exam_date,
            )

            if capacity is None:
                report.add(
                    "INVALID_ROOM_CAPACITY",
                    (
                        f"Room {room.room_code} has no unique "
                        "positive effective capacity."
                    ),
                    exam_id=item.exam_id,
                    room_id=room.room_id,
                )
            else:
                student_count = len(allocation.student_ids)

                if student_count > capacity:
                    report.add(
                        "ROOM_CAPACITY_EXCEEDED",
                        (
                            f"{room.room_code}: {student_count} "
                            f"students exceed capacity {capacity}."
                        ),
                        exam_id=item.exam_id,
                        room_id=room.room_id,
                    )

                if allocation.assigned_capacity < student_count:
                    report.add(
                        "ASSIGNED_CAPACITY_TOO_LOW",
                        f"{room.room_code}: assigned capacity is too low.",
                        exam_id=item.exam_id,
                        room_id=room.room_id,
                    )

                if allocation.assigned_capacity > capacity:
                    report.add(
                        "ASSIGNED_CAPACITY_EXCEEDS_ROOM",
                        f"{room.room_code}: assigned capacity exceeds room capacity.",
                        exam_id=item.exam_id,
                        room_id=room.room_id,
                    )

            if _room_is_closed(
                room,
                item.start,
                item.end,
            ):
                report.add(
                    "ROOM_CLOSED",
                    f"Room {room.room_code} is closed during the exam.",
                    exam_id=item.exam_id,
                    room_id=room.room_id,
                )

            if not _room_has_equipment(
                room,
                exam,
                exam_date,
            ):
                report.add(
                    "ROOM_EQUIPMENT_MISSING",
                    f"Room {room.room_code} lacks mandatory equipment.",
                    exam_id=item.exam_id,
                    room_id=room.room_id,
                )

            if (
                exam.accessibility_required
                and not room.is_accessible
            ):
                report.add(
                    "EXAM_ACCESSIBILITY_VIOLATION",
                    f"Room {room.room_code} is not accessible.",
                    exam_id=item.exam_id,
                    room_id=room.room_id,
                )

            for student_id in allocation.student_ids:
                participant = participant_by_id.get(student_id)

                if participant is None:
                    report.add(
                        "INELIGIBLE_STUDENT_ALLOCATED",
                        (
                            f"Student {student_id} is not eligible "
                            "on the exam date."
                        ),
                        exam_id=item.exam_id,
                        room_id=room.room_id,
                        student_id=student_id,
                    )
                    continue

                accommodations = _active_accommodations(
                    participant,
                    exam_date,
                )

                accommodation_types = {
                    accommodation.accommodation_type
                    for accommodation in accommodations
                }

                if "SPECIAL_EQUIPMENT" in accommodation_types:
                    report.add(
                        "UNSUPPORTED_SPECIAL_EQUIPMENT",
                        f"Student {student_id} has unsupported special equipment.",
                        exam_id=item.exam_id,
                        room_id=room.room_id,
                        student_id=student_id,
                    )

                if (
                    _requires_accessible_room(
                        participant,
                        exam_date,
                    )
                    and not room.is_accessible
                ):
                    report.add(
                        "ACCESSIBILITY_ACCOMMODATION_VIOLATION",
                        f"Student {student_id} requires an accessible room.",
                        exam_id=item.exam_id,
                        room_id=room.room_id,
                        student_id=student_id,
                    )

                needs_separate = _needs_separate_room(
                    participant,
                    exam_date,
                )

                if (
                    needs_separate
                    and allocation.group_type != "SEPARATE"
                ):
                    report.add(
                        "SEPARATE_ROOM_VIOLATION",
                        f"Student {student_id} requires a separate room.",
                        exam_id=item.exam_id,
                        room_id=room.room_id,
                        student_id=student_id,
                    )

                if (
                    not needs_separate
                    and allocation.group_type == "SEPARATE"
                ):
                    report.add(
                        "UNNECESSARY_SEPARATE_GROUP",
                        (
                            f"Student {student_id} is in a separate "
                            "group without that requirement."
                        ),
                        exam_id=item.exam_id,
                        room_id=room.room_id,
                        student_id=student_id,
                    )

            room_bookings[room.room_id].append(
                (
                    item.start,
                    item.end,
                    item.exam_id,
                )
            )

        # One room must not appear more than once within an exam.
        if len(exam_room_ids) != len(set(exam_room_ids)):
            report.add(
                "DUPLICATE_ROOM_IN_EXAM",
                "An exam uses the same room more than once.",
                exam_id=item.exam_id,
            )

        # Every eligible student must be allocated exactly once.
        student_counts = Counter(allocated_students)

        for student_id, count in student_counts.items():
            if count != 1:
                report.add(
                    "STUDENT_ALLOCATED_MULTIPLE_ROOMS",
                    (
                        f"Student {student_id} appears "
                        f"in {count} room allocations."
                    ),
                    exam_id=item.exam_id,
                    student_id=student_id,
                )

        allocated_set = set(allocated_students)

        for student_id in sorted(
            expected_students - allocated_set
        ):
            report.add(
                "STUDENT_NOT_ALLOCATED",
                f"Eligible student {student_id} has no room.",
                exam_id=item.exam_id,
                student_id=student_id,
            )

        for student_id in sorted(
            allocated_set - expected_students
        ):
            report.add(
                "UNEXPECTED_STUDENT_ALLOCATION",
                f"Student {student_id} is not eligible for this exam.",
                exam_id=item.exam_id,
                student_id=student_id,
            )

        for student_id in allocated_set:
            student_bookings[student_id].append(
                (
                    item.start,
                    item.end,
                    item.exam_id,
                )
            )

        # -------------------------------------------------------------
        # INVIGILATOR VALIDATION
        # -------------------------------------------------------------

        assignments = list(
            item.invigilator_assignments
        )

        if not assignments:
            report.add(
                "NO_INVIGILATOR_ASSIGNMENTS",
                "Scheduled exam has no invigilator assignments.",
                exam_id=item.exam_id,
            )

        staff_ids = [
            assignment.invigilator_id
            for assignment in assignments
        ]

        for staff_id, count in Counter(staff_ids).items():
            if count > 1:
                report.add(
                    "DUPLICATE_INVIGILATOR_WITHIN_EXAM",
                    f"Invigilator {staff_id} appears {count} times.",
                    exam_id=item.exam_id,
                    invigilator_id=staff_id,
                )

        primary_by_room = Counter(
            assignment.room_id
            for assignment in assignments
            if assignment.role == "PRIMARY"
        )

        expected_room_set = set(exam_room_ids)

        for room_id in expected_room_set:
            if primary_by_room[room_id] != 1:
                report.add(
                    "PRIMARY_COVERAGE_INVALID",
                    (
                        f"Room {room_id} has "
                        f"{primary_by_room[room_id]} PRIMARY assignments."
                    ),
                    exam_id=item.exam_id,
                    room_id=room_id,
                )

        if len(assignments) != len(allocations):
            report.add(
                "INVIGILATOR_COUNT_INVALID",
                (
                    f"Expected {len(allocations)} invigilators, "
                    f"found {len(assignments)}."
                ),
                exam_id=item.exam_id,
            )

        for assignment in assignments:
            if assignment.role != "PRIMARY":
                report.add(
                    "INVALID_INVIGILATOR_ROLE",
                    f"Unexpected invigilator role {assignment.role!r}.",
                    exam_id=item.exam_id,
                    invigilator_id=assignment.invigilator_id,
                )

            if assignment.room_id not in expected_room_set:
                report.add(
                    "STAFF_ASSIGNED_TO_UNKNOWN_ROOM",
                    (
                        f"Invigilator assignment references room "
                        f"{assignment.room_id}."
                    ),
                    exam_id=item.exam_id,
                    invigilator_id=assignment.invigilator_id,
                )

            if assignment.covered_room_ids:
                report.add(
                    "UNEXPECTED_RELIEF_COVERAGE",
                    "PRIMARY invigilator must not have relief coverage.",
                    exam_id=item.exam_id,
                    invigilator_id=assignment.invigilator_id,
                )

            staff = staff_by_id.get(
                assignment.invigilator_id
            )

            if staff is None:
                report.add(
                    "UNKNOWN_INVIGILATOR",
                    (
                        f"Invigilator {assignment.invigilator_id} "
                        "was not loaded."
                    ),
                    exam_id=item.exam_id,
                    invigilator_id=assignment.invigilator_id,
                )
                continue

            if not _invigilator_available(
                staff,
                item.start,
                item.end,
            ):
                report.add(
                    "INVIGILATOR_UNAVAILABLE",
                    (
                        f"Invigilator {staff.invigilator_code} "
                        "is not available for the full interval."
                    ),
                    exam_id=item.exam_id,
                    invigilator_id=staff.invigilator_id,
                )

            staff_bookings[staff.invigilator_id].append(
                (
                    item.start,
                    item.end,
                    item.exam_id,
                )
            )

    # -----------------------------------------------------------------
    # CROSS-EXAM CONFLICT VALIDATION
    # -----------------------------------------------------------------

    def check_double_bookings(
        bookings_by_resource,
        issue_code: str,
        resource_name: str,
    ) -> None:
        for resource_id, bookings in bookings_by_resource.items():
            ordered = sorted(
                bookings,
                key=lambda booking: (
                    booking[0],
                    booking[1],
                    booking[2],
                ),
            )

            for index, first in enumerate(ordered):
                for second in ordered[index + 1:]:
                    if second[0] >= first[1]:
                        break

                    if first[2] == second[2]:
                        continue

                    if _overlap(
                        first[0],
                        first[1],
                        second[0],
                        second[1],
                    ):
                        report.add(
                            issue_code,
                            (
                                f"{resource_name} {resource_id} is "
                                f"booked by exams {first[2]} and {second[2]}."
                            ),
                        )

    check_double_bookings(
        room_bookings,
        "ROOM_DOUBLE_BOOKED",
        "Room",
    )

    check_double_bookings(
        student_bookings,
        "STUDENT_DOUBLE_BOOKED",
        "Student",
    )

    check_double_bookings(
        staff_bookings,
        "INVIGILATOR_DOUBLE_BOOKED",
        "Invigilator",
    )

    # Invigilator daily workload.
    for staff_id, bookings in staff_bookings.items():
        staff = staff_by_id.get(staff_id)

        if staff is None:
            continue

        daily_minutes = defaultdict(int)

        for start, end, exam_id in bookings:
            daily_minutes[start.date()] += int(
                (end - start).total_seconds() // 60
            )

        maximum_minutes = int(
            Decimal(staff.max_daily_hours)
            * Decimal("60")
        )

        for day, minutes in daily_minutes.items():
            if minutes > maximum_minutes:
                report.add(
                    "INVIGILATOR_DAILY_LIMIT_EXCEEDED",
                    (
                        f"Invigilator {staff_id} has {minutes} minutes "
                        f"on {day}; maximum is {maximum_minutes}."
                    ),
                    invigilator_id=staff_id,
                )

    # -----------------------------------------------------------------
    # INPUT ACCOUNTING
    # -----------------------------------------------------------------

    accounted = set(scheduled_ids) | set(exception_ids)

    for exam_id in sorted(
        set(exams_by_id) - accounted
    ):
        report.add(
            "EXAM_NOT_ACCOUNTED_FOR",
            (
                f"Exam {exam_id} is neither scheduled "
                "nor recorded as an exception."
            ),
            exam_id=exam_id,
        )

    report.checks["input_exams"] = len(exams)
    report.checks["scheduled_exams"] = len(scheduled)
    report.checks["exceptions"] = len(exceptions)
    report.checks["issues"] = len(report.issues)

    return report


# ---------------------------------------------------------------------
# REPORT PRINTER
# ---------------------------------------------------------------------

def print_validation_report(
    report: ValidationReport,
) -> None:
    print("\nINDEPENDENT SCHEDULE VALIDATION")
    print("=" * 48)

    print(f"Input exams examined : {report.checks['input_exams']}")
    print(f"Scheduled exams      : {report.checks['scheduled_exams']}")
    print(f"Exceptions           : {report.checks['exceptions']}")
    print(f"Issues found         : {len(report.issues)}")

    if report.passed:
        print("\nRESULT: PASS")
        print("No violations were detected by the implemented checks.")
        return

    print("\nRESULT: FAIL")

    counts = Counter(
        issue.code
        for issue in report.issues
    )

    print("\nIssue counts:")

    for code, count in sorted(counts.items()):
        print(f"  {code:<42} {count:>6}")

    print("\nIssue details (first 100):")

    for issue in report.issues[:100]:
        context = []

        if issue.exam_id is not None:
            context.append(f"exam={issue.exam_id}")

        if issue.room_id is not None:
            context.append(f"room={issue.room_id}")

        if issue.invigilator_id is not None:
            context.append(
                f"invigilator={issue.invigilator_id}"
            )

        if issue.student_id is not None:
            context.append(f"student={issue.student_id}")

        suffix = (
            f" [{', '.join(context)}]"
            if context
            else ""
        )

        print(
            f"  [{issue.code}]{suffix} {issue.message}"
        )

    if len(report.issues) > 100:
        print(
            f"  ... {len(report.issues) - 100} "
            "additional issues omitted."
        )