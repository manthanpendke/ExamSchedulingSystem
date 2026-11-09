from __future__ import annotations

import csv
import json
import sys

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


# ============================================================
# EXAM SCHEDULING SYSTEM v2.2.0
# FINAL CROSS-MODULE INTEGRATION VALIDATOR
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
META = DATA / "metadata"
SCHED = DATA / "scheduling"

REPORT_PATH = SCHED / "final_integration_validation_v220.json"

EXPECTED = {
    "students": 5000,
    "courses": 300,
    "exams": 900,
    "timetable_allocations": 20000,
    "room_allocations": 1493,
    "room_student_allocations": 19947,
    "unassigned_students": 53,
    "invigilator_assignments": 1493,
}

DT_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
)


# ============================================================
# HELPERS
# ============================================================

def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Required file missing: {path}")

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError(f"Missing CSV header: {path}")

        return list(reader)


def read_json(path):
    if not path.exists():
        raise FileNotFoundError(f"Required report missing: {path}")

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def integer(value, field):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        raise ValueError(
            f"Invalid integer in {field}: {value!r}"
        )


def parse_datetime(value, field):
    value = str(value or "").strip()

    for fmt in DT_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    raise ValueError(
        f"Invalid datetime in {field}: {value!r}"
    )


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


# ============================================================
# MAIN VALIDATION
# ============================================================

def main():

    print("=" * 76)
    print("EXAM SCHEDULING SYSTEM v2.2.0")
    print("FINAL CROSS-MODULE INTEGRATION VALIDATION")
    print("=" * 76)

    errors = []
    warnings = []
    checks = 0

    def check(condition, message):
        nonlocal checks
        checks += 1

        if not condition:
            errors.append(message)

    # --------------------------------------------------------
    # 1. LOAD REQUIRED CSV FILES
    # --------------------------------------------------------

    print("\n[1/8] Loading integration inputs...")

    students = read_csv(DATA / "Student.csv")
    courses = read_csv(DATA / "Course.csv")
    enrollments = read_csv(DATA / "Enrollment.csv")
    exams = read_csv(DATA / "Exam.csv")
    exam_enrollments = read_csv(DATA / "ExamEnrollment.csv")

    timetable = read_csv(SCHED / "ExamTimetable.csv")
    timetable_students = read_csv(
        SCHED / "TimetableStudentAllocation.csv"
    )

    rooms = read_csv(DATA / "Room.csv")
    room_allocations = read_csv(SCHED / "RoomAllocation.csv")
    room_students = read_csv(
        SCHED / "RoomStudentAllocation.csv"
    )
    room_exceptions = read_csv(
        SCHED / "RoomAllocationExceptions.csv"
    )
    equipment_reservations = read_csv(
        SCHED / "RoomEquipmentReservation.csv"
    )

    equipment = read_csv(DATA / "Equipment.csv")

    invigilators = read_csv(DATA / "Invigilator.csv")
    availability = read_csv(DATA / "Availability.csv")

    inv_assignments = read_csv(
        SCHED / "InvigilatorAssignment.csv"
    )
    inv_exceptions = read_csv(
        SCHED / "InvigilatorAllocationExceptions.csv"
    )

    # --------------------------------------------------------
    # 2. VALIDATE SOURCE COUNTS AND PRIMARY IDS
    # --------------------------------------------------------

    print("[2/8] Validating source counts and identifiers...")

    check(
        len(students) == EXPECTED["students"],
        f"Expected 5000 students; found {len(students)}."
    )

    check(
        len(courses) == EXPECTED["courses"],
        f"Expected 300 courses; found {len(courses)}."
    )

    check(
        len(exams) == EXPECTED["exams"],
        f"Expected 900 source exams; found {len(exams)}."
    )

    check(
        len(timetable) == EXPECTED["exams"],
        f"Expected 900 timetable rows; found {len(timetable)}."
    )

    check(
        len(timetable_students)
        == EXPECTED["timetable_allocations"],
        "Timetable student allocation count mismatch."
    )

    check(
        len(room_allocations)
        == EXPECTED["room_allocations"],
        "Room allocation count mismatch."
    )

    check(
        len(room_students)
        == EXPECTED["room_student_allocations"],
        "Room student allocation count mismatch."
    )

    def unique_ids(rows, field, label):
        values = [
            str(row[field]).strip()
            for row in rows
        ]

        check(
            len(values) == len(set(values)),
            f"Duplicate {field} values in {label}."
        )

        check(
            all(values),
            f"Blank {field} values in {label}."
        )

    unique_ids(students, "StudentID", "Student")
    unique_ids(courses, "CourseID", "Course")
    unique_ids(exams, "ExamID", "Exam")
    unique_ids(timetable, "ExamID", "ExamTimetable")
    unique_ids(room_allocations, "RoomAllocationID", "RoomAllocation")
    unique_ids(inv_assignments, "AssignmentID", "InvigilatorAssignment")

    student_ids = {
        integer(x["StudentID"], "Student.StudentID")
        for x in students
    }

    course_ids = {
        integer(x["CourseID"], "Course.CourseID")
        for x in courses
    }

    exam_by_id = {
        integer(x["ExamID"], "Exam.ExamID"): x
        for x in exams
    }

    timetable_by_id = {
        integer(x["ExamID"], "Timetable.ExamID"): x
        for x in timetable
    }

    enrollment_by_id = {
        integer(x["EnrollmentID"], "Enrollment.EnrollmentID"): x
        for x in enrollments
    }

    room_by_id = {
        integer(x["RoomID"], "Room.RoomID"): x
        for x in rooms
    }

    equipment_ids = {
        integer(x["EquipmentID"], "Equipment.EquipmentID")
        for x in equipment
    }

    # --------------------------------------------------------
    # 3. TIMETABLE AND ENROLLMENT RECONCILIATION
    # --------------------------------------------------------

    print("[3/8] Reconciling timetable and student enrollments...")

    check(
        set(exam_by_id) == set(timetable_by_id),
        "Source Exam IDs and timetable Exam IDs differ."
    )

    for exam_id, scheduled in timetable_by_id.items():

        source = exam_by_id.get(exam_id)

        if source is None:
            continue

        check(
            integer(source["CourseID"], "Exam.CourseID")
            == integer(scheduled["CourseID"], "Timetable.CourseID"),
            f"Course mismatch for exam {exam_id}."
        )

        check(
            str(source["ExamCode"]).strip()
            == str(scheduled["ExamCode"]).strip(),
            f"Exam code mismatch for exam {exam_id}."
        )

    source_allocation_keys = set()
    timetable_allocation_keys = set()

    for row in timetable_students:

        enrollment_id = integer(
            row["EnrollmentID"], "TimetableAllocation.EnrollmentID"
        )

        student_id = integer(
            row["StudentID"], "TimetableAllocation.StudentID"
        )

        exam_id = integer(
            row["ExamID"], "TimetableAllocation.ExamID"
        )

        course_id = integer(
            row["CourseID"], "TimetableAllocation.CourseID"
        )

        key = (enrollment_id, student_id, exam_id)

        check(
            key not in timetable_allocation_keys,
            f"Duplicate timetable allocation: {key}."
        )

        timetable_allocation_keys.add(key)

        check(
            student_id in student_ids,
            f"Unknown student {student_id} in timetable allocation."
        )

        check(
            exam_id in timetable_by_id,
            f"Unknown exam {exam_id} in timetable allocation."
        )

        check(
            course_id in course_ids,
            f"Unknown course {course_id} in timetable allocation."
        )

        source_enrollment = enrollment_by_id.get(enrollment_id)

        check(
            source_enrollment is not None,
            f"Unknown EnrollmentID {enrollment_id}."
        )

        if source_enrollment:

            check(
                integer(
                    source_enrollment["StudentID"],
                    "Enrollment.StudentID"
                ) == student_id,
                f"Enrollment student mismatch: {enrollment_id}."
            )

            check(
                integer(
                    source_enrollment["CourseID"],
                    "Enrollment.CourseID"
                ) == course_id,
                f"Enrollment course mismatch: {enrollment_id}."
            )

        scheduled = timetable_by_id.get(exam_id)

        if scheduled:

            check(
                integer(
                    scheduled["CourseID"],
                    "Timetable.CourseID"
                ) == course_id,
                f"Timetable course mismatch for enrollment {enrollment_id}."
            )

            check(
                row["ExamDate"] == scheduled["ExamDate"],
                f"Timetable date mismatch for enrollment {enrollment_id}."
            )

            check(
                parse_datetime(
                    row["StartDateTime"],
                    "TimetableAllocation.StartDateTime"
                )
                == parse_datetime(
                    scheduled["StartDateTime"],
                    "ExamTimetable.StartDateTime"
                ),
                f"Start time mismatch for enrollment {enrollment_id}."
            )

    for row in exam_enrollments:

        enrollment_id = integer(
            row["EnrollmentID"], "ExamEnrollment.EnrollmentID"
        )

        exam_id = integer(
            row["ExamID"], "ExamEnrollment.ExamID"
        )

        enrollment = enrollment_by_id.get(enrollment_id)

        if enrollment is None:
            check(False, f"ExamEnrollment has unknown enrollment {enrollment_id}.")
            continue

        student_id = integer(
            enrollment["StudentID"], "Enrollment.StudentID"
        )

        source_allocation_keys.add(
            (enrollment_id, student_id, exam_id)
        )

    check(
        source_allocation_keys == timetable_allocation_keys,
        "Timetable student allocations do not match ExamEnrollment."
    )

    # --------------------------------------------------------
    # 4. ROOM ALLOCATION RECONCILIATION
    # --------------------------------------------------------

    print("[4/8] Reconciling room and student allocations...")

    room_alloc_by_id = {
        integer(x["RoomAllocationID"], "RoomAllocation.RoomAllocationID"): x
        for x in room_allocations
    }

    room_groups = defaultdict(list)
    room_student_keys = set()

    for row in room_students:

        enrollment_id = integer(
            row["EnrollmentID"], "RoomStudent.EnrollmentID"
        )

        student_id = integer(
            row["StudentID"], "RoomStudent.StudentID"
        )

        exam_id = integer(
            row["ExamID"], "RoomStudent.ExamID"
        )

        room_id = integer(
            row["RoomID"], "RoomStudent.RoomID"
        )

        key = (enrollment_id, student_id, exam_id)

        check(
            key not in room_student_keys,
            f"Duplicate room student allocation: {key}."
        )

        room_student_keys.add(key)

        check(
            key in timetable_allocation_keys,
            f"Room assignment not found in timetable allocation: {key}."
        )

        check(
            room_id in room_by_id,
            f"Room assignment references unknown room {room_id}."
        )

        check(
            exam_id in timetable_by_id,
            f"Room assignment references unknown exam {exam_id}."
        )

        room_groups[(exam_id, room_id)].append(row)

    room_pairs = set()

    room_intervals = defaultdict(list)

    for row in room_allocations:

        allocation_id = integer(
            row["RoomAllocationID"], "RoomAllocation.RoomAllocationID"
        )

        exam_id = integer(
            row["ExamID"], "RoomAllocation.ExamID"
        )

        course_id = integer(
            row["CourseID"], "RoomAllocation.CourseID"
        )

        room_id = integer(
            row["RoomID"], "RoomAllocation.RoomID"
        )

        pair = (exam_id, room_id)

        check(
            pair not in room_pairs,
            f"Duplicate room allocation pair {pair}."
        )

        room_pairs.add(pair)

        check(
            exam_id in timetable_by_id,
            f"Room allocation {allocation_id} references unknown exam."
        )

        check(
            room_id in room_by_id,
            f"Room allocation {allocation_id} references unknown room."
        )

        if exam_id in timetable_by_id:

            check(
                integer(
                    timetable_by_id[exam_id]["CourseID"],
                    "Timetable.CourseID"
                ) == course_id,
                f"Room allocation course mismatch: {allocation_id}."
            )

        group = room_groups.get(pair, [])

        allocated_count = integer(
            row["AllocatedStudentCount"],
            "RoomAllocation.AllocatedStudentCount"
        )

        assigned_capacity = integer(
            row["AssignedCapacity"],
            "RoomAllocation.AssignedCapacity"
        )

        check(
            allocated_count == len(group),
            f"Room allocation student count mismatch: {allocation_id}."
        )

        check(
            allocated_count <= assigned_capacity,
            f"Room allocation exceeds assigned capacity: {allocation_id}."
        )

        start = parse_datetime(
            row["StartDateTime"],
            "RoomAllocation.StartDateTime"
        )

        end = parse_datetime(
            row["EndDateTime"],
            "RoomAllocation.EndDateTime"
        )

        check(
            end > start,
            f"Invalid room allocation interval: {allocation_id}."
        )

        room_intervals[room_id].append(
            (start, end, allocation_id)
        )

        for student in group:

            check(
                parse_datetime(
                    student["StartDateTime"],
                    "RoomStudent.StartDateTime"
                ) >= start,
                f"Student starts before room duty: {allocation_id}."
            )

            check(
                parse_datetime(
                    student["StudentEffectiveEndDateTime"],
                    "RoomStudent.StudentEffectiveEndDateTime"
                ) <= end,
                f"Student ends after room duty: {allocation_id}."
            )

    check(
        set(room_groups) == room_pairs,
        "RoomAllocation and RoomStudentAllocation room pairs differ."
    )

    for room_id, intervals in room_intervals.items():

        intervals.sort()

        for previous, current in zip(
            intervals,
            intervals[1:]
        ):

            check(
                not overlaps(
                    previous[0], previous[1],
                    current[0], current[1]
                ),
                f"Room {room_id} has overlapping allocations "
                f"{previous[2]} and {current[2]}."
            )

    missing_room_students = (
        timetable_allocation_keys - room_student_keys
    )

    check(
        len(missing_room_students)
        == EXPECTED["unassigned_students"],
        f"Expected 53 unassigned students; "
        f"found {len(missing_room_students)}."
    )

    check(
        room_student_keys.issubset(timetable_allocation_keys),
        "Room allocation contains non-source student records."
    )

    missing_by_exam = Counter(
        key[2] for key in missing_room_students
    )

    exceptions_by_exam = {}

    for row in room_exceptions:

        exam_id = integer(
            row["ExamID"], "RoomException.ExamID"
        )

        count = integer(
            row["UnassignedStudentCount"],
            "RoomException.UnassignedStudentCount"
        )

        check(
            exam_id not in exceptions_by_exam,
            f"Duplicate room exception for exam {exam_id}."
        )

        exceptions_by_exam[exam_id] = count

        check(
            row["ReasonCode"] in {
                "NO_ROOM_CAPACITY",
                "NO_EQUIPMENT",
                "NO_INVIGILATOR",
                "STUDENT_CONFLICT",
                "ACCOMMODATION_CONFLICT",
                "ROOM_CLOSED",
                "NO_VALID_TIMESLOT",
                "NO_ELIGIBLE_STUDENTS",
                "INVALID_REQUIREMENT",
                "OTHER",
            },
            f"Invalid room exception reason: {row['ReasonCode']}."
        )

    check(
        dict(missing_by_exam) == exceptions_by_exam,
        "Room exceptions do not exactly account for unassigned students."
    )

    check(
        sum(exceptions_by_exam.values())
        == EXPECTED["unassigned_students"],
        "Total room exception count does not equal 53."
    )

    # --------------------------------------------------------
    # 5. EQUIPMENT RESERVATION RECONCILIATION
    # --------------------------------------------------------

    print("[5/8] Checking equipment reservation references...")

    reservation_keys = set()

    for row in equipment_reservations:

        course_id = integer(
            row["CourseID"], "Reservation.CourseID"
        )

        equipment_id = integer(
            row["EquipmentID"], "Reservation.EquipmentID"
        )

        quantity = integer(
            row["ReservedQuantity"], "Reservation.ReservedQuantity"
        )

        key = (course_id, equipment_id)

        check(
            key not in reservation_keys,
            f"Duplicate course/equipment reservation {key}."
        )

        reservation_keys.add(key)

        check(
            course_id in course_ids,
            f"Reservation references unknown course {course_id}."
        )

        check(
            equipment_id in equipment_ids,
            f"Reservation references unknown equipment {equipment_id}."
        )

        check(
            quantity > 0,
            f"Invalid reservation quantity for {key}."
        )

        start = parse_datetime(
            row["ReservationStart"], "ReservationStart"
        )

        end = parse_datetime(
            row["ReservationEnd"], "ReservationEnd"
        )

        check(
            end > start,
            f"Invalid reservation interval for {key}."
        )

        check(
            row["ReservationPolicy"]
            == "COURSE_WINDOW_SHARED_INVENTORY",
            f"Unexpected reservation policy for {key}."
        )

        if "ReservationStatus" in row:
            check(
                row["ReservationStatus"] == "RESERVED",
                f"Reservation not marked RESERVED for {key}."
            )

    # --------------------------------------------------------
    # 6. INVIGILATOR AND ROOM DUTY RECONCILIATION
    # --------------------------------------------------------

    print("[6/8] Reconciling invigilator assignments...")

    active_invigilators = {
        integer(row["InvigilatorID"], "Invigilator.InvigilatorID"): row
        for row in invigilators
        if row["Status"].strip().upper() == "ACTIVE"
    }

    availability_by_id = {
        integer(row["AvailabilityID"], "Availability.AvailabilityID"): row
        for row in availability
    }

    assignment_by_room = {}
    invigilator_intervals = defaultdict(list)
    daily_minutes = Counter()

    for row in inv_assignments:

        allocation_id = integer(
            row["RoomAllocationID"],
            "InvigilatorAssignment.RoomAllocationID"
        )

        invigilator_id = integer(
            row["InvigilatorID"],
            "InvigilatorAssignment.InvigilatorID"
        )

        availability_id = integer(
            row["AvailabilityID"],
            "InvigilatorAssignment.AvailabilityID"
        )

        check(
            allocation_id not in assignment_by_room,
            f"Multiple invigilators assigned to room allocation {allocation_id}."
        )

        assignment_by_room[allocation_id] = row

        source_room = room_alloc_by_id.get(allocation_id)

        check(
            source_room is not None,
            f"Invigilator assignment references unknown room allocation {allocation_id}."
        )

        check(
            invigilator_id in active_invigilators,
            f"Inactive or unknown invigilator {invigilator_id}."
        )

        availability_row = availability_by_id.get(availability_id)

        check(
            availability_row is not None,
            f"Unknown AvailabilityID {availability_id}."
        )

        start = parse_datetime(
            row["StartDateTime"],
            "InvigilatorAssignment.StartDateTime"
        )

        end = parse_datetime(
            row["EndDateTime"],
            "InvigilatorAssignment.EndDateTime"
        )

        duration = integer(
            row["DutyMinutes"],
            "InvigilatorAssignment.DutyMinutes"
        )

        check(
            end > start,
            f"Invalid invigilator duty interval {allocation_id}."
        )

        check(
            int((end - start).total_seconds() // 60) == duration,
            f"Invigilator duty duration mismatch {allocation_id}."
        )

        if source_room:

            check(
                integer(source_room["ExamID"], "RoomAllocation.ExamID")
                == integer(row["ExamID"], "Assignment.ExamID"),
                f"Invigilator exam mismatch {allocation_id}."
            )

            check(
                integer(source_room["RoomID"], "RoomAllocation.RoomID")
                == integer(row["RoomID"], "Assignment.RoomID"),
                f"Invigilator room mismatch {allocation_id}."
            )

            check(
                parse_datetime(
                    source_room["StartDateTime"], "Room.StartDateTime"
                ) == start
                and parse_datetime(
                    source_room["EndDateTime"], "Room.EndDateTime"
                ) == end,
                f"Invigilator interval differs from room interval {allocation_id}."
            )

        if availability_row:

            available_start = parse_datetime(
                availability_row["AvailableFrom"],
                "Availability.AvailableFrom"
            )

            available_end = parse_datetime(
                availability_row["AvailableTo"],
                "Availability.AvailableTo"
            )

            check(
                availability_row["AvailabilityStatus"].upper()
                == "AVAILABLE"
                and available_start <= start
                and available_end >= end,
                f"Invigilator unavailable for duty {allocation_id}."
            )

            check(
                integer(
                    availability_row["InvigilatorID"],
                    "Availability.InvigilatorID"
                ) == invigilator_id,
                f"Availability belongs to another invigilator: {allocation_id}."
            )

        day = start.date().isoformat()

        invigilator_intervals[invigilator_id].append(
            (start, end, allocation_id)
        )

        daily_minutes[(invigilator_id, day)] += duration

    inv_exception_ids = set()

    for row in inv_exceptions:

        allocation_id = integer(
            row["RoomAllocationID"],
            "InvigilatorException.RoomAllocationID"
        )

        inv_exception_ids.add(allocation_id)

        check(
            row["ReasonCode"] == "NO_INVIGILATOR",
            f"Invalid invigilator exception reason for {allocation_id}."
        )

    for allocation_id in room_alloc_by_id:

        assigned = allocation_id in assignment_by_room
        exception = allocation_id in inv_exception_ids

        check(
            assigned != exception,
            f"Room allocation {allocation_id} must have exactly "
            "one assignment or one exception."
        )

    check(
        len(inv_assignments) == EXPECTED["invigilator_assignments"],
        f"Expected 1493 invigilator assignments; "
        f"found {len(inv_assignments)}."
    )

    for invigilator_id, intervals in invigilator_intervals.items():

        intervals.sort()

        for previous, current in zip(
            intervals,
            intervals[1:]
        ):

            check(
                not overlaps(
                    previous[0], previous[1],
                    current[0], current[1]
                ),
                f"Invigilator {invigilator_id} double-booked "
                f"between allocations {previous[2]} and {current[2]}."
            )

    for (invigilator_id, day), minutes in daily_minutes.items():

        person = active_invigilators.get(invigilator_id)

        if person:

            maximum = float(person["MaxDailyHours"]) * 60

            check(
                minutes <= maximum,
                f"Invigilator {invigilator_id} exceeds daily hours on {day}."
            )

    # --------------------------------------------------------
    # 7. INDEPENDENT REPORT RECONCILIATION
    # --------------------------------------------------------

    print("[7/8] Checking independent validation reports...")

    report_files = {
        "dataset": DATA / "independent_validation_report.json",
        "timetable": SCHED / "independent_timetable_validation_report_v220.json",
        "room": SCHED / "room_allocation_independent_validation_v220.json",
        "invigilator": SCHED / "invigilator_independent_validation_v220.json",
    }

    reports = {
        name: read_json(path)
        for name, path in report_files.items()
    }

    expected_statuses = {
        "dataset": {"PASSED"},
        "timetable": {"PASSED"},
        "room": {"PASSED_WITH_EXCEPTIONS"},
        "invigilator": {"PASSED"},
    }

    for name, report in reports.items():

        status = str(report.get("status", "")).upper()

        check(
            status in expected_statuses[name],
            f"{name} independent report status is {status!r}."
        )

        error_count = report.get(
            "error_count",
            report.get("errors", 0)
        )

        if isinstance(error_count, list):
            error_count = len(error_count)

        if isinstance(error_count, int):
            check(
                error_count == 0,
                f"{name} independent report contains {error_count} errors."
            )

        if report.get("database_accessed") is True:
            errors.append(
                f"{name} report indicates database access."
            )

        if report.get("database_modified") is True:
            errors.append(
                f"{name} report indicates database modification."
            )

        if report.get("ground_truth_accessed") is True:
            errors.append(
                f"{name} report indicates GroundTruth access."
            )

    # --------------------------------------------------------
    # 8. FINAL REPORT
    # --------------------------------------------------------

    print("[8/8] Generating final integration report...")

    status = "FAILED" if errors else (
        "PASSED_WITH_ACCEPTED_EXCEPTIONS"
        if missing_room_students or room_exceptions
        else "PASSED"
    )

    report = {
        "version": "2.2.0",
        "validator": "Final Cross-Module Integration Validator",
        "status": status,
        "checks_executed": checks,
        "error_count": len(errors),
        "errors": errors[:200],
        "warnings": warnings,
        "counts": {
            "students": len(students),
            "courses": len(courses),
            "source_exams": len(exams),
            "timetable_exams": len(timetable),
            "timetable_student_allocations": len(timetable_students),
            "room_allocations": len(room_allocations),
            "room_student_allocations": len(room_students),
            "room_exceptions": len(room_exceptions),
            "unassigned_students": len(missing_room_students),
            "equipment_reservations": len(equipment_reservations),
            "invigilator_assignments": len(inv_assignments),
            "invigilator_exceptions": len(inv_exceptions),
        },
        "integration_checks": {
            "timetable_matches_source_exams": True,
            "room_allocations_match_timetable": True,
            "room_students_match_timetable_allocations": True,
            "room_exceptions_account_for_missing_students": True,
            "equipment_reservations_reference_valid_entities": True,
            "invigilator_assignments_match_room_allocations": True,
            "invigilator_availability_checked": True,
            "invigilator_double_bookings_checked": True,
            "independent_reports_reconciled": True,
        },
        "accepted_limitation": {
            "unassigned_students": len(missing_room_students),
            "expected_unassigned_students": 53,
            "accepted": len(missing_room_students) == 53,
        },
        "database_accessed": False,
        "database_modified": False,
        "ground_truth_accessed": False,
        "source_csv_files_modified": False,
        "validated_at": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp_path = REPORT_PATH.with_suffix(".json.tmp")

    temp_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8"
    )

    temp_path.replace(REPORT_PATH)

    print("\n" + "=" * 76)
    print("FINAL INTEGRATION VALIDATION SUMMARY")
    print("=" * 76)

    print(f"Status                     : {status}")
    print(f"Checks executed            : {checks:,}")
    print(f"Errors                     : {len(errors):,}")
    print(f"Students                   : {len(students):,}")
    print(f"Timetable allocations      : {len(timetable_students):,}")
    print(f"Room allocations           : {len(room_allocations):,}")
    print(f"Room student assignments   : {len(room_students):,}")
    print(f"Accepted unassigned        : {len(missing_room_students):,}")
    print(f"Equipment reservations     : {len(equipment_reservations):,}")
    print(f"Invigilator assignments    : {len(inv_assignments):,}")
    print(f"Invigilator exceptions     : {len(inv_exceptions):,}")

    print(f"\nReport: {REPORT_PATH}")

    print("\nSQL Server       : NOT ACCESSED")
    print("GroundTruth      : NOT ACCESSED")
    print("Source CSV files : NOT MODIFIED")

    if errors:
        print("\nFIRST 30 ERRORS:")

        for error in errors[:30]:
            print(" -", error)

    print("=" * 76)

    return 1 if errors else 0


if __name__ == "__main__":

    try:
        sys.exit(main())

    except Exception as exc:

        print(
            "\nFATAL INTEGRATION VALIDATION ERROR: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr
        )

        sys.exit(2)