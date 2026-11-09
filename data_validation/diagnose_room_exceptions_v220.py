
import csv
import json
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(r"E:\ExamSchedulingSystem\output_v2\full\v2.2.0")
SCHED = ROOT / "scheduling"
OUT = SCHED / "room_exception_diagnostic_v220.json"

def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def num(value, default=0):
    try:
        return float(value) if value not in ("", None) else default
    except (TypeError, ValueError):
        return default

def active_on(row, date):
    start = row.get("EffectiveFrom", "")
    end = row.get("EffectiveTo", "")
    return (not start or start[:10] <= date) and (
        not end or end[:10] >= date
    )

exceptions = read_csv(SCHED / "RoomAllocationExceptions.csv")
timetable = read_csv(SCHED / "ExamTimetable.csv")
requirements = read_csv(ROOT / "ExamRequiredEquipment.csv")
exam_requirements = read_csv(ROOT / "ExamRequirement.csv")
rooms = read_csv(ROOT / "Room.csv")
capacities = read_csv(ROOT / "RoomCapacity.csv")
room_equipment = read_csv(ROOT / "RoomEquipment.csv")
equipment = read_csv(ROOT / "Equipment.csv")
accommodations = read_csv(ROOT / "Accommodation.csv")
special = read_csv(ROOT / "metadata" / "StudentSpecialEquipmentRequirement.csv")
allocations = read_csv(SCHED / "TimetableStudentAllocation.csv")
room_allocations = read_csv(SCHED / "RoomAllocation.csv")
student_rooms = read_csv(SCHED / "RoomStudentAllocation.csv")

room_by_id = {r["RoomID"]: r for r in rooms}
equipment_by_id = {r["EquipmentID"]: r for r in equipment}
exam_by_id = {r["ExamID"]: r for r in timetable}

room_eq = defaultdict(list)
for r in room_equipment:
    room_eq[r["RoomID"]].append(r)

capacity_by_room = defaultdict(list)
for r in capacities:
    capacity_by_room[r["RoomID"]].append(r)

req_by_exam = defaultdict(list)
for r in requirements:
    req_by_exam[r["ExamID"]].append(r)

exam_req_by_id = {r["ExamID"]: r for r in exam_requirements}

acc_by_student = defaultdict(list)
for r in accommodations:
    if r.get("AccommodationStatus", "").upper() == "ACTIVE":
        acc_by_student[r["StudentID"]].append(r)

special_by_student = defaultdict(list)
for r in special:
    special_by_student[r["StudentID"]].append(r)

source_by_exam = defaultdict(list)
for r in allocations:
    source_by_exam[r["ExamID"]].append(r)

assigned_by_exam = defaultdict(list)
for r in student_rooms:
    assigned_by_exam[r["ExamID"]].append(r)

room_alloc_by_exam = defaultdict(list)
for r in room_allocations:
    room_alloc_by_exam[r["ExamID"]].append(r)

exception_report = []

for ex in exceptions:
    exam_id = ex["ExamID"]
    exam = exam_by_id.get(exam_id, {})
    date = exam.get("ExamDate", "")[:10]

    demand = source_by_exam[exam_id]
    assigned = assigned_by_exam[exam_id]

    accessible = 0
    separate = 0
    special_students = 0
    special_units = Counter()

    for student in demand:
        sid = student["StudentID"]
        student_acc = acc_by_student[sid]

        if any(a.get("AccommodationType") == "ACCESSIBLE_ROOM"
               for a in student_acc):
            accessible += 1

        if any(a.get("RequiresSeparateRoom", "").lower() == "true"
               or a.get("RequiresSeparateRoom") == "1"
               for a in student_acc):
            separate += 1

        if special_by_student[sid]:
            special_students += 1
            for sr in special_by_student[sid]:
                special_units[sr["EquipmentID"]] += num(
                    sr.get("QuantityRequired")
                )

    valid_rooms = []
    for room in rooms:
        rid = room["RoomID"]
        if room.get("IsActive", "").lower() not in ("true", "1"):
            continue

        valid_capacity = [
            c for c in capacity_by_room[rid]
            if active_on(c, date)
        ]
        if not valid_capacity:
            continue

        cap = max(num(c["Capacity"]) for c in valid_capacity)

        available_equipment = {}
        for item in room_eq[rid]:
            if active_on(item, date):
                eid = item["EquipmentID"]
                available_equipment[eid] = (
                    available_equipment.get(eid, 0)
                    + num(item["Quantity"])
                )

        valid_rooms.append({
            "RoomID": rid,
            "RoomCode": room.get("RoomCode"),
            "RoomType": room.get("RoomType"),
            "Capacity": cap,
            "Equipment": available_equipment
        })

    mandatory = []
    for r in req_by_exam[exam_id]:
        eid = r["EquipmentID"]
        mandatory.append({
            "EquipmentID": eid,
            "EquipmentName": equipment_by_id.get(eid, {}).get(
                "EquipmentName"
            ),
            "QuantityRequired": num(r["QuantityRequired"]),
            "IsMandatory": r.get("IsMandatory")
        })

    equipment_room_coverage = []
    for req in mandatory:
        eid = req["EquipmentID"]
        eligible = [
            r for r in valid_rooms
            if r["Equipment"].get(eid, 0) >= req["QuantityRequired"]
        ]
        equipment_room_coverage.append({
            **req,
            "eligible_room_count": len(eligible),
            "eligible_room_ids": [r["RoomID"] for r in eligible]
        })

    special_room_coverage = {}
    for eid, units in special_units.items():
        eligible = [
            r for r in valid_rooms
            if r["Equipment"].get(eid, 0) >= units
        ]
        special_room_coverage[eid] = {
            "equipment_name": equipment_by_id.get(eid, {}).get(
                "EquipmentName"
            ),
            "required_units_across_exam": units,
            "rooms_with_at_least_that_quantity": len(eligible)
        }

    exception_report.append({
        "exam": exam,
        "exception": ex,
        "source_students": len(demand),
        "assigned_students": len(assigned),
        "accessible_students": accessible,
        "separate_room_students": separate,
        "special_equipment_students": special_students,
        "mandatory_equipment": mandatory,
        "equipment_room_coverage": equipment_room_coverage,
        "special_equipment_room_coverage": special_room_coverage,
        "valid_rooms_on_exam_date": len(valid_rooms),
        "room_allocations": room_alloc_by_exam[exam_id],
        "exam_requirement": exam_req_by_id.get(exam_id, {})
    })

result = {
    "version": "2.2.0",
    "exception_records": len(exceptions),
    "source_allocations": len(allocations),
    "assigned_student_room_rows": len(student_rooms),
    "diagnostics": exception_report
}

OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")

print(json.dumps({
    "status": "COMPLETED",
    "exception_records_inspected": len(exception_report),
    "output": str(OUT),
    "database_accessed": False,
    "database_modified": False,
    "ground_truth_accessed": False
}, indent=2))
