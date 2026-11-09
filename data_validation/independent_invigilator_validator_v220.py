import csv
import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter

# ============================================================
# EXAM SCHEDULING SYSTEM v2.2.0
# INDEPENDENT INVIGILATOR ALLOCATION VALIDATOR
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
SCHED = DATA / "scheduling"

INV_FILE = DATA / "Invigilator.csv"
AVAIL_FILE = DATA / "Availability.csv"
ROOM_FILE = SCHED / "RoomAllocation.csv"

ASSIGN_FILE = SCHED / "InvigilatorAssignment.csv"
EXCEPT_FILE = SCHED / "InvigilatorAllocationExceptions.csv"

REPORT_FILE = SCHED / "invigilator_independent_validation_v220.json"

APPROVED_REASON_CODES = {"NO_INVIGILATOR"}


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        if not reader.fieldnames:
            raise ValueError(f"Missing CSV header: {path}")

        return list(reader)


def parse_datetime(value, field):
    value = (value or "").strip()

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass

    raise ValueError(f"Invalid datetime in {field}: {value}")


def overlaps(start1, end1, start2, end2):
    return start1 < end2 and start2 < end1


def main():

    print("\nLoading independent validation inputs...")

    invigilator_rows = read_csv(INV_FILE)
    availability_rows = read_csv(AVAIL_FILE)
    room_rows = read_csv(ROOM_FILE)
    assignments = read_csv(ASSIGN_FILE)
    exceptions = read_csv(EXCEPT_FILE)

    errors = []
    checks = 0

    def check(condition, message):
        nonlocal checks
        checks += 1

        if not condition:
            errors.append(message)

    # --------------------------------------------------------
    # 1. ACTIVE INVIGILATORS
    # --------------------------------------------------------

    invigilators = {}

    for row in invigilator_rows:

        iid = row["InvigilatorID"].strip()

        if row["Status"].strip().upper() == "ACTIVE":

            if iid in invigilators:
                errors.append(f"Duplicate active InvigilatorID: {iid}")
                continue

            invigilators[iid] = row

    # --------------------------------------------------------
    # 2. AVAILABLE TIME WINDOWS
    # --------------------------------------------------------

    availability_by_inv = defaultdict(list)

    for row in availability_rows:

        iid = row["InvigilatorID"].strip()

        if iid not in invigilators:
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

        availability_by_inv[iid].append({
            "ID": row["AvailabilityID"].strip(),
            "Start": start,
            "End": end
        })

    # --------------------------------------------------------
    # 3. SOURCE ROOM ALLOCATIONS
    # --------------------------------------------------------

    rooms = {}

    for row in room_rows:

        rid = row["RoomAllocationID"].strip()

        if rid in rooms:
            errors.append(f"Duplicate RoomAllocationID: {rid}")
            continue

        rooms[rid] = row

    # --------------------------------------------------------
    # 4. ASSIGNMENT COVERAGE AND CONSTRAINTS
    # --------------------------------------------------------

    assignment_count = Counter()
    exception_count = Counter()

    duty_by_inv_day = defaultdict(list)
    daily_minutes = defaultdict(int)
    inv_assignment_count = Counter()

    for row in assignments:

        rid = row["RoomAllocationID"].strip()
        iid = row["InvigilatorID"].strip()

        assignment_count[rid] += 1

        check(
            rid in rooms,
            f"Unknown RoomAllocationID in assignment: {rid}"
        )

        check(
            iid in invigilators,
            f"Unknown or inactive InvigilatorID: {iid}"
        )

        if rid not in rooms or iid not in invigilators:
            continue

        source = rooms[rid]

        source_start = parse_datetime(
            source["StartDateTime"],
            "RoomAllocation.StartDateTime"
        )

        source_end = parse_datetime(
            source["EndDateTime"],
            "RoomAllocation.EndDateTime"
        )

        assigned_start = parse_datetime(
            row["StartDateTime"],
            "Assignment.StartDateTime"
        )

        assigned_end = parse_datetime(
            row["EndDateTime"],
            "Assignment.EndDateTime"
        )

        check(
            assigned_start == source_start
            and assigned_end == source_end,
            f"Assignment interval mismatch: RoomAllocationID {rid}"
        )

        check(
            row["ExamID"].strip() == source["ExamID"].strip(),
            f"ExamID mismatch: RoomAllocationID {rid}"
        )

        check(
            row["RoomID"].strip() == source["RoomID"].strip(),
            f"RoomID mismatch: RoomAllocationID {rid}"
        )

        matching_availability = [
            av["ID"]
            for av in availability_by_inv[iid]
            if (
                av["Start"] <= assigned_start
                and av["End"] >= assigned_end
            )
        ]

        check(
            len(matching_availability) > 0,
            f"Invigilator {iid} unavailable for complete duty: {rid}"
        )

        check(
            row["AvailabilityID"].strip() in matching_availability,
            f"Incorrect AvailabilityID for room duty: {rid}"
        )

        duration = int(
            (assigned_end - assigned_start).total_seconds() // 60
        )

        check(
            int(row["DutyMinutes"]) == duration,
            f"DutyMinutes mismatch: RoomAllocationID {rid}"
        )

        day = assigned_start.date().isoformat()

        duty_by_inv_day[(iid, day)].append({
            "Start": assigned_start,
            "End": assigned_end,
            "RoomAllocationID": rid
        })

        daily_minutes[(iid, day)] += duration
        inv_assignment_count[iid] += 1

    # --------------------------------------------------------
    # 5. EXCEPTION VALIDATION
    # --------------------------------------------------------

    for row in exceptions:

        rid = row["RoomAllocationID"].strip()

        exception_count[rid] += 1

        check(
            rid in rooms,
            f"Unknown RoomAllocationID in exception: {rid}"
        )

        check(
            row["ReasonCode"].strip() in APPROVED_REASON_CODES,
            f"Unapproved exception reason code: {row['ReasonCode']}"
        )

        check(
            int(row["UnassignedRoomCount"]) == 1,
            f"UnassignedRoomCount must be 1: {rid}"
        )

    # --------------------------------------------------------
    # 6. EXACTLY ONE ASSIGNMENT OR EXCEPTION PER ROOM
    # --------------------------------------------------------

    for rid in rooms:

        total = assignment_count[rid] + exception_count[rid]

        check(
            total == 1,
            f"RoomAllocationID {rid} must have exactly one "
            f"assignment or exception; found {total}"
        )

    for rid in set(assignment_count) | set(exception_count):

        check(
            rid in rooms,
            f"Unexpected room reference: {rid}"
        )

    for rid, count in assignment_count.items():

        check(
            count <= 1,
            f"Multiple invigilators assigned to room allocation {rid}"
        )

    for rid, count in exception_count.items():

        check(
            count <= 1,
            f"Duplicate exception for room allocation {rid}"
        )

    for rid in set(assignment_count) & set(exception_count):

        check(
            False,
            f"Room allocation {rid} has both assignment and exception"
        )

    # --------------------------------------------------------
    # 7. DOUBLE-BOOKING VALIDATION
    # --------------------------------------------------------

    overlapping_pairs = 0

    for (iid, day), duties in duty_by_inv_day.items():

        duties.sort(
            key=lambda x: (x["Start"], x["End"])
        )

        for i in range(len(duties)):

            for j in range(i + 1, len(duties)):

                first = duties[i]
                second = duties[j]

                if second["Start"] >= first["End"]:
                    break

                if overlaps(
                    first["Start"],
                    first["End"],
                    second["Start"],
                    second["End"]
                ):

                    overlapping_pairs += 1

                    errors.append(
                        f"INVIGILATOR DOUBLE-BOOKING: {iid}, {day}, "
                        f"RoomAllocationIDs "
                        f"{first['RoomAllocationID']} and "
                        f"{second['RoomAllocationID']}"
                    )

    # --------------------------------------------------------
    # 8. DAILY WORKING-HOUR VALIDATION
    # --------------------------------------------------------

    for (iid, day), minutes in daily_minutes.items():

        max_hours = float(
            invigilators[iid]["MaxDailyHours"]
        )

        max_minutes = int(round(max_hours * 60))

        check(
            minutes <= max_minutes,
            f"Invigilator {iid} exceeds daily limit on {day}: "
            f"{minutes} minutes > {max_minutes} minutes"
        )

    # --------------------------------------------------------
    # 9. FINAL REPORT
    # --------------------------------------------------------

    source_count = len(rooms)
    assigned_count = len(assignments)
    exception_total = len(exceptions)

    coverage = (
        assigned_count * 100 / source_count
        if source_count else 100
    )

    if errors:
        status = "FAILED"
    elif exception_total:
        status = "PASSED_WITH_EXCEPTIONS"
    else:
        status = "PASSED"

    report = {
        "version": "2.2.0",
        "module": "INVIGILATOR_ALLOCATION_INDEPENDENT_VALIDATION",
        "status": status,
        "checks_executed": checks,
        "error_count": len(errors),
        "errors": errors,
        "source_room_allocations": source_count,
        "assigned_room_allocations": assigned_count,
        "unassigned_room_allocations": exception_total,
        "assignment_coverage_percentage": round(coverage, 2),
        "exception_reason_counts": dict(
            Counter(
                row["ReasonCode"]
                for row in exceptions
            )
        ),
        "invigilators_with_assignments": len(inv_assignment_count),
        "overlapping_duty_pairs": overlapping_pairs,
        "daily_workload_records_checked": len(daily_minutes),
        "sql_server_accessed": False,
        "sql_server_modified": False,
        "groundtruth_accessed": False,
        "timetable_modified": False,
        "room_allocations_modified": False,
        "validated_at": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    }

    temp = REPORT_FILE.with_suffix(".json.tmp")

    with temp.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    temp.replace(REPORT_FILE)

    # --------------------------------------------------------
    # 10. CONSOLE SUMMARY
    # --------------------------------------------------------

    print("\n" + "=" * 65)
    print("INDEPENDENT INVIGILATOR VALIDATION")
    print("=" * 65)

    print(f"Status                 : {status}")
    print(f"Checks executed        : {checks:,}")
    print(f"Validation errors      : {len(errors):,}")
    print(f"Source room allocations: {source_count:,}")
    print(f"Assigned               : {assigned_count:,}")
    print(f"Exceptions             : {exception_total:,}")
    print(f"Assignment coverage    : {coverage:.2f}%")
    print(f"Double-booking pairs   : {overlapping_pairs}")

    print(f"\nReport: {REPORT_FILE}")

    print("\nSQL Server       : NOT ACCESSED")
    print("GroundTruth      : NOT ACCESSED")
    print("Timetable        : NOT MODIFIED")
    print("Room allocations : NOT MODIFIED")

    if errors:

        print("\nFIRST 30 VALIDATION ERRORS:")

        for error in errors[:30]:
            print(" -", error)

    print("=" * 65)

    if errors:
        return 1

    return 0


if __name__ == "__main__":

    try:
        sys.exit(main())

    except Exception as error:
        print(f"\nFATAL VALIDATION ERROR: {error}", file=sys.stderr)
        raise