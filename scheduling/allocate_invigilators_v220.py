import csv
import json
import os
import shutil
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter

# ============================================================
# EXAM SCHEDULING SYSTEM v2.2.0
# INVIGILATOR ALLOCATION
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
SCHED = DATA / "scheduling"

INV_FILE = DATA / "Invigilator.csv"
AVAIL_FILE = DATA / "Availability.csv"
ROOM_FILE = SCHED / "RoomAllocation.csv"

OUT_ASSIGN = SCHED / "InvigilatorAssignment.csv"
OUT_EXCEPT = SCHED / "InvigilatorAllocationExceptions.csv"
OUT_REPORT = SCHED / "invigilator_allocation_report_v220.json"

APPROVED_REASON_CODES = {"NO_INVIGILATOR"}


def read_csv(path, required):
    if not path.exists():
        raise FileNotFoundError(f"Missing input file: {path}")

    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        if not reader.fieldnames:
            raise ValueError(f"Missing CSV header: {path}")

        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(
                f"{path.name} missing columns: {sorted(missing)}"
            )

        rows = list(reader)

    if not rows:
        raise ValueError(f"Input file is empty: {path}")

    return rows


def parse_datetime(value, field):
    value = (value or "").strip()

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass

    raise ValueError(f"Invalid datetime in {field}: {value}")


def overlaps(start1, end1, start2, end2):
    # Half-open interval: adjacent duties are allowed.
    return start1 < end2 and start2 < end1


def atomic_csv(path, columns, rows):
    temp = path.with_suffix(path.suffix + ".tmp")

    with temp.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=columns,
            extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)

    os.replace(temp, path)


def atomic_json(path, payload):
    temp = path.with_suffix(path.suffix + ".tmp")

    with temp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    os.replace(temp, path)


def create_backups(paths):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backups = []

    for path in paths:
        if path.exists():
            backup = path.with_name(
                f"{path.stem}.backup_{stamp}{path.suffix}"
            )
            shutil.copy2(path, backup)
            backups.append(str(backup))

    return backups


def main():

    SCHED.mkdir(parents=True, exist_ok=True)

    print("\nLoading invigilator allocation inputs...")

    invigilators = read_csv(
        INV_FILE,
        {
            "InvigilatorID",
            "InvigilatorCode",
            "FullName",
            "MaxDailyHours",
            "Status"
        }
    )

    availability = read_csv(
        AVAIL_FILE,
        {
            "AvailabilityID",
            "InvigilatorID",
            "AvailableFrom",
            "AvailableTo",
            "AvailabilityStatus"
        }
    )

    room_allocations = read_csv(
        ROOM_FILE,
        {
            "RoomAllocationID",
            "ExamID",
            "CourseID",
            "RoomID",
            "StartDateTime",
            "EndDateTime",
            "AllocatedStudentCount"
        }
    )

    # --------------------------------------------------------
    # 1. LOAD ACTIVE INVIGILATORS
    # --------------------------------------------------------

    inv_by_id = {}

    for row in invigilators:

        iid = row["InvigilatorID"].strip()

        if not iid or iid in inv_by_id:
            raise ValueError(f"Duplicate or blank InvigilatorID: {iid}")

        if row["Status"].strip().upper() != "ACTIVE":
            continue

        try:
            max_minutes = int(
                round(float(row["MaxDailyHours"]) * 60)
            )
        except ValueError:
            raise ValueError(
                f"Invalid MaxDailyHours for invigilator {iid}"
            )

        if max_minutes <= 0:
            raise ValueError(
                f"Invalid MaxDailyHours for invigilator {iid}"
            )

        row["_max_minutes"] = max_minutes
        inv_by_id[iid] = row

    if not inv_by_id:
        raise ValueError("No ACTIVE invigilators found.")

    # --------------------------------------------------------
    # 2. LOAD AVAILABLE TIME WINDOWS
    # --------------------------------------------------------

    availability_by_inv = defaultdict(list)
    availability_ids = set()

    for row in availability:

        aid = row["AvailabilityID"].strip()

        if not aid or aid in availability_ids:
            raise ValueError(f"Duplicate or blank AvailabilityID: {aid}")

        availability_ids.add(aid)

        iid = row["InvigilatorID"].strip()

        if iid not in inv_by_id:
            continue

        if row["AvailabilityStatus"].strip().upper() != "AVAILABLE":
            continue

        start = parse_datetime(
            row["AvailableFrom"],
            "Availability.AvailableFrom"
        )

        end = parse_datetime(
            row["AvailableTo"],
            "Availability.AvailableTo"
        )

        if end <= start:
            raise ValueError(f"Invalid availability interval: {aid}")

        availability_by_inv[iid].append({
            "AvailabilityID": aid,
            "Start": start,
            "End": end
        })

    # --------------------------------------------------------
    # 3. VALIDATE AND PREPARE ROOM DUTIES
    # --------------------------------------------------------

    prepared = []
    room_ids = set()

    for row in room_allocations:

        rid = row["RoomAllocationID"].strip()

        if not rid or rid in room_ids:
            raise ValueError(f"Duplicate or blank RoomAllocationID: {rid}")

        room_ids.add(rid)

        start = parse_datetime(
            row["StartDateTime"],
            "RoomAllocation.StartDateTime"
        )

        end = parse_datetime(
            row["EndDateTime"],
            "RoomAllocation.EndDateTime"
        )

        if end <= start:
            raise ValueError(
                f"Invalid room allocation interval: {rid}"
            )

        duration = int((end - start).total_seconds() // 60)

        row["_start"] = start
        row["_end"] = end
        row["_date"] = start.date().isoformat()
        row["_minutes"] = duration

        prepared.append(row)

    # --------------------------------------------------------
    # 4. FIND INVIGILATORS AVAILABLE FOR EACH ROOM DUTY
    # --------------------------------------------------------

    eligible = {}

    for room in prepared:

        candidates = []

        for iid, person in inv_by_id.items():

            if person["_max_minutes"] < room["_minutes"]:
                continue

            for av in availability_by_inv.get(iid, []):

                if (
                    av["Start"] <= room["_start"]
                    and av["End"] >= room["_end"]
                ):
                    candidates.append((iid, av))
                    break

        eligible[room["RoomAllocationID"]] = candidates

    # Most constrained room duties first.
    # This helps avoid using scarce available staff too early.
    prepared.sort(
        key=lambda r: (
            len(eligible[r["RoomAllocationID"]]),
            r["_start"],
            -r["_minutes"],
            -int(float(r["AllocatedStudentCount"] or 0)),
            int(r["RoomAllocationID"])
            if r["RoomAllocationID"].isdigit()
            else r["RoomAllocationID"]
        )
    )

    # --------------------------------------------------------
    # 5. ALLOCATE INVIGILATORS
    # --------------------------------------------------------

    duty_by_inv_day = defaultdict(list)
    daily_minutes = defaultdict(int)
    total_minutes = defaultdict(int)
    assignment_count = Counter()

    assignments = []
    exceptions = []

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for room in prepared:

        rid = room["RoomAllocationID"]
        day = room["_date"]
        duration = room["_minutes"]

        candidates = eligible[rid]
        feasible = []

        for iid, av in candidates:

            person = inv_by_id[iid]

            # Daily maximum working hours.
            if (
                daily_minutes[(iid, day)] + duration
                > person["_max_minutes"]
            ):
                continue

            # Prevent overlapping duties.
            conflict = any(
                overlaps(
                    room["_start"],
                    room["_end"],
                    old_start,
                    old_end
                )
                for old_start, old_end in duty_by_inv_day[(iid, day)]
            )

            if conflict:
                continue

            feasible.append((iid, av))

        if feasible:

            # Balance daily and total workload.
            feasible.sort(
                key=lambda x: (
                    daily_minutes[(x[0], day)],
                    total_minutes[x[0]],
                    assignment_count[x[0]],
                    int(x[0]) if x[0].isdigit() else x[0]
                )
            )

            iid, av = feasible[0]
            person = inv_by_id[iid]

            duty_by_inv_day[(iid, day)].append(
                (room["_start"], room["_end"])
            )

            daily_minutes[(iid, day)] += duration
            total_minutes[iid] += duration
            assignment_count[iid] += 1

            assignments.append({
                "AssignmentID": str(len(assignments) + 1),
                "RoomAllocationID": rid,
                "ExamID": room["ExamID"],
                "CourseID": room["CourseID"],
                "RoomID": room["RoomID"],
                "InvigilatorID": iid,
                "InvigilatorCode": person["InvigilatorCode"],
                "InvigilatorName": person["FullName"],
                "AvailabilityID": av["AvailabilityID"],
                "StartDateTime": room["_start"].strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "EndDateTime": room["_end"].strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "ExamDate": day,
                "DutyMinutes": str(duration),
                "DutyHours": f"{duration / 60:.2f}",
                "AssignmentStatus": "ASSIGNED",
                "CreatedAt": created_at
            })

        else:

            if not candidates:
                detail = (
                    "No active invigilator has an AVAILABLE window "
                    "covering the complete room duty."
                )

            elif not any(
                daily_minutes[(iid, day)] + duration
                <= inv_by_id[iid]["_max_minutes"]
                for iid, _ in candidates
            ):
                detail = (
                    "Available invigilators would exceed MaxDailyHours."
                )

            else:
                detail = (
                    "Available invigilators are already assigned "
                    "during overlapping intervals."
                )

            exceptions.append({
                "ExceptionID": str(len(exceptions) + 1),
                "RoomAllocationID": rid,
                "ExamID": room["ExamID"],
                "CourseID": room["CourseID"],
                "RoomID": room["RoomID"],
                "StartDateTime": room["_start"].strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "EndDateTime": room["_end"].strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "ReasonCode": "NO_INVIGILATOR",
                "UnassignedRoomCount": "1",
                "Details": detail,
                "CreatedAt": created_at
            })

    # --------------------------------------------------------
    # 6. WRITE OUTPUTS
    # --------------------------------------------------------

    assignment_columns = [
        "AssignmentID",
        "RoomAllocationID",
        "ExamID",
        "CourseID",
        "RoomID",
        "InvigilatorID",
        "InvigilatorCode",
        "InvigilatorName",
        "AvailabilityID",
        "StartDateTime",
        "EndDateTime",
        "ExamDate",
        "DutyMinutes",
        "DutyHours",
        "AssignmentStatus",
        "CreatedAt"
    ]

    exception_columns = [
        "ExceptionID",
        "RoomAllocationID",
        "ExamID",
        "CourseID",
        "RoomID",
        "StartDateTime",
        "EndDateTime",
        "ReasonCode",
        "UnassignedRoomCount",
        "Details",
        "CreatedAt"
    ]

    backups = create_backups([
        OUT_ASSIGN,
        OUT_EXCEPT,
        OUT_REPORT
    ])

    atomic_csv(
        OUT_ASSIGN,
        assignment_columns,
        assignments
    )

    atomic_csv(
        OUT_EXCEPT,
        exception_columns,
        exceptions
    )

    # --------------------------------------------------------
    # 7. GENERATE SUMMARY REPORT
    # --------------------------------------------------------

    total_rooms = len(prepared)
    assigned = len(assignments)
    unassigned = len(exceptions)

    report = {
        "version": "2.2.0",
        "module": "INVIGILATOR_ALLOCATION",
        "status": "COMPLETED_WITHOUT_FORCED_ASSIGNMENTS",
        "active_invigilators": len(inv_by_id),
        "availability_records": len(availability),
        "room_allocations": total_rooms,
        "assigned_room_allocations": assigned,
        "unassigned_room_allocations": unassigned,
        "assignment_percentage": round(
            assigned * 100 / total_rooms, 2
        ) if total_rooms else 100,
        "exception_percentage": round(
            unassigned * 100 / total_rooms, 2
        ) if total_rooms else 0,
        "exception_reason_counts": dict(
            Counter(x["ReasonCode"] for x in exceptions)
        ),
        "invigilator_workload": [
            {
                "InvigilatorID": iid,
                "InvigilatorCode": person["InvigilatorCode"],
                "Assignments": assignment_count[iid],
                "TotalDutyMinutes": total_minutes[iid],
                "MaxDailyHours": float(person["MaxDailyHours"]),
                "DailyDutyHours": {
                    day: round(minutes / 60, 2)
                    for (staff_id, day), minutes in daily_minutes.items()
                    if staff_id == iid
                }
            }
            for iid, person in inv_by_id.items()
        ],
        "backups_created": backups,
        "sql_server_accessed": False,
        "sql_server_modified": False,
        "groundtruth_accessed": False,
        "timetable_modified": False,
        "room_allocations_modified": False,
        "generated_at": created_at
    }

    atomic_json(OUT_REPORT, report)

    print("\n" + "=" * 65)
    print("INVIGILATOR ALLOCATION SUMMARY")
    print("=" * 65)
    print(f"Active invigilators : {len(inv_by_id):,}")
    print(f"Room duties         : {total_rooms:,}")
    print(f"Assigned            : {assigned:,}")
    print(f"Unassigned          : {unassigned:,}")
    print(f"Assignment rate     : {report['assignment_percentage']:.2f}%")
    print(f"Exceptions          : {report['exception_reason_counts']}")
    print(f"\nAssignments: {OUT_ASSIGN}")
    print(f"Exceptions : {OUT_EXCEPT}")
    print(f"Report     : {OUT_REPORT}")
    print("\nSQL Server       : NOT ACCESSED")
    print("GroundTruth      : NOT ACCESSED")
    print("Timetable        : NOT MODIFIED")
    print("Room allocations : NOT MODIFIED")
    print("=" * 65)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nFATAL ERROR: {error}", file=sys.stderr)
        raise