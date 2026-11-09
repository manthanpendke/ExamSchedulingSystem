
from __future__ import annotations

import csv
import hashlib
import json
import sys

from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "dataset_config_v2.json"


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=columns,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path):
    digest = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_cohort_ranks(students):
    groups = defaultdict(list)

    for student in students:
        key = (
            student["Programme"],
            int(student["YearOfStudy"]),
        )
        groups[key].append(int(student["StudentID"]))

    ranks = {}

    for key, ids in groups.items():
        for rank, student_id in enumerate(sorted(ids)):
            ranks[student_id] = rank

    return ranks, groups


def validate_inputs(
    students,
    enrollments,
    exams,
    exam_enrollments,
    offerings,
    classifications,
):
    errors = []

    student_by_id = {
        int(x["StudentID"]): x for x in students
    }

    course_offering = {
        int(x["CourseID"]): x for x in offerings
    }

    classification_by_enrollment = {
        int(x["EnrollmentID"]): x for x in classifications
    }

    enrollment_by_id = {
        int(x["EnrollmentID"]): x for x in enrollments
    }

    exam_by_course = defaultdict(list)

    for exam in exams:
        exam_by_course[int(exam["CourseID"])].append(exam)

    for course_id, course_exams in exam_by_course.items():
        if len(course_exams) != 3:
            errors.append(
                f"Course {course_id}: expected 3 sittings, "
                f"found {len(course_exams)}."
            )

    if len(enrollment_by_id) != len(enrollments):
        errors.append("Duplicate EnrollmentID in Enrollment.csv.")

    if len(classification_by_enrollment) != len(classifications):
        errors.append("Duplicate EnrollmentID in classification metadata.")

    if set(enrollment_by_id) != set(classification_by_enrollment):
        errors.append(
            "Enrollment and classification metadata do not match."
        )

    existing_ids = [
        int(x["EnrollmentID"]) for x in exam_enrollments
    ]

    if len(existing_ids) != len(set(existing_ids)):
        errors.append("Duplicate EnrollmentID in ExamEnrollment.csv.")

    if set(existing_ids) != set(enrollment_by_id):
        errors.append(
            "ExamEnrollment and Enrollment ID sets do not match."
        )

    student_enrollments = defaultdict(list)

    for enrollment in enrollments:
        enrollment_id = int(enrollment["EnrollmentID"])
        student_id = int(enrollment["StudentID"])
        course_id = int(enrollment["CourseID"])

        student = student_by_id.get(student_id)
        offering = course_offering.get(course_id)
        classification = classification_by_enrollment.get(enrollment_id)

        if student is None:
            errors.append(f"Enrollment {enrollment_id}: unknown student.")
            continue

        if offering is None:
            errors.append(f"Enrollment {enrollment_id}: missing course offering.")
            continue

        if classification is None:
            errors.append(f"Enrollment {enrollment_id}: missing classification.")
            continue

        if (
            student["Programme"] != offering["Programme"]
            or int(student["YearOfStudy"]) != int(offering["YearOfStudy"])
        ):
            errors.append(
                f"Enrollment {enrollment_id}: course is outside "
                "the student's programme/year cohort."
            )

        if int(classification["CourseID"]) != course_id:
            errors.append(
                f"Enrollment {enrollment_id}: classification CourseID mismatch."
            )

        if int(classification["StudentID"]) != student_id:
            errors.append(
                f"Enrollment {enrollment_id}: classification StudentID mismatch."
            )

        if int(classification["CourseLane"]) != int(offering["CourseLane"]):
            errors.append(
                f"Enrollment {enrollment_id}: course lane mismatch."
            )

        student_enrollments[student_id].append(enrollment)

    for student_id, rows in student_enrollments.items():
        compulsory = [
            r for r in rows
            if classification_by_enrollment[
                int(r["EnrollmentID"])
            ]["EnrollmentType"] == "COMPULSORY"
        ]

        optional = [
            r for r in rows
            if classification_by_enrollment[
                int(r["EnrollmentID"])
            ]["EnrollmentType"] == "OPTIONAL"
        ]

        if not 2 <= len(compulsory) <= 3:
            errors.append(
                f"Student {student_id}: compulsory course count "
                "must be 2 or 3."
            )

        if len(optional) > 1:
            errors.append(
                f"Student {student_id}: more than one optional course."
            )

        compulsory_lanes = [
            int(course_offering[int(r["CourseID"])]["CourseLane"])
            for r in compulsory
        ]

        if len(compulsory_lanes) != len(set(compulsory_lanes)):
            errors.append(
                f"Student {student_id}: compulsory courses share a lane."
            )

        if optional and len(compulsory) == 2:
            optional_lane = int(
                course_offering[int(optional[0]["CourseID"])]["CourseLane"]
            )

            if optional_lane in compulsory_lanes:
                errors.append(
                    f"Student {student_id}: optional course must fill "
                    "the unused lane."
                )

        if optional and len(compulsory) == 3:
            optional_lane = int(
                course_offering[int(optional[0]["CourseID"])]["CourseLane"]
            )

            if optional_lane != 1:
                errors.append(
                    f"Student {student_id}: optional fourth course "
                    "must use the alternate lane-1 offering."
                )

    return errors


def allocate_sittings(
    students,
    enrollments,
    exams,
    exam_enrollments,
    offerings,
    classifications,
):
    ranks, cohort_groups = build_cohort_ranks(students)

    offering_by_course = {
        int(x["CourseID"]): x for x in offerings
    }

    classification_by_enrollment = {
        int(x["EnrollmentID"]): x for x in classifications
    }

    exams_by_course = defaultdict(list)

    for exam in exams:
        exams_by_course[int(exam["CourseID"])].append(exam)

    for course_id in exams_by_course:
        exams_by_course[course_id].sort(
            key=lambda x: int(x["ExamID"])
        )

    exam_enrollment_id_by_enrollment = {
        int(x["EnrollmentID"]): int(x["ExamEnrollmentID"])
        for x in exam_enrollments
    }

    registered_at_by_enrollment = {
        int(x["EnrollmentID"]): x["RegisteredAt"]
        for x in exam_enrollments
    }

    allocations = []
    output_exam_enrollments = []

    sitting_loads = defaultdict(lambda: [0, 0, 0])
    ordinal_reuse = Counter()
    student_courses = defaultdict(list)

    for enrollment in enrollments:
        student_id = int(enrollment["StudentID"])
        enrollment_id = int(enrollment["EnrollmentID"])
        course_id = int(enrollment["CourseID"])

        offering = offering_by_course[course_id]

        lane = int(offering["CourseLane"])
        rank = ranks[student_id]

        # Deterministic cohort rotation:
        # same lane gets the same ordinal for a given cohort rank.
        ordinal = ((rank + lane - 1) % 3) + 1

        selected_exam = exams_by_course[course_id][ordinal - 1]
        exam_id = int(selected_exam["ExamID"])

        enrollment_type = classification_by_enrollment[
            enrollment_id
        ]["EnrollmentType"]

        sitting_loads[course_id][ordinal - 1] += 1

        student_courses[student_id].append({
            "CourseID": course_id,
            "CourseLane": lane,
            "SittingOrdinal": ordinal,
            "EnrollmentType": enrollment_type,
        })

        output_exam_enrollments.append({
            "ExamEnrollmentID": exam_enrollment_id_by_enrollment[
                enrollment_id
            ],
            "ExamID": exam_id,
            "EnrollmentID": enrollment_id,
            "CourseID": course_id,
            "ParticipationStatus": "REGISTERED",
            "RegisteredAt": registered_at_by_enrollment[enrollment_id],
        })

        allocations.append({
            "EnrollmentID": enrollment_id,
            "StudentID": student_id,
            "CourseID": course_id,
            "ExamID": exam_id,
            "SittingOrdinal": ordinal,
            "CourseLane": lane,
            "EnrollmentType": enrollment_type,
            "Programme": offering["Programme"],
            "YearOfStudy": int(offering["YearOfStudy"]),
            "CohortRank": rank,
        })

    for student_id, rows in student_courses.items():
        ordinals = [x["SittingOrdinal"] for x in rows]

        ordinal_reuse[
            len(ordinals) - len(set(ordinals))
        ] += 1

    output_exam_enrollments.sort(
        key=lambda x: int(x["ExamEnrollmentID"])
    )

    allocations.sort(
        key=lambda x: int(x["EnrollmentID"])
    )

    report = {
        "algorithm": "cohort_lane_rotation_v2_1",
        "students_processed": len(students),
        "enrollments_allocated": len(allocations),
        "cohort_count": len(cohort_groups),
        "students_with_ordinal_reuse": sum(
            count
            for reuse, count in ordinal_reuse.items()
            if reuse > 0
        ),
        "ordinal_reuse_distribution": {
            str(k): v for k, v in sorted(ordinal_reuse.items())
        },
        "course_sitting_distribution": {
            str(course_id): {
                f"Sitting_{i + 1}": loads[i]
                for i in range(3)
            }
            for course_id, loads in sorted(sitting_loads.items())
        },
    }

    return output_exam_enrollments, allocations, report


def validate_allocations(
    students,
    enrollments,
    exams,
    allocations,
    offerings,
    classifications,
):
    errors = []

    enrollment_ids = {
        int(x["EnrollmentID"]) for x in enrollments
    }

    exam_by_id = {
        int(x["ExamID"]): x for x in exams
    }

    offering_by_course = {
        int(x["CourseID"]): x for x in offerings
    }

    classification_by_enrollment = {
        int(x["EnrollmentID"]): x for x in classifications
    }

    allocation_counts = Counter(
        int(x["EnrollmentID"]) for x in allocations
    )

    sitting_counts = Counter()

    for row in allocations:
        enrollment_id = int(row["EnrollmentID"])
        exam_id = int(row["ExamID"])
        course_id = int(row["CourseID"])
        student_id = int(row["StudentID"])
        ordinal = int(row["SittingOrdinal"])

        exam = exam_by_id.get(exam_id)

        if exam is None:
            errors.append(f"Unknown ExamID {exam_id}.")
            continue

        if int(exam["CourseID"]) != course_id:
            errors.append(
                f"Enrollment {enrollment_id}: exam/course mismatch."
            )

        if ordinal not in (1, 2, 3):
            errors.append(
                f"Enrollment {enrollment_id}: invalid sitting ordinal."
            )

        sitting_counts[(course_id, ordinal)] += 1

        offering = offering_by_course[course_id]
        classification = classification_by_enrollment[enrollment_id]

        expected_ordinal = (
            (
                int(row["CohortRank"])
                + int(offering["CourseLane"])
                - 1
            ) % 3
        ) + 1

        if ordinal != expected_ordinal:
            errors.append(
                f"Enrollment {enrollment_id}: sitting formula mismatch."
            )

        if int(classification["StudentID"]) != student_id:
            errors.append(
                f"Enrollment {enrollment_id}: student mismatch."
            )

    for enrollment_id in enrollment_ids:
        if allocation_counts[enrollment_id] != 1:
            errors.append(
                f"Enrollment {enrollment_id}: expected one allocation."
            )

    course_ids = {
        int(x["CourseID"]) for x in exams
    }

    for course_id in course_ids:
        for ordinal in (1, 2, 3):
            if sitting_counts[(course_id, ordinal)] == 0:
                errors.append(
                    f"Course {course_id}: sitting {ordinal} has no students."
                )

    return errors


def main():
    config = load_config()

    base_dir = ROOT / config["output_directory"]
    metadata_dir = base_dir / "metadata"
    output_dir = base_dir / "cohort_allocation"

    print("=" * 70)
    print("COHORT SITTING ALLOCATOR V2.1.0")
    print("=" * 70)

    students = read_csv(base_dir / "Student.csv")
    enrollments = read_csv(base_dir / "Enrollment.csv")
    exams = read_csv(base_dir / "Exam.csv")
    exam_enrollments = read_csv(base_dir / "ExamEnrollment.csv")

    offerings = read_csv(
        metadata_dir / "CourseOffering.csv"
    )

    classifications = read_csv(
        metadata_dir / "EnrollmentClassification.csv"
    )

    errors = validate_inputs(
        students,
        enrollments,
        exams,
        exam_enrollments,
        offerings,
        classifications,
    )

    if errors:
        print("\nINPUT VALIDATION FAILED")
        for error in errors[:100]:
            print(" -", error)
        print(f"Total errors: {len(errors)}")
        return 1

    allocated_exam_enrollments, allocations, report = allocate_sittings(
        students,
        enrollments,
        exams,
        exam_enrollments,
        offerings,
        classifications,
    )

    errors = validate_allocations(
        students,
        enrollments,
        exams,
        allocations,
        offerings,
        classifications,
    )

    if errors:
        print("\nALLOCATION VALIDATION FAILED")
        for error in errors[:100]:
            print(" -", error)
        print(f"Total errors: {len(errors)}")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    exam_enrollment_columns = [
        "ExamEnrollmentID",
        "ExamID",
        "EnrollmentID",
        "CourseID",
        "ParticipationStatus",
        "RegisteredAt",
    ]

    allocation_columns = [
        "EnrollmentID",
        "StudentID",
        "CourseID",
        "ExamID",
        "SittingOrdinal",
        "CourseLane",
        "EnrollmentType",
        "Programme",
        "YearOfStudy",
        "CohortRank",
    ]

    exam_enrollment_path = output_dir / "ExamEnrollment.csv"
    allocation_path = output_dir / "SittingAllocation.csv"

    write_csv(
        exam_enrollment_path,
        allocated_exam_enrollments,
        exam_enrollment_columns,
    )

    write_csv(
        allocation_path,
        allocations,
        allocation_columns,
    )

    report["status"] = "PASSED"
    report["validation_errors"] = []
    report["output_directory"] = str(output_dir)

    report_path = output_dir / "allocation_report.json"

    report_path.write_text(
        json.dumps(report, indent=4),
        encoding="utf-8",
    )

    manifest = {
        "version": config["version"],
        "seed": config["seed"],
        "files": {
            "ExamEnrollment.csv": sha256_file(exam_enrollment_path),
            "SittingAllocation.csv": sha256_file(allocation_path),
            "allocation_report.json": sha256_file(report_path),
        },
    }

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=4),
        encoding="utf-8",
    )

    print("\nALLOCATION COMPLETED")
    print(f"Students: {report['students_processed']:,}")
    print(f"Enrollments: {report['enrollments_allocated']:,}")
    print(f"Cohorts: {report['cohort_count']}")
    print(
        "Students with repeated sitting ordinal: "
        f"{report['students_with_ordinal_reuse']:,}"
    )
    print("Validation: PASSED")
    print(f"Output: {output_dir}")
    print("Original source CSV files: UNCHANGED")
    print("SQL Server: NOT MODIFIED")

    return 0


if __name__ == "__main__":
    sys.exit(main())
