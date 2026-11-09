
"""Read-only diagnostic report for the current exam scheduler."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    

from collections import Counter
from time import perf_counter


from database.repositories.scheduling_repository import SchedulingRepository
from scheduling.engine import ExamScheduler

from scheduling.validator import (
    validate_schedule,
    print_validation_report,
)


def extract_blockers(issue):
    prefix = "Observed blocking reasons: "

    if prefix not in issue.details:
        return (issue.reason_code,)

    raw = issue.details.split(prefix, 1)[1]
    raw = raw.rsplit(".", 1)[0]

    reasons = tuple(
        sorted(
            reason.strip()
            for reason in raw.split(",")
            if reason.strip() and reason.strip() != "NONE"
        )
    )

    return reasons or (issue.reason_code,)


def main():
    total_start = perf_counter()

    print("=" * 65)
    print("EXAM SCHEDULER DIAGNOSTIC REPORT")
    print("=" * 65)

    print("\n1. Loading source data...")
    load_start = perf_counter()

    data = SchedulingRepository().load_all()

    exams = data["exams"]
    rooms = data["rooms"]
    invigilators = data["invigilators"]

    print(f"Exams loaded: {len(exams)}")
    print(f"Rooms loaded: {len(rooms)}")
    print(f"Invigilators loaded: {len(invigilators)}")
    print(f"Data loading time: {perf_counter() - load_start:.2f}s")

    print("\n2. Running current scheduler...")
    scheduler = ExamScheduler(
        candidate_interval_minutes=30,
        relief_rooms_per_invigilator=4,
    )

    schedule_start = perf_counter()

    result = scheduler.schedule(
        exams=exams,
        rooms=rooms,
        invigilators=invigilators,
    )
    
   

    report = validate_schedule(
        exams=exams,
        rooms=rooms,
        invigilators=invigilators,
        result=result,
        relief_rooms_per_invigilator=4,
    )

    print_validation_report(report)

    if not report.passed:
        raise SystemExit("Independent schedule validation FAILED.")


    schedule_seconds = perf_counter() - schedule_start

    print(f"Scheduling time: {schedule_seconds:.2f}s")
    print(f"Total exams: {len(exams)}")
    print(f"Scheduled: {result.scheduled_count}")
    print(f"Unassigned: {result.unassigned_count}")

    if exams:
        print(
            "Scheduling success rate: "
            f"{result.scheduled_count / len(exams) * 100:.2f}%"
        )

    print("\n3. Exception reason codes...")
    reason_counts = Counter(
        issue.reason_code for issue in result.exceptions
    )

    for reason, count in reason_counts.most_common():
        print(f"{reason}: {count}")

    print("\n4. Actual observed blocker combinations...")
    combination_counts = Counter(
        extract_blockers(issue)
        for issue in result.exceptions
    )

    for combination, count in combination_counts.most_common():
        print(f"{' + '.join(combination)}: {count}")

    print("\n5. Frequency of observed blocking conditions...")
    blocker_counts = Counter()

    for issue in result.exceptions:
        blocker_counts.update(extract_blockers(issue))

    for reason, count in blocker_counts.most_common():
        print(f"{reason}: {count}")

    print("\n6. Scheduled exams by date...")
    date_counts = Counter(
        exam.start.date().isoformat()
        for exam in result.scheduled_exams
    )

    for exam_date, count in sorted(date_counts.items()):
        print(f"{exam_date}: {count} exams")

    print("\n7. Scheduled start-time distribution...")
    time_counts = Counter(
        exam.start.strftime("%H:%M")
        for exam in result.scheduled_exams
    )

    for start_time, count in sorted(time_counts.items()):
        print(f"{start_time}: {count} exams")

    print("\n8. Invigilator role distribution...")
    role_counts = Counter(
        assignment.role
        for exam in result.scheduled_exams
        for assignment in exam.invigilator_assignments
    )

    for role, count in sorted(role_counts.items()):
        print(f"{role}: {count}")

    print("\n9. Room allocation statistics...")
    room_counts = [
        len(exam.room_allocations)
        for exam in result.scheduled_exams
    ]

    if room_counts:
        print(f"Total room allocations: {sum(room_counts)}")
        print(f"Minimum rooms per exam: {min(room_counts)}")
        print(f"Maximum rooms per exam: {max(room_counts)}")
        print(
            "Average rooms per scheduled exam: "
            f"{sum(room_counts) / len(room_counts):.2f}"
        )
    else:
        print("No room allocations.")

    print("\n10. Unassigned exam examples...")
    for issue in result.exceptions[:15]:
        print(
            f"{issue.exam_code} | "
            f"Selected reason: {issue.reason_code} | "
            f"Observed blockers: {', '.join(extract_blockers(issue))}"
        )

    print("\n11. Final integrity checks...")

    assert result.scheduled_count + result.unassigned_count == len(exams)
    assert len({
        exam.exam_id for exam in result.scheduled_exams
    }) == result.scheduled_count

    for exam in result.scheduled_exams:
        assert exam.end > exam.start
        assert exam.room_allocations
        assert exam.invigilator_assignments

    print("Exam accounting: PASS")
    print("Unique scheduled exam IDs: PASS")
    print("Positive scheduled intervals: PASS")
    print("Room and staff assignments present: PASS")

    print("\n" + "=" * 65)
    print(f"TOTAL DIAGNOSTIC TIME: {perf_counter() - total_start:.2f}s")
    print("READ-ONLY DIAGNOSTIC COMPLETED")
    print("=" * 65)


if __name__ == "__main__":
    main()
