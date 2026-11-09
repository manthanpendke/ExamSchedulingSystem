
#!/usr/bin/env python3
"""Fixed-timetable physical room allocator for Exam Scheduling System v2.2.0.

Implements soft protection for scarce specialist rooms while preserving
all existing hard constraints, CSV schemas and equipment reservations.

Does not modify timetable, SQL Server or GroundTruth.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
SCHED = DATA / "scheduling"
META = DATA / "metadata"

OUT_ROOM = SCHED / "RoomAllocation.csv"
OUT_STUDENT = SCHED / "RoomStudentAllocation.csv"
OUT_EQUIP = SCHED / "RoomEquipmentReservation.csv"
OUT_EXCEPT = SCHED / "RoomAllocationExceptions.csv"
OUT_REPORT = SCHED / "room_allocation_report_v220.json"

REASON_CODES = {
    "NO_ROOM_CAPACITY", "NO_EQUIPMENT", "NO_INVIGILATOR",
    "STUDENT_CONFLICT", "ACCOMMODATION_CONFLICT", "ROOM_CLOSED",
    "NO_VALID_TIMESLOT", "NO_ELIGIBLE_STUDENTS",
    "INVALID_REQUIREMENT", "OTHER",
}

TRUE = {"1", "true", "yes", "y"}
DT_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
)


def read_csv(path: Path, required=True):
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required input file missing: {path}")
        return []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=columns,
            extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)

    tmp.replace(path)


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, default=str),
        encoding="utf-8"
    )
    tmp.replace(path)


def as_int(value, field):
    try:
        return int(float(str(value).strip()))
    except Exception as exc:
        raise ValueError(
            f"{field} must be an integer; got {value!r}"
        ) from exc


def as_bool(value):
    return str(value or "").strip().lower() in TRUE


def parse_dt(value, field):
    value = str(value or "").strip()

    for fmt in DT_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass

    raise ValueError(
        f"Invalid datetime in {field}: {value!r}"
    )


def parse_date(value, field):
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except Exception as exc:
        raise ValueError(
            f"Invalid date in {field}: {value!r}"
        ) from exc


def active_on(row, target_date):
    if str(row.get("EffectiveFrom", "")).strip():
        if target_date < parse_date(
            row["EffectiveFrom"], "EffectiveFrom"
        ):
            return False

    if str(row.get("EffectiveTo", "")).strip():
        if target_date > parse_date(
            row["EffectiveTo"], "EffectiveTo"
        ):
            return False

    return True


def overlap(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def load_inputs():
    files = {
        "timetable": SCHED / "ExamTimetable.csv",
        "students": SCHED / "TimetableStudentAllocation.csv",
        "rooms": DATA / "Room.csv",
        "capacities": DATA / "RoomCapacity.csv",
        "closures": DATA / "RoomClosure.csv",
        "room_equipment": DATA / "RoomEquipment.csv",
        "equipment": DATA / "Equipment.csv",
        "exam_requirement": DATA / "ExamRequirement.csv",
        "exam_equipment": DATA / "ExamRequiredEquipment.csv",
        "accommodations": DATA / "Accommodation.csv",
        "special": META / "StudentSpecialEquipmentRequirement.csv",
    }

    data = {
        key: read_csv(path)
        for key, path in files.items()
    }

    if not data["timetable"]:
        raise ValueError("ExamTimetable.csv is empty.")

    if not data["students"]:
        raise ValueError("TimetableStudentAllocation.csv is empty.")

    if not data["rooms"]:
        raise ValueError("Room.csv is empty.")

    return data


def validate_inputs(data):
    errors = []

    def unique(rows, key, label):
        values = [
            str(row.get(key, "")).strip()
            for row in rows
        ]

        if "" in values:
            errors.append(f"{label}: blank {key}")

        if len(values) != len(set(values)):
            errors.append(f"{label}: duplicate {key}")

    unique(data["timetable"], "ExamID", "ExamTimetable")
    unique(data["rooms"], "RoomID", "Room")
    unique(data["equipment"], "EquipmentID", "Equipment")
    unique(
        data["students"],
        "EnrollmentID",
        "TimetableStudentAllocation"
    )

    exam_ids = {
        str(row["ExamID"])
        for row in data["timetable"]
    }

    room_ids = {
        str(row["RoomID"])
        for row in data["rooms"]
    }

    equipment_ids = {
        str(row["EquipmentID"])
        for row in data["equipment"]
    }

    for row in data["students"]:
        if str(row["ExamID"]) not in exam_ids:
            errors.append(
                f"Student allocation references missing exam "
                f"{row['ExamID']}"
            )

        # --------------------------------------------------------
    # STUDENT EFFECTIVE-INTERVAL CONFLICT VALIDATION
    # --------------------------------------------------------
    # Reject source timetables that assign one student to
    # overlapping effective exam intervals. Extended time is
    # included. Adjacent intervals are allowed.
    exam_by_id = {
        as_int(row["ExamID"], "ExamID"): row
        for row in data["timetable"]
    }

    acc_for_conflicts = accommodation_index(data["accommodations"])
    student_intervals = defaultdict(list)

    for row in data["students"]:
        exam_id = as_int(
            row["ExamID"],
            "StudentAllocation.ExamID"
        )

        if exam_id not in exam_by_id:
            continue

        exam_row = exam_by_id[exam_id]

        exam_date = parse_date(
            exam_row["ExamDate"],
            "ExamTimetable.ExamDate"
        )

        start = parse_dt(
            row["StartDateTime"],
            "StudentAllocation.StartDateTime"
        )

        base_end = parse_dt(
            exam_row["EndDateTime"],
            "ExamTimetable.EndDateTime"
        )

        effective_end = student_end(
            row,
            start,
            base_end,
            acc_for_conflicts,
            exam_date
        )

        student_id = as_int(
            row["StudentID"],
            "StudentAllocation.StudentID"
        )

        if effective_end <= start:
            errors.append(
                f"Student {student_id}, exam {exam_id}: "
                "invalid effective interval."
            )
            continue

        student_intervals[student_id].append(
            (start, effective_end, exam_id)
        )

    for student_id, intervals in student_intervals.items():
        intervals.sort(
            key=lambda item: (item[0], item[1], item[2])
        )

        for previous, current in zip(
            intervals,
            intervals[1:]
        ):
            if overlap(
                previous[0],
                previous[1],
                current[0],
                current[1]
            ):
                errors.append(
                    f"STUDENT CONFLICT: student {student_id} "
                    f"has overlapping effective exam intervals "
                    f"for exams {previous[2]} and {current[2]}."
                )

    for row in data["capacities"]:
        if str(row["RoomID"]) not in room_ids:
            errors.append(
                f"RoomCapacity references missing room "
                f"{row['RoomID']}"
            )

    for row in data["room_equipment"]:
        if (
            str(row["RoomID"]) not in room_ids
            or str(row["EquipmentID"]) not in equipment_ids
        ):
            errors.append(
                f"RoomEquipment has invalid reference: {row}"
            )

    for row in data["exam_equipment"]:
        if (
            str(row["ExamID"]) not in exam_ids
            or str(row["EquipmentID"]) not in equipment_ids
        ):
            errors.append(
                f"ExamRequiredEquipment has invalid reference: {row}"
            )

    # Reconcile ExamRequirement JSON with normalized bridge table.
    normalized = defaultdict(list)

    for row in data["exam_equipment"]:
        normalized[str(row["ExamID"])].append({
            "EquipmentID": as_int(
                row["EquipmentID"],
                "ExamRequiredEquipment.EquipmentID"
            ),
            "QuantityRequired": as_int(
                row["QuantityRequired"],
                "ExamRequiredEquipment.QuantityRequired"
            ),
            "IsMandatory": as_bool(row.get("IsMandatory")),
        })

    for row in data["exam_requirement"]:
        raw = str(
            row.get("RequiredEquipment", "") or ""
        ).strip()

        if not raw:
            expected = []
        else:
            try:
                parsed = json.loads(raw)

                expected = [{
                    "EquipmentID": as_int(
                        item["EquipmentID"],
                        "RequiredEquipment.EquipmentID"
                    ),
                    "QuantityRequired": as_int(
                        item["QuantityRequired"],
                        "RequiredEquipment.QuantityRequired"
                    ),
                    "IsMandatory": as_bool(
                        item["IsMandatory"]
                    ),
                } for item in parsed]

            except Exception as exc:
                errors.append(
                    "Invalid RequiredEquipment JSON for exam "
                    f"{row.get('ExamID')}: {exc}"
                )
                continue

        actual = normalized.get(str(row["ExamID"]), [])

        sort_key = lambda x: (
            x["EquipmentID"],
            x["QuantityRequired"],
            x["IsMandatory"]
        )

        if sorted(expected, key=sort_key) != sorted(
            actual, key=sort_key
        ):
            errors.append(
                "ExamRequirement JSON and "
                "ExamRequiredEquipment differ for exam "
                f"{row['ExamID']}"
            )

    if errors:
        raise ValueError(
            "Input preflight failed:\n - "
            + "\n - ".join(errors[:80])
        )


def accommodation_index(rows):
    result = defaultdict(list)

    for row in rows:
        result[
            as_int(row["StudentID"], "Accommodation.StudentID")
        ].append(row)

    return result


def special_index(rows):
    result = defaultdict(list)

    for row in rows:
        result[
            as_int(row["StudentID"], "Special.StudentID")
        ].append({
            "EquipmentID": as_int(
                row["EquipmentID"], "Special.EquipmentID"
            ),
            "Quantity": as_int(
                row["QuantityRequired"],
                "Special.QuantityRequired"
            ),
            "Name": row.get("EquipmentName", ""),
        })

    return result


def accommodations_for(student_id, exam_date, acc_index):
    result = set()

    for row in acc_index.get(student_id, []):
        if str(
            row.get("AccommodationStatus", "")
        ).upper() != "ACTIVE":
            continue

        if not active_on(row, exam_date):
            continue

        result.add(
            str(row.get("AccommodationType", "")).upper()
        )

        if as_bool(row.get("RequiresSeparateRoom")):
            result.add("SEPARATE_ROOM")

    return result


def student_end(row, start, base_end, acc_index, exam_date):
    raw = str(
        row.get("EffectiveEndDateTime", "")
    ).strip()

    if raw:
        return parse_dt(raw, "EffectiveEndDateTime")

    raw_duration = str(
        row.get("EffectiveDurationMinutes", "")
    ).strip()

    if raw_duration:
        return start + timedelta(
            minutes=as_int(
                raw_duration,
                "EffectiveDurationMinutes"
            )
        )

    # Compatibility with earlier allocation schema.
    student_id = as_int(row["StudentID"], "StudentID")
    percentage = 0.0

    for accommodation in acc_index.get(student_id, []):
        if (
            str(accommodation.get("AccommodationType", "")).upper()
            == "EXTENDED_TIME"
            and str(
                accommodation.get("AccommodationStatus", "")
            ).upper() == "ACTIVE"
            and active_on(accommodation, exam_date)
        ):
            percentage = max(
                percentage,
                float(
                    accommodation.get("ExtensionPercentage") or 0
                )
            )

    base_minutes = int(
        round((base_end - start).total_seconds() / 60)
    )

    extended_minutes = int(
        round(base_minutes * (1 + percentage / 100))
    )

    return start + timedelta(minutes=extended_minutes)


def equipment_by_exam(data):
    result = defaultdict(dict)

    names = {
        as_int(row["EquipmentID"], "EquipmentID"):
        row["EquipmentName"]
        for row in data["equipment"]
    }

    for row in data["exam_equipment"]:
        if not as_bool(row.get("IsMandatory")):
            continue

        equipment_id = as_int(
            row["EquipmentID"], "ExamRequiredEquipment.EquipmentID"
        )

        quantity = as_int(
            row["QuantityRequired"],
            "ExamRequiredEquipment.QuantityRequired"
        )

        exam_id = as_int(
            row["ExamID"], "ExamRequiredEquipment.ExamID"
        )

        result[exam_id][equipment_id] = (
            result[exam_id].get(equipment_id, 0) + quantity
        )

    return result, names


def effective_room_equipment(data, room_id, exam_date):
    quantity = defaultdict(int)

    active_ids = {
        as_int(row["EquipmentID"], "EquipmentID")
        for row in data["equipment"]
        if as_bool(row.get("IsActive"))
    }

    for row in data["room_equipment"]:
        if as_int(row["RoomID"], "RoomEquipment.RoomID") != room_id:
            continue

        equipment_id = as_int(
            row["EquipmentID"], "RoomEquipment.EquipmentID"
        )

        if equipment_id not in active_ids:
            continue

        if active_on(row, exam_date):
            quantity[equipment_id] += as_int(
                row["Quantity"], "RoomEquipment.Quantity"
            )

    return quantity


def effective_capacity(data, room_id, exam_date):
    matches = []

    for row in data["capacities"]:
        if (
            as_int(row["RoomID"], "RoomCapacity.RoomID") == room_id
            and active_on(row, exam_date)
        ):
            matches.append(
                as_int(row["Capacity"], "RoomCapacity.Capacity")
            )

    return max(matches) if matches else 0


def is_closed(data, room_id, start, end):
    for row in data["closures"]:
        if as_int(row["RoomID"], "RoomClosure.RoomID") != room_id:
            continue

        if str(row.get("ClosureStatus", "")).upper() != "ACTIVE":
            continue

        closure_start = parse_dt(
            row["ClosureStart"], "RoomClosure.ClosureStart"
        )

        closure_end = parse_dt(
            row["ClosureEnd"], "RoomClosure.ClosureEnd"
        )

        if closure_end <= closure_start:
            raise ValueError(
                f"Invalid room closure interval: {row}"
            )

        if overlap(start, end, closure_start, closure_end):
            return True

    return False


def build_course_reservations(
    data,
    exam_mandatory,
    special_by_student,
    acc_index,
    equipment_names
):
    students_by_exam = defaultdict(list)

    for student in data["students"]:
        students_by_exam[
            as_int(student["ExamID"], "StudentAllocation.ExamID")
        ].append(student)

    exams_by_course = defaultdict(list)

    for exam in data["timetable"]:
        exams_by_course[
            as_int(exam["CourseID"], "Timetable.CourseID")
        ].append(exam)

    course_need = {}

    for course_id, exams in exams_by_course.items():
        per_exam = []

        for exam in exams:
            exam_id = as_int(exam["ExamID"], "ExamID")

            need = defaultdict(
                int,
                exam_mandatory.get(exam_id, {})
            )

            exam_date = parse_date(
                exam["ExamDate"], "ExamDate"
            )

            for student in students_by_exam[exam_id]:
                student_id = as_int(
                    student["StudentID"], "StudentID"
                )

                if "SPECIAL_EQUIPMENT" in accommodations_for(
                    student_id, exam_date, acc_index
                ):
                    for item in special_by_student.get(
                        student_id, []
                    ):
                        need[item["EquipmentID"]] += item["Quantity"]

            per_exam.append(need)

        peak = defaultdict(int)

        for need in per_exam:
            for equipment_id, quantity in need.items():
                peak[equipment_id] = max(
                    peak[equipment_id], quantity
                )

        reservation_start = min(
            parse_dt(exam["StartDateTime"], "StartDateTime")
            for exam in exams
        )

        reservation_end = max(
            parse_dt(exam["EndDateTime"], "EndDateTime")
            for exam in exams
        )

        # Include extended-time student endpoints.
        for exam in exams:
            exam_id = as_int(exam["ExamID"], "ExamID")
            exam_date = parse_date(exam["ExamDate"], "ExamDate")

            for student in students_by_exam[exam_id]:
                reservation_end = max(
                    reservation_end,
                    student_end(
                        student,
                        parse_dt(
                            student["StartDateTime"],
                            "Student.StartDateTime"
                        ),
                        parse_dt(
                            student["EndDateTime"],
                            "Student.EndDateTime"
                        ),
                        acc_index,
                        exam_date
                    )
                )

        course_need[course_id] = {
            "start": reservation_start,
            "end": reservation_end,
            "need": dict(peak),
            "exam_ids": sorted(
                as_int(exam["ExamID"], "ExamID")
                for exam in exams
            ),
        }

    accepted = []
    rejected = {}
    reservations = []

    active_equipment = {
        as_int(row["EquipmentID"], "EquipmentID")
        for row in data["equipment"]
        if as_bool(row.get("IsActive"))
    }

    course_order = sorted(
        course_need,
        key=lambda course_id: (
            course_need[course_id]["start"],
            -sum(course_need[course_id]["need"].values()),
            course_id
        )
    )

    for course_id in course_order:
        item = course_need[course_id]
        conflict = None

        for equipment_id, quantity in item["need"].items():
            if equipment_id not in active_equipment:
                conflict = (
                    f"EquipmentID {equipment_id} is inactive or missing."
                )
                break

            dates = {
                item["start"].date(),
                item["end"].date()
            }

            dates.update(
                other["start"].date()
                for other in accepted
                if overlap(
                    item["start"], item["end"],
                    other["start"], other["end"]
                )
            )

            available_values = []

            for target_date in dates:
                total = 0

                for room in data["rooms"]:
                    room_id = as_int(room["RoomID"], "RoomID")

                    if not as_bool(room.get("IsActive")):
                        continue

                    total += effective_room_equipment(
                        data, room_id, target_date
                    ).get(equipment_id, 0)

                available_values.append(total)

            available = (
                min(available_values)
                if available_values else 0
            )

            concurrent = sum(
                other["need"].get(equipment_id, 0)
                for other in accepted
                if overlap(
                    item["start"], item["end"],
                    other["start"], other["end"]
                )
            )

            if concurrent + quantity > available:
                conflict = (
                    f"{equipment_names.get(equipment_id, equipment_id)} "
                    f"reservation requires {concurrent + quantity}, "
                    f"but shared effective inventory is {available}."
                )
                break

        if conflict:
            rejected[course_id] = conflict
            continue

        accepted.append({
            "course_id": course_id,
            **item
        })

        for equipment_id, quantity in sorted(item["need"].items()):
            inventory_rooms = []

            for room in data["rooms"]:
                room_id = as_int(room["RoomID"], "RoomID")

                if effective_room_equipment(
                    data, room_id, item["start"].date()
                ).get(equipment_id, 0) > 0:
                    inventory_rooms.append(room_id)

            reservations.append({
                "CourseID": course_id,
                "EquipmentID": equipment_id,
                "EquipmentName": equipment_names.get(
                    equipment_id, str(equipment_id)
                ),
                "ReservedQuantity": quantity,
                "ReservationStart": item["start"].strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "ReservationEnd": item["end"].strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "ExamIDs": json.dumps(item["exam_ids"]),
                "ReservationPolicy": "COURSE_WINDOW_SHARED_INVENTORY",
                "InventoryRoomIDs": json.dumps(inventory_rooms),
                "ReservationStatus": "RESERVED",
            })

    return course_need, rejected, reservations


def allocate(data):
    validate_inputs(data)

    acc_index = accommodation_index(data["accommodations"])
    special_by_student = special_index(data["special"])

    exam_mandatory, equipment_names = equipment_by_exam(data)

    exam_by_id = {
        as_int(row["ExamID"], "ExamID"): row
        for row in data["timetable"]
    }

    # Equipment category/name indexes for specialist-room scoring.
    equipment_category = {
        as_int(row["EquipmentID"], "EquipmentID"):
        str(row.get("EquipmentCategory", "")).strip().upper()
        for row in data["equipment"]
    }

    equipment_names_upper = {
        as_int(row["EquipmentID"], "EquipmentID"):
        str(row.get("EquipmentName", "")).strip().upper()
        for row in data["equipment"]
    }

    lab_equipment_ids = {
        equipment_id
        for equipment_id in equipment_names_upper
        if (
            "LAB" in equipment_category.get(equipment_id, "")
            or "LAB" in equipment_names_upper.get(equipment_id, "")
        )
    }

    accessible_equipment_ids = {
        equipment_id
        for equipment_id in equipment_names_upper
        if (
            "ACCESS" in equipment_category.get(equipment_id, "")
            or "ACCESS" in equipment_names_upper.get(equipment_id, "")
        )
    }

    # Cache equipment scarcity by exam date.
    specialist_coverage_cache = {}

    def specialist_room_score(room, exam_date, required, group):
        """
        Lower score is preferred.

        Rooms containing scarce equipment receive a soft penalty when
        that equipment is not needed by the exam.

        Specialist rooms remain eligible if necessary.
        """
        if exam_date not in specialist_coverage_cache:
            active_rooms = [
                candidate
                for candidate in data["rooms"]
                if (
                    as_bool(candidate.get("IsActive"))
                    and effective_capacity(
                        data,
                        as_int(candidate["RoomID"], "RoomID"),
                        exam_date
                    ) > 0
                )
            ]

            coverage = defaultdict(int)

            for candidate in active_rooms:
                candidate_id = as_int(
                    candidate["RoomID"], "RoomID"
                )

                stock = effective_room_equipment(
                    data, candidate_id, exam_date
                )

                for equipment_id, quantity in stock.items():
                    if quantity > 0:
                        coverage[equipment_id] += 1

            total_rooms = max(1, len(active_rooms))

            specialist_ids = {
                equipment_id
                for equipment_id, room_count in coverage.items()
                if room_count / total_rooms <= 0.40
            }

            specialist_coverage_cache[exam_date] = {
                "coverage": dict(coverage),
                "specialist_ids": specialist_ids,
                "total_rooms": total_rooms,
            }

        info = specialist_coverage_cache[exam_date]

        coverage = info["coverage"]
        specialist_ids = info["specialist_ids"]
        total_rooms = info["total_rooms"]

        room_id = as_int(room["RoomID"], "RoomID")

        stock = effective_room_equipment(
            data, room_id, exam_date
        )

        required_ids = set(required.keys())

        score = 0.0

        # Preserve scarce equipment for exams that need it.
        for equipment_id, quantity in stock.items():
            if quantity <= 0:
                continue

            if (
                equipment_id in specialist_ids
                and equipment_id not in required_ids
            ):
                ratio = coverage.get(
                    equipment_id, 0
                ) / total_rooms

                score += 1.0 + (1.0 - ratio)

        room_type = str(
            room.get("RoomType", "")
        ).strip().upper()

        needs_accessibility = any(
            student["accessible"] for student in group
        )

        needs_lab = bool(
            required_ids.intersection(lab_equipment_ids)
        )

        needs_accessible_equipment = bool(
            required_ids.intersection(accessible_equipment_ids)
        )

        if (
            room_type in {"LAB", "LABORATORY"}
            and not needs_lab
        ):
            score += 1.0

        if (
            room_type == "ACCESSIBLE"
            and not (
                needs_accessibility
                or needs_accessible_equipment
            )
        ):
            score += 0.75

        return round(score, 6)

    students_by_exam = defaultdict(list)

    for student in data["students"]:
        students_by_exam[
            as_int(student["ExamID"], "StudentAllocation.ExamID")
        ].append(student)

    course_need, rejected_courses, reservations = (
        build_course_reservations(
            data,
            exam_mandatory,
            special_by_student,
            acc_index,
            equipment_names
        )
    )

    room_bookings = defaultdict(list)

    room_allocations = []
    student_allocations = []
    exceptions = []

    room_alloc_id = 0
    allocated_student_keys = set()
    reason_counts = defaultdict(int)

    exams = sorted(
        data["timetable"],
        key=lambda exam: (
            parse_dt(exam["StartDateTime"], "StartDateTime"),
            -len(
                students_by_exam[
                    as_int(exam["ExamID"], "ExamID")
                ]
            ),
            as_int(exam["ExamID"], "ExamID"),
        )
    )

    for exam in exams:
        exam_id = as_int(exam["ExamID"], "ExamID")
        course_id = as_int(exam["CourseID"], "CourseID")
        exam_code = exam["ExamCode"]

        exam_date = parse_date(
            exam["ExamDate"], "ExamDate"
        )

        start = parse_dt(
            exam["StartDateTime"], "StartDateTime"
        )

        nominal_end = parse_dt(
            exam["EndDateTime"], "EndDateTime"
        )

        participants = students_by_exam[exam_id]

        if not participants:
            exceptions.append({
                "ExamID": exam_id,
                "ExamCode": exam_code,
                "CourseID": course_id,
                "ReasonCode": "NO_ELIGIBLE_STUDENTS",
                "UnassignedStudentCount": 0,
                "Details": "No student allocations exist for this sitting.",
            })

            reason_counts["NO_ELIGIBLE_STUDENTS"] += 1
            continue

        if course_id in rejected_courses:
            exceptions.append({
                "ExamID": exam_id,
                "ExamCode": exam_code,
                "CourseID": course_id,
                "ReasonCode": "NO_EQUIPMENT",
                "UnassignedStudentCount": len(participants),
                "Details": (
                    "Course equipment reservation rejected: "
                    + rejected_courses[course_id]
                ),
            })

            reason_counts["NO_EQUIPMENT"] += 1
            continue

        mandatory = dict(
            exam_mandatory.get(exam_id, {})
        )

        students = []

        for source in participants:
            student_id = as_int(
                source["StudentID"], "StudentID"
            )

            student_start = parse_dt(
                source["StartDateTime"],
                "Student.StartDateTime"
            )

            student_finish = student_end(
                source,
                student_start,
                parse_dt(
                    source["EndDateTime"],
                    "Student.EndDateTime"
                ),
                acc_index,
                exam_date
            )

            accommodations = accommodations_for(
                student_id, exam_date, acc_index
            )

            is_separate = "SEPARATE_ROOM" in accommodations
            is_accessible = "ACCESSIBLE_ROOM" in accommodations

            special_equipment = (
                special_by_student.get(student_id, [])
                if "SPECIAL_EQUIPMENT" in accommodations
                else []
            )

            students.append({
                "source": source,
                "sid": student_id,
                "start": student_start,
                "end": student_finish,
                "acc": accommodations,
                "separate": is_separate,
                "accessible": is_accessible,
                "special": special_equipment,
            })

        pending = sorted(
            students,
            key=lambda student: (
                0 if student["separate"] else 1,
                0 if student["accessible"] else 1,
                0 if student["special"] else 1,
                -student["end"].timestamp(),
                student["sid"],
            )
        )

        assigned_for_exam = []
        unassigned = []

        local_room_ids = set()

        def room_candidate(
            room,
            group,
            allowed_room_id=None
        ):
            room_id = as_int(room["RoomID"], "RoomID")

            if (
                room_id in local_room_ids
                and room_id != allowed_room_id
            ):
                return None

            if not as_bool(room.get("IsActive")):
                return None

            capacity = effective_capacity(
                data, room_id, exam_date
            )

            if capacity <= 0 or len(group) > capacity:
                return None

            group_start = min(
                student["start"] for student in group
            )

            group_end = max(
                student["end"] for student in group
            )

            if is_closed(
                data, room_id, group_start, group_end
            ):
                return None

            if any(
                overlap(
                    group_start,
                    group_end,
                    booking_start,
                    booking_end
                )
                for booking_start, booking_end, _ in room_bookings[room_id]
            ):
                return None

            if (
                any(student["accessible"] for student in group)
                and str(room.get("RoomType", "")).upper()
                != "ACCESSIBLE"
            ):
                return None

            available = effective_room_equipment(
                data, room_id, exam_date
            )

            required = defaultdict(int, mandatory)

            for student in group:
                for item in student["special"]:
                    required[item["EquipmentID"]] += item["Quantity"]

            for equipment_id, quantity in required.items():
                if available.get(equipment_id, 0) < quantity:
                    return None

            return (
                capacity,
                group_start,
                group_end,
                required
            )

        # -----------------------------------------------------
        # Separate-room students: one student per room.
        # -----------------------------------------------------
        for student in [
            item for item in pending if item["separate"]
        ]:
            candidates = []

            for room in data["rooms"]:
                result = room_candidate(room, [student])

                if result:
                    capacity = result[0]
                    room_id = as_int(room["RoomID"], "RoomID")

                    preference = specialist_room_score(
                        room,
                        exam_date,
                        result[3],
                        [student]
                    )

                    candidates.append((
                        preference,
                        capacity,
                        room_id,
                        room,
                        result
                    ))

            if not candidates:
                unassigned.append(student)
                continue

            _, _, room_id, room, result = min(
                candidates,
                key=lambda item: (
                    item[0], item[1], item[2]
                )
            )

            assigned_for_exam.append(
                (room, [student], result, "SEPARATE")
            )

            local_room_ids.add(room_id)

        # -----------------------------------------------------
        # Remaining students: best-fit room batching.
        # -----------------------------------------------------
        ordinary = [
            student
            for student in pending
            if not student["separate"]
        ]

        bins = []

        for student in ordinary:
            best = None

            # Try adding the student to an existing room group.
            for index, (room, group, _) in enumerate(bins):
                trial = group + [student]

                result = room_candidate(
                    room,
                    trial,
                    allowed_room_id=as_int(
                        room["RoomID"], "RoomID"
                    )
                )

                if result:
                    slack = result[0] - len(trial)

                    preference = specialist_room_score(
                        room,
                        exam_date,
                        result[3],
                        trial
                    )

                    score = (
                        preference,
                        slack,
                        as_int(room["RoomID"], "RoomID")
                    )

                    if best is None or score < best[0]:
                        best = (score, index, result)

            if best:
                _, index, result = best

                bins[index][1].append(student)

                bins[index] = (
                    bins[index][0],
                    bins[index][1],
                    result
                )

                continue

            # Otherwise open a new room.
            candidates = []

            for room in data["rooms"]:
                result = room_candidate(
                    room, [student]
                )

                if result:
                    capacity = result[0]

                    preference = specialist_room_score(
                        room,
                        exam_date,
                        result[3],
                        [student]
                    )

                    candidates.append((
                        preference,
                        capacity - 1,
                        as_int(room["RoomID"], "RoomID"),
                        room,
                        result
                    ))

            if candidates:
                _, _, _, room, result = min(
                    candidates,
                    key=lambda item: (
                        item[0], item[1], item[2]
                    )
                )

                bins.append((room, [student], result))

                local_room_ids.add(
                    as_int(room["RoomID"], "RoomID")
                )

            else:
                unassigned.append(student)

        assigned_for_exam.extend(
            (room, group, result, "STANDARD")
            for room, group, result in bins
        )

        # -----------------------------------------------------
        # Commit room and student allocations.
        # -----------------------------------------------------
        for room, group, result, group_type in assigned_for_exam:
            capacity, group_start, group_end, required = result

            room_id = as_int(room["RoomID"], "RoomID")

            room_alloc_id += 1

            student_ids = [
                student["sid"] for student in group
            ]

            room_allocations.append({
                "RoomAllocationID": room_alloc_id,
                "ExamID": exam_id,
                "CourseID": course_id,
                "RoomID": room_id,
                "RoomCode": room.get("RoomCode", ""),
                "GroupType": group_type,
                "StartDateTime": group_start.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "EndDateTime": group_end.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "AssignedCapacity": capacity,
                "AllocatedStudentCount": len(group),
                "EquipmentRequirementsJSON": json.dumps(
                    dict(required), sort_keys=True
                ),
                "StudentIDsJSON": json.dumps(student_ids),
            })

            room_bookings[room_id].append(
                (group_start, group_end, exam_id)
            )

            for student in group:
                source = student["source"]

                key = (
                    as_int(source["EnrollmentID"], "EnrollmentID"),
                    student["sid"],
                    exam_id
                )

                if key in allocated_student_keys:
                    raise ValueError(
                        f"Duplicate student allocation: {key}"
                    )

                allocated_student_keys.add(key)

                student_allocations.append({
                    "EnrollmentID": source["EnrollmentID"],
                    "StudentID": student["sid"],
                    "CourseID": course_id,
                    "ExamID": exam_id,
                    "RoomID": room_id,
                    "StartDateTime": student["start"].strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "StudentEffectiveEndDateTime": student["end"].strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "EffectiveDurationMinutes": int(
                        (
                            student["end"] - student["start"]
                        ).total_seconds() // 60
                    ),
                    "HasExtendedTime": str(
                        student["end"] > nominal_end
                    ).lower(),
                    "RequiresSeparateRoom": str(
                        student["separate"]
                    ).lower(),
                    "RequiresAccessibleRoom": str(
                        student["accessible"]
                    ).lower(),
                    "SpecialEquipmentJSON": json.dumps([
                        {
                            "EquipmentID": item["EquipmentID"],
                            "Quantity": item["Quantity"]
                        }
                        for item in student["special"]
                    ], sort_keys=True),
                })

        # -----------------------------------------------------
        # Record any unassigned students.
        # -----------------------------------------------------
        if unassigned:
            has_access = any(
                student["accessible"] for student in unassigned
            )

            has_separate = any(
                student["separate"] for student in unassigned
            )

            has_special = any(
                student["special"] for student in unassigned
            )

            reason = (
                "ACCOMMODATION_CONFLICT"
                if has_access or has_separate
                else (
                    "NO_EQUIPMENT"
                    if has_special or mandatory
                    else "NO_ROOM_CAPACITY"
                )
            )

            available_open = False

            latest_end = max(
                student["end"] for student in unassigned
            )

            for room in data["rooms"]:
                room_id = as_int(room["RoomID"], "RoomID")

                if (
                    as_bool(room.get("IsActive"))
                    and effective_capacity(
                        data, room_id, exam_date
                    ) > 0
                ):
                    if not is_closed(
                        data, room_id, start, latest_end
                    ):
                        available_open = True
                        break

            if not available_open:
                reason = "ROOM_CLOSED"

            if reason not in REASON_CODES:
                reason = "OTHER"

            exceptions.append({
                "ExamID": exam_id,
                "ExamCode": exam_code,
                "CourseID": course_id,
                "ReasonCode": reason,
                "UnassignedStudentCount": len(unassigned),
                "Details": (
                    f"{len(unassigned)} student(s) could not be "
                    "assigned without relaxing hard constraints."
                ),
            })

            reason_counts[reason] += 1

    report = {
        "version": "2.2.0",
        "status": (
            "COMPLETED_WITH_EXCEPTIONS"
            if exceptions else "PASSED"
        ),
        "algorithm": (
            "Fixed timetable; best-fit room batching; "
            "student-level accommodations; course-window "
            "equipment reservations; soft specialist-room protection"
        ),
        "room_selection_policy": {
            "type": "SOFT_PREFERENCE",
            "specialist_equipment_threshold": (
                "equipment available in 40% or fewer "
                "of active rooms"
            ),
            "policy": (
                "Prefer rooms without scarce equipment unless "
                "the exam requires it. Prefer LAB and ACCESSIBLE "
                "room types for matching requirements. Specialist "
                "rooms remain eligible when needed."
            ),
            "hard_constraints_unchanged": True,
        },
        "equipment_reservation_policy": {
            "scope": "shared physical inventory pool",
            "window": (
                "first course sitting start through "
                "final sitting effective end"
            ),
            "quantity": (
                "peak required quantity across the "
                "course's three sittings"
            ),
            "room_policy": (
                "Different rooms allowed between sittings; "
                "each assigned room must contain required "
                "equipment locally."
            ),
            "release": "after reservation end",
        },
        "counts": {
            "timetable_exams": len(data["timetable"]),
            "student_timetable_allocations": len(data["students"]),
            "rooms": len(data["rooms"]),
            "room_allocations": len(room_allocations),
            "student_room_allocations": len(student_allocations),
            "equipment_reservation_rows": len(reservations),
            "exceptions": len(exceptions),
            "unassigned_students": sum(
                as_int(
                    row["UnassignedStudentCount"],
                    "UnassignedStudentCount"
                )
                for row in exceptions
            ),
            "fully_allocated_exams": (
                len({
                    int(row["ExamID"])
                    for row in room_allocations
                })
                - len({
                    int(row["ExamID"])
                    for row in exceptions
                    if int(row["UnassignedStudentCount"]) > 0
                })
            ),
        },
        "exception_reason_counts": dict(reason_counts),
        "course_equipment_reservation_rejections": {
            str(key): value
            for key, value in rejected_courses.items()
        },
        "database_accessed": False,
        "database_modified": False,
        "ground_truth_accessed": False,
        "timetable_modified": False,
        "notes": [
            "Course equipment reservation is a shared-inventory hold, "
            "not a physical transfer of equipment between rooms.",
            "Room-local equipment is independently checked for "
            "every assigned room.",
            "Separate-room students are assigned one per room.",
            "Invigilator assignment is a later phase.",
            "Any exception means the affected student(s) or sitting "
            "is not fully assigned.",
        ],
    }

    return (
        room_allocations,
        student_allocations,
        reservations,
        exceptions,
        report
    )


def main():
    SCHED.mkdir(parents=True, exist_ok=True)

    data = load_inputs()

    (
        room_rows,
        student_rows,
        equipment_rows,
        exception_rows,
        report
    ) = allocate(data)

    # Write only after the full allocation calculation succeeds.
    write_csv(OUT_ROOM, room_rows, [
        "RoomAllocationID",
        "ExamID",
        "CourseID",
        "RoomID",
        "RoomCode",
        "GroupType",
        "StartDateTime",
        "EndDateTime",
        "AssignedCapacity",
        "AllocatedStudentCount",
        "EquipmentRequirementsJSON",
        "StudentIDsJSON",
    ])

    write_csv(OUT_STUDENT, student_rows, [
        "EnrollmentID",
        "StudentID",
        "CourseID",
        "ExamID",
        "RoomID",
        "StartDateTime",
        "StudentEffectiveEndDateTime",
        "EffectiveDurationMinutes",
        "HasExtendedTime",
        "RequiresSeparateRoom",
        "RequiresAccessibleRoom",
        "SpecialEquipmentJSON",
    ])

    write_csv(OUT_EQUIP, equipment_rows, [
        "CourseID",
        "EquipmentID",
        "EquipmentName",
        "ReservedQuantity",
        "ReservationStart",
        "ReservationEnd",
        "ExamIDs",
        "ReservationPolicy",
        "InventoryRoomIDs",
        "ReservationStatus",
    ])

    write_csv(OUT_EXCEPT, exception_rows, [
        "ExamID",
        "ExamCode",
        "CourseID",
        "ReasonCode",
        "UnassignedStudentCount",
        "Details",
    ])

    write_json(OUT_REPORT, report)

    print("\n" + "=" * 65)
    print("ROOM ALLOCATION SUMMARY — v2.2.0")
    print("=" * 65)

    counts = report["counts"]

    print(f"Timetable exams       : {counts['timetable_exams']:,}")
    print(
        f"Source allocations    : "
        f"{counts['student_timetable_allocations']:,}"
    )
    print(f"Rooms                 : {counts['rooms']:,}")
    print(f"Room allocations      : {counts['room_allocations']:,}")
    print(
        f"Student assignments   : "
        f"{counts['student_room_allocations']:,}"
    )
    print(
        f"Unassigned students   : "
        f"{counts['unassigned_students']:,}"
    )
    print(f"Exceptions            : {counts['exceptions']:,}")

    total = counts["student_timetable_allocations"]
    assigned = counts["student_room_allocations"]

    coverage = (
        assigned / total * 100
        if total else 0
    )

    print(f"Assignment coverage   : {coverage:.2f}%")
    print(f"Status                : {report['status']}")
    print(
        f"Exception reasons     : "
        f"{report['exception_reason_counts']}"
    )

    print("\nOutputs:")

    for path in (
        OUT_ROOM,
        OUT_STUDENT,
        OUT_EQUIP,
        OUT_EXCEPT,
        OUT_REPORT
    ):
        print(path)

    print("\nSQL Server       : NOT ACCESSED OR MODIFIED")
    print("GroundTruth      : NOT ACCESSED")
    print("Timetable        : NOT MODIFIED")
    print("Room inventory   : NOT MODIFIED")
    print("=" * 65)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(
            f"\nROOM ALLOCATOR FAILED: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr
        )
        sys.exit(1)
