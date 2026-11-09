
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from scheduling.models_v2 import (
    RoomBooking,
    ConstraintViolation,
    ValidationResult,
)
from scheduling.room_occupancy_v2 import (
    build_occupancy_intervals,
    validate_room_capacity,
)


def overlaps(
    start_a: datetime,
    end_a: datetime,
    start_b: datetime,
    end_b: datetime,
) -> bool:
    """Half-open interval overlap test."""
    return start_a < end_b and start_b < end_a


def validate_room_closures(
    bookings: list[RoomBooking],
    closures: list[dict],
) -> list[ConstraintViolation]:

    intervals = build_occupancy_intervals(bookings)
    violations = []

    for closure in closures:
        if closure.get("ClosureStatus") != "ACTIVE":
            continue

        room_id = int(closure["RoomID"])
        closure_start = datetime.fromisoformat(closure["ClosureStart"])
        closure_end = datetime.fromisoformat(closure["ClosureEnd"])

        for interval in intervals:
            if interval.room_id != room_id:
                continue

            if overlaps(
                interval.start_time,
                interval.end_time,
                closure_start,
                closure_end,
            ):
                violations.append(
                    ConstraintViolation(
                        code="ROOM_CLOSED_DURING_EXAM",
                        severity="HARD",
                        message=(
                            f"Student {interval.student_id} has an exam "
                            f"in room {room_id} during an active closure."
                        ),
                        exam_ids=[interval.exam_id],
                        room_id=room_id,
                        details={
                            "student_id": interval.student_id,
                            "closure_start": closure_start.isoformat(),
                            "closure_end": closure_end.isoformat(),
                        },
                    )
                )

    return violations


def validate_accommodations(
    bookings: list[RoomBooking],
    rooms: dict[int, dict],
    accommodations: list[dict],
) -> list[ConstraintViolation]:

    active_accommodations = defaultdict(list)

    for accommodation in accommodations:
        if accommodation.get("AccommodationStatus") != "ACTIVE":
            continue

        active_accommodations[
            int(accommodation["StudentID"])
        ].append(accommodation)

    violations = []

    for booking in bookings:
        room = rooms.get(booking.room_id)

        if room is None:
            violations.append(
                ConstraintViolation(
                    code="ROOM_NOT_FOUND",
                    severity="HARD",
                    message=f"Room {booking.room_id} does not exist.",
                    exam_ids=[booking.exam_id],
                    room_id=booking.room_id,
                )
            )
            continue

        room_type = room.get("RoomType")

        for student_id in booking.batch.student_ids:
            student_accommodations = active_accommodations[student_id]

            requires_separate = any(
                accommodation["AccommodationType"] == "SEPARATE_ROOM"
                or accommodation.get("RequiresSeparateRoom") in (1, "1")
                for accommodation in student_accommodations
            )

            requires_accessible = any(
                accommodation["AccommodationType"] == "ACCESSIBLE_ROOM"
                for accommodation in student_accommodations
            )

            if requires_separate and len(booking.batch.student_ids) > 1:
                violations.append(
                    ConstraintViolation(
                        code="SEPARATE_ROOM_REQUIRED",
                        severity="HARD",
                        message=(
                            f"Student {student_id} requires a separate "
                            "room but is assigned to a shared batch."
                        ),
                        exam_ids=[booking.exam_id],
                        room_id=booking.room_id,
                        details={"student_id": student_id},
                    )
                )

            if requires_accessible and room_type != "ACCESSIBLE":
                violations.append(
                    ConstraintViolation(
                        code="ACCESSIBLE_ROOM_REQUIRED",
                        severity="HARD",
                        message=(
                            f"Student {student_id} requires an accessible "
                            f"room; room {booking.room_id} is {room_type}."
                        ),
                        exam_ids=[booking.exam_id],
                        room_id=booking.room_id,
                        details={"student_id": student_id},
                    )
                )

            has_extended_time = any(
                accommodation["AccommodationType"] == "EXTENDED_TIME"
                for accommodation in student_accommodations
            )

            is_extended = (
                student_id in booking.batch.extended_student_ids
            )

            if has_extended_time and not is_extended:
                violations.append(
                    ConstraintViolation(
                        code="EXTENDED_TIME_NOT_APPLIED",
                        severity="HARD",
                        message=(
                            f"Student {student_id} has an active "
                            "extended-time accommodation but is not "
                            "included in the extended-time occupancy group."
                        ),
                        exam_ids=[booking.exam_id],
                        room_id=booking.room_id,
                        details={"student_id": student_id},
                    )
                )

            if is_extended and not has_extended_time:
                violations.append(
                    ConstraintViolation(
                        code="UNSUPPORTED_EXTENDED_TIME",
                        severity="HARD",
                        message=(
                            f"Student {student_id} is marked extended-time "
                            "without an active extended-time accommodation."
                        ),
                        exam_ids=[booking.exam_id],
                        room_id=booking.room_id,
                        details={"student_id": student_id},
                    )
                )

    return violations


def validate_course_equipment_blocks(
    bookings: list[RoomBooking],
    changeover_minutes: int = 30,
) -> list[ConstraintViolation]:
    """
    Prevent different courses from sharing a room during the same
    course block.

    A course block begins at its earliest sitting and ends after
    its latest sitting finishes, including equipment changeover.

    All three sittings must finish before the room can be reconfigured
    for another course.
    """

    if changeover_minutes < 0:
        raise ValueError("Changeover minutes cannot be negative.")

    by_room_course = defaultdict(list)

    for booking in bookings:
        by_room_course[
            (booking.room_id, booking.course_id)
        ].append(booking)

    blocks = defaultdict(list)

    for (room_id, course_id), course_bookings in by_room_course.items():
        start = min(
            booking.start_time for booking in course_bookings
        )

        last_exam_end = max(
            booking.latest_end for booking in course_bookings
        )

        block_end = last_exam_end + timedelta(
            minutes=changeover_minutes
        )

        blocks[room_id].append({
            "course_id": course_id,
            "start": start,
            "end": block_end,
            "exam_ids": sorted({
                booking.exam_id for booking in course_bookings
            }),
            "sitting_count": len(course_bookings),
        })

    violations = []

    for room_id, room_blocks in blocks.items():
        room_blocks.sort(key=lambda block: block["start"])

        for index, first in enumerate(room_blocks):
            for second in room_blocks[index + 1:]:
                if second["start"] >= first["end"]:
                    break

                if overlaps(
                    first["start"],
                    first["end"],
                    second["start"],
                    second["end"],
                ):
                    violations.append(
                        ConstraintViolation(
                            code="COURSE_EQUIPMENT_CHANGEOVER_CONFLICT",
                            severity="HARD",
                            message=(
                                f"Room {room_id} has overlapping course "
                                f"blocks for courses {first['course_id']} "
                                f"and {second['course_id']}. The first "
                                "course has not completed its full block "
                                "and changeover period."
                            ),
                            exam_ids=(
                                first["exam_ids"] + second["exam_ids"]
                            ),
                            room_id=room_id,
                            details={
                                "first_course_id": first["course_id"],
                                "second_course_id": second["course_id"],
                                "first_block_end": first["end"].isoformat(),
                                "second_block_start": second["start"].isoformat(),
                                "first_sitting_count": first["sitting_count"],
                                "second_sitting_count": second["sitting_count"],
                            },
                        )
                    )

    return violations


def validate_schedule(
    bookings: list[RoomBooking],
    room_capacities: dict[int, int],
    rooms: dict[int, dict],
    closures: list[dict],
    accommodations: list[dict],
    changeover_minutes: int = 30,
) -> ValidationResult:

    violations = []

    # Room occupancy and physical capacity.
    violations.extend(
        validate_room_capacity(
            bookings,
            room_capacities,
        )
    )

    # Active room closures.
    violations.extend(
        validate_room_closures(
            bookings,
            closures,
        )
    )

    # Student accommodations.
    violations.extend(
        validate_accommodations(
            bookings,
            rooms,
            accommodations,
        )
    )

    # Course-wide equipment reservation.
    violations.extend(
        validate_course_equipment_blocks(
            bookings,
            changeover_minutes,
        )
    )

    return ValidationResult(
        passed=(len(violations) == 0),
        violations=violations,
    )
