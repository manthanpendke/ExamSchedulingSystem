
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
META = DATA / "metadata"
SCHED = DATA / "scheduling"

OUTPUT = SCHED / "room_allocation_preflight_v220.json"

FILES = {
    "ExamTimetable": SCHED / "ExamTimetable.csv",
    "TimetableStudentAllocation": SCHED / "TimetableStudentAllocation.csv",
    "Room": DATA / "Room.csv",
    "RoomCapacity": DATA / "RoomCapacity.csv",
    "RoomClosure": DATA / "RoomClosure.csv",
    "RoomEquipment": DATA / "RoomEquipment.csv",
    "Equipment": DATA / "Equipment.csv",
    "ExamRequirement": DATA / "ExamRequirement.csv",
    "ExamRequiredEquipment": DATA / "ExamRequiredEquipment.csv",
    "Accommodation": DATA / "Accommodation.csv",
    "StudentSpecialEquipmentRequirement": (
        META / "StudentSpecialEquipmentRequirement.csv"
    ),
}

EXPECTED_COLUMNS = {
    "ExamTimetable": {
        "ExamID", "ExamCode", "CourseID", "SittingOrdinal",
        "ExamDate", "StartDateTime", "EndDateTime",
        "EnrolledStudentCount",
    },
    "TimetableStudentAllocation": {
        "StudentID", "CourseID", "ExamID", "StartDateTime",
        "EffectiveEndDateTime", "EffectiveDurationMinutes",
    },
    "Room": {"RoomID", "RoomCode", "RoomType", "IsActive"},
    "RoomCapacity": {
        "RoomID", "Capacity", "EffectiveFrom", "EffectiveTo",
    },
    "RoomClosure": {
        "RoomID", "ClosureStart", "ClosureEnd", "ClosureStatus",
    },
    "RoomEquipment": {
        "RoomID", "EquipmentID", "Quantity",
        "EffectiveFrom", "EffectiveTo",
    },
    "Equipment": {"EquipmentID", "EquipmentName", "IsActive"},
    "ExamRequirement": {
        "ExamID", "DurationMinutes", "RequiredEquipment",
        "AccessibilityRequired",
    },
    "ExamRequiredEquipment": {
        "ExamID", "EquipmentID", "QuantityRequired", "IsMandatory",
    },
    "Accommodation": {
        "StudentID", "AccommodationType", "RequiresSeparateRoom",
        "EffectiveFrom", "EffectiveTo", "AccommodationStatus",
    },
    "StudentSpecialEquipmentRequirement": {
        "StudentID", "EquipmentID", "QuantityRequired",
    },
}


def read_csv(name: str) -> list[dict]:
    path = FILES[name]
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        rows = list(reader)

    missing = EXPECTED_COLUMNS[name] - set(reader.fieldnames)
    if missing:
        raise ValueError(
            f"{name}.csv is missing expected columns: {sorted(missing)}"
        )

    return rows


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def integer(value, default=0) -> int:
    value = clean(value)
    if not value:
        return default
    return int(float(value))


def truth(value) -> bool:
    return clean(value).lower() in {"1", "true", "yes", "y"}


def parse_datetime(value):
    value = clean(value)
    if not value:
        return None

    # Repair known malformed closure timestamps such as:
    # 2026-11-1614:30:00
    if len(value) >= 17 and value[10].isdigit():
        value = value[:10] + "T" + value[10:]

    value = value.replace(" ", "T", 1) if " " in value and "T" not in value else value
    return datetime.fromisoformat(value)


def parse_date(value):
    value = clean(value)
    if not value:
        return None
    return date.fromisoformat(value[:10])


def effective_on(row, target_date, start_col="EffectiveFrom",
                 end_col="EffectiveTo"):
    start = parse_date(row.get(start_col))
    end = parse_date(row.get(end_col))
    return (
        start is not None
        and start <= target_date
        and (end is None or target_date <= end)
    )


def active(value):
    return clean(value).upper() in {"1", "TRUE", "YES", "ACTIVE"}


def main():
    print("=" * 76)
    print("ROOM ALLOCATION PREFLIGHT AUDIT V2.2.0")
    print("=" * 76)

    data = {name: read_csv(name) for name in FILES}

    report = {
        "version": "2.2.0",
        "audit_type": "READ_ONLY_ROOM_ALLOCATION_PREFLIGHT",
        "sql_server_accessed": False,
        "files": {},
        "resource_summary": {},
        "timetable_demand": {},
        "warnings": [],
        "errors": [],
    }

    # ---------------------------------------------------------
    # 1. Actual schemas and record counts
    # ---------------------------------------------------------
    print("\n[1/7] CSV schemas and record counts")

    for name, rows in data.items():
        columns = list(rows[0].keys()) if rows else []
        report["files"][name] = {
            "path": str(FILES[name]),
            "rows": len(rows),
            "columns": columns,
        }
        print(f"\n{name}: {len(rows):,} rows")
        print("  Columns:", ", ".join(columns))

    # ---------------------------------------------------------
    # 2. Resource inventory
    # ---------------------------------------------------------
    print("\n[2/7] Room and equipment inventory")

    rooms = data["Room"]
    capacities = data["RoomCapacity"]
    room_equipment = data["RoomEquipment"]
    equipment = data["Equipment"]

    room_by_id = {
        integer(r["RoomID"]): r for r in rooms
    }
    equipment_by_id = {
        integer(r["EquipmentID"]): r for r in equipment
    }

    report["resource_summary"]["room_types"] = dict(
        Counter(clean(r["RoomType"]) for r in rooms)
    )
    report["resource_summary"]["active_rooms"] = sum(
        active(r["IsActive"]) for r in rooms
    )
    report["resource_summary"]["equipment_types"] = {
        str(integer(r["EquipmentID"])): clean(r["EquipmentName"])
        for r in equipment
    }
    report["resource_summary"]["room_equipment_quantity"] = {
        equipment_by_id.get(eid, {}).get("EquipmentName", str(eid)): qty
        for eid, qty in Counter({
            integer(r["EquipmentID"]): 0
            for r in room_equipment
        }).items()
    }

    equipment_totals = Counter()
    for row in room_equipment:
        equipment_totals[integer(row["EquipmentID"])] += integer(
            row["Quantity"]
        )

    report["resource_summary"]["equipment_units"] = {
        equipment_by_id.get(eid, {}).get("EquipmentName", str(eid)): qty
        for eid, qty in equipment_totals.items()
    }

    capacity_values = Counter(integer(r["Capacity"]) for r in capacities)
    report["resource_summary"]["capacity_distribution"] = {
        str(k): v for k, v in sorted(capacity_values.items())
    }

    print("Room types:", report["resource_summary"]["room_types"])
    print("Active rooms:", report["resource_summary"]["active_rooms"])
    print("Capacity distribution:", dict(capacity_values))
    print("Equipment units:", dict(report["resource_summary"]["equipment_units"]))

    # ---------------------------------------------------------
    # 3. Timetable and student demand
    # ---------------------------------------------------------
    print("\n[3/7] Timetable demand")

    timetable = data["ExamTimetable"]
    allocations = data["TimetableStudentAllocation"]

    allocations_by_exam = defaultdict(list)
    for row in allocations:
        allocations_by_exam[integer(row["ExamID"])].append(row)

    accommodation_by_student = defaultdict(list)
    for row in data["Accommodation"]:
        accommodation_by_student[integer(row["StudentID"])].append(row)

    special_by_student = defaultdict(list)
    for row in data["StudentSpecialEquipmentRequirement"]:
        special_by_student[integer(row["StudentID"])].append(row)

    exam_requirements = {
        integer(r["ExamID"]): r for r in data["ExamRequirement"]
    }

    normalized_equipment_by_exam = defaultdict(list)
    for row in data["ExamRequiredEquipment"]:
        normalized_equipment_by_exam[integer(row["ExamID"])].append(row)

    slot_summary = defaultdict(lambda: {
        "sittings": 0,
        "students": 0,
        "accessible_students": 0,
        "separate_room_students": 0,
        "special_equipment_students": 0,
        "special_equipment_units": Counter(),
        "mandatory_exam_equipment": Counter(),
    })

    accommodation_counts = Counter()
    special_equipment_counts = Counter()
    invalid_student_references = []

    for exam in timetable:
        exam_id = integer(exam["ExamID"])
        exam_date = parse_date(exam["ExamDate"])
        slot_key = (
            clean(exam["ExamDate"]),
            integer(exam.get("DayIndex")),
            integer(exam.get("SlotNumber")),
        )

        bucket = slot_summary[slot_key]
        bucket["sittings"] += 1

        exam_students = allocations_by_exam.get(exam_id, [])
        bucket["students"] += len(exam_students)

        for allocation in exam_students:
            sid = integer(allocation["StudentID"])
            active_types = set()

            for accommodation in accommodation_by_student.get(sid, []):
                if (
                    clean(accommodation["AccommodationStatus"]).upper()
                    != "ACTIVE"
                ):
                    continue
                if not effective_on(accommodation, exam_date):
                    continue

                kind = clean(accommodation["AccommodationType"]).upper()
                active_types.add(kind)
                accommodation_counts[kind] += 1

                if kind == "ACCESSIBLE_ROOM":
                    bucket["accessible_students"] += 1

                if (
                    kind == "SEPARATE_ROOM"
                    or truth(accommodation["RequiresSeparateRoom"])
                ):
                    bucket["separate_room_students"] += 1

            special_requirements = special_by_student.get(sid, [])
            if special_requirements:
                bucket["special_equipment_students"] += 1

            for special in special_requirements:
                eid = integer(special["EquipmentID"])
                qty = integer(special["QuantityRequired"])
                bucket["special_equipment_units"][eid] += qty
                special_equipment_counts[eid] += qty

        requirement = exam_requirements.get(exam_id)
        if requirement is None:
            report["errors"].append(
                f"Exam {exam_id} has no ExamRequirement record."
            )
        else:
            for item in normalized_equipment_by_exam.get(exam_id, []):
                if truth(item["IsMandatory"]):
                    eid = integer(item["EquipmentID"])
                    qty = integer(item["QuantityRequired"])
                    bucket["mandatory_exam_equipment"][eid] += qty

    report["timetable_demand"] = {
        "exam_sittings": len(timetable),
        "student_allocations": len(allocations),
        "unique_students": len({
            integer(r["StudentID"]) for r in allocations
        }),
        "occupied_slots": len(slot_summary),
        "accommodation_counts_seen_in_allocations": dict(
            accommodation_counts
        ),
        "special_equipment_units_seen_in_allocations": {
            equipment_by_id.get(eid, {}).get("EquipmentName", str(eid)): qty
            for eid, qty in special_equipment_counts.items()
        },
        "slot_demand": [],
    }

    for slot_key, bucket in sorted(slot_summary.items()):
        report["timetable_demand"]["slot_demand"].append({
            "exam_date": slot_key[0],
            "day_index": slot_key[1],
            "slot_number": slot_key[2],
            "sittings": bucket["sittings"],
            "students": bucket["students"],
            "accessible_students": bucket["accessible_students"],
            "separate_room_students": bucket["separate_room_students"],
            "special_equipment_students": bucket["special_equipment_students"],
            "special_equipment_units": {
                equipment_by_id.get(eid, {}).get("EquipmentName", str(eid)): qty
                for eid, qty in bucket["special_equipment_units"].items()
            },
            "mandatory_exam_equipment": {
                equipment_by_id.get(eid, {}).get("EquipmentName", str(eid)): qty
                for eid, qty in bucket["mandatory_exam_equipment"].items()
            },
        })

    # ---------------------------------------------------------
    # 4. Effective room capacity and equipment coverage
    # ---------------------------------------------------------
    print("\n[4/7] Effective room resource coverage")

    dates = sorted({
        parse_date(r["ExamDate"]) for r in timetable
    })

    coverage = {}
    for target_date in dates:
        date_key = target_date.isoformat()
        valid_capacity_rooms = set()
        valid_accessible_rooms = set()
        valid_room_equipment = defaultdict(set)

        for room_id, room in room_by_id.items():
            if not active(room["IsActive"]):
                continue

            cap_rows = [
                r for r in capacities
                if integer(r["RoomID"]) == room_id
                and effective_on(r, target_date)
            ]
            if len(cap_rows) == 1 and integer(cap_rows[0]["Capacity"]) > 0:
                valid_capacity_rooms.add(room_id)
                if clean(room["RoomType"]).upper() == "ACCESSIBLE":
                    valid_accessible_rooms.add(room_id)

        for row in room_equipment:
            room_id = integer(row["RoomID"])
            eid = integer(row["EquipmentID"])
            if (
                room_id in valid_capacity_rooms
                and effective_on(row, target_date)
                and integer(row["Quantity"]) > 0
                and active(equipment_by_id.get(eid, {}).get("IsActive"))
            ):
                valid_room_equipment[eid].add(room_id)

        coverage[date_key] = {
            "rooms_with_valid_capacity": len(valid_capacity_rooms),
            "accessible_rooms_with_valid_capacity": len(valid_accessible_rooms),
            "rooms_by_equipment": {
                equipment_by_id.get(eid, {}).get("EquipmentName", str(eid)): len(ids)
                for eid, ids in valid_room_equipment.items()
            },
        }

    report["resource_summary"]["effective_daily_coverage"] = coverage
    print(json.dumps(coverage, indent=2))

    # ---------------------------------------------------------
    # 5. Closures and date parsing
    # ---------------------------------------------------------
    print("\n[5/7] Room closure inspection")

    closure_summary = Counter()
    malformed_closures = []

    for row in data["RoomClosure"]:
        status = clean(row["ClosureStatus"]).upper()
        closure_summary[status] += 1

        try:
            start = parse_datetime(row["ClosureStart"])
            end = parse_datetime(row["ClosureEnd"])
            if start is None or end is None or end <= start:
                malformed_closures.append({
                    "RoomID": row["RoomID"],
                    "ClosureStart": row["ClosureStart"],
                    "ClosureEnd": row["ClosureEnd"],
                    "issue": "Invalid closure interval",
                })
        except Exception as exc:
            malformed_closures.append({
                "RoomID": row["RoomID"],
                "ClosureStart": row["ClosureStart"],
                "ClosureEnd": row["ClosureEnd"],
                "issue": str(exc),
            })

    report["resource_summary"]["closure_status_counts"] = dict(
        closure_summary
    )
    report["resource_summary"]["malformed_closures"] = malformed_closures

    # ---------------------------------------------------------
    # 6. Data integrity checks
    # ---------------------------------------------------------
    print("\n[6/7] Data integrity checks")

    def duplicate_count(rows, key):
        values = [clean(r[key]) for r in rows]
        return len(values) - len(set(values))

    duplicate_checks = {
        "Room.RoomID": duplicate_count(rooms, "RoomID"),
        "Equipment.EquipmentID": duplicate_count(equipment, "EquipmentID"),
        "ExamTimetable.ExamID": duplicate_count(timetable, "ExamID"),
    }

    report["resource_summary"]["duplicate_primary_key_counts"] = (
        duplicate_checks
    )

    for label, count in duplicate_checks.items():
        if count:
            report["errors"].append(
                f"{label} contains {count} duplicate key(s)."
            )

    room_ids = set(room_by_id)
    for row in room_equipment:
        if integer(row["RoomID"]) not in room_ids:
            report["errors"].append(
                f"RoomEquipment references unknown RoomID {row['RoomID']}."
            )

    for row in room_equipment:
        if integer(row["EquipmentID"]) not in equipment_by_id:
            report["errors"].append(
                "RoomEquipment references unknown EquipmentID "
                f"{row['EquipmentID']}."
            )

    for row in data["StudentSpecialEquipmentRequirement"]:
        if integer(row["EquipmentID"]) not in equipment_by_id:
            report["errors"].append(
                "Student special-equipment requirement references unknown "
                f"EquipmentID {row['EquipmentID']}."
            )

    for exam in timetable:
        exam_id = integer(exam["ExamID"])
        expected = integer(exam["EnrolledStudentCount"])
        actual = len(allocations_by_exam.get(exam_id, []))
        if expected != actual:
            report["errors"].append(
                f"Exam {exam_id}: timetable count {expected}, "
                f"allocation count {actual}."
            )

    if malformed_closures:
        report["warnings"].append(
            f"{len(malformed_closures)} room closure interval(s) "
            "need manual review."
        )

    # ---------------------------------------------------------
    # 7. Final report
    # ---------------------------------------------------------
    print("\n[7/7] Writing audit report")

    report["status"] = (
        "ERRORS_FOUND" if report["errors"] else "PREFLIGHT_COMPLETE"
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )

    print("\n" + "=" * 76)
    print("ROOM ALLOCATION PREFLIGHT COMPLETE")
    print("=" * 76)
    print("Files inspected          :", len(data))
    print("Room records             :", len(rooms))
    print("Timetable sittings       :", len(timetable))
    print("Student allocations      :", len(allocations))
    print("Occupied slots           :", len(slot_summary))
    print("Duplicate key errors     :", sum(duplicate_checks.values()))
    print("Malformed closures       :", len(malformed_closures))
    print("Errors                   :", len(report["errors"]))
    print("Warnings                 :", len(report["warnings"]))
    print("SQL Server                : NOT ACCESSED")
    print("GroundTruth               : NOT ACCESSED")
    print("Report                   :", OUTPUT)

    if report["errors"]:
        print("\nERROR DETAILS:")
        for error in report["errors"][:30]:
            print(" -", error)

    if report["warnings"]:
        print("\nWARNINGS:")
        for warning in report["warnings"]:
            print(" -", warning)


if __name__ == "__main__":
    main()
