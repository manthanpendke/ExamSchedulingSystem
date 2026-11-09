
"""Constraint-aware examination scheduling engine v1.2.0.

- Fixed daily start times: 08:00, 09:30, 11:00, 12:30, 14:00, 15:30.
- Operating window: 08:00–17:00.
- Course sittings are grouped on the same day where feasible.
- Extended-time duration is calculated for the students in each room.
- One primary invigilator per room.
- Separate room, student and invigilator bookings.
- In-memory only. No SQL writes or GroundTruth access.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from scheduling.conflict_graph import build_conflict_graph
from scheduling.constraints import (
    effective_duration_minutes,
    invigilator_is_available,
    invigilator_workload_allows,
    room_capacity_on,
    room_is_eligible,
    separate_room_students,
    student_conflict_exists,
)
from scheduling.models import Exam, Invigilator, Room, ScheduledInterval


DAILY_STARTS = (
    time(8, 0),
    time(9, 30),
    time(11, 0),
    time(12, 30),
    time(14, 0),
    time(15, 30),
)


@dataclass(frozen=True)
class RoomAllocation:
    exam_id: int
    exam_code: str
    room_id: int
    room_code: str
    group_type: str
    student_ids: frozenset[int]
    start: datetime
    end: datetime
    assigned_capacity: int


@dataclass(frozen=True)
class InvigilatorAssignment:
    exam_id: int
    invigilator_id: int
    invigilator_code: str
    role: str
    room_id: int | None = None
    covered_room_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ScheduledExam:
    exam_id: int
    exam_code: str
    start: datetime
    end: datetime
    room_allocations: tuple[RoomAllocation, ...]
    invigilator_assignments: tuple[InvigilatorAssignment, ...]


@dataclass(frozen=True)
class SchedulingIssue:
    exam_id: int
    exam_code: str
    reason_code: str
    severity: str
    details: str


@dataclass
class ScheduleResult:
    scheduled_exams: list[ScheduledExam] = field(default_factory=list)
    exceptions: list[SchedulingIssue] = field(default_factory=list)
    candidate_interval_minutes: int = 90
    relief_rooms_per_invigilator: int = 1

    @property
    def scheduled_count(self) -> int:
        return len(self.scheduled_exams)

    @property
    def unassigned_count(self) -> int:
        return len(self.exceptions)

    @property
    def room_allocation_count(self) -> int:
        return sum(len(x.room_allocations) for x in self.scheduled_exams)

    @property
    def invigilator_assignment_count(self) -> int:
        return sum(
            len(x.invigilator_assignments) for x in self.scheduled_exams
        )


class ExamScheduler:
    """Deterministic scheduler with hard constraints and course grouping."""

    def __init__(
        self,
        candidate_interval_minutes: int = 90,
        relief_rooms_per_invigilator: int = 1,
        operating_start: time = time(8, 0),
        operating_end: time = time(17, 0),
        room_search_limit: int = 5000,
    ):
        if candidate_interval_minutes != 90:
            raise ValueError(
                "v1.2.0 uses fixed 90-minute slots; "
                "candidate_interval_minutes must be 90."
            )
        if operating_start != time(8, 0) or operating_end != time(17, 0):
            raise ValueError(
                "v1.2.0 operating hours are fixed at 08:00–17:00."
            )
        if room_search_limit < 1:
            raise ValueError("room_search_limit must be positive.")

        self.candidate_interval_minutes = 90
        self.relief_rooms_per_invigilator = relief_rooms_per_invigilator
        self.operating_start = operating_start
        self.operating_end = operating_end
        self.room_search_limit = room_search_limit

    def schedule(
        self,
        exams: list[Exam],
        rooms: list[Room],
        invigilators: list[Invigilator],
    ) -> ScheduleResult:
        result = ScheduleResult()
        self._check_unique_ids(exams, rooms, invigilators)

        exam_by_id = {x.exam_id: x for x in exams}
        students_by_exam = {
            x.exam_id: {p.student_id for p in x.participants}
            for x in exams
        }
        graph = build_conflict_graph(students_by_exam)

        pending = set(exam_by_id)
        intervals: list[ScheduledInterval] = []
        room_bookings = defaultdict(list)
        course_history = defaultdict(list)

        while pending:
            def priority(exam_id):
                exam = exam_by_id[exam_id]
                neighbors = graph.neighbors(exam_id)
                saturation = len({
                    (x.start, x.end)
                    for x in intervals
                    if any(
                        n == x.exam_id for n in neighbors
                    )
                })
                already_scheduled = len(course_history[exam.course_id])
                return (
                    already_scheduled > 0,
                    saturation,
                    graph.degree(exam_id),
                    exam.participant_count,
                    exam.base_duration_minutes,
                    -exam_id,
                )

            exam_id = max(pending, key=priority)
            pending.remove(exam_id)
            exam = exam_by_id[exam_id]

            issue = self._validate_exam_input(exam)
            if issue:
                result.exceptions.append(issue)
                continue

            scheduled, reasons, new_intervals = self._schedule_one_exam(
                exam=exam,
                rooms=rooms,
                invigilators=invigilators,
                existing_intervals=intervals,
                room_bookings=room_bookings,
                previous_course_sittings=course_history[exam.course_id],
            )

            if scheduled is None:
                result.exceptions.append(self._make_issue(exam, reasons))
                continue

            result.scheduled_exams.append(scheduled)
            intervals.extend(new_intervals)
            course_history[exam.course_id].append(
                (scheduled.start, scheduled.end)
            )

            for allocation in scheduled.room_allocations:
                room_bookings[allocation.room_id].append(
                    (allocation.start, allocation.end, exam.exam_id)
                )

        return result

    @staticmethod
    def _check_unique_ids(exams, rooms, invigilators):
        for label, records, getter in (
            ("exam", exams, lambda x: x.exam_id),
            ("room", rooms, lambda x: x.room_id),
            ("invigilator", invigilators, lambda x: x.invigilator_id),
        ):
            values = [getter(x) for x in records]
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {label} IDs supplied.")

    @staticmethod
    def _validate_exam_input(exam):
        if exam.window_end <= exam.window_start:
            reason = "NO_VALID_TIMESLOT"
            details = "Exam window is invalid."
        elif exam.base_duration_minutes <= 0:
            reason = "INVALID_REQUIREMENT"
            details = "Exam duration must be positive."
        elif not exam.participants:
            reason = "NO_ELIGIBLE_STUDENTS"
            details = "No registered participants were loaded."
        else:
            ids = [p.student_id for p in exam.participants]
            if len(ids) != len(set(ids)):
                reason = "INVALID_REQUIREMENT"
                details = "Duplicate participants exist."
            else:
                return None

        return SchedulingIssue(
            exam.exam_id, exam.exam_code, reason, "HIGH", details
        )

    @staticmethod
    def _duration_for_students(exam, student_ids, exam_date):
        participants = [
            p for p in exam.participants_on(exam_date)
            if p.student_id in student_ids
        ]
        accommodations = (
            a
            for p in participants
            for a in p.active_accommodations_on(exam_date)
        )
        return effective_duration_minutes(
            exam.base_duration_minutes, accommodations, exam_date
        )

    def _candidate_starts(self, exam, duration, preferred_dates=()):
        dates = []
        current = exam.window_start.date()
        while current <= exam.window_end.date():
            dates.append(current)
            current += timedelta(days=1)

        preferred = set(preferred_dates)
        starts = []

        for day in dates:
            for clock in DAILY_STARTS:
                start = datetime.combine(day, clock)
                end = start + timedelta(minutes=duration)

                if start < exam.window_start:
                    continue
                if end > exam.window_end:
                    continue
                if start.time() < self.operating_start:
                    continue
                if end.time() > self.operating_end:
                    continue

                starts.append(start)

        def date_distance(day):
            if not preferred:
                return 0
            return min(abs((day - x).days) for x in preferred)

        starts.sort(
            key=lambda x: (
                date_distance(x.date()),
                x.date(),
                x.time(),
            )
        )
        return starts

    def _schedule_one_exam(
        self,
        exam,
        rooms,
        invigilators,
        existing_intervals,
        room_bookings,
        previous_course_sittings,
    ):
        reasons = Counter()
        dates = sorted({x[0].date() for x in previous_course_sittings})

        all_participants = list(exam.participants)
        if not all_participants:
            return None, Counter({"NO_ELIGIBLE_STUDENTS": 1}), []

        # The longest duration determines which start times are possible.
        maximum_duration = max(
            self._duration_for_students(
                exam,
                {p.student_id for p in all_participants},
                exam.window_start.date(),
            ),
            exam.base_duration_minutes,
        )

        starts = self._candidate_starts(
            exam, maximum_duration, dates
        )
        if not starts:
            return None, Counter({"NO_VALID_TIMESLOT": 1}), []

        for start in starts:
            exam_date = start.date()
            participants = list(exam.participants_on(exam_date))
            student_ids = {p.student_id for p in participants}

            if not student_ids:
                reasons["NO_ELIGIBLE_STUDENTS"] += 1
                continue

            separate_ids = set(separate_room_students(exam, exam_date))
            if not separate_ids.issubset(student_ids):
                reasons["ACCOMMODATION_CONFLICT"] += 1
                continue

            # Partition by both duration and mandatory separate-room status.
            groups = defaultdict(set)
            for participant in participants:
                sid = participant.student_id
                accommodations = participant.active_accommodations_on(
                    exam_date
                )
                duration = self._duration_for_students(
                    exam, {sid}, exam_date
                )
                group_type = (
                    "SEPARATE" if sid in separate_ids else "MAIN"
                )
                groups[(group_type, duration)].add(sid)

            # Enforce student non-overlap using each group's actual duration.
            student_conflict = False
            for (_, duration), group_student_ids in groups.items():
                group_end = start + timedelta(minutes=duration)
                if student_conflict_exists(
                    group_student_ids,
                    start,
                    group_end,
                    existing_intervals,
                ):
                    reasons["STUDENT_CONFLICT"] += 1
                    student_conflict = True
                    break

            if student_conflict:
                continue

            allocations = []
            used_rooms = set()
            local_room_bookings = []
            room_search_nodes = [0]

            ordered_groups = sorted(
                groups.items(),
                key=lambda item: (
                    0 if item[0][0] == "SEPARATE" else 1,
                    -item[0][1],
                    len(item[1]),
                ),
            )

            def allocate_group(index):
                if index == len(ordered_groups):
                    return True
                if room_search_nodes[0] >= self.room_search_limit:
                    return False

                (group_type, duration), remaining_set = ordered_groups[index]
                remaining = set(remaining_set)
                end = start + timedelta(minutes=duration)

                def recurse():
                    if not remaining:
                        return allocate_group(index + 1)

                    room_search_nodes[0] += 1
                    if room_search_nodes[0] > self.room_search_limit:
                        return False

                    candidates = []
                    for room in rooms:
                        if room.room_id in used_rooms or not room.is_active:
                            continue

                        if any(
                            start < booked_end and booked_start < end
                            for booked_start, booked_end, _ in
                            room_bookings.get(room.room_id, ())
                        ):
                            continue

                        try:
                            capacity = room_capacity_on(room, exam_date)
                        except ValueError:
                            reasons["NO_ROOM_CAPACITY"] += 1
                            continue

                        if not capacity or capacity <= 0:
                            reasons["NO_ROOM_CAPACITY"] += 1
                            continue

                        chunk = set(sorted(remaining)[:capacity])
                        eligible, reason = room_is_eligible(
                            room=room,
                            exam=exam,
                            start=start,
                            end=end,
                            allocated_student_count=len(chunk),
                            allocated_student_ids=chunk,
                        )
                        if not eligible:
                            reasons[reason or "NO_ROOM_CAPACITY"] += 1
                            continue

                        candidates.append(
                            (capacity - len(chunk), room.room_code, room, chunk, capacity)
                        )

                    candidates.sort(key=lambda x: (x[0], x[1]))

                    for _, _, room, chunk, capacity in candidates:
                        allocation = RoomAllocation(
                            exam_id=exam.exam_id,
                            exam_code=exam.exam_code,
                            room_id=room.room_id,
                            room_code=room.room_code,
                            group_type=group_type,
                            student_ids=frozenset(chunk),
                            start=start,
                            end=end,
                            assigned_capacity=capacity,
                        )
                        used_rooms.add(room.room_id)
                        allocations.append(allocation)
                        remaining.difference_update(chunk)

                        if recurse():
                            return True

                        remaining.update(chunk)
                        allocations.pop()
                        used_rooms.remove(room.room_id)

                    return False

                return recurse()

            if not allocate_group(0):
                if not reasons:
                    reasons["NO_ROOM_CAPACITY"] += 1
                continue

            # One distinct primary invigilator for each room, for that room's
            # own actual duration.
            selected_staff = set()
            assignments = []
            new_intervals = []
            staff_failed = False

            for allocation in allocations:
                staff_candidates = []
                for staff in invigilators:
                    if staff.invigilator_id in selected_staff:
                        continue
                    if not invigilator_is_available(
                        staff, allocation.start, allocation.end
                    ):
                        continue

                    if not invigilator_workload_allows(
                        staff,
                        allocation.start,
                        allocation.end,
                        existing_intervals + new_intervals,
                    ):
                        continue

                    staff_candidates.append(staff)

                staff_candidates.sort(
                    key=lambda x: (
                        x.max_daily_hours,
                        x.invigilator_code,
                        x.invigilator_id,
                    )
                )

                if not staff_candidates:
                    reasons["NO_INVIGILATOR"] += 1
                    staff_failed = True
                    break

                staff = staff_candidates[0]
                selected_staff.add(staff.invigilator_id)

                assignments.append(
                    InvigilatorAssignment(
                        exam_id=exam.exam_id,
                        invigilator_id=staff.invigilator_id,
                        invigilator_code=staff.invigilator_code,
                        role="PRIMARY",
                        room_id=allocation.room_id,
                    )
                )

                new_intervals.append(
                    ScheduledInterval(
                        exam_id=exam.exam_id,
                        start=allocation.start,
                        end=allocation.end,
                        student_ids=allocation.student_ids,
                        room_id=allocation.room_id,
                        invigilator_ids=frozenset({staff.invigilator_id}),
                    )
                )

            if staff_failed:
                continue

            allocated = set().union(
                *(set(x.student_ids) for x in allocations)
            )
            if allocated != student_ids:
                reasons["NO_ELIGIBLE_STUDENTS"] += 1
                continue

            max_end = max(x.end for x in allocations)
            scheduled = ScheduledExam(
                exam_id=exam.exam_id,
                exam_code=exam.exam_code,
                start=start,
                end=max_end,
                room_allocations=tuple(allocations),
                invigilator_assignments=tuple(assignments),
            )
            return scheduled, reasons, new_intervals

        return None, reasons, []

    @staticmethod
    def _make_issue(exam, reasons):
        if reasons:
            reason = sorted(
                reasons.items(), key=lambda x: (-x[1], x[0])
            )[0][0]
            details = "; ".join(
                f"{k}={v}" for k, v in sorted(reasons.items())
            )
        else:
            reason = "NO_VALID_TIMESLOT"
            details = "No valid candidate time was found."

        severity = (
            "CRITICAL"
            if reason in {
                "NO_ROOM_CAPACITY",
                "ROOM_CLOSED",
                "ACCOMMODATION_CONFLICT",
            }
            else "HIGH"
        )
        return SchedulingIssue(
            exam_id=exam.exam_id,
            exam_code=exam.exam_code,
            reason_code=reason,
            severity=severity,
            details=(
                "No candidate time satisfied all hard constraints. "
                f"Blocker counts: {details}."
            ),
        )
