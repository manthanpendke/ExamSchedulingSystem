#!/usr/bin/env python3
"""Independent validator for v2.2.0 room allocation outputs.

Does not import the allocator or its helper functions. Reconstructs hard
constraints from source CSVs and checks the produced allocation artifacts.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict, Counter
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
SCHED = DATA / "scheduling"
REPORT_PATH = SCHED / "room_allocation_independent_validation_v220.json"

TRUE = {"1", "true", "yes", "y"}
DT_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
)


def read(path):
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def integer(value):
    return int(float(str(value).strip()))


def boolean(value):
    return str(value or "").strip().lower() in TRUE


def dt(value):
    for fmt in DT_FORMATS:
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            pass
    raise ValueError(f"Invalid datetime {value!r}")


def day(value):
    return date.fromisoformat(str(value).strip()[:10])


def active(row, target_date):
    if row.get("EffectiveFrom") and target_date < day(row["EffectiveFrom"]):
        return False
    if row.get("EffectiveTo") and target_date > day(row["EffectiveTo"]):
        return False
    return True


def overlaps(a_start, a_end, b_start, b_end):
    # Half-open intervals: adjacent exams are permitted.
    return a_start < b_end and b_start < a_end


def run():
    timetable = read(SCHED / "ExamTimetable.csv")
    source_students = read(SCHED / "TimetableStudentAllocation.csv")
    rooms = read(DATA / "Room.csv")
    capacities = read(DATA / "RoomCapacity.csv")
    closures = read(DATA / "RoomClosure.csv")
    room_equipment = read(DATA / "RoomEquipment.csv")
    equipment = read(DATA / "Equipment.csv")
    exam_equipment = read(DATA / "ExamRequiredEquipment.csv")
    accommodations = read(DATA / "Accommodation.csv")
    special = read(DATA / "metadata" / "StudentSpecialEquipmentRequirement.csv")

    room_alloc = read(SCHED / "RoomAllocation.csv")
    student_alloc = read(SCHED / "RoomStudentAllocation.csv")
    reservations = read(SCHED / "RoomEquipmentReservation.csv")
    exceptions = read(SCHED / "RoomAllocationExceptions.csv")

    errors = []
    checks = 0

    def check(condition, message):
        nonlocal checks
        checks += 1
        if not condition and len(errors) < 500:
            errors.append(message)

    exam = {
        integer(row["ExamID"]): row
        for row in timetable
    }
    room = {
        integer(row["RoomID"]): row
        for row in rooms
    }
    equipment_active = {
        integer(row["EquipmentID"])
        for row in equipment
        if boolean(row.get("IsActive"))
    }

    src_by_key = {
        (
            integer(row["EnrollmentID"]),
            integer(row["StudentID"]),
            integer(row["ExamID"]),
        ): row
        for row in source_students
    }

    room_alloc_by_id = {
        integer(row["RoomAllocationID"]): row
        for row in room_alloc
    }

    students_by_room_alloc = defaultdict(list)
    for row in student_alloc:
        students_by_room_alloc[
            (integer(row["ExamID"]), integer(row["RoomID"]))
        ].append(row)

    # --------------------------------------------------------
    # 1. SOURCE COVERAGE AND UNIQUENESS
    # --------------------------------------------------------
    actual_keys = [
        (
            integer(row["EnrollmentID"]),
            integer(row["StudentID"]),
            integer(row["ExamID"]),
        )
        for row in student_alloc
    ]

    check(
        len(actual_keys) == len(set(actual_keys)),
        "Duplicate student-room assignment key."
    )
    check(
        set(actual_keys).issubset(set(src_by_key)),
        "Room assignment references a non-source student/exam allocation."
    )

    missing = set(src_by_key) - set(actual_keys)
    missing_by_exam = Counter(key[2] for key in missing)

    exception_by_exam = {
        integer(row["ExamID"]): integer(row["UnassignedStudentCount"])
        for row in exceptions
    }

    check(
        dict(missing_by_exam) == exception_by_exam,
        "Unassigned source students are not exactly accounted for by exception rows."
    )
    check(
        len(exam) == len(timetable),
        "Duplicate ExamID in timetable source."
    )

    # --------------------------------------------------------
    # 2. ACCOMMODATION AND SPECIAL-EQUIPMENT INDEXES
    # --------------------------------------------------------
    acc = defaultdict(list)
    for row in accommodations:
        acc[integer(row["StudentID"])].append(row)

    spec = defaultdict(list)
    for row in special:
        spec[integer(row["StudentID"])].append(
            (
                integer(row["EquipmentID"]),
                integer(row["QuantityRequired"]),
            )
        )

    def active_types(student_id, exam_date):
        types = set()

        for accommodation in acc[student_id]:
            if str(
                accommodation.get("AccommodationStatus", "")
            ).upper() != "ACTIVE":
                continue

            if not active(accommodation, exam_date):
                continue

            types.add(
                str(
                    accommodation.get("AccommodationType", "")
                ).upper()
            )

            if boolean(accommodation.get("RequiresSeparateRoom")):
                types.add("SEPARATE_ROOM")

        return types

    # --------------------------------------------------------
    # 3. STUDENT EFFECTIVE-INTERVAL CONFLICT VALIDATION
    # --------------------------------------------------------
    # This uses source timetable allocations, not room assignment
    # output. Therefore, an unassigned student cannot hide a conflict.
    source_intervals_by_student = defaultdict(list)

    for source in source_students:
        student_id = integer(source["StudentID"])
        exam_id = integer(source["ExamID"])

        if exam_id not in exam:
            check(
                False,
                f"Student {student_id} references unknown exam "
                f"{exam_id} during conflict validation."
            )
            continue

        exam_row = exam[exam_id]
        exam_date = day(exam_row["ExamDate"])

        start_value = str(
            source.get("StartDateTime", "")
        ).strip()

        if not start_value:
            start_value = str(
                exam_row.get("StartDateTime", "")
            ).strip()

        if not start_value:
            check(
                False,
                f"Student {student_id}, exam {exam_id}: "
                "missing start time for conflict validation."
            )
            continue

        start = dt(start_value)

        effective_end_value = str(
            source.get("EffectiveEndDateTime", "")
        ).strip()

        duration_value = str(
            source.get("EffectiveDurationMinutes", "")
        ).strip()

        if effective_end_value:
            end = dt(effective_end_value)

        elif duration_value:
            end = start + timedelta(
                minutes=integer(duration_value)
            )

        else:
            base_end_value = str(
                exam_row.get("EndDateTime", "")
            ).strip()

            if not base_end_value:
                check(
                    False,
                    f"Student {student_id}, exam {exam_id}: "
                    "missing effective end time for conflict validation."
                )
                continue

            base_end = dt(base_end_value)

            extension = max(
                (
                    float(
                        accommodation.get("ExtensionPercentage") or 0
                    )
                    for accommodation in acc[student_id]
                    if (
                        str(
                            accommodation.get("AccommodationType", "")
                        ).upper() == "EXTENDED_TIME"
                        and str(
                            accommodation.get("AccommodationStatus", "")
                        ).upper() == "ACTIVE"
                        and active(accommodation, exam_date)
                    )
                ),
                default=0.0,
            )

            end = start + (
                (base_end - start) * (1 + extension / 100.0)
            )

        check(
            end > start,
            f"Student {student_id}, exam {exam_id}: "
            "invalid effective interval."
        )

        if end > start:
            source_intervals_by_student[student_id].append(
                (start, end, exam_id)
            )

    for student_id, intervals in source_intervals_by_student.items():
        intervals.sort(
            key=lambda item: (item[0], item[1], item[2])
        )

        for previous, current in zip(
            intervals,
            intervals[1:]
        ):
            check(
                not overlaps(
                    previous[0],
                    previous[1],
                    current[0],
                    current[1],
                ),
                f"STUDENT CONFLICT: student {student_id} has "
                f"overlapping effective exam intervals for exams "
                f"{previous[2]} and {current[2]}.",
            )

    # --------------------------------------------------------
    # 4. INDEPENDENT MANDATORY EQUIPMENT REQUIREMENTS
    # --------------------------------------------------------
    mandatory = defaultdict(lambda: defaultdict(int))

    for row in exam_equipment:
        if boolean(row.get("IsMandatory")):
            mandatory[integer(row["ExamID"])][
                integer(row["EquipmentID"])
            ] += integer(row["QuantityRequired"])

    # --------------------------------------------------------
    # 5. CAPACITY, CLOSURE, ACCESSIBILITY, SEPARATE ROOM,
    #    EQUIPMENT, AND ROOM-INTERVAL VALIDATION
    # --------------------------------------------------------
    room_bookings = defaultdict(list)
    by_exam_room = defaultdict(list)

    for row in student_alloc:
        by_exam_room[
            (integer(row["ExamID"]), integer(row["RoomID"]))
        ].append(row)

    alloc_rows_by_exam_room = {
        (integer(row["ExamID"]), integer(row["RoomID"])): row
        for row in room_alloc
    }

    for key, group in by_exam_room.items():
        exam_id, room_id = key

        check(
            room_id in room,
            f"Assignment references unknown room {room_id}."
        )

        if room_id not in room or exam_id not in exam:
            continue

        exam_row = exam[exam_id]
        exam_date = day(exam_row["ExamDate"])

        starts = [
            dt(row["StartDateTime"])
            for row in group
        ]
        ends = [
            dt(row["StudentEffectiveEndDateTime"])
            for row in group
        ]

        start = min(starts)
        end = max(ends)

        room_row = room[room_id]

        check(
            boolean(room_row.get("IsActive")),
            f"Inactive room {room_id} assigned to exam {exam_id}."
        )

        effective_capacities = [
            integer(capacity["Capacity"])
            for capacity in capacities
            if (
                integer(capacity["RoomID"]) == room_id
                and active(capacity, exam_date)
            )
        ]

        capacity = (
            max(effective_capacities)
            if effective_capacities
            else 0
        )

        check(
            capacity > 0,
            f"Room {room_id} has no effective capacity on {exam_date}."
        )

        check(
            len(group) <= capacity,
            f"Room {room_id} exam {exam_id}: "
            f"{len(group)} students exceed capacity {capacity}."
        )

        # Active room closures.
        for closure in closures:
            if (
                integer(closure["RoomID"]) != room_id
                or str(
                    closure.get("ClosureStatus", "")
                ).upper() != "ACTIVE"
            ):
                continue

            check(
                not overlaps(
                    start,
                    end,
                    dt(closure["ClosureStart"]),
                    dt(closure["ClosureEnd"]),
                ),
                f"Room {room_id} exam {exam_id} overlaps "
                f"active closure {closure.get('RoomClosureID', '')}.",
            )

        # Accessible-room rule.
        has_accessible = any(
            "ACCESSIBLE_ROOM" in active_types(
                integer(row["StudentID"]),
                exam_date
            )
            for row in group
        )

        if has_accessible:
            check(
                str(room_row.get("RoomType", "")).upper() == "ACCESSIBLE",
                f"Accessible student assigned to non-accessible "
                f"room {room_id}, exam {exam_id}."
            )

        # Separate-room rule.
        separate_students = [
            row
            for row in group
            if "SEPARATE_ROOM" in active_types(
                integer(row["StudentID"]),
                exam_date
            )
        ]

        if separate_students:
            check(
                len(group) == 1 and len(separate_students) == 1,
                f"Separate-room student shares room {room_id}, "
                f"exam {exam_id}."
            )

        # Mandatory exam equipment plus student-specific equipment.
        required = Counter(mandatory[exam_id])

        for row in group:
            student_id = integer(row["StudentID"])

            if "SPECIAL_EQUIPMENT" in active_types(
                student_id,
                exam_date
            ):
                for equipment_id, quantity in spec[student_id]:
                    required[equipment_id] += quantity

        available = Counter()

        for item in room_equipment:
            if (
                integer(item["RoomID"]) == room_id
                and active(item, exam_date)
            ):
                available[
                    integer(item["EquipmentID"])
                ] += integer(item["Quantity"])

        for equipment_id, quantity in required.items():
            check(
                equipment_id in equipment_active,
                f"Inactive/missing equipment {equipment_id} "
                f"required by exam {exam_id}."
            )

            check(
                available[equipment_id] >= quantity,
                f"Room {room_id}, exam {exam_id}: equipment "
                f"{equipment_id} needs {quantity}, "
                f"has {available[equipment_id]}."
            )

        room_bookings[room_id].append(
            (start, end, exam_id)
        )

        allocation = alloc_rows_by_exam_room.get(key)

        check(
            allocation is not None,
            f"Missing RoomAllocation summary for exam "
            f"{exam_id}, room {room_id}."
        )

        if allocation:
            check(
                integer(allocation["AllocatedStudentCount"]) == len(group),
                f"RoomAllocation count mismatch for exam "
                f"{exam_id}, room {room_id}."
            )

            check(
                integer(allocation["AssignedCapacity"]) == capacity,
                f"AssignedCapacity mismatch for room "
                f"{room_id}, exam {exam_id}."
            )

    # No room can host overlapping effective intervals.
    for room_id, bookings in room_bookings.items():
        bookings.sort()

        for previous, current in zip(
            bookings,
            bookings[1:]
        ):
            check(
                not overlaps(
                    previous[0],
                    previous[1],
                    current[0],
                    current[1],
                ),
                f"Room {room_id} has overlapping exams "
                f"{previous[2]} and {current[2]}.",
            )

    # --------------------------------------------------------
    # 6. ROOM SUMMARY AND EXCEPTION VALIDATION
    # --------------------------------------------------------
    expected_pairs = set(by_exam_room)

    actual_pairs = {
        (integer(row["ExamID"]), integer(row["RoomID"]))
        for row in room_alloc
    }

    check(
        expected_pairs == actual_pairs,
        "RoomAllocation and RoomStudentAllocation room pairs differ."
    )

    approved_reasons = {
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
    }

    for row in exceptions:
        check(
            str(row["ReasonCode"]) in approved_reasons,
            f"Invalid exception reason code {row['ReasonCode']}."
        )

    # --------------------------------------------------------
    # 7. INDEPENDENT COURSE-WINDOW EQUIPMENT RESERVATION CHECK
    # --------------------------------------------------------
    timetable_by_course = defaultdict(list)

    for row in timetable:
        timetable_by_course[
            integer(row["CourseID"])
        ].append(row)

    source_students_by_exam = defaultdict(list)

    for row in source_students:
        source_students_by_exam[
            integer(row["ExamID"])
        ].append(row)

    rejected_course_ids = {
        integer(row["CourseID"])
        for row in exceptions
        if (
            str(row.get("ReasonCode", "")).upper() == "NO_EQUIPMENT"
            and str(row.get("Details", "")).startswith(
                "Course equipment reservation rejected:"
            )
        )
    }

    expected_reservations = {}

    for course_id, exams in timetable_by_course.items():
        if course_id in rejected_course_ids:
            continue

        peak = Counter()

        for exam_row in exams:
            exam_id = integer(exam_row["ExamID"])
            need = Counter(mandatory[exam_id])
            exam_date = day(exam_row["ExamDate"])

            for student in source_students_by_exam[exam_id]:
                student_id = integer(student["StudentID"])

                if "SPECIAL_EQUIPMENT" in active_types(
                    student_id,
                    exam_date
                ):
                    for equipment_id, quantity in spec[student_id]:
                        need[equipment_id] += quantity

            for equipment_id, quantity in need.items():
                peak[equipment_id] = max(
                    peak[equipment_id],
                    quantity
                )

        for equipment_id, quantity in peak.items():
            expected_reservations[
                (course_id, equipment_id)
            ] = quantity

    actual_reservations = {}

    for row in reservations:
        key = (
            integer(row["CourseID"]),
            integer(row["EquipmentID"]),
        )

        check(
            key not in actual_reservations,
            f"Duplicate course/equipment reservation {key}."
        )

        actual_reservations[key] = integer(
            row["ReservedQuantity"]
        )

        check(
            str(row.get("ReservationPolicy"))
            == "COURSE_WINDOW_SHARED_INVENTORY",
            f"Wrong reservation policy for course/equipment {key}."
        )

        check(
            dt(row["ReservationEnd"]) > dt(row["ReservationStart"]),
            f"Invalid reservation window for {key}."
        )

    check(
        actual_reservations == expected_reservations,
        "Course equipment reservation quantities differ from "
        "independently derived needs. "
        f"Expected {len(expected_reservations)} rows, "
        f"got {len(actual_reservations)}."
    )

    # Overlapping course reservation demand must not exceed inventory.
    all_equipment_ids = {
        integer(row["EquipmentID"])
        for row in equipment
        if boolean(row.get("IsActive"))
    }

    for equipment_id in all_equipment_ids:
        rows = [
            row
            for row in reservations
            if integer(row["EquipmentID"]) == equipment_id
        ]

        points = sorted(
            {
                dt(row["ReservationStart"])
                for row in rows
            }
            |
            {
                dt(row["ReservationEnd"])
                for row in rows
            }
        )

        for point in points:
            demand = sum(
                integer(row["ReservedQuantity"])
                for row in rows
                if (
                    dt(row["ReservationStart"]) <= point
                    < dt(row["ReservationEnd"])
                )
            )

            inventory = 0

            for room_row in rooms:
                if not boolean(room_row.get("IsActive")):
                    continue

                room_id = integer(room_row["RoomID"])

                for item in room_equipment:
                    if (
                        integer(item["RoomID"]) == room_id
                        and integer(item["EquipmentID"]) == equipment_id
                        and active(item, point.date())
                    ):
                        inventory += integer(item["Quantity"])

            check(
                demand <= inventory,
                f"Equipment {equipment_id} reservation demand "
                f"{demand} exceeds inventory {inventory} at {point}."
            )

    # --------------------------------------------------------
    # 8. STUDENT INTERVALS MUST FIT ROOM ALLOCATION INTERVALS
    # --------------------------------------------------------
    for row in student_alloc:
        exam_id = integer(row["ExamID"])
        room_id = integer(row["RoomID"])

        matching_rows = [
            allocation
            for allocation in room_alloc
            if (
                integer(allocation["ExamID"]) == exam_id
                and integer(allocation["RoomID"]) == room_id
            )
        ]

        if matching_rows:
            allocation = matching_rows[0]

            check(
                dt(allocation["StartDateTime"])
                <= dt(row["StartDateTime"]),
                f"Student starts before room allocation: "
                f"{row['StudentID']}, exam {exam_id}."
            )

            check(
                dt(row["StudentEffectiveEndDateTime"])
                <= dt(allocation["EndDateTime"]),
                f"Student ends after room allocation: "
                f"{row['StudentID']}, exam {exam_id}."
            )

    # --------------------------------------------------------
    # 9. FINAL REPORT
    # --------------------------------------------------------
    report = {
        "version": "2.2.0",
        "status": (
            "FAILED"
            if errors
            else (
                "PASSED_WITH_EXCEPTIONS"
                if exceptions or missing
                else "PASSED"
            )
        ),
        "checks": checks,
        "errors": len(errors),
        "error_samples": errors[:100],
        "counts": {
            "timetable_exams": len(timetable),
            "source_student_allocations": len(source_students),
            "room_allocations": len(room_alloc),
            "student_room_allocations": len(student_alloc),
            "equipment_reservation_rows": len(reservations),
            "exceptions": len(exceptions),
            "unassigned_source_allocations": len(
                set(src_by_key) - set(actual_keys)
            ),
        },
        "independent": True,
        "allocator_imported": False,
        "database_accessed": False,
        "database_modified": False,
        "ground_truth_accessed": False,
    }

    SCHED.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8"
    )

    print(json.dumps(report, indent=2))
    print(f"\nReport: {REPORT_PATH}")

    return 0 if not errors else 1


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as exc:
        print(
            f"\nINDEPENDENT VALIDATION FAILED TO RUN: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr
        )
        sys.exit(2)