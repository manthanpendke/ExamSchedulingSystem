
import csv
import json
import math
import shutil
import os
from pathlib import Path
from collections import defaultdict
from datetime import date, datetime, time

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
META = DATA / "metadata"
SCHED = DATA / "scheduling"

EXAM_DATE = date(2026, 11, 21)
DAY_START = datetime.combine(EXAM_DATE, time(8, 0))
DAY_END = datetime.combine(EXAM_DATE, time(17, 30))

TARGET_MIN_ACCESSIBLE_ROOMS = 22
MIN_CONVERTED_ROOM_CAPACITY = 30
ACCESSIBLE_EQUIPMENT_ID = 4
COMPUTER_EQUIPMENT_ID = 1

REPORT = SCHED / "accessible_room_augmentation_report_v220.json"


def locate(name):
    for folder in (DATA, META, SCHED):
        path = folder / name
        if path.exists():
            return path
    raise FileNotFoundError(f"Cannot locate {name}")


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv_temp(path, rows, fields):
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=fields, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)
    return temp


def parse_date(value):
    if not value:
        return None
    return date.fromisoformat(value.strip()[:10])


def parse_dt(value):
    if not value:
        return None

    value = value.strip()

    # Handles values such as 2026-11-1614:30:00.
    if len(value) >= 19 and value[10] != " ":
        value = value[:10] + " " + value[10:]

    return datetime.fromisoformat(value)


def active_on(row, day):
    start = parse_date(row.get("EffectiveFrom"))
    end = parse_date(row.get("EffectiveTo"))

    return (
        (start is None or start <= day)
        and (end is None or day <= end)
    )


def truth(value):
    return str(value).strip().lower() in (
        "1", "true", "yes", "y"
    )


def room_is_closed(room_id, closures):
    for row in closures:
        if int(row["RoomID"]) != room_id:
            continue

        if row.get("ClosureStatus", "").strip().upper() != "ACTIVE":
            continue

        start = parse_dt(row["ClosureStart"])
        end = parse_dt(row["ClosureEnd"])

        if start and end and DAY_START < end and start < DAY_END:
            return True

    return False


def capacity_for(room_id, capacities):
    values = []

    for row in capacities:
        if int(row["RoomID"]) != room_id:
            continue

        if active_on(row, EXAM_DATE):
            values.append(int(row["Capacity"]))

    return max(values) if values else 0


def equipment_quantity(room_id, equipment_id, room_equipment):
    total = 0

    for row in room_equipment:
        if (
            int(row["RoomID"]) == room_id
            and int(row["EquipmentID"]) == equipment_id
            and active_on(row, EXAM_DATE)
        ):
            total += int(row["Quantity"])

    return total


def equipment_inventory(equipment_id, rooms, room_equipment, closures):
    total = 0

    for room in rooms:
        room_id = int(room["RoomID"])

        if not truth(room["IsActive"]):
            continue

        if capacity_for(room_id, capacities_global) <= 0:
            continue

        if room_is_closed(room_id, closures):
            continue

        total += equipment_quantity(
            room_id, equipment_id, room_equipment
        )

    return total


def active_room_capacity(room_id, capacities):
    return capacity_for(room_id, capacities)


def add_equipment_units(
    room_id, equipment_id, quantity,
    room_equipment, fields, next_id
):
    if quantity <= 0:
        return next_id

    active_rows = [
        row for row in room_equipment
        if (
            int(row["RoomID"]) == room_id
            and int(row["EquipmentID"]) == equipment_id
            and active_on(row, EXAM_DATE)
        )
    ]

    if active_rows:
        # Add to one existing effective-dated record.
        active_rows[0]["Quantity"] = str(
            int(active_rows[0]["Quantity"]) + quantity
        )
        return next_id

    new_row = {field: "" for field in fields}
    new_row.update({
        "RoomEquipmentID": str(next_id),
        "RoomID": str(room_id),
        "EquipmentID": str(equipment_id),
        "Quantity": str(quantity),
        "EffectiveFrom": "2026-01-01",
        "EffectiveTo": "",
    })

    if "CreatedAt" in new_row:
        new_row["CreatedAt"] = "2026-11-09 00:00:00"

    room_equipment.append(new_row)
    return next_id + 1


def main():
    global capacities_global

    print("=" * 78)
    print("V2.2.0 ACCESSIBLE ROOM INVENTORY AUGMENTATION")
    print("=" * 78)

    room_path = locate("Room.csv")
    capacity_path = locate("RoomCapacity.csv")
    closure_path = locate("RoomClosure.csv")
    equipment_path = locate("Equipment.csv")
    room_equipment_path = locate("RoomEquipment.csv")
    accommodation_path = locate("Accommodation.csv")
    special_path = locate("StudentSpecialEquipmentRequirement.csv")
    timetable_path = locate("ExamTimetable.csv")
    allocation_path = locate("TimetableStudentAllocation.csv")
    wave_plan_path = locate("optional_wave_plan_preview.csv")

    rooms = read_csv(room_path)
    capacities_global = read_csv(capacity_path)
    closures = read_csv(closure_path)
    equipment = read_csv(equipment_path)
    room_equipment = read_csv(room_equipment_path)
    accommodations = read_csv(accommodation_path)
    special_requirements = read_csv(special_path)
    timetable = read_csv(timetable_path)
    allocations = read_csv(allocation_path)
    wave_plan = read_csv(wave_plan_path)

    errors = []
    warnings = []

    # ---------------------------------------------------------
    # 1. Validate the two-wave optional course plan.
    # ---------------------------------------------------------
    course_wave = {}

    for row in wave_plan:
        course_id = int(row["CourseID"])
        wave = row["Period"].strip().upper()

        if wave not in ("MORNING", "AFTERNOON"):
            errors.append(
                f"Invalid wave {wave} for course {course_id}"
            )
            continue

        if course_id in course_wave:
            errors.append(
                f"Optional course {course_id} appears more than once"
            )
        else:
            course_wave[course_id] = wave

    morning_count = sum(
        wave == "MORNING" for wave in course_wave.values()
    )
    afternoon_count = sum(
        wave == "AFTERNOON" for wave in course_wave.values()
    )

    if len(course_wave) != 75:
        errors.append(
            f"Expected 75 optional courses in wave plan; "
            f"found {len(course_wave)}"
        )

    if morning_count != 38 or afternoon_count != 37:
        errors.append(
            f"Expected 38/37 course split; found "
            f"{morning_count}/{afternoon_count}"
        )

    # ---------------------------------------------------------
    # 2. Validate active equipment catalogue.
    # ---------------------------------------------------------
    equipment_by_id = {
        int(row["EquipmentID"]): row for row in equipment
    }

    for equipment_id in (
        ACCESSIBLE_EQUIPMENT_ID,
        COMPUTER_EQUIPMENT_ID
    ):
        item = equipment_by_id.get(equipment_id)

        if not item:
            errors.append(
                f"EquipmentID {equipment_id} is missing"
            )
        elif not truth(item.get("IsActive")):
            errors.append(
                f"EquipmentID {equipment_id} is inactive"
            )

    # ---------------------------------------------------------
    # 3. Build accommodation and student equipment mappings.
    # ---------------------------------------------------------
    accommodation_by_student = defaultdict(list)

    for row in accommodations:
        if row.get("AccommodationStatus", "").upper() == "ACTIVE":
            accommodation_by_student[
                int(row["StudentID"])
            ].append(row)

    special_by_student = {
        int(row["StudentID"]): int(row["EquipmentID"])
        for row in special_requirements
    }

    for row in accommodations:
        if (
            row["AccommodationType"].strip().upper()
            == "SPECIAL_EQUIPMENT"
            and row.get("AccommodationStatus", "").upper()
            == "ACTIVE"
        ):
            sid = int(row["StudentID"])
            if sid not in special_by_student:
                errors.append(
                    f"Missing special equipment mapping for student {sid}"
                )

    # ---------------------------------------------------------
    # 4. Build exam/course/sitting relationships.
    # ---------------------------------------------------------
    optional_exams = {
        int(row["ExamID"]): row
        for row in timetable
        if row["CourseRole"].strip().upper() == "OPTIONAL"
    }

    exams_by_course = defaultdict(dict)

    for exam_id, row in optional_exams.items():
        exams_by_course[int(row["CourseID"])][
            int(row["SittingOrdinal"])
        ] = exam_id

    allocations_by_exam = defaultdict(list)

    for row in allocations:
        allocations_by_exam[int(row["ExamID"])].append(row)

    for course_id in course_wave:
        sittings = exams_by_course.get(course_id, {})

        if set(sittings) != {1, 2, 3}:
            errors.append(
                f"Optional course {course_id} does not have 3 sittings"
            )

    # ---------------------------------------------------------
    # 5. Identify usable current and candidate rooms.
    # ---------------------------------------------------------
    current_accessible = []
    candidates = []

    for room in rooms:
        room_id = int(room["RoomID"])

        if not truth(room["IsActive"]):
            continue

        cap = capacity_for(room_id, capacities_global)

        if cap < MIN_CONVERTED_ROOM_CAPACITY:
            continue

        if room_is_closed(room_id, closures):
            continue

        room_type = room["RoomType"].strip().upper()

        item = {
            "RoomID": room_id,
            "RoomCode": room.get("RoomCode", ""),
            "Capacity": cap,
            "Building": room.get("Building", ""),
            "Floor": room.get("Floor", ""),
            "CurrentEquipment4": equipment_quantity(
                room_id, ACCESSIBLE_EQUIPMENT_ID, room_equipment
            ),
        }

        if room_type == "ACCESSIBLE":
            current_accessible.append(item)

        elif room_type == "STANDARD":
            candidates.append(item)

    candidates.sort(
        key=lambda r: (-r["Capacity"], r["RoomID"])
    )

    # ---------------------------------------------------------
    # 6. Calculate course-level reservation demand.
    #
    # The same course's room/equipment configuration is reserved
    # across all three sittings. Therefore, take the maximum
    # simultaneous requirement across its three sittings, then
    # sum across courses running in the same wave.
    # ---------------------------------------------------------
    max_accessible_capacity = max(
        [r["Capacity"] for r in current_accessible + candidates],
        default=0
    )

    if max_accessible_capacity <= 0:
        errors.append("No usable accessible-room capacity found")

    course_accessible_demand = {}
    course_equipment_demand = {}

    peak_accessible_students = {
        "MORNING": [0, 0, 0],
        "AFTERNOON": [0, 0, 0],
    }

    for course_id, wave in course_wave.items():
        accessible_need_by_sitting = []
        equipment_need_by_sitting = {
            1: [],
            4: [],
        }

        for ordinal in (1, 2, 3):
            exam_id = exams_by_course.get(
                course_id, {}
            ).get(ordinal)

            if exam_id is None:
                continue

            students = allocations_by_exam.get(exam_id, [])

            separate_ids = set()
            accessible_ids = set()
            special_counts = defaultdict(int)

            for allocation in students:
                sid = int(allocation["StudentID"])

                for acc in accommodation_by_student.get(sid, []):
                    if not active_on(acc, EXAM_DATE):
                        continue

                    kind = acc["AccommodationType"].strip().upper()

                    if (
                        kind == "SEPARATE_ROOM"
                        or truth(acc.get("RequiresSeparateRoom"))
                    ):
                        separate_ids.add(sid)

                    if kind == "ACCESSIBLE_ROOM":
                        accessible_ids.add(sid)

                    if kind == "SPECIAL_EQUIPMENT":
                        eq_id = special_by_student.get(sid)

                        if eq_id not in (1, 4):
                            errors.append(
                                f"Unsupported equipment mapping for student {sid}"
                            )
                        else:
                            special_counts[eq_id] += 1

            accessible_separate = len(
                accessible_ids.intersection(separate_ids)
            )
            accessible_shared = len(
                accessible_ids - separate_ids
            )

            accessible_rooms_this_sitting = (
                accessible_separate
                + (
                    math.ceil(
                        accessible_shared / max_accessible_capacity
                    )
                    if accessible_shared else 0
                )
            )

            accessible_need_by_sitting.append(
                accessible_rooms_this_sitting
            )

            peak_accessible_students[wave][ordinal - 1] += len(
                accessible_ids
            )

            for equipment_id in (1, 4):
                equipment_need_by_sitting[equipment_id].append(
                    special_counts[equipment_id]
                )

        course_accessible_demand[course_id] = max(
            accessible_need_by_sitting, default=0
        )

        course_equipment_demand[course_id] = {
            equipment_id: max(values, default=0)
            for equipment_id, values
            in equipment_need_by_sitting.items()
        }

    wave_accessible_demand = {
        wave: sum(
            course_accessible_demand[cid]
            for cid in course_wave
            if course_wave[cid] == wave
        )
        for wave in ("MORNING", "AFTERNOON")
    }

    wave_equipment_demand = {}

    for wave in ("MORNING", "AFTERNOON"):
        wave_equipment_demand[wave] = {}

        for equipment_id in (1, 4):
            wave_equipment_demand[wave][equipment_id] = sum(
                course_equipment_demand[cid][equipment_id]
                for cid in course_wave
                if course_wave[cid] == wave
            )

    max_accessible_room_demand = max(
        wave_accessible_demand.values(), default=0
    )

    target_accessible_count = max(
        TARGET_MIN_ACCESSIBLE_ROOMS,
        max_accessible_room_demand
    )

    peak_accessible_students_by_wave = {
        wave: max(values, default=0)
        for wave, values in peak_accessible_students.items()
    }

    peak_accessible_students = max(
        peak_accessible_students_by_wave.values(),
        default=0
    )

    # ---------------------------------------------------------
    # 7. Select rooms to convert.
    # ---------------------------------------------------------
    selected_candidates = list(current_accessible)
    remaining = list(candidates)

    while (
        len(selected_candidates) < target_accessible_count
        or sum(r["Capacity"] for r in selected_candidates)
        < peak_accessible_students
    ):
        if not remaining:
            errors.append(
                "Insufficient suitable standard rooms to reach "
                "the required accessible-room count and capacity"
            )
            break

        selected_candidates.append(remaining.pop(0))

    converted_ids = {
        r["RoomID"] for r in selected_candidates
        if r["RoomID"] not in {
            x["RoomID"] for x in current_accessible
        }
    }

    accessible_room_count_after = len(selected_candidates)
    accessible_capacity_after = sum(
        r["Capacity"] for r in selected_candidates
    )

    # ---------------------------------------------------------
    # 8. Check total equipment inventory.
    # ---------------------------------------------------------
    active_room_ids = {
        int(room["RoomID"])
        for room in rooms
        if (
            truth(room["IsActive"])
            and capacity_for(
                int(room["RoomID"]), capacities_global
            ) > 0
            and not room_is_closed(int(room["RoomID"]), closures)
        )
    }

    current_equipment_units = {}

    for equipment_id in (1, 4):
        current_equipment_units[equipment_id] = sum(
            equipment_quantity(
                room_id, equipment_id, room_equipment
            )
            for room_id in active_room_ids
        )

    required_equipment_units = {
        equipment_id: max(
            wave_equipment_demand["MORNING"][equipment_id],
            wave_equipment_demand["AFTERNOON"][equipment_id]
        )
        for equipment_id in (1, 4)
    }

    # Accessible rooms must each have at least one accessible desk.
    required_equipment_units[4] = max(
        required_equipment_units[4],
        accessible_room_count_after
    )

    if (
        current_equipment_units[1]
        < required_equipment_units[1]
    ):
        errors.append(
            "Desktop computer inventory is insufficient: "
            f"available {current_equipment_units[1]}, "
            f"required {required_equipment_units[1]}"
        )

    # ---------------------------------------------------------
    # 9. Check accessible-room capacity for each wave.
    # ---------------------------------------------------------
    for wave in ("MORNING", "AFTERNOON"):
        demand = wave_accessible_demand[wave]

        if demand > accessible_room_count_after:
            errors.append(
                f"{wave}: accessible-room reservation demand "
                f"{demand} exceeds accessible rooms "
                f"{accessible_room_count_after}"
            )

        students = peak_accessible_students_by_wave[wave]

        if students > accessible_capacity_after:
            errors.append(
                f"{wave}: accessible student demand {students} "
                f"exceeds accessible-room capacity "
                f"{accessible_capacity_after}"
            )

    # ---------------------------------------------------------
    # 10. Build planned Room and RoomEquipment updates.
    # ---------------------------------------------------------
    planned_rooms = [dict(r) for r in rooms]
    planned_equipment = [dict(r) for r in room_equipment]

    for room in planned_rooms:
        if int(room["RoomID"]) in converted_ids:
            room["RoomType"] = "ACCESSIBLE"

    room_equipment_fields = list(room_equipment[0].keys())

    next_equipment_id = max(
        (int(r["RoomEquipmentID"]) for r in planned_equipment),
        default=0
    ) + 1

    # Ensure every usable accessible room has at least one
    # Accessible Desk (EquipmentID 4).
    for room in selected_candidates:
        rid = room["RoomID"]

        current = equipment_quantity(
            rid, ACCESSIBLE_EQUIPMENT_ID, planned_equipment
        )

        if current < 1:
            next_equipment_id = add_equipment_units(
                rid,
                ACCESSIBLE_EQUIPMENT_ID,
                1 - current,
                planned_equipment,
                room_equipment_fields,
                next_equipment_id
            )

    # Recalculate equipment 4 inventory after one desk per room.
    planned_equipment_units_4 = sum(
        equipment_quantity(
            room_id, ACCESSIBLE_EQUIPMENT_ID, planned_equipment
        )
        for room_id in active_room_ids
    )

    extra_desk_units = max(
        0,
        required_equipment_units[4] - planned_equipment_units_4
    )

    # Place any additional desks in the highest-capacity
    # accessible rooms. Quantity remains explicitly recorded.
    if extra_desk_units:
        target_room = max(
            selected_candidates,
            key=lambda r: (r["Capacity"], -r["RoomID"])
        )

        next_equipment_id = add_equipment_units(
            target_room["RoomID"],
            ACCESSIBLE_EQUIPMENT_ID,
            extra_desk_units,
            planned_equipment,
            room_equipment_fields,
            next_equipment_id
        )

    # ---------------------------------------------------------
    # 11. Validate the proposed post-change inventory.
    # ---------------------------------------------------------
    planned_room_by_id = {
        int(r["RoomID"]): r for r in planned_rooms
    }

    usable_accessible_after = []

    for room in planned_rooms:
        rid = int(room["RoomID"])

        if (
            room["RoomType"].strip().upper() == "ACCESSIBLE"
            and truth(room["IsActive"])
            and capacity_for(rid, capacities_global) > 0
            and not room_is_closed(rid, closures)
        ):
            usable_accessible_after.append(rid)

    equipment_units_after = {
        equipment_id: sum(
            equipment_quantity(
                rid, equipment_id, planned_equipment
            )
            for rid in active_room_ids
        )
        for equipment_id in (1, 4)
    }

    if len(usable_accessible_after) < TARGET_MIN_ACCESSIBLE_ROOMS:
        errors.append(
            "Post-change accessible-room count is below 22"
        )

    if (
        equipment_units_after[4]
        < required_equipment_units[4]
    ):
        errors.append(
            "Post-change Accessible Desk inventory is insufficient"
        )

    for rid in usable_accessible_after:
        if equipment_quantity(
            rid, ACCESSIBLE_EQUIPMENT_ID, planned_equipment
        ) < 1:
            errors.append(
                f"Accessible room {rid} has no active Accessible Desk"
            )

    report = {
        "Version": "2.2.0",
        "Operation": "Synthetic accessible-room augmentation",
        "ExamDate": EXAM_DATE.isoformat(),
        "WavePlan": {
            "MorningCourses": morning_count,
            "AfternoonCourses": afternoon_count,
        },
        "AccessibleRooms": {
            "CurrentUsable": len(current_accessible),
            "RequiredForCourseReservation": max_accessible_room_demand,
            "MinimumTarget": TARGET_MIN_ACCESSIBLE_ROOMS,
            "PlannedAfter": len(usable_accessible_after),
            "ConvertedRoomIDs": sorted(converted_ids),
            "AccessibleCapacityAfter": accessible_capacity_after,
            "PeakAccessibleStudents": peak_accessible_students,
        },
        "CourseLevelAccessibleDemandByWave": wave_accessible_demand,
        "PeakAccessibleStudentsByWave": peak_accessible_students_by_wave,
        "Equipment": {
            "CurrentUnits": current_equipment_units,
            "RequiredUnits": required_equipment_units,
            "PlannedUnitsAfter": equipment_units_after,
            "EquipmentNames": {
                "1": "Desktop Computer",
                "4": "Accessible Desk",
            },
        },
        "Errors": errors,
        "Warnings": warnings,
        "Status": "PASSED" if not errors else "FAILED",
        "FilesModified": [],
        "SQLServer": "NOT ACCESSED OR MODIFIED",
    }

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8"
    )

    print("\n" + "=" * 78)
    print("ACCESSIBLE ROOM AUGMENTATION PREFLIGHT")
    print("=" * 78)
    print(f"Current usable accessible rooms : {len(current_accessible)}")
    print(f"Course-level reservation demand : {max_accessible_room_demand}")
    print(f"Required target                 : {target_accessible_count}")
    print(f"Planned accessible rooms        : {len(usable_accessible_after)}")
    print(f"Converted standard rooms        : {len(converted_ids)}")
    print(f"Accessible capacity             : {accessible_capacity_after}")
    print(f"Peak accessible students        : {peak_accessible_students}")

    print("\nEquipment inventory:")
    for equipment_id, name in (
        (1, "Desktop Computer"),
        (4, "Accessible Desk"),
    ):
        print(
            f"  {name}: current={current_equipment_units[equipment_id]}, "
            f"required={required_equipment_units[equipment_id]}, "
            f"planned={equipment_units_after[equipment_id]}"
        )

    if errors:
        print("\nPREFLIGHT FAILED — NO SOURCE FILES MODIFIED")
        for error in errors:
            print("  ERROR:", error)

        print(f"\nReport: {REPORT}")
        print("SQL Server: NOT ACCESSED OR MODIFIED")
        return

    # ---------------------------------------------------------
    # 12. Create backups and commit both CSV files.
    # ---------------------------------------------------------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    room_backup = room_path.with_name(
        room_path.stem + f".backup_{timestamp}" + room_path.suffix
    )
    equipment_backup = room_equipment_path.with_name(
        room_equipment_path.stem
        + f".backup_{timestamp}"
        + room_equipment_path.suffix
    )

    room_temp = write_csv_temp(
        room_path, planned_rooms, list(rooms[0].keys())
    )
    equipment_temp = write_csv_temp(
        room_equipment_path,
        planned_equipment,
        room_equipment_fields
    )

    shutil.copy2(room_path, room_backup)
    shutil.copy2(room_equipment_path, equipment_backup)

    try:
        os.replace(room_temp, room_path)
        os.replace(equipment_temp, room_equipment_path)

    except Exception:
        # Restore both originals if either replacement fails.
        shutil.copy2(room_backup, room_path)
        shutil.copy2(equipment_backup, room_equipment_path)

        if room_temp.exists():
            room_temp.unlink()

        if equipment_temp.exists():
            equipment_temp.unlink()

        raise

    report["Status"] = "PASSED"
    report["FilesModified"] = [
        str(room_path),
        str(room_equipment_path),
    ]
    report["Backups"] = [
        str(room_backup),
        str(equipment_backup),
    ]

    REPORT.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8"
    )

    print("\n" + "=" * 78)
    print("ACCESSIBLE ROOM AUGMENTATION COMPLETED")
    print("=" * 78)
    print(f"Accessible rooms after : {len(usable_accessible_after)}")
    print(f"Rooms converted        : {len(converted_ids)}")
    print(f"Accessible desks after : {equipment_units_after[4]}")
    print(f"Room backup            : {room_backup}")
    print(f"Equipment backup       : {equipment_backup}")
    print(f"Report                 : {REPORT}")
    print("Timetable              : NOT MODIFIED")
    print("Student allocations    : NOT MODIFIED")
    print("SQL Server             : NOT ACCESSED OR MODIFIED")


if __name__ == "__main__":
    main()
