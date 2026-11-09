
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from scheduling.models_v2 import (
    OccupancyInterval,
    RoomBooking,
    ConstraintViolation,
)


def build_occupancy_intervals(
    bookings: list[RoomBooking],
) -> list[OccupancyInterval]:
    intervals = []

    for booking in bookings:
        extended_ids = set(booking.batch.extended_student_ids)

        for student_id in booking.batch.student_ids:
            if student_id in extended_ids:
                end_time = booking.extended_end
            else:
                end_time = booking.standard_end

            intervals.append(
                OccupancyInterval(
                    room_id=booking.room_id,
                    exam_id=booking.exam_id,
                    course_id=booking.course_id,
                    student_id=student_id,
                    start_time=booking.start_time,
                    end_time=end_time,
                )
            )

    return intervals


def calculate_peak_occupancy(
    intervals: list[OccupancyInterval],
    room_id: int,
) -> tuple[int, datetime | None]:
    """
    Calculate maximum simultaneous student occupancy.

    Intervals are half-open: [start_time, end_time).
    A student finishing at 09:30 does not occupy a seat at 09:30.
    Therefore another student may begin at exactly 09:30.
    """

    events = []

    for interval in intervals:
        if interval.room_id != room_id:
            continue

        if interval.end_time <= interval.start_time:
            raise ValueError("Occupancy interval has invalid time order.")

        # End events sort before start events at equal timestamps.
        events.append((interval.start_time, 1))
        events.append((interval.end_time, -1))

    events.sort(key=lambda event: (event[0], event[1]))

    current_occupancy = 0
    peak_occupancy = 0
    peak_time = None

    for event_time, change in events:
        current_occupancy += change

        if current_occupancy < 0:
            raise ValueError("Occupancy event sequence became negative.")

        if current_occupancy > peak_occupancy:
            peak_occupancy = current_occupancy
            peak_time = event_time

    return peak_occupancy, peak_time


def validate_room_capacity(
    bookings: list[RoomBooking],
    room_capacities: dict[int, int],
) -> list[ConstraintViolation]:

    intervals = build_occupancy_intervals(bookings)

    bookings_by_room = defaultdict(list)

    for booking in bookings:
        bookings_by_room[booking.room_id].append(booking)

    violations = []

    for room_id, room_bookings in bookings_by_room.items():
        capacity = room_capacities.get(room_id)

        if capacity is None:
            violations.append(
                ConstraintViolation(
                    code="ROOM_CAPACITY_NOT_FOUND",
                    severity="HARD",
                    message=f"No capacity record found for room {room_id}.",
                    room_id=room_id,
                )
            )
            continue

        if capacity <= 0:
            violations.append(
                ConstraintViolation(
                    code="INVALID_ROOM_CAPACITY",
                    severity="HARD",
                    message=f"Room {room_id} has non-positive capacity.",
                    room_id=room_id,
                )
            )
            continue

        peak, peak_time = calculate_peak_occupancy(
            intervals,
            room_id,
        )

        if peak > capacity:
            exam_ids = sorted({
                booking.exam_id
                for booking in room_bookings
            })

            violations.append(
                ConstraintViolation(
                    code="ROOM_CAPACITY_EXCEEDED",
                    severity="HARD",
                    message=(
                        f"Room {room_id} reaches {peak} simultaneous "
                        f"students, exceeding capacity {capacity}."
                    ),
                    exam_ids=exam_ids,
                    room_id=room_id,
                    details={
                        "peak_occupancy": peak,
                        "capacity": capacity,
                        "peak_time": (
                            peak_time.isoformat()
                            if peak_time else None
                        ),
                    },
                )
            )

    return violations
