
import csv
from collections import defaultdict, Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "output_v2" / "full" / "v2.1.0"
ALLOCATION_DIR = DATA_DIR / "cohort_allocation"

ALLOCATION_FILE = ALLOCATION_DIR / "SittingAllocation.csv"
EXAM_FILE = DATA_DIR / "Exam.csv"


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")

    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    print("=" * 72)
    print("TIMETABLE CONFLICT GRAPH DIAGNOSTICS V2")
    print("=" * 72)

    allocations = read_csv(ALLOCATION_FILE)
    exams = read_csv(EXAM_FILE)

    required = {
        "EnrollmentID",
        "StudentID",
        "CourseID",
        "ExamID",
        "SittingOrdinal",
    }

    if not allocations:
        raise ValueError("SittingAllocation.csv is empty.")

    missing = required - set(allocations[0].keys())

    if missing:
        raise ValueError(
            f"SittingAllocation.csv missing columns: {sorted(missing)}"
        )

    exam_courses = {
        int(row["ExamID"]): int(row["CourseID"])
        for row in exams
    }

    graph = {exam_id: set() for exam_id in exam_courses}

    student_exams = defaultdict(set)
    student_courses = defaultdict(set)
    course_students = defaultdict(set)
    course_sittings = defaultdict(list)
    course_sitting_counts = defaultdict(Counter)

    enrollment_ids = set()
    allocation_errors = []

    for row in allocations:
        enrollment_id = int(row["EnrollmentID"])
        student_id = int(row["StudentID"])
        course_id = int(row["CourseID"])
        exam_id = int(row["ExamID"])
        ordinal = int(row["SittingOrdinal"])

        if enrollment_id in enrollment_ids:
            allocation_errors.append(
                f"Duplicate EnrollmentID: {enrollment_id}"
            )

        enrollment_ids.add(enrollment_id)

        if exam_id not in graph:
            allocation_errors.append(
                f"Unknown ExamID {exam_id} in allocation."
            )
            continue

        if exam_courses[exam_id] != course_id:
            allocation_errors.append(
                f"Course mismatch for ExamID {exam_id}."
            )

        student_exams[student_id].add(exam_id)
        student_courses[student_id].add(course_id)

        course_students[course_id].add(student_id)
        course_sitting_counts[course_id][ordinal] += 1

        if exam_id not in course_sittings[course_id]:
            course_sittings[course_id].append(exam_id)

    if allocation_errors:
        print("\nALLOCATION ERRORS:")
        for error in allocation_errors[:20]:
            print(" -", error)

        raise ValueError(
            f"Found {len(allocation_errors)} allocation errors."
        )

    # Student conflict edges.
    student_edge_count = 0

    for student_id, assigned_exams in student_exams.items():
        assigned_exams = sorted(assigned_exams)

        for i, exam_a in enumerate(assigned_exams):
            for exam_b in assigned_exams[i + 1:]:
                if exam_b not in graph[exam_a]:
                    graph[exam_a].add(exam_b)
                    graph[exam_b].add(exam_a)
                    student_edge_count += 1

    # Three sittings belonging to one course must use distinct slots.
    course_edge_count = 0

    for course_id, sitting_ids in course_sittings.items():
        sitting_ids = sorted(set(sitting_ids))

        for i, exam_a in enumerate(sitting_ids):
            for exam_b in sitting_ids[i + 1:]:
                if exam_b not in graph[exam_a]:
                    graph[exam_a].add(exam_b)
                    graph[exam_b].add(exam_a)
                    course_edge_count += 1

    node_count = len(graph)

    edge_count = sum(len(v) for v in graph.values()) // 2

    degrees = {
        exam_id: len(neighbors)
        for exam_id, neighbors in graph.items()
    }

    # Greedy DSATUR coloring: diagnostic only.
    colors = {}

    while len(colors) < node_count:
        remaining = set(graph) - set(colors)

        def priority(exam_id):
            saturation = len({
                colors[n]
                for n in graph[exam_id]
                if n in colors
            })

            return (
                saturation,
                degrees[exam_id],
                -exam_id,
            )

        exam_id = max(remaining, key=priority)

        unavailable = {
            colors[n]
            for n in graph[exam_id]
            if n in colors
        }

        color = 0
        while color in unavailable:
            color += 1

        colors[exam_id] = color

    greedy_color_count = max(colors.values(), default=-1) + 1

    # Connected components.
    unseen = set(graph)
    component_sizes = []

    while unseen:
        start = unseen.pop()
        stack = [start]
        size = 0

        while stack:
            node = stack.pop()
            size += 1

            for neighbor in graph[node]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)

        component_sizes.append(size)

    component_sizes.sort(reverse=True)

    # Course-pair student overlap.
    course_pair_overlap = Counter()

    for student_id, courses in student_courses.items():
        ordered = sorted(courses)

        for i, course_a in enumerate(ordered):
            for course_b in ordered[i + 1:]:
                course_pair_overlap[(course_a, course_b)] += 1

    # Student enrollment distribution.
    student_course_counts = Counter(
        len(courses)
        for courses in student_courses.values()
    )

    # Per-course sitting distribution.
    sitting_issues = []

    for course_id in sorted(course_sittings):
        sitting_ids = set(course_sittings[course_id])

        if len(sitting_ids) != 3:
            sitting_issues.append(
                (course_id, len(sitting_ids))
            )

    print("\n1. DATASET SUMMARY")
    print("-" * 72)
    print(f"Exams:                    {node_count:,}")
    print(f"Student allocations:      {len(allocations):,}")
    print(f"Students:                 {len(student_courses):,}")
    print(f"Courses:                  {len(course_students):,}")

    print("\n2. STUDENT COURSE DISTRIBUTION")
    print("-" * 72)

    for count, students in sorted(student_course_counts.items()):
        print(f"{count} courses: {students:,} students")

    print("\n3. CONFLICT GRAPH")
    print("-" * 72)
    print(f"Unique graph edges:        {edge_count:,}")
    print(f"Student conflict edges:   {student_edge_count:,}")
    print(f"Course sitting edges:     {course_edge_count:,}")
    print(f"Average degree:            {sum(degrees.values()) / max(node_count, 1):.2f}")
    print(f"Maximum degree:            {max(degrees.values(), default=0)}")
    print(f"Minimum degree:            {min(degrees.values(), default=0)}")
    print(f"Graph density:             {2 * edge_count / max(node_count * (node_count - 1), 1):.4f}")

    print("\n4. HIGHEST-DEGREE EXAMS")
    print("-" * 72)

    for exam_id, degree in sorted(
        degrees.items(),
        key=lambda item: item[1],
        reverse=True
    )[:15]:
        print(
            f"ExamID={exam_id:<6} "
            f"CourseID={exam_courses[exam_id]:<6} "
            f"Degree={degree}"
        )

    print("\n5. CONNECTED COMPONENTS")
    print("-" * 72)
    print(f"Number of components:     {len(component_sizes)}")
    print(f"Largest component:        {component_sizes[0] if component_sizes else 0}")
    print(f"Component sizes (top 10): {component_sizes[:10]}")

    print("\n6. COURSE-PAIR OVERLAP")
    print("-" * 72)
    print("Top 20 course pairs sharing students:")

    for (course_a, course_b), overlap in course_pair_overlap.most_common(20):
        print(
            f"Course {course_a:>3} <-> Course {course_b:<3} "
            f"Shared students: {overlap}"
        )

    print("\n7. COURSE SITTING DISTRIBUTION")
    print("-" * 72)

    for course_id in sorted(course_sitting_counts):
        counts = course_sitting_counts[course_id]
        print(
            f"Course {course_id:>3}: "
            f"Sitting 1={counts.get(1, 0):>4}, "
            f"Sitting 2={counts.get(2, 0):>4}, "
            f"Sitting 3={counts.get(3, 0):>4}, "
            f"Total={len(course_students[course_id]):>4}"
        )

    if sitting_issues:
        print("\nWARNING: Courses without exactly three allocated sittings:")
        print(sitting_issues[:20])
    else:
        print("\nAll courses have exactly three allocated sittings.")

    print("\n8. GREEDY DSATUR BASELINE")
    print("-" * 72)
    print(f"Colors required by this greedy run: {greedy_color_count}")
    print("Note: This is a heuristic result, not a minimum-color proof.")

    print("\n" + "=" * 72)
    print("DIAGNOSTICS COMPLETED - NO FILES OR DATABASE MODIFIED")
    print("=" * 72)


if __name__ == "__main__":
    main()
