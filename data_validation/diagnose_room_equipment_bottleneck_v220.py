
import csv
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
SCHED = DATA / "scheduling"

FILES = {
    "rooms": DATA / "Room.csv",
    "room_equipment": DATA / "RoomEquipment.csv",
    "equipment": DATA / "Equipment.csv",
    "room_allocations": SCHED / "RoomAllocation.csv",
    "timetable": SCHED / "ExamTimetable.csv",
    "requirements": DATA / "ExamRequiredEquipment.csv",
    "student_allocations": SCHED / "TimetableStudentAllocation.csv",
}

OUT_OCCUPANCY = SCHED / "specialist_room_occupancy_v220.csv"
OUT_INTERSECTION = SCHED / "room_equipment_type_intersection_v220.csv"


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Required input file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_dt(value):
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(f"Unsupported datetime format: {value}")


def parse_date(value):
    if not value:
        return None
    return date.fromisoformat(value.strip()[:10])


def is_active_on(row, target_date):
    start = parse_date(row.get("EffectiveFrom", ""))
    end = parse_date(row.get("EffectiveTo", ""))
    return (start is None or start <= target_date) and (
        end is None or target_date <= end
    )


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def main():
    print("Loading room equipment diagnostic inputs...")

    rooms = read_csv(FILES["rooms"])
    room_equipment = read_csv(FILES["room_equipment"])
    equipment = read_csv(FILES["equipment"])
    room_allocations = read_csv(FILES["room_allocations"])
    timetable = read_csv(FILES["timetable"])
    requirements = read_csv(FILES["requirements"])
    student_allocations = read_csv(FILES["student_allocations"])

    room_by_id = {r["RoomID"]: r for r in rooms}
    equipment_by_id = {e["EquipmentID"]: e for e in equipment}
    timetable_by_exam = {r["ExamID"]: r for r in timetable}

    # Build effective exam intervals. Extended-time student allocations
    # are included when calculating each exam's actual end time.
    exam_intervals = {}

    for exam_id, row in timetable_by_exam.items():
        start = parse_dt(row.get("StartDateTime", ""))
        end = parse_dt(row.get("EndDateTime", ""))
        if start and end:
            exam_intervals[exam_id] = [start, end]

    student_ends = defaultdict(list)
    for row in student_allocations:
        exam_id = row.get("ExamID", "")
        end = parse_dt(row.get("EffectiveEndDateTime", ""))
        start = parse_dt(row.get("StartDateTime", ""))
        if end:
            student_ends[exam_id].append(end)
        if start and exam_id not in exam_intervals:
            exam_intervals[exam_id] = [start, end or start]

    for exam_id, ends in student_ends.items():
        if exam_id in exam_intervals and ends:
            exam_intervals[exam_id][1] = max(
                exam_intervals[exam_id][1], max(ends)
            )

    # Build equipment inventory by room and equipment.
    inventory = defaultdict(int)
    inventory_rows = defaultdict(list)

    for row in room_equipment:
        room_id = row["RoomID"]
        equipment_id = row["EquipmentID"]
        inventory_rows[(room_id, equipment_id)].append(row)

    # Room allocations indexed by room.
    allocations_by_room = defaultdict(list)
    allocations_by_exam = defaultdict(list)

    for row in room_allocations:
        room_id = row["RoomID"]
        exam_id = row["ExamID"]
        start = parse_dt(row.get("StartDateTime", ""))
        end = parse_dt(row.get("EndDateTime", ""))

        if not start or not end:
            continue

        record = {
            "ExamID": exam_id,
            "CourseID": row.get("CourseID", ""),
            "RoomID": room_id,
            "RoomCode": row.get("RoomCode", ""),
            "Start": start,
            "End": end,
            "GroupType": row.get("GroupType", ""),
            "AllocatedStudentCount": row.get("AllocatedStudentCount", ""),
        }
        allocations_by_room[room_id].append(record)
        allocations_by_exam[exam_id].append(record)

    # Mandatory exam equipment requirements.
    requirements_by_exam = defaultdict(list)
    for row in requirements:
        mandatory = str(row.get("IsMandatory", "")).strip().lower()
        if mandatory not in ("1", "true", "yes"):
            continue

        requirements_by_exam[row["ExamID"]].append({
            "EquipmentID": row["EquipmentID"],
            "QuantityRequired": int(float(row.get("QuantityRequired") or 0)),
        })

    # Evaluate inventory effective dates separately for each exam date.
    def room_has_equipment(room_id, equipment_id, quantity, target_date):
        total = 0
        for item in inventory_rows.get((room_id, equipment_id), []):
            if is_active_on(item, target_date):
                total += int(float(item.get("Quantity") or 0))
        return total >= quantity, total

    occupancy_rows = []

    for exam_id, exam_requirements in requirements_by_exam.items():
        interval = exam_intervals.get(exam_id)
        timetable_row = timetable_by_exam.get(exam_id, {})

        if not interval:
            continue

        exam_start, exam_end = interval
        target_date = exam_start.date()

        for requirement in exam_requirements:
            equipment_id = requirement["EquipmentID"]
            quantity = requirement["QuantityRequired"]
            equipment_name = equipment_by_id.get(
                equipment_id, {}
            ).get("EquipmentName", "UNKNOWN")

            eligible_rooms = []
            occupied_rooms = []
            free_rooms = []

            for room_id, room in room_by_id.items():
                if str(room.get("IsActive", "")).strip().lower() not in (
                    "1", "true", "yes", "active"
                ):
                    continue

                has_equipment, available_quantity = room_has_equipment(
                    room_id, equipment_id, quantity, target_date
                )

                if not has_equipment:
                    continue

                eligible_rooms.append(room_id)

                conflicting = [
                    allocation
                    for allocation in allocations_by_room.get(room_id, [])
                    if allocation["ExamID"] != exam_id
                    and overlaps(
                        exam_start, exam_end,
                        allocation["Start"], allocation["End"]
                    )
                ]

                if conflicting:
                    occupied_rooms.append(room_id)
                    for allocation in conflicting:
                        occupancy_rows.append({
                            "ExamID": exam_id,
                            "CourseID": timetable_row.get("CourseID", ""),
                            "CourseRole": timetable_row.get("CourseRole", ""),
                            "ExamDate": target_date.isoformat(),
                            "ExamStart": exam_start.isoformat(sep=" "),
                            "ExamEnd": exam_end.isoformat(sep=" "),
                            "RequiredEquipmentID": equipment_id,
                            "RequiredEquipment": equipment_name,
                            "QuantityRequired": quantity,
                            "CandidateRoomID": room_id,
                            "CandidateRoomCode": room.get("RoomCode", ""),
                            "CandidateRoomType": room.get("RoomType", ""),
                            "CandidateRoomEquipmentQuantity": available_quantity,
                            "CandidateRoomStatus": "OCCUPIED",
                            "BlockingExamID": allocation["ExamID"],
                            "BlockingCourseID": allocation["CourseID"],
                            "BlockingStart": allocation["Start"].isoformat(sep=" "),
                            "BlockingEnd": allocation["End"].isoformat(sep=" "),
                            "BlockingGroupType": allocation["GroupType"],
                            "BlockingStudentCount": allocation["AllocatedStudentCount"],
                        })
                else:
                    free_rooms.append(room_id)
                    occupancy_rows.append({
                        "ExamID": exam_id,
                        "CourseID": timetable_row.get("CourseID", ""),
                        "CourseRole": timetable_row.get("CourseRole", ""),
                        "ExamDate": target_date.isoformat(),
                        "ExamStart": exam_start.isoformat(sep=" "),
                        "ExamEnd": exam_end.isoformat(sep=" "),
                        "RequiredEquipmentID": equipment_id,
                        "RequiredEquipment": equipment_name,
                        "QuantityRequired": quantity,
                        "CandidateRoomID": room_id,
                        "CandidateRoomCode": room.get("RoomCode", ""),
                        "CandidateRoomType": room.get("RoomType", ""),
                        "CandidateRoomEquipmentQuantity": available_quantity,
                        "CandidateRoomStatus": "FREE",
                        "BlockingExamID": "",
                        "BlockingCourseID": "",
                        "BlockingStart": "",
                        "BlockingEnd": "",
                        "BlockingGroupType": "",
                        "BlockingStudentCount": "",
                    })

            # Add a summary row even when no equipped room exists.
            occupancy_rows.append({
                "ExamID": exam_id,
                "CourseID": timetable_row.get("CourseID", ""),
                "CourseRole": timetable_row.get("CourseRole", ""),
                "ExamDate": target_date.isoformat(),
                "ExamStart": exam_start.isoformat(sep=" "),
                "ExamEnd": exam_end.isoformat(sep=" "),
                "RequiredEquipmentID": equipment_id,
                "RequiredEquipment": equipment_name,
                "QuantityRequired": quantity,
                "CandidateRoomID": "",
                "CandidateRoomCode": "",
                "CandidateRoomType": "",
                "CandidateRoomEquipmentQuantity": "",
                "CandidateRoomStatus": "SUMMARY",
                "BlockingExamID": "",
                "BlockingCourseID": "",
                "BlockingStart": "",
                "BlockingEnd": "",
                "BlockingGroupType": "",
                "BlockingStudentCount": "",
                "EligibleRoomCount": len(eligible_rooms),
                "OccupiedRoomCount": len(occupied_rooms),
                "FreeRoomCount": len(free_rooms),
            })

    # Room/equipment intersection: one row per room/equipment inventory row.
    intersection_rows = []

    for (room_id, equipment_id), rows in inventory_rows.items():
        room = room_by_id.get(room_id, {})
        equip = equipment_by_id.get(equipment_id, {})

        total_quantity = sum(
            int(float(r.get("Quantity") or 0)) for r in rows
        )

        occupied_allocations = allocations_by_room.get(room_id, [])

        intersection_rows.append({
            "RoomID": room_id,
            "RoomCode": room.get("RoomCode", ""),
            "Building": room.get("Building", ""),
            "Floor": room.get("Floor", ""),
            "RoomType": room.get("RoomType", ""),
            "RoomIsActive": room.get("IsActive", ""),
            "EquipmentID": equipment_id,
            "EquipmentName": equip.get("EquipmentName", ""),
            "EquipmentCategory": equip.get("EquipmentCategory", ""),
            "TotalRecordedQuantity": total_quantity,
            "EffectiveFromValues": ";".join(
                sorted(set(r.get("EffectiveFrom", "") for r in rows))
            ),
            "EffectiveToValues": ";".join(
                sorted(set(r.get("EffectiveTo", "") for r in rows))
            ),
            "RoomAllocationCount": len(occupied_allocations),
            "AllocatedExamIDs": ";".join(sorted(set(
                a["ExamID"] for a in occupied_allocations
            ))),
        })

    occupancy_fields = [
        "ExamID", "CourseID", "CourseRole", "ExamDate",
        "ExamStart", "ExamEnd", "RequiredEquipmentID",
        "RequiredEquipment", "QuantityRequired",
        "CandidateRoomID", "CandidateRoomCode", "CandidateRoomType",
        "CandidateRoomEquipmentQuantity", "CandidateRoomStatus",
        "BlockingExamID", "BlockingCourseID", "BlockingStart",
        "BlockingEnd", "BlockingGroupType", "BlockingStudentCount",
        "EligibleRoomCount", "OccupiedRoomCount", "FreeRoomCount",
    ]

    intersection_fields = [
        "RoomID", "RoomCode", "Building", "Floor", "RoomType",
        "RoomIsActive", "EquipmentID", "EquipmentName",
        "EquipmentCategory", "TotalRecordedQuantity",
        "EffectiveFromValues", "EffectiveToValues",
        "RoomAllocationCount", "AllocatedExamIDs",
    ]

    write_csv(OUT_OCCUPANCY, occupancy_rows, occupancy_fields)
    write_csv(OUT_INTERSECTION, intersection_rows, intersection_fields)

    summary_rows = [
        r for r in occupancy_rows if r["CandidateRoomStatus"] == "SUMMARY"
    ]

    print("\n" + "=" * 65)
    print("ROOM EQUIPMENT BOTTLENECK DIAGNOSTIC")
    print("=" * 65)
    print(f"Rooms                         : {len(rooms):,}")
    print(f"Room equipment records        : {len(room_equipment):,}")
    print(f"Room allocations examined     : {len(room_allocations):,}")
    print(f"Exam equipment requirements   : {sum(map(len, requirements_by_exam.values())):,}")
    print(f"Exam/equipment summaries      : {len(summary_rows):,}")
    print(f"Occupancy detail rows         : {len(occupancy_rows):,}")
    print("\nEquipment demand summary:")

    for row in summary_rows:
        print(
            f"Exam {row['ExamID']} | Course {row['CourseID']} | "
            f"{row['RequiredEquipment']} | "
            f"Eligible={row['EligibleRoomCount']} | "
            f"Occupied={row['OccupiedRoomCount']} | "
            f"Free={row['FreeRoomCount']}"
        )

    print("\nCreated:")
    print(OUT_OCCUPANCY)
    print(OUT_INTERSECTION)
    print("\nSQL Server      : NOT ACCESSED")
    print("GroundTruth     : NOT ACCESSED")
    print("Source datasets : NOT MODIFIED")
    print("=" * 65)


if __name__ == "__main__":
    main()

