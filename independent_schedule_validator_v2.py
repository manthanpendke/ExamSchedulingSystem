
from __future__ import annotations

import csv
import hashlib
import json
import sys

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


# ============================================================
# EXAM SCHEDULING SYSTEM - INDEPENDENT VALIDATOR V2.1.0
# ============================================================

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "dataset_config_v2.json"

EXPECTED_VERSION = "2.1.0"

# These slots are independently defined from the timetable
# allocator. They must match the approved v2.1.0 timetable.
TIME_SLOTS = {
    1: {"day": 1, "start": "08:00", "end": "09:30"},
    2: {"day": 1, "start": "10:00", "end": "11:30"},
    3: {"day": 1, "start": "13:00", "end": "14:30"},
    4: {"day": 1, "start": "15:00", "end": "16:30"},
    5: {"day": 2, "start": "08:00", "end": "09:30"},
    6: {"day": 2, "start": "10:00", "end": "11:30"},
    7: {"day": 2, "start": "13:00", "end": "14:30"},
    8: {"day": 2, "start": "15:00", "end": "16:30"},
}

EXPECTED_DATES = {
    1: "2026-11-16",
    2: "2026-11-17",
}

REQUIRED_COLUMNS = {
    "Student.csv": {
        "StudentID",
    },
    "Enrollment.csv": {
        "EnrollmentID",
        "StudentID",
        "CourseID",
    },
    "Exam.csv": {
        "ExamID",
        "CourseID",
        "ExamCode",
    },
    "SittingAllocation.csv": {
        "EnrollmentID",
        "StudentID",
        "CourseID",
        "ExamID",
        "SittingOrdinal",
    },
    "ExamTimetable.csv": {
        "ExamID",
        "CourseID",
        "ExamCode",
        "SittingSlotID",
        "DayNumber",
        "ExamDate",
        "StartTime",
        "EndTime",
        "StudentCount",
    },
}


class IndependentValidator:

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.checks = Counter()
        self.metrics = {}

    def error(self, code, message):
        self.errors.append({
            "code": code,
            "message": message,
        })

    def warning(self, code, message):
        self.warnings.append({
            "code": code,
            "message": message,
        })

    @staticmethod
    def read_csv(path):
        if not path.exists():
            raise FileNotFoundError(
                f"Required input file not found: {path}"
            )

        with path.open(
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as file:
            reader = csv.DictReader(file)

            if not reader.fieldnames:
                raise ValueError(
                    f"CSV has no header: {path}"
                )

            return list(reader), set(reader.fieldnames)

    @staticmethod
    def sha256(path):
        digest = hashlib.sha256()

        with path.open("rb") as file:
            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b""
            ):
                digest.update(chunk)

        return digest.hexdigest()

    @staticmethod
    def integer(value, field):
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"Invalid integer in {field}: {value!r}"
            )

    @staticmethod
    def parse_datetime(date_value, time_value):
        return datetime.strptime(
            f"{date_value} {time_value}",
            "%Y-%m-%d %H:%M"
        )

    def load_inputs(self):
        if not CONFIG_PATH.exists():
            raise FileNotFoundError(
                f"Configuration not found: {CONFIG_PATH}"
            )

        config = json.loads(
            CONFIG_PATH.read_text(encoding="utf-8")
        )

        version = str(config.get("version", ""))

        if version != EXPECTED_VERSION:
            raise ValueError(
                f"Expected configuration version "
                f"{EXPECTED_VERSION}, found {version!r}."
            )

        base_dir = ROOT / config["output_directory"]
        allocation_dir = base_dir / "cohort_allocation"

        paths = {
            "Student.csv": base_dir / "Student.csv",
            "Enrollment.csv": base_dir / "Enrollment.csv",
            "Exam.csv": base_dir / "Exam.csv",
            "SittingAllocation.csv":
                allocation_dir / "SittingAllocation.csv",
            "ExamTimetable.csv":
                allocation_dir / "ExamTimetable.csv",
        }

        data = {}

        for filename, path in paths.items():
            rows, columns = self.read_csv(path)

            missing = REQUIRED_COLUMNS[filename] - columns

            if missing:
                raise ValueError(
                    f"{filename} is missing columns: "
                    f"{sorted(missing)}"
                )

            data[filename] = rows

        self.base_dir = base_dir
        self.allocation_dir = allocation_dir
        self.paths = paths
        self.config = config

        return data

    def validate_source_records(self, data):
        students = data["Student.csv"]
        enrollments = data["Enrollment.csv"]
        exams = data["Exam.csv"]
        allocations = data["SittingAllocation.csv"]
        timetable = data["ExamTimetable.csv"]

        student_ids = [
            self.integer(x["StudentID"], "StudentID")
            for x in students
        ]

        if len(student_ids) != len(set(student_ids)):
            self.error(
                "DUPLICATE_STUDENT",
                "Student.csv contains duplicate StudentID values."
            )

        student_set = set(student_ids)

        self.checks["students_examined"] = len(student_ids)

        # ----------------------------------------------------
        # Source enrollment validation
        # ----------------------------------------------------

        enrollment_by_id = {}
        enrollment_keys = set()

        for row in enrollments:
            enrollment_id = self.integer(
                row["EnrollmentID"], "EnrollmentID"
            )
            student_id = self.integer(
                row["StudentID"], "Enrollment.StudentID"
            )
            course_id = self.integer(
                row["CourseID"], "Enrollment.CourseID"
            )

            if enrollment_id in enrollment_by_id:
                self.error(
                    "DUPLICATE_ENROLLMENT_ID",
                    f"Duplicate EnrollmentID {enrollment_id}."
                )
                continue

            enrollment_by_id[enrollment_id] = (
                student_id,
                course_id,
            )

            key = (student_id, course_id)

            if key in enrollment_keys:
                self.error(
                    "DUPLICATE_STUDENT_COURSE_ENROLLMENT",
                    f"Duplicate enrollment for student {student_id}, "
                    f"course {course_id}."
                )

            enrollment_keys.add(key)

            if student_id not in student_set:
                self.error(
                    "UNKNOWN_ENROLLED_STUDENT",
                    f"Enrollment {enrollment_id} references "
                    f"unknown student {student_id}."
                )

        self.checks["source_enrollments"] = len(enrollments)

        # ----------------------------------------------------
        # Exam validation
        # ----------------------------------------------------

        exam_by_id = {}
        exams_by_course = defaultdict(list)

        for row in exams:
            exam_id = self.integer(
                row["ExamID"], "ExamID"
            )
            course_id = self.integer(
                row["CourseID"], "Exam.CourseID"
            )

            if exam_id in exam_by_id:
                self.error(
                    "DUPLICATE_EXAM_ID",
                    f"Duplicate ExamID {exam_id}."
                )
                continue

            exam_by_id[exam_id] = row
            exams_by_course[course_id].append(exam_id)

        self.checks["source_exams"] = len(exams)

        for course_id, exam_ids in exams_by_course.items():
            if len(exam_ids) != 3:
                self.error(
                    "INVALID_COURSE_SITTING_COUNT",
                    f"Course {course_id} has {len(exam_ids)} "
                    "exams instead of exactly 3."
                )

        # ----------------------------------------------------
        # Sitting allocation validation
        # ----------------------------------------------------

        allocation_by_enrollment = {}
        exam_students = defaultdict(set)
        student_exams = defaultdict(list)
        course_ordinal_exam = {}
        course_ordinal_counts = Counter()

        for row in allocations:
            enrollment_id = self.integer(
                row["EnrollmentID"], "Allocation.EnrollmentID"
            )
            student_id = self.integer(
                row["StudentID"], "Allocation.StudentID"
            )
            course_id = self.integer(
                row["CourseID"], "Allocation.CourseID"
            )
            exam_id = self.integer(
                row["ExamID"], "Allocation.ExamID"
            )
            ordinal = self.integer(
                row["SittingOrdinal"], "SittingOrdinal"
            )

            if enrollment_id in allocation_by_enrollment:
                self.error(
                    "DUPLICATE_ALLOCATION",
                    f"Enrollment {enrollment_id} has multiple "
                    "sitting allocations."
                )
                continue

            allocation_by_enrollment[enrollment_id] = row

            if enrollment_id not in enrollment_by_id:
                self.error(
                    "UNKNOWN_ALLOCATION_ENROLLMENT",
                    f"Allocation references unknown enrollment "
                    f"{enrollment_id}."
                )
                continue

            source_student, source_course = (
                enrollment_by_id[enrollment_id]
            )

            if (
                student_id != source_student
                or course_id != source_course
            ):
                self.error(
                    "ALLOCATION_SOURCE_MISMATCH",
                    f"Allocation {enrollment_id} does not match "
                    "the source Enrollment record."
                )

            if student_id not in student_set:
                self.error(
                    "ALLOCATION_UNKNOWN_STUDENT",
                    f"Allocation references unknown student "
                    f"{student_id}."
                )

            if exam_id not in exam_by_id:
                self.error(
                    "ALLOCATION_UNKNOWN_EXAM",
                    f"Allocation references unknown exam {exam_id}."
                )
                continue

            exam_course = self.integer(
                exam_by_id[exam_id]["CourseID"],
                "Exam.CourseID"
            )

            if exam_course != course_id:
                self.error(
                    "ALLOCATION_COURSE_MISMATCH",
                    f"Enrollment {enrollment_id}: allocated course "
                    f"{course_id}, but exam {exam_id} belongs "
                    f"to course {exam_course}."
                )

            if ordinal not in (1, 2, 3):
                self.error(
                    "INVALID_SITTING_ORDINAL",
                    f"Enrollment {enrollment_id} has ordinal "
                    f"{ordinal}; expected 1, 2 or 3."
                )

            ordinal_key = (course_id, ordinal)
            existing_exam = course_ordinal_exam.get(ordinal_key)

            if existing_exam is not None and existing_exam != exam_id:
                self.error(
                    "ORDINAL_MAP_INCONSISTENT",
                    f"Course {course_id}, sitting {ordinal} maps "
                    "to multiple exams."
                )
            else:
                course_ordinal_exam[ordinal_key] = exam_id

            course_ordinal_counts[ordinal_key] += 1

            if student_id in exam_students[exam_id]:
                self.error(
                    "DUPLICATE_STUDENT_IN_EXAM",
                    f"Student {student_id} appears more than once "
                    f"in exam {exam_id}."
                )

            exam_students[exam_id].add(student_id)
            student_exams[student_id].append(exam_id)

        # No source enrollment may silently disappear.
        missing_enrollments = (
            set(enrollment_by_id)
            - set(allocation_by_enrollment)
        )

        for enrollment_id in sorted(missing_enrollments):
            self.error(
                "ENROLLMENT_NOT_ALLOCATED",
                f"Source enrollment {enrollment_id} has no "
                "exam sitting allocation."
            )

        # Every course must have three sitting ordinals.
        for course_id in exams_by_course:
            for ordinal in (1, 2, 3):
                if (course_id, ordinal) not in course_ordinal_exam:
                    self.error(
                        "COURSE_SITTING_MISSING",
                        f"Course {course_id} has no allocation "
                        f"for sitting {ordinal}."
                    )

        self.checks["sitting_allocations"] = len(allocations)
        self.metrics["students_with_enrollments"] = len(
            student_exams
        )
        self.metrics["students_with_four_courses"] = sum(
            1 for values in student_exams.values()
            if len(values) == 4
        )

        # ----------------------------------------------------
        # Optional / compulsory classification audit
        # ----------------------------------------------------

        classification_path = (
            self.base_dir
            / "metadata"
            / "EnrollmentClassification.csv"
        )

        if classification_path.exists():
            classification_rows, _ = self.read_csv(
                classification_path
            )

            classified_ids = set()

            for row in classification_rows:
                enrollment_id = self.integer(
                    row["EnrollmentID"],
                    "Classification.EnrollmentID"
                )

                if enrollment_id in classified_ids:
                    self.error(
                        "DUPLICATE_CLASSIFICATION",
                        f"Enrollment {enrollment_id} has multiple "
                        "classification records."
                    )

                classified_ids.add(enrollment_id)

                if enrollment_id not in enrollment_by_id:
                    self.error(
                        "UNKNOWN_CLASSIFIED_ENROLLMENT",
                        f"Classification references unknown "
                        f"enrollment {enrollment_id}."
                    )

            missing_classifications = (
                set(enrollment_by_id) - classified_ids
            )

            for enrollment_id in sorted(
                missing_classifications
            ):
                self.error(
                    "MISSING_ENROLLMENT_CLASSIFICATION",
                    f"Enrollment {enrollment_id} has no "
                    "classification metadata."
                )

            types = Counter(
                row.get("EnrollmentType", "").strip().upper()
                for row in classification_rows
            )

            self.metrics["enrollment_classification"] = dict(types)

            self.checks["classifications_examined"] = len(
                classification_rows
            )
        else:
            self.warning(
                "CLASSIFICATION_FILE_NOT_FOUND",
                "EnrollmentClassification.csv was not found. "
                "Compulsory/optional classification was not audited."
            )

        return exam_by_id, exam_students, student_exams

    def validate_timetable(
        self,
        data,
        exam_by_id,
        exam_students,
        student_exams,
    ):
        timetable = data["ExamTimetable.csv"]

        timetable_by_exam = {}
        student_intervals = defaultdict(list)
        course_days = defaultdict(set)
        slot_counts = Counter()

        # ----------------------------------------------------
        # Timetable row validation
        # ----------------------------------------------------

        for row in timetable:
            exam_id = self.integer(
                row["ExamID"], "Timetable.ExamID"
            )
            course_id = self.integer(
                row["CourseID"], "Timetable.CourseID"
            )
            slot_id = self.integer(
                row["SittingSlotID"], "SittingSlotID"
            )
            day_number = self.integer(
                row["DayNumber"], "DayNumber"
            )
            student_count = self.integer(
                row["StudentCount"], "StudentCount"
            )

            if exam_id in timetable_by_exam:
                self.error(
                    "DUPLICATE_TIMETABLE_EXAM",
                    f"Exam {exam_id} appears more than once."
                )
                continue

            timetable_by_exam[exam_id] = row

            if exam_id not in exam_by_id:
                self.error(
                    "UNKNOWN_TIMETABLE_EXAM",
                    f"Timetable references unknown exam {exam_id}."
                )
                continue

            source_exam = exam_by_id[exam_id]
            source_course = self.integer(
                source_exam["CourseID"], "Exam.CourseID"
            )

            if source_course != course_id:
                self.error(
                    "TIMETABLE_COURSE_MISMATCH",
                    f"Exam {exam_id}: timetable course {course_id}, "
                    f"source course {source_course}."
                )

            if row["ExamCode"] != source_exam["ExamCode"]:
                self.error(
                    "TIMETABLE_EXAM_CODE_MISMATCH",
                    f"Exam {exam_id} has an incorrect ExamCode."
                )

            if slot_id not in TIME_SLOTS:
                self.error(
                    "INVALID_SLOT_ID",
                    f"Exam {exam_id} has invalid slot {slot_id}."
                )
                continue

            slot = TIME_SLOTS[slot_id]

            if day_number != slot["day"]:
                self.error(
                    "SLOT_DAY_MISMATCH",
                    f"Exam {exam_id}: slot {slot_id} belongs to "
                    f"day {slot['day']}, not day {day_number}."
                )

            expected_date = EXPECTED_DATES[slot["day"]]

            if row["ExamDate"] != expected_date:
                self.error(
                    "INVALID_EXAM_DATE",
                    f"Exam {exam_id}: expected {expected_date}, "
                    f"found {row['ExamDate']}."
                )

            if row["StartTime"] != slot["start"]:
                self.error(
                    "INVALID_START_TIME",
                    f"Exam {exam_id}: expected {slot['start']}, "
                    f"found {row['StartTime']}."
                )

            if row["EndTime"] != slot["end"]:
                self.error(
                    "INVALID_END_TIME",
                    f"Exam {exam_id}: expected {slot['end']}, "
                    f"found {row['EndTime']}."
                )

            try:
                start = self.parse_datetime(
                    row["ExamDate"], row["StartTime"]
                )
                end = self.parse_datetime(
                    row["ExamDate"], row["EndTime"]
                )
            except ValueError as exc:
                self.error(
                    "INVALID_DATETIME",
                    f"Exam {exam_id}: {exc}"
                )
                continue

            if end <= start:
                self.error(
                    "INVALID_EXAM_INTERVAL",
                    f"Exam {exam_id} ends before or at its start."
                )
                continue

            duration = int(
                (end - start).total_seconds() // 60
            )

            if duration != 90:
                self.error(
                    "INVALID_BASE_DURATION",
                    f"Exam {exam_id} has {duration} minutes; "
                    "expected 90 minutes in the base timetable."
                )

            expected_count = len(exam_students.get(exam_id, set()))

            if student_count != expected_count:
                self.error(
                    "STUDENT_COUNT_MISMATCH",
                    f"Exam {exam_id}: timetable says "
                    f"{student_count}, allocation contains "
                    f"{expected_count}."
                )

            course_days[course_id].add(day_number)
            slot_counts[slot_id] += 1

            for student_id in exam_students.get(exam_id, set()):
                student_intervals[student_id].append(
                    (start, end, exam_id)
                )

        # ----------------------------------------------------
        # Every source exam must appear in timetable
        # ----------------------------------------------------

        missing_exams = (
            set(exam_by_id) - set(timetable_by_exam)
        )

        for exam_id in sorted(missing_exams):
            self.error(
                "EXAM_NOT_SCHEDULED",
                f"Source exam {exam_id} is missing from timetable."
            )

        unknown_exams = (
            set(timetable_by_exam) - set(exam_by_id)
        )

        for exam_id in sorted(unknown_exams):
            self.error(
                "UNKNOWN_SCHEDULED_EXAM",
                f"Timetable contains unknown exam {exam_id}."
            )

        # ----------------------------------------------------
        # Independent student overlap detection
        # ----------------------------------------------------

        overlap_count = 0

        for student_id, intervals in student_intervals.items():
            intervals.sort(key=lambda x: (x[0], x[1]))

            for index, first in enumerate(intervals):
                for second in intervals[index + 1:]:
                    if second[0] >= first[1]:
                        break

                    if (
                        first[0] < second[1]
                        and second[0] < first[1]
                    ):
                        overlap_count += 1

                        self.error(
                            "STUDENT_EXAM_OVERLAP",
                            f"Student {student_id} has overlapping "
                            f"exams {first[2]} and {second[2]}."
                        )

        self.checks["student_intervals_examined"] = sum(
            len(values) for values in student_intervals.values()
        )

        self.metrics["student_overlap_count"] = overlap_count

        # ----------------------------------------------------
        # Same-course sitting separation
        # ----------------------------------------------------

        course_slots = defaultdict(set)

        for exam_id, row in timetable_by_exam.items():
            course_id = self.integer(
                row["CourseID"], "Timetable.CourseID"
            )
            slot_id = self.integer(
                row["SittingSlotID"], "SittingSlotID"
            )
            course_slots[course_id].add(slot_id)

        for course_id, slots in course_slots.items():
            if len(slots) != 3:
                self.error(
                    "COURSE_SITTINGS_NOT_DISTINCT",
                    f"Course {course_id} uses {len(slots)} "
                    "distinct slots instead of 3."
                )

        # ----------------------------------------------------
        # Course date grouping objective
        # ----------------------------------------------------

        same_day = 0
        two_consecutive_days = 0
        invalid_spread = 0

        for course_id, days in course_days.items():
            ordered_days = sorted(days)

            if len(ordered_days) == 1:
                same_day += 1

            elif (
                len(ordered_days) == 2
                and ordered_days[1] - ordered_days[0] == 1
            ):
                two_consecutive_days += 1

            else:
                invalid_spread += 1

                self.error(
                    "COURSE_DATE_SPREAD",
                    f"Course {course_id} sittings span "
                    f"non-consecutive or excessive days: {ordered_days}."
                )

        self.metrics["courses_all_sittings_same_day"] = same_day
        self.metrics["courses_using_two_consecutive_days"] = (
            two_consecutive_days
        )
        self.metrics["courses_with_invalid_date_spread"] = (
            invalid_spread
        )

        self.metrics["slot_distribution"] = {
            str(slot): count
            for slot, count in sorted(slot_counts.items())
        }

        self.checks["timetable_rows_examined"] = len(timetable)

    def validate_graph_conflicts(
        self,
        exam_by_id,
        exam_students,
        timetable,
    ):
        """
        Independently rebuild the conflict graph:
        - Shared student between exams.
        - Different sittings of the same course.
        """

        graph = {
            exam_id: set()
            for exam_id in exam_by_id
        }

        exams_by_course = defaultdict(list)

        for exam_id, exam in exam_by_id.items():
            course_id = self.integer(
                exam["CourseID"], "Exam.CourseID"
            )
            exams_by_course[course_id].append(exam_id)

        for exam_ids in exams_by_course.values():
            for index, first in enumerate(exam_ids):
                for second in exam_ids[index + 1:]:
                    graph[first].add(second)
                    graph[second].add(first)

        student_exam_map = defaultdict(set)

        for exam_id, student_ids in exam_students.items():
            for student_id in student_ids:
                student_exam_map[student_id].add(exam_id)

        for exam_ids in student_exam_map.values():
            exam_ids = sorted(exam_ids)

            for index, first in enumerate(exam_ids):
                for second in exam_ids[index + 1:]:
                    graph[first].add(second)
                    graph[second].add(first)

        timetable_by_exam = {
            self.integer(row["ExamID"], "ExamID"): row
            for row in timetable
        }

        edge_count = sum(
            len(neighbors) for neighbors in graph.values()
        ) // 2

        violations = 0

        for exam_id, neighbors in graph.items():
            first = timetable_by_exam.get(exam_id)

            if first is None:
                continue

            for neighbor_id in neighbors:
                if neighbor_id <= exam_id:
                    continue

                second = timetable_by_exam.get(neighbor_id)

                if second is None:
                    continue

                first_slot = self.integer(
                    first["SittingSlotID"], "SittingSlotID"
                )
                second_slot = self.integer(
                    second["SittingSlotID"], "SittingSlotID"
                )

                if first_slot == second_slot:
                    violations += 1

                    self.error(
                        "CONFLICT_GRAPH_SLOT_COLLISION",
                        f"Conflict edge {exam_id}-{neighbor_id} "
                        f"uses slot {first_slot} for both exams."
                    )

        self.metrics["independent_conflict_edges"] = edge_count
        self.metrics["conflict_graph_slot_collisions"] = violations

    def build_report(self):
        return {
            "validator": "independent_schedule_validator_v2",
            "version": EXPECTED_VERSION,
            "status": "PASSED" if not self.errors else "FAILED",
            "sql_server_modified": False,
            "ground_truth_accessed": False,
            "inputs": {
                name: {
                    "path": str(path),
                    "sha256": self.sha256(path),
                }
                for name, path in self.paths.items()
            },
            "checks": dict(self.checks),
            "metrics": self.metrics,
            "warnings": self.warnings,
            "error_count": len(self.errors),
            "errors": self.errors,
            "scope_limitations": [
                "Room allocation has not yet been generated.",
                "Room capacity and physical occupancy are not checked.",
                "Room equipment compatibility is not checked.",
                "Room closures and accessibility are not checked.",
                "Extended-time room batching is not checked.",
                "Invigilator assignment, availability and workload "
                "are not checked."
            ],
        }

    def run(self):
        print("=" * 68)
        print("INDEPENDENT EXAM SCHEDULE VALIDATOR V2.1.0")
        print("=" * 68)

        data = self.load_inputs()

        print("\nLoaded v2.1.0 source files.")
        print("Reconstructing enrollment and exam relationships...")

        exam_by_id, exam_students, student_exams = (
            self.validate_source_records(data)
        )

        print("Checking timetable and student time intervals...")

        self.validate_timetable(
            data,
            exam_by_id,
            exam_students,
            student_exams,
        )

        print("Rebuilding conflict graph independently...")

        self.validate_graph_conflicts(
            exam_by_id,
            exam_students,
            data["ExamTimetable.csv"],
        )

        report = self.build_report()

        report_path = (
            self.allocation_dir
            / "independent_schedule_validation_report_v2.json"
        )

        report_path.write_text(
            json.dumps(report, indent=4),
            encoding="utf-8",
        )

        print("\n" + "=" * 68)
        print("VALIDATION RESULTS")
        print("=" * 68)

        for key, value in self.checks.items():
            print(f"{key:<38} {value:>10,}")

        print("\nKEY METRICS")

        for key, value in self.metrics.items():
            print(f"{key:<42} {value}")

        print(f"\nWarnings: {len(self.warnings)}")
        print(f"Errors:   {len(self.errors)}")

        if self.errors:
            print("\nVALIDATION FAILED")

            print("\nFirst 50 errors:")

            for issue in self.errors[:50]:
                print(
                    f"[{issue['code']}] "
                    f"{issue['message']}"
                )

            if len(self.errors) > 50:
                print(
                    f"... {len(self.errors) - 50} "
                    "additional errors are in the report."
                )
        else:
            print("\nVALIDATION PASSED")
            print("No timetable or student allocation violations found.")

        print("\nScope:")
        print("- Dataset and timetable independently checked.")
        print("- Room and invigilator checks pending room allocation.")
        print("- GroundTruth not accessed.")
        print("- SQL Server not modified.")

        print(f"\nJSON report: {report_path}")

        return 0 if not self.errors else 1


def main():
    try:
        validator = IndependentValidator()
        return validator.run()

    except Exception as exc:
        print("\nVALIDATOR EXECUTION ERROR")
        print(f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
