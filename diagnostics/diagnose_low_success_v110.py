
"""Read-only root-cause diagnostics for v1.1.0 exam scheduling."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    
    
from collections import Counter
from datetime import datetime, time, timedelta
from statistics import mean, median

from database.connection_v110 import get_connection_v110
from database.repositories.scheduling_repository import SchedulingRepository
from scheduling.conflict_graph import build_conflict_graph
from scheduling.constraints import exam_duration_minutes


OPERATING_START = time(8, 0)
OPERATING_END = time(18, 0)
SLOT_MINUTES = 30


def percentile(values, fraction):
    if not values:
        return 0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def dsatur_coloring(graph, exams):
    """Deterministic DSATUR greedy coloring; returns an upper bound."""
    exam_ids = set(graph.adjacency)
    colors = {}

    while exam_ids:
        def priority(exam_id):
            neighbor_colors = {
                colors[n]
                for n in graph.neighbors(exam_id)
                if n in colors
            }
            return (
                len(neighbor_colors),
                graph.degree(exam_id),
                -exam_id,
            )

        selected = max(exam_ids, key=priority)
        unavailable = {
            colors[n]
            for n in graph.neighbors(selected)
            if n in colors
        }

        color = 0
        while color in unavailable:
            color += 1

        colors[selected] = color
        exam_ids.remove(selected)

    return colors


def candidate_slots(exam):
    """Count valid 30-minute starts, including effective extended duration."""
    total = 0
    daily_counts = []

    day = exam.window_start.date()
    last_day = exam.window_end.date()

    while day <= last_day:
        day_start = datetime.combine(day, OPERATING_START)
        day_end = datetime.combine(day, OPERATING_END)

        lower = max(exam.window_start, day_start)
        upper = min(exam.window_end, day_end)

        duration = exam_duration_minutes(exam, day_start)
        duration_delta = timedelta(minutes=duration)

        # Align to the 30-minute clock grid.
        minute_of_day = lower.hour * 60 + lower.minute
        remainder = minute_of_day % SLOT_MINUTES

        if remainder:
            lower += timedelta(minutes=SLOT_MINUTES - remainder)

        count = 0
        current = lower

        while current + duration_delta <= upper:
            count += 1
            current += timedelta(minutes=SLOT_MINUTES)

        daily_counts.append(count)
        total += count
        day += timedelta(days=1)

    return total, daily_counts


def main():
    print("=" * 76)
    print("V1.1.0 SCHEDULING ROOT-CAUSE DIAGNOSTICS")
    print("READ ONLY - NO SQL WRITES - NO GROUNDTRUTH ACCESS")
    print("=" * 76)

    repository = SchedulingRepository(
        connection_factory=get_connection_v110
    )
    data = repository.load_all()

    exams = data["exams"]
    rooms = data["rooms"]
    invigilators = data["invigilators"]

    print("\n1. INPUT COUNTS")
    print("-" * 76)
    print("Database:", data["source"])
    print("Exams:", len(exams))
    print("Rooms:", len(rooms))
    print("Invigilators:", len(invigilators))
    print(
        "Registered participants:",
        sum(len(e.participants) for e in exams),
    )

    if data["source"] != "ExamSchedulingDB_v110":
        raise RuntimeError("Unexpected database source.")

    if len(exams) != 300:
        raise RuntimeError("Expected 300 exams; stopping diagnostics.")

    exam_students = {
        exam.exam_id: {
            participant.student_id
            for participant in exam.participants
        }
        for exam in exams
    }

    graph = build_conflict_graph(exam_students)
    degrees = [graph.degree(e.exam_id) for e in exams]

    print("\n2. STUDENT CONFLICT GRAPH")
    print("-" * 76)
    possible_pairs = len(exams) * (len(exams) - 1) // 2
    actual_pairs = sum(degrees) // 2

    print("Possible exam pairs:", possible_pairs)
    print("Conflicting pairs:", actual_pairs)
    print(
        "Graph density:",
        f"{actual_pairs / possible_pairs * 100:.2f}%"
        if possible_pairs else "N/A",
    )
    print("Average degree:", round(mean(degrees), 2))
    print("Median degree:", median(degrees))
    print("Minimum degree:", min(degrees))
    print("Maximum degree:", max(degrees))
    print("Degree percentiles:",
          "P25 =", percentile(degrees, 0.25),
          "| P75 =", percentile(degrees, 0.75))

    print("\n3. DSATUR CONFLICT-COLORING ANALYSIS")
    print("-" * 76)

    colors = dsatur_coloring(graph, exams)
    color_counts = Counter(colors.values())

    print("Greedy DSATUR colors required:", len(color_counts))
    print("Largest color group:", max(color_counts.values()))
    print("Smallest color group:", min(color_counts.values()))
    print("Color group sizes:", sorted(color_counts.values(), reverse=True))

    print(
        "Interpretation: this is a greedy coloring upper bound, "
        "not an exact minimum-slot proof."
    )

    print("\n4. VALID TIME-SLOT AVAILABILITY")
    print("-" * 76)

    slot_counts = {}
    for exam in exams:
        total, daily = candidate_slots(exam)
        slot_counts[exam.exam_id] = total

    values = list(slot_counts.values())
    print("Operating hours:", OPERATING_START, "to", OPERATING_END)
    print("Candidate interval:", SLOT_MINUTES, "minutes")
    print("Minimum candidate starts:", min(values))
    print("Median candidate starts:", median(values))
    print("Average candidate starts:", round(mean(values), 2))
    print("Maximum candidate starts:", max(values))
    print("Exams with zero candidate starts:", sum(v == 0 for v in values))
    print("Exams with 1-5 starts:", sum(1 <= v <= 5 for v in values))
    print("Exams with 6-15 starts:", sum(6 <= v <= 15 for v in values))
    print("Exams with more than 15 starts:", sum(v > 15 for v in values))

    print("\n5. EXAM SIZE AND DURATION")
    print("-" * 76)

    sizes = [len(e.participants) for e in exams]
    durations = [e.base_duration_minutes for e in exams]

    print("Minimum participants:", min(sizes))
    print("Median participants:", median(sizes))
    print("Average participants:", round(mean(sizes), 2))
    print("Maximum participants:", max(sizes))
    print("Duration distribution:", dict(sorted(Counter(durations).items())))

    print("\n6. ROOM CAPACITY OVERVIEW")
    print("-" * 76)

    capacities = []
    for room in rooms:
        for period in room.capacity_periods:
            capacities.append(period.capacity)

    print("Room records:", len(rooms))
    print("Active rooms:", sum(r.is_active for r in rooms))
    print("Accessible rooms:", sum(
        r.is_active and r.is_accessible for r in rooms
    ))

    if capacities:
        print("Capacity records:", len(capacities))
        print("Total capacity across capacity records:", sum(capacities))
        print("Minimum recorded capacity:", min(capacities))
        print("Maximum recorded capacity:", max(capacities))

    print("\n7. INVIGILATOR OVERVIEW")
    print("-" * 76)

    print("Active invigilators:", len(invigilators))
    print(
        "Total theoretical daily staff hours:",
        round(sum(float(i.max_daily_hours) for i in invigilators), 2),
    )
    print(
        "Average maximum daily hours:",
        round(mean(float(i.max_daily_hours) for i in invigilators), 2),
    )
    print(
        "Invigilators with no availability records:",
        sum(not i.availability for i in invigilators),
    )

    print("\n8. MOST CONSTRAINED EXAMS")
    print("-" * 76)

    exam_map = {e.exam_id: e for e in exams}
    worst = sorted(
        exams,
        key=lambda e: (
            -graph.degree(e.exam_id),
            slot_counts[e.exam_id],
            -len(e.participants),
        ),
    )[:15]

    print(
        f"{'Exam ID':>8} {'Students':>9} {'Degree':>8} "
        f"{'Slots':>7} {'Duration':>10}"
    )
    for exam in worst:
        print(
            f"{exam.exam_id:>8} "
            f"{len(exam.participants):>9} "
            f"{graph.degree(exam.exam_id):>8} "
            f"{slot_counts[exam.exam_id]:>7} "
            f"{exam.base_duration_minutes:>10}"
        )

    print("\n9. DIAGNOSTIC CONCLUSION")
    print("-" * 76)

    if sum(v == 0 for v in values):
        print("WARNING: Some exams have no valid time starts.")
    elif len(color_counts) > min(values):
        print(
            "WARNING: DSATUR color count exceeds the minimum candidate "
            "starts for an exam. Timetable pressure is significant."
        )
    else:
        print(
            "The conflict graph's greedy coloring fits within the "
            "minimum individual candidate-start count."
        )

    print(
        "This diagnostic does not prove room, equipment, or staff "
        "feasibility and does not prove the exact maximum schedule size."
    )
    print("=" * 76)


if __name__ == "__main__":
    main()
