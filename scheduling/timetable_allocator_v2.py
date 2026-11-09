
from __future__ import annotations

import csv
import heapq
import json
import random
import sys

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "dataset_config_v2.json"

BASE_SEED = 20261022
ATTEMPTS_PER_LIMIT = 40

# Four 90-minute exam slots per day.
# Prefer the first two days; use day three only if necessary.

TIME_SLOTS = [
    {"slot_id": 1, "day": 1, "start": "08:00", "end": "09:30"},
    {"slot_id": 2, "day": 1, "start": "10:00", "end": "11:30"},
    {"slot_id": 3, "day": 1, "start": "13:00", "end": "14:30"},
    {"slot_id": 4, "day": 1, "start": "15:00", "end": "16:30"},

    {"slot_id": 5, "day": 2, "start": "08:00", "end": "09:30"},
    {"slot_id": 6, "day": 2, "start": "10:00", "end": "11:30"},
    {"slot_id": 7, "day": 2, "start": "13:00", "end": "14:30"},
    {"slot_id": 8, "day": 2, "start": "15:00", "end": "16:30"},

    {"slot_id": 9, "day": 3, "start": "08:00", "end": "09:30"},
    {"slot_id": 10, "day": 3, "start": "10:00", "end": "11:30"},
    {"slot_id": 11, "day": 3, "start": "13:00", "end": "14:30"},
    {"slot_id": 12, "day": 3, "start": "15:00", "end": "16:30"},
]

EXAM_DATES = {
    1: "2026-11-16",
    2: "2026-11-17",
    3: "2026-11-18",
}


# ============================================================
# CSV HELPERS
# ============================================================

def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Missing input file: {path}")

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        return list(csv.DictReader(file))


def write_csv(
    path: Path,
    rows: list[dict],
    columns: list[str],
) -> None:

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=columns,
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(rows)


def load_inputs(base_dir: Path):
    exams = read_csv(base_dir / "Exam.csv")

    allocations = read_csv(
        base_dir
        / "cohort_allocation"
        / "SittingAllocation.csv"
    )

    return exams, allocations


# ============================================================
# INPUT VALIDATION
# ============================================================

def validate_inputs(
    exams: list[dict],
    allocations: list[dict],
) -> None:

    exam_ids = [
        int(row["ExamID"])
        for row in exams
    ]

    if len(exam_ids) != len(set(exam_ids)):
        raise ValueError("Duplicate ExamID in Exam.csv.")

    exam_lookup = {
        int(row["ExamID"]): int(row["CourseID"])
        for row in exams
    }

    if not exams:
        raise ValueError("No exams found.")

    allocation_ids = set()

    for row in allocations:
        exam_id = int(row["ExamID"])
        student_id = int(row["StudentID"])
        course_id = int(row["CourseID"])
        enrollment_id = int(row["EnrollmentID"])

        if exam_id not in exam_lookup:
            raise ValueError(
                f"Allocation references unknown ExamID {exam_id}."
            )

        if exam_lookup[exam_id] != course_id:
            raise ValueError(
                f"Exam {exam_id}: allocation CourseID mismatch."
            )

        if student_id <= 0 or enrollment_id <= 0:
            raise ValueError(
                f"Invalid student/enrollment ID in allocation."
            )

        if enrollment_id in allocation_ids:
            raise ValueError(
                f"Enrollment {enrollment_id} has multiple allocations."
            )

        allocation_ids.add(enrollment_id)

    exams_by_course = defaultdict(list)

    for exam in exams:
        exams_by_course[int(exam["CourseID"])].append(
            int(exam["ExamID"])
        )

    for course_id, exam_ids in exams_by_course.items():
        if len(exam_ids) != 3:
            raise ValueError(
                f"Course {course_id}: expected exactly 3 sittings; "
                f"found {len(exam_ids)}."
            )

    if not allocation_ids:
        raise ValueError("No student allocations found.")


# ============================================================
# CONFLICT GRAPH
# ============================================================

def build_exam_students(
    exams: list[dict],
    allocations: list[dict],
):
    exam_students = defaultdict(set)
    exam_courses = {}

    for exam in exams:
        exam_id = int(exam["ExamID"])
        exam_courses[exam_id] = int(exam["CourseID"])

    for row in allocations:
        exam_id = int(row["ExamID"])
        student_id = int(row["StudentID"])

        if exam_id not in exam_courses:
            raise ValueError(
                f"Unknown ExamID {exam_id} in allocation."
            )

        exam_students[exam_id].add(student_id)

    return exam_students, exam_courses


def build_conflict_graph(
    exams: list[dict],
    exam_students: dict,
    exam_courses: dict,
):
    """
    An edge means two exams cannot occupy the same time slot.

    Hard conflicts:
      1. Exams attended by the same student.
      2. Different sittings of the same course.
    """

    graph = {
        int(exam["ExamID"]): set()
        for exam in exams
    }

    exams_by_course = defaultdict(list)

    for exam in exams:
        exam_id = int(exam["ExamID"])
        course_id = int(exam["CourseID"])

        exams_by_course[course_id].append(exam_id)

    # Each course's three sittings must have different slots.
    for course_id, exam_ids in exams_by_course.items():

        if len(exam_ids) != 3:
            raise ValueError(
                f"Course {course_id} must have exactly 3 sittings."
            )

        for index, first in enumerate(exam_ids):
            for second in exam_ids[index + 1:]:
                graph[first].add(second)
                graph[second].add(first)

    # Build student -> exams mapping.
    student_exams = defaultdict(list)

    for exam_id, student_ids in exam_students.items():
        for student_id in student_ids:
            student_exams[student_id].append(exam_id)

    # Exams sharing a student cannot use the same slot.
    for student_id, exam_ids in student_exams.items():

        exam_ids = sorted(set(exam_ids))

        for index, first in enumerate(exam_ids):
            for second in exam_ids[index + 1:]:
                graph[first].add(second)
                graph[second].add(first)

    return graph


# ============================================================
# COLORING QUALITY
# ============================================================

def calculate_coloring_score(
    colors: dict[int, int],
    exam_courses: dict[int, int],
):
    """
    Lower score is better.

    Priorities:
      1. Keep all three course sittings on one day.
      2. Avoid excessive slot loading.
      3. Balance exams across slots.
      4. Prefer fewer used slots.
    """

    course_days = defaultdict(set)
    slot_loads = Counter()

    for exam_id, slot_id in colors.items():
        slot = TIME_SLOTS[slot_id - 1]

        course_id = exam_courses[exam_id]

        course_days[course_id].add(slot["day"])
        slot_loads[slot_id] += 1

    total_course_days = sum(
        len(days)
        for days in course_days.values()
    )

    loads = [
        slot_loads[slot["slot_id"]]
        for slot in TIME_SLOTS
    ]

    maximum_load = max(loads, default=0)

    squared_load = sum(
        load * load
        for load in loads
    )

    used_slots = sum(
        1 for load in loads if load > 0
    )

    return (
        total_course_days,
        maximum_load,
        squared_load,
        used_slots,
    )


# ============================================================
# OPTIMIZED DSATUR
# ============================================================

def dsatur_attempt(
    graph: dict[int, set[int]],
    exam_courses: dict[int, int],
    max_colors: int,
    seed: int,
):
    """
    Priority-queue DSATUR.

    Unlike the earlier implementation, this does not scan every
    remaining exam to find the next vertex.

    Runtime is approximately O((V + E) log V) per attempt.
    """

    rng = random.Random(seed)

    colors = {}

    degrees = {
        node: len(neighbors)
        for node, neighbors in graph.items()
    }

    # Colors already used by each node's colored neighbors.
    saturation_colors = {
        node: set()
        for node in graph
    }

    versions = {
        node: 0
        for node in graph
    }

    # Stable randomized tie-breaking for this attempt.
    tie_breakers = {
        node: rng.random()
        for node in graph
    }

    # Heap fields:
    # (-saturation, -degree, tie_breaker, node, version)
    heap = []

    for node in graph:
        heapq.heappush(
            heap,
            (
                0,
                -degrees[node],
                tie_breakers[node],
                node,
                0,
            ),
        )

    course_colors = defaultdict(set)

    slot_loads = Counter()
    day_loads = Counter()

    slot_day = {
        slot["slot_id"]: slot["day"]
        for slot in TIME_SLOTS
    }

    while heap:

        negative_saturation, negative_degree, tie, node, version = (
            heapq.heappop(heap)
        )

        if node in colors:
            continue

        if version != versions[node]:
            continue

        forbidden = saturation_colors[node]

        course_id = exam_courses[node]
        existing_course_colors = course_colors[course_id]

        existing_course_days = {
            slot_day[color]
            for color in existing_course_colors
        }

        candidates = [
            color
            for color in range(1, max_colors + 1)
            if color not in forbidden
        ]

        if not candidates:
            return None

        def candidate_score(color):

            day = slot_day[color]

            # Strong preference for keeping all course sittings
            # on the same day once the first sitting is assigned.
            day_penalty = (
                0
                if not existing_course_days
                or day in existing_course_days
                else 1
            )

            resulting_course_days = len(
                existing_course_days | {day}
            )

            return (
                day_penalty,
                resulting_course_days,
                day_loads[day],
                slot_loads[color],
                color,
            )

        selected_color = min(
            candidates,
            key=candidate_score,
        )

        colors[node] = selected_color

        course_colors[course_id].add(selected_color)

        slot_loads[selected_color] += 1

        day_loads[slot_day[selected_color]] += 1

        # Update saturation only for uncolored neighbors.
        for neighbor in graph[node]:

            if neighbor in colors:
                continue

            if selected_color not in saturation_colors[neighbor]:

                saturation_colors[neighbor].add(
                    selected_color
                )

                versions[neighbor] += 1

                heapq.heappush(
                    heap,
                    (
                        -len(saturation_colors[neighbor]),
                        -degrees[neighbor],
                        tie_breakers[neighbor],
                        neighbor,
                        versions[neighbor],
                    ),
                )

    return colors



def tabu_color_attempt(
    graph: dict[int, set[int]],
    exam_courses: dict[int, int],
    max_colors: int,
    seed: int,
    max_iterations: int = 25000,
):
    """
    DSATUR initialization followed by tabu-search optimization.

    Unlike ordinary greedy coloring, this can move previously
    assigned exams to resolve conflicts.

    Returns:
        colors: complete exam-to-slot mapping, or None
        best_conflicts: minimum conflicts found
    """

    import random

    rng = random.Random(seed)

    nodes = sorted(graph)
    node_set = set(nodes)

    # Convert graph to indexed adjacency for faster operations.
    index = {node: i for i, node in enumerate(nodes)}

    adjacency = [
        [index[n] for n in graph[node] if n in node_set]
        for node in nodes
    ]

    count = len(nodes)

    # --------------------------------------------------------
    # DSATUR INITIALIZATION
    # --------------------------------------------------------

    colors = [-1] * count
    remaining = set(range(count))

    degrees = [len(adjacency[i]) for i in range(count)]

    course_colors = defaultdict(set)

    slot_loads = [0] * max_colors

    slot_day = [
        TIME_SLOTS[i]["day"]
        for i in range(max_colors)
    ]

    while remaining:

        def priority(i):
            saturation = len({
                colors[j]
                for j in adjacency[i]
                if colors[j] >= 0
            })

            return saturation, degrees[i], -nodes[i]

        vertex = max(remaining, key=priority)

        course_id = exam_courses[nodes[vertex]]

        existing_days = {
            slot_day[c]
            for c in course_colors[course_id]
        }

        candidate_scores = []

        for color in range(max_colors):

            conflicts = sum(
                1
                for neighbor in adjacency[vertex]
                if colors[neighbor] == color
            )

            day = slot_day[color]

            day_penalty = (
                0
                if not existing_days or day in existing_days
                else 1
            )

            candidate_scores.append((
                conflicts,
                day_penalty,
                slot_loads[color],
                rng.random(),
                color,
            ))

        selected = min(candidate_scores)[-1]

        colors[vertex] = selected

        course_colors[course_id].add(selected)

        slot_loads[selected] += 1

        remaining.remove(vertex)

    # --------------------------------------------------------
    # BUILD NEIGHBOR COLOR COUNTS
    # --------------------------------------------------------

    neighbor_counts = [
        [0] * max_colors
        for _ in range(count)
    ]

    for vertex in range(count):
        for neighbor in adjacency[vertex]:
            neighbor_counts[vertex][colors[neighbor]] += 1

    def conflict_count(vertex):
        return neighbor_counts[vertex][colors[vertex]]

    conflicted = {
        vertex
        for vertex in range(count)
        if conflict_count(vertex) > 0
    }

    total_conflicts = sum(
        conflict_count(vertex)
        for vertex in range(count)
    ) // 2

    best_conflicts = total_conflicts
    best_colors = colors.copy()

    if total_conflicts == 0:
        return (
            {nodes[i]: colors[i] + 1 for i in range(count)},
            0,
        )

    # Tabu expiration for moving a vertex back to a color.
    tabu_until = [
        [0] * max_colors
        for _ in range(count)
    ]

    # --------------------------------------------------------
    # TABU SEARCH
    # --------------------------------------------------------

    for iteration in range(1, max_iterations + 1):

        if not conflicted:
            best_colors = colors.copy()
            best_conflicts = 0
            break

        # Select one of the most conflicted exams.
        maximum_conflicts = max(
            conflict_count(v)
            for v in conflicted
        )

        candidates = [
            v for v in conflicted
            if conflict_count(v) == maximum_conflicts
        ]

        vertex = rng.choice(candidates)

        old_color = colors[vertex]
        old_conflicts = neighbor_counts[vertex][old_color]

        best_move = None
        best_delta = None

        # Find the best alternative color.
        for new_color in range(max_colors):

            if new_color == old_color:
                continue

            new_conflicts = neighbor_counts[vertex][new_color]

            delta = new_conflicts - old_conflicts

            resulting_conflicts = total_conflicts + delta

            is_tabu = (
                tabu_until[vertex][new_color] > iteration
            )

            # Aspiration: allow a tabu move if it improves
            # the best global solution.
            if is_tabu and resulting_conflicts >= best_conflicts:
                continue

            if (
                best_delta is None
                or delta < best_delta
                or (
                    delta == best_delta
                    and rng.random() < 0.5
                )
            ):
                best_delta = delta
                best_move = new_color

        # If every candidate is tabu, permit the least harmful move.
        if best_move is None:

            alternatives = [
                color
                for color in range(max_colors)
                if color != old_color
            ]

            best_move = min(
                alternatives,
                key=lambda color: neighbor_counts[vertex][color],
            )

            best_delta = (
                neighbor_counts[vertex][best_move]
                - old_conflicts
            )

        new_color = best_move

        # Move the vertex.
        colors[vertex] = new_color

        total_conflicts += best_delta

        # Prevent immediate reversal.
        tabu_tenure = rng.randint(7, 15)

        tabu_until[vertex][old_color] = (
            iteration + tabu_tenure
        )

        # Update neighboring color counts.
        for neighbor in adjacency[vertex]:

            neighbor_counts[neighbor][old_color] -= 1
            neighbor_counts[neighbor][new_color] += 1

            if conflict_count(neighbor) > 0:
                conflicted.add(neighbor)
            else:
                conflicted.discard(neighbor)

        if conflict_count(vertex) > 0:
            conflicted.add(vertex)
        else:
            conflicted.discard(vertex)

        # Record the best solution.
        if total_conflicts < best_conflicts:

            best_conflicts = total_conflicts
            best_colors = colors.copy()

            if best_conflicts == 0:
                break

    if best_conflicts == 0:
        result = {
            nodes[i]: best_colors[i] + 1
            for i in range(count)
        }

        return result, 0

    return None, best_conflicts


def color_graph(
    graph: dict[int, set[int]],
    exam_courses: dict[int, int],
    max_colors: int = 12,
    attempts_per_limit: int = 8,
):
    """
    Try eight slots first, then twelve.

    Each attempt uses DSATUR initialization and tabu search.
    All student and course conflicts remain hard constraints.
    """

    best_conflicts = None
    total_attempts = 0

    limits = [8]

    if max_colors > 8:
        limits.append(max_colors)

    for color_limit in limits:

        print(
            f"\nTrying {color_limit} slots using "
            f"DSATUR + tabu search..."
        )

        for attempt in range(attempts_per_limit):

            total_attempts += 1

            colors, conflicts = tabu_color_attempt(
                graph=graph,
                exam_courses=exam_courses,
                max_colors=color_limit,
                seed=BASE_SEED + color_limit * 1000 + attempt,
                max_iterations=25000,
            )

            if conflicts == 0:

                print(
                    f"  Feasible timetable found "
                    f"on attempt {attempt + 1}."
                )

                score = calculate_coloring_score(
                    colors,
                    exam_courses,
                )

                return (
                    colors,
                    total_attempts,
                    score,
                    color_limit,
                )

            if (
                best_conflicts is None
                or conflicts < best_conflicts
            ):
                best_conflicts = conflicts

            print(
                f"  Attempt {attempt + 1}/"
                f"{attempts_per_limit}: "
                f"remaining conflicts = {conflicts}"
            )

    raise RuntimeError(
        f"No conflict-free timetable found. "
        f"Best remaining conflicts: {best_conflicts}. "
        f"Attempts: {total_attempts}. "
        "This does not prove infeasibility. "
        "No output was modified."
    )

# ============================================================
# TIMETABLE CONSTRUCTION
# ============================================================

def create_timetable(
    exams: list[dict],
    allocations: list[dict],
):
    exam_students, exam_courses = build_exam_students(
        exams,
        allocations,
    )

    graph = build_conflict_graph(
        exams,
        exam_students,
        exam_courses,
    )

    (
        colors,
        attempts,
        score,
        coloring_limit,
    ) = color_graph(
        graph=graph,
        exam_courses=exam_courses,
        max_colors=len(TIME_SLOTS),
    )

    exam_lookup = {
        int(exam["ExamID"]): exam
        for exam in exams
    }

    timetable = []

    for exam_id in sorted(colors):

        exam = exam_lookup[exam_id]

        slot_id = colors[exam_id]

        slot = TIME_SLOTS[slot_id - 1]

        timetable.append({
            "ExamID": exam_id,
            "CourseID": int(exam["CourseID"]),
            "ExamCode": exam["ExamCode"],
            "SittingSlotID": slot_id,
            "DayNumber": slot["day"],
            "ExamDate": EXAM_DATES[slot["day"]],
            "StartTime": slot["start"],
            "EndTime": slot["end"],
            "StudentCount": len(
                exam_students[exam_id]
            ),
        })

    timetable.sort(
        key=lambda row: (
            row["DayNumber"],
            row["StartTime"],
            row["CourseID"],
            row["ExamID"],
        )
    )

    return (
        timetable,
        graph,
        attempts,
        score,
        coloring_limit,
    )


# ============================================================
# INDEPENDENT TIMETABLE VALIDATION
# ============================================================

def validate_timetable(
    timetable: list[dict],
    graph: dict,
    allocations: list[dict],
    exams: list[dict],
):
    errors = []

    by_exam = {
        int(row["ExamID"]): row
        for row in timetable
    }

    expected_exam_ids = {
        int(row["ExamID"])
        for row in exams
    }

    actual_exam_ids = set(by_exam)

    if len(by_exam) != len(timetable):
        errors.append("Duplicate ExamID in timetable.")

    if actual_exam_ids != expected_exam_ids:
        errors.append(
            "Timetable does not contain exactly all source exams."
        )

    # Verify every graph conflict.
    for exam_id, neighbors in graph.items():

        if exam_id not in by_exam:
            continue

        for neighbor in neighbors:

            if neighbor not in by_exam:
                continue

            if (
                by_exam[exam_id]["SittingSlotID"]
                == by_exam[neighbor]["SittingSlotID"]
            ):
                errors.append(
                    f"Hard conflict: exams {exam_id} and {neighbor} "
                    "share a time slot."
                )

    # Verify actual student schedules.
    student_slots = defaultdict(list)

    for allocation in allocations:

        exam_id = int(allocation["ExamID"])
        student_id = int(allocation["StudentID"])

        if exam_id not in by_exam:
            errors.append(
                f"Student {student_id}: exam {exam_id} missing."
            )
            continue

        student_slots[student_id].append(
            int(by_exam[exam_id]["SittingSlotID"])
        )

    for student_id, slots in student_slots.items():

        if len(slots) != len(set(slots)):
            errors.append(
                f"Student {student_id}: overlapping exams."
            )

    # Verify exactly three distinct sittings per course.
    course_slots = defaultdict(set)
    course_days = defaultdict(set)

    for row in timetable:

        course_id = int(row["CourseID"])

        course_slots[course_id].add(
            int(row["SittingSlotID"])
        )

        course_days[course_id].add(
            int(row["DayNumber"])
        )

    expected_courses = {
        int(row["CourseID"])
        for row in exams
    }

    for course_id in expected_courses:

        slots = course_slots[course_id]

        if len(slots) != 3:
            errors.append(
                f"Course {course_id}: expected 3 distinct slots; "
                f"found {len(slots)}."
            )

    return errors, course_days


# ============================================================
# MAIN
# ============================================================

def main() -> int:

    config = json.loads(
        CONFIG_PATH.read_text(encoding="utf-8")
    )

    base_dir = ROOT / config["output_directory"]

    output_dir = base_dir / "cohort_allocation"

    print("=" * 70)
    print("EXAM SCHEDULING SYSTEM - TIMETABLE ALLOCATOR V2.0.0")
    print("=" * 70)

    exams, allocations = load_inputs(base_dir)

    print(f"\nSource exams: {len(exams):,}")
    print(f"Student allocations: {len(allocations):,}")

    validate_inputs(
        exams,
        allocations,
    )

    (
        timetable,
        graph,
        attempts,
        score,
        coloring_limit,
    ) = create_timetable(
        exams,
        allocations,
    )

    errors, course_days = validate_timetable(
        timetable,
        graph,
        allocations,
        exams,
    )

    if errors:

        print("\nTIMETABLE VALIDATION FAILED")

        for error in errors[:100]:
            print(f" - {error}")

        print(f"\nTotal errors: {len(errors)}")

        return 1

    # --------------------------------------------------------
    # Prepare report
    # --------------------------------------------------------

    slot_counts = Counter(
        int(row["SittingSlotID"])
        for row in timetable
    )

    day_counts = Counter(
        int(row["DayNumber"])
        for row in timetable
    )

    courses_on_one_day = sum(
        1
        for days in course_days.values()
        if len(days) == 1
    )

    courses_spread_across_days = sum(
        1
        for days in course_days.values()
        if len(days) > 1
    )

    unique_students = len({
        int(row["StudentID"])
        for row in allocations
    })

    report = {
        "version": config["version"],
        "algorithm": "OPTIMIZED_MULTI_START_DS​​ATUR",
        "status": "PASSED",
        "exam_count": len(timetable),
        "student_count": unique_students,
        "allocation_count": len(allocations),
        "conflict_edges": sum(
            len(neighbors)
            for neighbors in graph.values()
        ) // 2,
        "attempts_completed": attempts,
        "slots_available": coloring_limit,
        "days_used": len(day_counts),
        "coloring_score": {
            "course_day_total": score[0],
            "maximum_slot_load": score[1],
            "squared_slot_load": score[2],
            "slots_used": score[3],
        },
        "course_distribution": {
            "all_sittings_same_day": courses_on_one_day,
            "sittings_across_multiple_days": courses_spread_across_days,
        },
        "slots": {
            str(slot["slot_id"]): {
                "day": slot["day"],
                "date": EXAM_DATES[slot["day"]],
                "start": slot["start"],
                "end": slot["end"],
                "exam_count": slot_counts[slot["slot_id"]],
            }
            for slot in TIME_SLOTS[:coloring_limit]
        },
        "day_exam_counts": {
            str(day): count
            for day, count in sorted(day_counts.items())
        },
        "validation_errors": errors,
    }

    # --------------------------------------------------------
    # Write outputs only after successful validation
    # --------------------------------------------------------

    output_columns = [
        "ExamID",
        "CourseID",
        "ExamCode",
        "SittingSlotID",
        "DayNumber",
        "ExamDate",
        "StartTime",
        "EndTime",
        "StudentCount",
    ]

    output_path = output_dir / "ExamTimetable.csv"

    write_csv(
        output_path,
        timetable,
        output_columns,
    )

    report_path = output_dir / "timetable_report.json"

    report_path.write_text(
        json.dumps(report, indent=4),
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print("\nTIMETABLE GENERATED SUCCESSFULLY")

    print(f"Exams scheduled: {len(timetable):,}")
    print(f"Students: {unique_students:,}")
    print(f"Conflict edges: {report['conflict_edges']:,}")
    print(f"DSATUR attempts: {attempts}")
    print(f"Days used: {report['days_used']}")

    print("\nDAILY DISTRIBUTION")

    for day, count in sorted(day_counts.items()):
        print(f"Day {day}: {count} exams")

    print("\nCOURSE SITTING DISTRIBUTION")

    print(
        f"All three sittings on one day: "
        f"{courses_on_one_day}"
    )

    print(
        f"Sittings spread across days: "
        f"{courses_spread_across_days}"
    )

    print("\nSLOT DISTRIBUTION")

    for slot in TIME_SLOTS[:coloring_limit]:

        print(
            f"Day {slot['day']} | "
            f"{slot['start']}-{slot['end']} | "
            f"{slot_counts[slot['slot_id']]} exams"
        )

    print("\nVALIDATION: PASSED")
    print(f"Timetable: {output_path}")
    print(f"Report: {report_path}")
    print("Original dataset: UNCHANGED")
    print("SQL Server: NOT MODIFIED")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())

    except KeyboardInterrupt:
        print("\nAllocation cancelled by user.")
        sys.exit(130)

    except Exception as exc:
        print(f"\nTIMETABLE ALLOCATION FAILED: {exc}")
        sys.exit(1)
