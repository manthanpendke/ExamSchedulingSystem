from datetime import date, datetime
from decimal import Decimal

from scheduling.engine import ExamScheduler
from scheduling.models import (
    Exam,
    Invigilator,
    InvigilatorAvailability,
    Room,
    RoomCapacityPeriod,
    StudentAccommodation,
    StudentParticipant,
)

EXAM_DATE = date(2026, 11, 16)


def make_exam(exam_id=1, student_ids=None, window_end_hour=17):
    student_ids = student_ids or [101]
    participants = tuple(
        StudentParticipant(
            exam_enrollment_id=index,
            student_id=student_id,
            student_code=f"STU-{student_id:06d}",
            seat_number=f"SEAT-{student_id}",
        )
        for index, student_id in enumerate(student_ids, start=1)
    )
    return Exam(
        exam_id=exam_id,
        exam_code=f"EXAM-{exam_id:06d}",
        course_id=1,
        window_start=datetime(2026, 11, 16, 9),
        window_end=datetime(2026, 11, 16, window_end_hour),
        base_duration_minutes=60,
        accessibility_required=False,
        participants=participants,
    )


def make_separate_room_exam():
    ordinary = [
        StudentParticipant(1, 101, "STU-000101", "SEAT-101"),
        StudentParticipant(2, 102, "STU-000102", "SEAT-102"),
    ]
    separate = StudentParticipant(
        exam_enrollment_id=3,
        student_id=103,
        student_code="STU-000103",
        seat_number="SEAT-103",
        accommodations=(
            StudentAccommodation(
                accommodation_type="SEPARATE_ROOM",
                extension_percentage=None,
                requires_separate_room=True,
                effective_from=date(2026, 1, 1),
                effective_to=None,
                status="ACTIVE",
            ),
        ),
    )
    exam = make_exam(student_ids=[101, 102, 103])
    return Exam(
        exam_id=exam.exam_id,
        exam_code=exam.exam_code,
        course_id=exam.course_id,
        window_start=exam.window_start,
        window_end=exam.window_end,
        base_duration_minutes=exam.base_duration_minutes,
        accessibility_required=False,
        participants=tuple(ordinary + [separate]),
    )


def make_room(room_id, capacity=100, accessible=True):
    return Room(
        room_id=room_id,
        room_code=f"ROOM-{room_id:06d}",
        is_active=True,
        is_accessible=accessible,
        capacity_periods=(
            RoomCapacityPeriod(
                capacity=capacity,
                effective_from=date(2026, 1, 1),
                effective_to=None,
            ),
        ),
        equipment=(),
        closures=(),
    )


def make_invigilators(count):
    return [
        Invigilator(
            invigilator_id=index,
            invigilator_code=f"INV-{index:06d}",
            max_daily_hours=Decimal("8"),
            status="ACTIVE",
            availability=(
                InvigilatorAvailability(
                    start=datetime(2026, 11, 16, 9),
                    end=datetime(2026, 11, 16, 17),
                    status="AVAILABLE",
                ),
            ),
        )
        for index in range(1, count + 1)
    ]


def test_one_room_requires_exactly_one_primary_invigilator():
    result = ExamScheduler().schedule(
        exams=[make_exam()],
        rooms=[make_room(1)],
        invigilators=make_invigilators(1),
    )
    assert result.scheduled_count == 1
    assignments = result.scheduled_exams[0].invigilator_assignments
    assert len(assignments) == 1
    assert assignments[0].role == "PRIMARY"
    assert assignments[0].room_id == 1


def test_separate_room_students_are_allocated_separately():
    result = ExamScheduler().schedule(
        exams=[make_separate_room_exam()],
        rooms=[make_room(1), make_room(2)],
        invigilators=make_invigilators(2),
    )
    assert result.scheduled_count == 1
    scheduled = result.scheduled_exams[0]
    assert len(scheduled.room_allocations) == 2
    main = next(a for a in scheduled.room_allocations if a.group_type == "MAIN")
    separate = next(a for a in scheduled.room_allocations if a.group_type == "SEPARATE")
    assert main.student_ids == frozenset({101, 102})
    assert separate.student_ids == frozenset({103})
    assert main.room_id != separate.room_id
    assert len(scheduled.invigilator_assignments) == 2
    assert {a.room_id for a in scheduled.invigilator_assignments} == {
        a.room_id for a in scheduled.room_allocations
    }


def test_four_rooms_require_exactly_four_invigilators():
    exam = make_exam(student_ids=[101, 102, 103, 104])
    result = ExamScheduler().schedule(
        exams=[exam],
        rooms=[make_room(i, capacity=1) for i in range(1, 5)],
        invigilators=make_invigilators(4),
    )
    assert result.scheduled_count == 1
    scheduled = result.scheduled_exams[0]
    assert len(scheduled.room_allocations) == 4
    assert len(scheduled.invigilator_assignments) == 4
    assert all(a.role == "PRIMARY" for a in scheduled.invigilator_assignments)
    assert {a.room_id for a in scheduled.invigilator_assignments} == {
        a.room_id for a in scheduled.room_allocations
    }


def test_five_rooms_require_exactly_five_invigilators():
    exam = make_exam(student_ids=[101, 102, 103, 104, 105])
    result = ExamScheduler().schedule(
        exams=[exam],
        rooms=[make_room(i, capacity=1) for i in range(1, 6)],
        invigilators=make_invigilators(5),
    )
    assert result.scheduled_count == 1
    scheduled = result.scheduled_exams[0]
    assert len(scheduled.room_allocations) == 5
    assert len(scheduled.invigilator_assignments) == 5
    assert len({a.invigilator_id for a in scheduled.invigilator_assignments}) == 5
    assert all(a.role == "PRIMARY" for a in scheduled.invigilator_assignments)


def test_insufficient_invigilators_prevents_scheduling():
    result = ExamScheduler().schedule(
        exams=[make_exam()],
        rooms=[make_room(1)],
        invigilators=[],
    )
    assert result.scheduled_count == 0
    assert result.unassigned_count == 1
    assert result.exceptions[0].reason_code == "NO_INVIGILATOR"


def test_shared_student_exams_do_not_overlap():
    exams = [
        make_exam(exam_id=1, student_ids=[101]),
        make_exam(exam_id=2, student_ids=[101]),
    ]
    result = ExamScheduler().schedule(
        exams=exams,
        rooms=[make_room(1), make_room(2)],
        invigilators=make_invigilators(2),
    )
    assert result.scheduled_count == 2
    first, second = sorted(result.scheduled_exams, key=lambda item: item.exam_id)
    assert first.end <= second.start or second.end <= first.start


def test_every_student_is_allocated_exactly_once():
    exam = make_exam(student_ids=[101, 102, 103, 104, 105])
    result = ExamScheduler().schedule(
        exams=[exam],
        rooms=[make_room(i, capacity=2) for i in range(1, 4)],
        invigilators=make_invigilators(3),
    )
    assert result.scheduled_count == 1
    scheduled = result.scheduled_exams[0]
    allocated = [
        student_id
        for allocation in scheduled.room_allocations
        for student_id in allocation.student_ids
    ]
    assert sorted(allocated) == [101, 102, 103, 104, 105]
    assert len(allocated) == len(set(allocated))
    assert len(scheduled.invigilator_assignments) == len(scheduled.room_allocations)
