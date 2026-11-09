
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

from data_generation import dataset_generator as base

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "dataset_config.json"
OUTPUT_ROOT = PROJECT_ROOT / "output_v120"

VERSION = "1.2.0"
SEED = 20261108
OPTIONAL_RATE = 0.65
COHORT_SIZE = 200


def student_number(code):
    return int(code.rsplit("-", 1)[-1])


def build_bundles(courses):
    courses = sorted(courses, key=lambda r: r["CourseCode"])

    if len(courses) % 4:
        raise ValueError("Course count must be divisible by four.")

    bundles = {}

    for index in range(0, len(courses), 4):
        cohort = index // 4
        group = courses[index:index + 4]
        core_count = 3 if cohort % 2 == 0 else 2

        bundles[cohort] = {
            "cohort": f"COHORT-{cohort + 1:03d}",
            "core": [r["CourseCode"] for r in group[:core_count]],
            "optional": [r["CourseCode"] for r in group[core_count:]],
        }

    return bundles


def create_enrollments(data):
    bundles = build_bundles(data["Course"])
    enrollments = []
    classifications = []

    for student in sorted(
        data["Student"],
        key=lambda r: student_number(r["StudentCode"])
    ):
        number = student_number(student["StudentCode"])
        cohort_index = (number - 1) // COHORT_SIZE

        if cohort_index not in bundles:
            raise ValueError(f"No course bundle for {student['StudentCode']}")

        bundle = bundles[cohort_index]

        def add(course_code, enrollment_type):
            enrollments.append({
                "StudentCode": student["StudentCode"],
                "CourseCode": course_code,
                "EnrollmentDate": base.date(2026, 1, 5),
                "EnrollmentStatus": "ENROLLED",
                "EffectiveFrom": base.date(2026, 1, 5),
                "EffectiveTo": None,
            })

            classifications.append({
                "StudentCode": student["StudentCode"],
                "CourseCode": course_code,
                "EnrollmentType": enrollment_type,
                "CohortCode": bundle["cohort"],
                "OptionalCoursePool": "|".join(bundle["optional"]),
            })

        for course in bundle["core"]:
            add(course, "COMPULSORY")

        pool = bundle["optional"]

        decision = int(hashlib.sha256(
            f"{SEED}:{student['StudentCode']}:OPTIONAL".encode()
        ).hexdigest()[:8], 16) / 0xFFFFFFFF

        if pool and decision < OPTIONAL_RATE:
            choice_hash = hashlib.sha256(
                f"{SEED}:{student['StudentCode']}:CHOICE".encode()
            ).hexdigest()

            selected = pool[int(choice_hash[:8], 16) % len(pool)]
            add(selected, "OPTIONAL")

    data["Enrollment"] = sorted(
        enrollments,
        key=lambda r: (r["StudentCode"], r["CourseCode"])
    )

    return sorted(
        classifications,
        key=lambda r: (r["StudentCode"], r["CourseCode"])
    )


def assign_sittings(data):
    course_exams = defaultdict(list)
    course_students = defaultdict(list)

    for exam in data["Exam"]:
        course_exams[exam["CourseCode"]].append(exam["ExamCode"])

    for enrollment in data["Enrollment"]:
        course_students[enrollment["CourseCode"]].append(
            enrollment["StudentCode"]
        )

    assignments = []

    for course, students in sorted(course_students.items()):
        sittings = sorted(course_exams[course])

        if len(sittings) != 3:
            raise ValueError(f"{course} does not have exactly 3 sittings.")

        ranked = sorted(
            set(students),
            key=lambda student: hashlib.sha256(
                f"{SEED}:{course}:{student}".encode()
            ).hexdigest()
        )

        for index, student in enumerate(ranked):
            assignments.append({
                "ExamCode": sittings[index % 3],
                "StudentCode": student,
                "CourseCode": course,
                "ParticipationStatus": "REGISTERED",
            })

    data["ExamEnrollment"] = sorted(
        assignments,
        key=lambda r: (r["ExamCode"], r["StudentCode"])
    )


def validate_v120(data, classifications, config):
    base.validate_dataset(data, config, "full")

    by_student = defaultdict(list)

    for row in classifications:
        by_student[row["StudentCode"]].append(row)

    if len(by_student) != len(data["Student"]):
        raise ValueError("Missing student enrollment classifications.")

    for student in data["Student"]:
        rows = by_student[student["StudentCode"]]
        compulsory = sum(
            r["EnrollmentType"] == "COMPULSORY" for r in rows
        )
        optional = sum(
            r["EnrollmentType"] == "OPTIONAL" for r in rows
        )

        if compulsory not in (2, 3) or optional not in (0, 1):
            raise ValueError(
                f"Invalid bundle for {student['StudentCode']}: "
                f"{compulsory} compulsory, {optional} optional."
            )

    expected = {
        (r["StudentCode"], r["CourseCode"])
        for r in data["Enrollment"]
    }

    actual = {
        (r["StudentCode"], r["CourseCode"])
        for r in classifications
    }

    if expected != actual:
        raise ValueError("Enrollment classification mismatch.")

    assigned = defaultdict(int)

    for row in data["ExamEnrollment"]:
        assigned[(row["StudentCode"], row["CourseCode"])] += 1

    if set(assigned) != expected:
        raise ValueError("Some course enrollments have no sitting assignment.")

    if any(count != 1 for count in assigned.values()):
        raise ValueError("A student has multiple sittings for one course.")

    sitting_counts = defaultdict(int)

    for row in data["ExamEnrollment"]:
        sitting_counts[row["ExamCode"]] += 1

    for exam in data["Exam"]:
        if sitting_counts[exam["ExamCode"]] == 0:
            raise ValueError(f"Empty sitting: {exam['ExamCode']}")


def write_classification(rows, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)

    fields = [
        "StudentCode",
        "CourseCode",
        "EnrollmentType",
        "CohortCode",
        "OptionalCoursePool",
    ]

    with (output_dir / "enrollment_classification.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    (output_dir / "enrollment_classification.json").write_text(
        json.dumps(rows, indent=2),
        encoding="utf-8"
    )


def main():
    config = deepcopy(
        json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    )

    config["dataset"]["version"] = VERSION
    config["dataset"]["random_seed"] = SEED
    config["generation"]["default_profile"] = "full"
    config["generation"]["enrollment_min_courses"] = 2
    config["generation"]["enrollment_max_courses"] = 4
    config["generation"]["ground_truth_separate"] = True
    config["generation"]["validate_before_export"] = True

    profile = "full"
    counts = config["profiles"][profile]

    if (
        counts["students"] != 5000
        or counts["courses"] != 100
        or counts["exams"] != 300
    ):
        raise ValueError("Unexpected full-profile dataset dimensions.")

    output = OUTPUT_ROOT / profile / f"v{VERSION}"

    if output.exists() and any(output.iterdir()):
        raise FileExistsError(
            f"Refusing to overwrite existing output: {output}"
        )

    output.mkdir(parents=True, exist_ok=True)

    print("Generating v1.2.0...")
    data = base.generate_dataset(config, profile)

    print("Building structured course enrollments...")
    classifications = create_enrollments(data)

    print("Assigning students to balanced exam sittings...")
    assign_sittings(data)

    print("Running independent dataset validation...")
    validate_v120(data, classifications, config)

    baseline = {
        name: rows for name, rows in data.items()
        if name != "GroundTruth"
    }

    ground_truth = {"GroundTruth": data["GroundTruth"]}
    formats = set(config["dataset"]["output_format"])

    if "csv" in formats:
        base.write_csv_files(baseline, output / "csv")
        base.write_csv_files(
            ground_truth, output / "ground_truth" / "csv"
        )

    if "json" in formats:
        base.write_json_files(baseline, output / "json")
        base.write_json_files(
            ground_truth, output / "ground_truth" / "json"
        )

    if "sql" in formats:
        base.write_sql_file(baseline, output / "sql")
        base.write_ground_truth_sql_file(
            data["GroundTruth"],
            output / "ground_truth" / "sql"
        )

    write_classification(classifications, output / "metadata")

    summary = {
        "version": VERSION,
        "seed": SEED,
        "students": len(data["Student"]),
        "courses": len(data["Course"]),
        "exams": len(data["Exam"]),
        "enrollments": len(data["Enrollment"]),
        "exam_enrollments": len(data["ExamEnrollment"]),
        "compulsory_enrollments": sum(
            r["EnrollmentType"] == "COMPULSORY"
            for r in classifications
        ),
        "optional_enrollments": sum(
            r["EnrollmentType"] == "OPTIONAL"
            for r in classifications
        ),
        "sql_import_performed": False,
    }

    (output / "v120_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8"
    )

    print(json.dumps(summary, indent=2))
    print("v1.2.0 generated and validated. No SQL writes performed.")


if __name__ == "__main__":
    main()
