
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

REPORT = SCHED / "resource_feasibility_audit_v220.json"


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def integer(value, field):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {field}: {value!r}")


def parse_date(value):
    return date.fromisoformat(value)


def parse_datetime(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def active_on(row, exam_date):
    start = parse_date(row["EffectiveFrom"])
    end = parse_date(row["EffectiveTo"]) if row["EffectiveTo"] else None
    return start <= exam_date and (end is None or exam_date <= end)


def overlaps(start1, end1, start2, end2):
    return start1 < end2 and start2 < end1


def main():
    print("=" * 78)
    print("V2.2.0 RESOURCE FEASIBILITY AUDIT")
    print("=" * 78)

    timetable = read_csv(SCHED / "ExamTimetable.csv")
    allocations = read_csv(SCHED / "TimetableStudentAllocation.csv")

    rooms = read_csv(DATA / "Room.csv")
    capacities = read_csv(DATA / "RoomCapacity.csv")
    closures = read_csv(DATA / "RoomClosure.csv")
    room_equipment = read_csv(DATA / "RoomEquipment.csv")
    equipment = read_csv(DATA / "Equipment.csv")
    exam_equipment = read_csv(DATA / "ExamRequiredEquipment.csv")
    requirements = read_csv(DATA / "ExamRequirement.csv")
    accommodations = read_csv(DATA / "Accommodation.csv")
    invigilators = read_csv(DATA / "Invigilator.csv")
    availability = read_csv(DATA / "Availability.csv")
    physical_grid = read_csv(META / "PhysicalRoomGrid.csv")

    errors = []
    warnings = []

    def error(message):
        errors.append(message)

    def warning(message):
        warnings.append(message)

    print("\n[1/8] Checking room resources...")

    room_by_id = {
        integer(r["RoomID"], "RoomID"): r
        for r in rooms
    }

    capacity_by_room = defaultdict(list)
    for row in capacities:
        capacity_by_room[integer(row["RoomID"], "RoomCapacity.RoomID")].append(row)

    equipment_by_room = defaultdict(list)
    for row in room_equipment:
        equipment_by_room[
            integer(row["RoomID"], "RoomEquipment.RoomID")
        ].append(row)

    equipment_by_id = {
        integer(r["EquipmentID"], "EquipmentID"): r
        for r in equipment
    }

    closure_by_room = defaultdict(list)
    for row in closures:
        closure_by_room[
            integer(row["RoomID"], "RoomClosure.RoomID")
        ].append(row)

    for room_id in room_by_id:
        if not capacity_by_room[room_id]:
            error(f"Room {room_id} has no capacity record.")

    print("\n[2/8] Checking accommodation distribution...")

    accommodation_counts = Counter()
    active_accommodation_counts = Counter()
    accommodation_by_student = defaultdict(list)

    for row in accommodations:
        kind = row["AccommodationType"].strip().upper()
        status = row["AccommodationStatus"].strip().upper()

        accommodation_counts[kind] += 1

        student_id = integer(row["StudentID"], "Accommodation.StudentID")
        accommodation_by_student[student_id].append(row)

        if status == "ACTIVE":
            active_accommodation_counts[kind] += 1

        if kind == "EXTENDED_TIME":
            percentage = float(row["ExtensionPercentage"])

            if not 0 < percentage <= 200:
                error(
                    f"Accommodation {row['AccommodationID']} "
                    f"has invalid extension {percentage}."
                )

        if kind != "EXTENDED_TIME" and row["ExtensionPercentage"]:
            warning(
                f"Accommodation {row['AccommodationID']} has an "
                "extension percentage but is not EXTENDED_TIME."
            )

        if row["EffectiveTo"]:
            if parse_date(row["EffectiveTo"]) < parse_date(row["EffectiveFrom"]):
                error(
                    f"Accommodation {row['AccommodationID']} has "
                    "an invalid effective date range."
                )

    print("\n[3/8] Checking exam requirements and equipment...")

    requirement_by_exam = {}
    for row in requirements:
        exam_id = integer(row["ExamID"], "ExamRequirement.ExamID")

        if exam_id in requirement_by_exam:
            error(f"Duplicate ExamRequirement for exam {exam_id}.")

        requirement_by_exam[exam_id] = row

    equipment_by_exam = defaultdict(list)

    for row in exam_equipment:
        exam_id = integer(row["ExamID"], "ExamRequiredEquipment.ExamID")
        equipment_id = integer(
            row["EquipmentID"], "ExamRequiredEquipment.EquipmentID"
        )
        quantity = integer(
            row["QuantityRequired"],
            "ExamRequiredEquipment.QuantityRequired",
        )

        equipment_by_exam[exam_id].append({
            "EquipmentID": equipment_id,
            "QuantityRequired": quantity,
            "IsMandatory": row["IsMandatory"],
        })

        if equipment_id not in equipment_by_id:
            error(
                f"Exam {exam_id} references unknown equipment {equipment_id}."
            )

        if quantity <= 0:
            error(f"Exam {exam_id} has non-positive equipment quantity.")

    for row in timetable:
        exam_id = integer(row["ExamID"], "Timetable.ExamID")

        if exam_id not in requirement_by_exam:
            error(f"Exam {exam_id} has no ExamRequirement record.")

    print("\n[4/8] Checking capacity and room closures against timetable...")

    room_count_by_slot = Counter()
    available_room_count_by_slot = {}
    capacity_total_by_slot = {}

    for row in timetable:
        exam_date = parse_date(row["ExamDate"])
        start = parse_datetime(row["StartDateTime"])
        end = parse_datetime(row["EndDateTime"])

        slot_key = (row["ExamDate"], integer(row["SlotNumber"], "SlotNumber"))

        eligible_rooms = []
        available_capacity = 0

        for room_id, room in room_by_id.items():
            if str(room["IsActive"]).strip() not in ("1", "True", "true"):
                continue

            valid_capacities = [
                c for c in capacity_by_room[room_id]
                if active_on(c, exam_date)
            ]

            if not valid_capacities:
                continue

            capacity = max(
                integer(c["Capacity"], "RoomCapacity.Capacity")
                for c in valid_capacities
            )

            is_closed = False

            for closure in closure_by_room[room_id]:
                if closure["ClosureStatus"].upper() != "ACTIVE":
                    continue

                closure_start = parse_datetime(closure["ClosureStart"])
                closure_end = parse_datetime(closure["ClosureEnd"])

                if overlaps(start, end, closure_start, closure_end):
                    is_closed = True
                    break

            if not is_closed:
                eligible_rooms.append(room_id)
                available_capacity += capacity

        available_room_count_by_slot[slot_key] = len(eligible_rooms)
        capacity_total_by_slot[slot_key] = available_capacity

        room_count_by_slot[slot_key] += 1

    for slot_key, exam_count in room_count_by_slot.items():
        available_rooms = available_room_count_by_slot[slot_key]

        if exam_count > available_rooms:
            warning(
                f"{slot_key}: {exam_count} exam sittings versus "
                f"{available_rooms} rooms available before batching."
            )

    print("\n[5/8] Checking equipment availability by effective date...")

    equipment_gaps = []

    for row in timetable:
        exam_id = integer(row["ExamID"], "Timetable.ExamID")
        exam_date = parse_date(row["ExamDate"])

        for required in equipment_by_exam[exam_id]:
            equipment_id = required["EquipmentID"]
            quantity_required = required["QuantityRequired"]

            available_quantity = 0

            for room_id, records in equipment_by_room.items():
                room = room_by_id.get(room_id)

                if not room or str(room["IsActive"]) != "1":
                    continue

                for record in records:
                    if (
                        integer(record["EquipmentID"], "RoomEquipment.EquipmentID")
                        == equipment_id
                        and active_on(record, exam_date)
                    ):
                        available_quantity += integer(
                            record["Quantity"],
                            "RoomEquipment.Quantity",
                        )

            if available_quantity < quantity_required:
                equipment_gaps.append({
                    "ExamID": exam_id,
                    "EquipmentID": equipment_id,
                    "RequiredQuantityPerExam": quantity_required,
                    "AvailableInventoryQuantity": available_quantity,
                })

    if equipment_gaps:
        warning(
            f"{len(equipment_gaps)} exam/equipment combinations require "
            "review. Inventory totals alone do not prove room feasibility."
        )

    print("\n[6/8] Checking invigilator availability...")


    print("\n[6/8] Checking invigilator availability against actual exam intervals...")

    active_invigilators = {
        integer(row["InvigilatorID"], "InvigilatorID"): row
        for row in invigilators
        if row["Status"].strip().upper() == "ACTIVE"
    }

    availability_by_invigilator = defaultdict(list)

    for row in availability:
        invigilator_id = integer(
            row["InvigilatorID"], "Availability.InvigilatorID"
        )

        if invigilator_id not in active_invigilators:
            continue

        availability_by_invigilator[invigilator_id].append(row)

    def is_available_for_interval(invigilator_id, exam_start, exam_end):
        records = availability_by_invigilator[invigilator_id]

        available_intervals = []
        unavailable_intervals = []

        for record in records:
            status = record["AvailabilityStatus"].strip().upper()
            start = parse_datetime(record["AvailableFrom"])
            end = parse_datetime(record["AvailableTo"])

            if status == "UNAVAILABLE":
                unavailable_intervals.append((start, end))
            elif status == "AVAILABLE":
                available_intervals.append((start, end))

        # Any overlapping UNAVAILABLE interval disqualifies the person.
        for start, end in unavailable_intervals:
            if overlaps(exam_start, exam_end, start, end):
                return False

        # Merge AVAILABLE intervals and verify continuous coverage.
        relevant = sorted(
            (start, end)
            for start, end in available_intervals
            if overlaps(exam_start, exam_end, start, end)
        )

        cursor = exam_start

        for start, end in relevant:
            if end <= cursor:
                continue

            if start > cursor:
                return False

            cursor = max(cursor, end)

            if cursor >= exam_end:
                return True

        return False

    # Evaluate each distinct exam interval, not the entire calendar day.
    interval_groups = defaultdict(list)

    for row in timetable:
        start = parse_datetime(row["StartDateTime"])
        end = parse_datetime(row["EndDateTime"])
        key = (row["ExamDate"], start, end)
        interval_groups[key].append(row)

    invigilator_interval_summary = {}

    for exam_date, start, end in sorted(interval_groups):
        eligible_ids = [
            invigilator_id
            for invigilator_id in active_invigilators
            if is_available_for_interval(invigilator_id, start, end)
        ]

        exam_count = len(interval_groups[(exam_date, start, end)])

        key = f"{exam_date}|{start.strftime('%H:%M')}|{end.strftime('%H:%M')}"

        invigilator_interval_summary[key] = {
            "eligible_invigilators": len(eligible_ids),
            "exam_sittings": exam_count,
            "minimum_invigilators_required": exam_count,
            "lower_bound_coverage": len(eligible_ids) >= exam_count,
        }

        if len(eligible_ids) < exam_count:
            warning(
                f"{key}: only {len(eligible_ids)} invigilators cover "
                f"{exam_count} exam sittings. This is below the "
                "one-invigilator-per-sitting minimum."
            )


    print("\n[7/8] Checking physical room grid...")

    expected_grid = 100 * 6 * 6

    if len(physical_grid) != expected_grid:
        error(
            f"Expected {expected_grid} physical grid rows; "
            f"found {len(physical_grid)}."
        )

    grid_keys = {
        (
            integer(r["RoomID"], "Grid.RoomID"),
            integer(r["DayIndex"], "Grid.DayIndex"),
            integer(r["SlotNumber"], "Grid.SlotNumber"),
        )
        for r in physical_grid
    }

    if len(grid_keys) != expected_grid:
        error("Physical room grid contains duplicate room/day/slot units.")

    print("\n[8/8] Writing resource feasibility report...")

    report = {
        "version": "2.2.0",
        "status": "REVIEW_REQUIRED" if warnings or errors else "PASSED",
        "database_accessed": False,
        "database_modified": False,
        "counts": {
            "rooms": len(rooms),
            "capacity_records": len(capacities),
            "closures": len(closures),
            "room_equipment_records": len(room_equipment),
            "equipment_types": len(equipment),
            "exam_equipment_requirements": len(exam_equipment),
            "exam_requirements": len(requirements),
            "accommodations": len(accommodations),
            "invigilators": len(invigilators),
            "availability_records": len(availability),
            "physical_grid_units": len(physical_grid),
        },
        "accommodation_distribution": dict(accommodation_counts),
        "active_accommodation_distribution": dict(active_accommodation_counts),
        "invigilator_interval_summary": invigilator_interval_summary,
        "slot_room_summary": {
            f"{date_value}|{slot}": {
                "exam_sittings": room_count_by_slot[(date_value, slot)],
                "available_rooms_before_batching": available_room_count_by_slot[
                    (date_value, slot)
                ],
                "sum_of_available_room_capacity": capacity_total_by_slot[
                    (date_value, slot)
                ],
            }
            for date_value, slot in sorted(room_count_by_slot)
        },
        "equipment_gaps": equipment_gaps,
        "warnings": warnings,
        "errors": errors,
        "limitations": [
            "Room capacity is summarized, not yet allocated to individual exams.",
            "Equipment quantities are inventory totals, not proof of simultaneous room compatibility.",
            "Accommodation-to-room placement has not been performed.",
            "Extended-time room occupancy has not been simulated.",
            "Invigilator coverage has not been assigned or workload-validated.",
            "Equipment changeover between course sittings has not been modeled.",
        ],
    }

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=4), encoding="utf-8")

    print("\n" + "=" * 78)
    print("RESOURCE FEASIBILITY AUDIT RESULT")
    print("=" * 78)
    print("Status:", report["status"])
    print("Warnings:", len(warnings))
    print("Errors:", len(errors))
    print("Equipment gaps:", len(equipment_gaps))

    print("\nAccommodation distribution:")
    for key, value in sorted(accommodation_counts.items()):
        print(f"{key:25} {value:>6}")

    print("\nInvigilator coverage by exam interval:")
    for key, value in sorted(invigilator_interval_summary.items()):
        print(
            f"{key}: "
            f"{value['eligible_invigilators']} available / "
            f"{value['exam_sittings']} exam sittings"
        )
    if warnings:
        print("\nWarnings:")
        for item in warnings[:30]:
            print(" -", item)

    if errors:
        print("\nErrors:")
        for item in errors[:30]:
            print(" -", item)

    print("\nReport:")
    print(REPORT)

    print("\nSQL Server: NOT ACCESSED OR MODIFIED")

    return 1 if errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("\nRESOURCE AUDIT FAILED TO EXECUTE")
        print(f"{type(exc).__name__}: {exc}")
        raise SystemExit(1)
