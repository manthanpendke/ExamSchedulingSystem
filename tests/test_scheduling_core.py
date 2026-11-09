
from datetime import date, datetime
from decimal import Decimal

from scheduling.conflict_graph import build_conflict_graph
from scheduling.constraints import (
    effective_duration_minutes,
    intervals_overlap,
    invigilator_is_available,
    invigilator_workload_allows,
    room_capacity_on,
    room_has_required_equipment,
    room_is_closed,
    room_is_eligible,
    separate_room_students,
    student_conflict_exists,
)
from scheduling.models import (
    EquipmentRequirement,
    Exam,
    Invigilator,
    InvigilatorAvailability,
    Room,
    RoomCapacityPeriod,
    RoomClosure,
    RoomEquipment,
    ScheduledInterval,
    StudentAccommodation,
    StudentParticipant,
)


def dt(hour, minute=0, day=16):
    return datetime(2026, 11, day, hour, minute)


def make_accommodation(
    accommodation_type="EXTENDED_TIME",
    percentage=Decimal("50"),
    separate=False,
    status="ACTIVE",
):
    return StudentAccommodation(
        accommodation_type=accommodation_type,
        extension_percentage=percentage,
        requires_separate_room=separate,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        status=status,
    )


def make_exam(
    participants=(),
    equipment=(),
    accessibility=False,
):
    return Exam(
        exam_id=1,
        exam_code="EXAM-2026-000001",
        course_id=1,
        window_start=dt(9),
        window_end=dt(17),
        base_duration_minutes=120,
        accessibility_required=accessibility,
        participants=tuple(participants),
        equipment_requirements=tuple(equipment),
    )


def make_room(
    capacity=100,
    equipment=(),
    closures=(),
    accessible=True,
):
    return Room(
        room_id=1,
        room_code="ROOM-000001",
        is_active=True,
        is_accessible=accessible,
        capacity_periods=(
            RoomCapacityPeriod(
                capacity=capacity,
                effective_from=date(2026, 1, 1),
                effective_to=None,
            ),
        ),
        equipment=tuple(equipment),
        closures=tuple(closures),
    )


def make_invigilator(
    invigilator_id=1,
    max_hours=Decimal("8"),
    availability=(),
):
    return Invigilator(
        invigilator_id=invigilator_id,
        invigilator_code=f"INV-{invigilator_id:06d}",
        max_daily_hours=max_hours,
        status="ACTIVE",
        availability=tuple(availability),
    )


def test_conflict_graph_connects_shared_students():
    graph = build_conflict_graph({
        1: [10, 11],
        2: [11, 12],
        3: [20],
    })

    assert graph.conflicts(1, 2)
    assert not graph.conflicts(1, 3)
    assert graph.degree(1) == 1
    assert graph.ordered_exams() == [1, 2, 3]


def test_conflict_graph_handles_empty_and_duplicate_students():
    graph = build_conflict_graph({
        1: [],
        2: [10, 10],
    })

    assert graph.neighbors(1) == frozenset()
    assert graph.neighbors(2) == frozenset()


def test_touching_intervals_do_not_overlap():
    assert not intervals_overlap(
        dt(9), dt(10),
        dt(10), dt(11),
    )


def test_overlapping_intervals_are_detected():
    assert intervals_overlap(
        dt(9), dt(11),
        dt(10), dt(12),
    )


def test_extended_duration_uses_highest_active_percentage():
    accommodations = [
        make_accommodation(percentage=Decimal("25")),
        make_accommodation(percentage=Decimal("50")),
    ]

    result = effective_duration_minutes(
        120,
        accommodations,
        date(2026, 11, 16),
    )

    assert result == 180


def test_inactive_accommodation_is_ignored():
    accommodation = make_accommodation(
        percentage=Decimal("50"),
        status="REVOKED",
    )

    assert effective_duration_minutes(
        120,
        [accommodation],
        date(2026, 11, 16),
    ) == 120


def test_invalid_extended_time_is_rejected():
    accommodation = make_accommodation(percentage=None)

    try:
        effective_duration_minutes(
            120,
            [accommodation],
            date(2026, 11, 16),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid extension should raise ValueError")


def test_room_capacity_is_resolved_by_effective_date():
    room = make_room(capacity=80)

    assert room_capacity_on(
        room,
        date(2026, 11, 16),
    ) == 80


def test_room_closure_blocks_overlapping_exam():
    room = make_room(
        closures=[
            RoomClosure(
                start=dt(10),
                end=dt(12),
                status="ACTIVE",
            )
        ]
    )

    assert room_is_closed(room, dt(11), dt(13))
    assert not room_is_closed(room, dt(12), dt(13))


def test_cancelled_closure_does_not_block_exam():
    room = make_room(
        closures=[
            RoomClosure(
                start=dt(10),
                end=dt(12),
                status="CANCELLED",
            )
        ]
    )

    assert not room_is_closed(room, dt(10), dt(11))


def test_mandatory_equipment_must_be_available():
    exam = make_exam(
        equipment=[
            EquipmentRequirement(
                equipment_id=1,
                quantity_required=2,
                mandatory=True,
            )
        ]
    )

    room = make_room(
        equipment=[
            RoomEquipment(
                equipment_id=1,
                quantity=2,
                effective_from=date(2026, 1, 1),
                effective_to=None,
            )
        ]
    )

    assert room_has_required_equipment(
        room, exam, date(2026, 11, 16)
    )


def test_insufficient_equipment_is_rejected():
    exam = make_exam(
        equipment=[
            EquipmentRequirement(
                equipment_id=1,
                quantity_required=3,
                mandatory=True,
            )
        ]
    )

    room = make_room(
        equipment=[
            RoomEquipment(
                equipment_id=1,
                quantity=2,
                effective_from=date(2026, 1, 1),
                effective_to=None,
            )
        ]
    )

    assert not room_has_required_equipment(
        room, exam, date(2026, 11, 16)
    )


def test_room_capacity_violation_is_rejected():
    exam = make_exam()
    room = make_room(capacity=20)

    eligible, reason = room_is_eligible(
        room, exam, dt(9), dt(11), 25
    )

    assert not eligible
    assert reason == "NO_ROOM_CAPACITY"


def test_separate_room_accommodation_is_detected():
    participant = StudentParticipant(
        exam_enrollment_id=1,
        student_id=101,
        student_code="STU-000101",
        seat_number="S-001",
        accommodations=(
            make_accommodation(
                accommodation_type="SEPARATE_ROOM",
                percentage=None,
                separate=True,
            ),
        ),
    )

    exam = make_exam(participants=[participant])

    assert separate_room_students(
        exam, date(2026, 11, 16)
    ) == frozenset({101})


def test_student_conflict_detected_against_existing_assignment():
    existing = ScheduledInterval(
        exam_id=2,
        start=dt(10),
        end=dt(12),
        student_ids=frozenset({101}),
        room_id=2,
    )

    assert student_conflict_exists(
        [101],
        dt(11),
        dt(13),
        [existing],
    )


def test_student_without_conflict_can_be_scheduled():
    existing = ScheduledInterval(
        exam_id=2,
        start=dt(10),
        end=dt(12),
        student_ids=frozenset({101}),
        room_id=2,
    )

    assert not student_conflict_exists(
        [102],
        dt(11),
        dt(13),
        [existing],
    )


def test_invigilator_must_be_available_for_entire_exam():
    invigilator = make_invigilator(
        availability=[
            InvigilatorAvailability(
                start=dt(9),
                end=dt(12),
                status="AVAILABLE",
            )
        ]
    )

    assert invigilator_is_available(
        invigilator, dt(10), dt(11)
    )

    assert not invigilator_is_available(
        invigilator, dt(11), dt(13)
    )


def test_invigilator_daily_workload_counts_all_assignments():
    invigilator = make_invigilator(
        max_hours=Decimal("4")
    )

    existing = [
        ScheduledInterval(
            exam_id=2,
            start=dt(9),
            end=dt(11),
            student_ids=frozenset(),
            room_id=2,
            invigilator_ids=frozenset({1}),
        ),
        ScheduledInterval(
            exam_id=3,
            start=dt(12),
            end=dt(14),
            student_ids=frozenset(),
            room_id=3,
            invigilator_ids=frozenset({1}),
        ),
    ]

    # Existing workload is already four hours.
    assert not invigilator_workload_allows(
        invigilator,
        dt(15),
        dt(16),
        existing,
    )


def test_invigilator_overlapping_assignment_is_rejected():
    invigilator = make_invigilator()

    existing = [
        ScheduledInterval(
            exam_id=2,
            start=dt(10),
            end=dt(12),
            student_ids=frozenset(),
            room_id=2,
            invigilator_ids=frozenset({1}),
        )
    ]

    assert not invigilator_workload_allows(
        invigilator,
        dt(11),
        dt(13),
        existing,
    )


def test_invigilator_within_daily_limit_is_accepted():
    invigilator = make_invigilator(
        max_hours=Decimal("8")
    )

    existing = [
        ScheduledInterval(
            exam_id=2,
            start=dt(9),
            end=dt(11),
            student_ids=frozenset(),
            room_id=2,
            invigilator_ids=frozenset({1}),
        )
    ]

    assert invigilator_workload_allows(
        invigilator,
        dt(13),
        dt(15),
        existing,
    )
