#!/usr/bin/env python3
"""
Isolated evaluator edge-case tests for Exam Scheduling System v2.2.0.

Runs the supplied independent validators against synthetic temporary projects.
Never reads or writes the user's production dataset, SQL Server, or GroundTruth.

Scenarios:
1. Student has overlapping examinations.
2. Room capacity is exceeded.
3. One invigilator is double-booked.
4. Accessible-room accommodation is ignored.
5. Exam overlaps an active room-closure interval.
6. Positive control: a valid room allocation must pass.

Exit code:
  0 = all tests passed
  1 = at least one expected violation was not detected
  2 = test harness failed to execute
"""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent

DATE = "2026-11-16"
START = "2026-11-16 09:00:00"
END = "2026-11-16 10:30:00"


def locate_script(canonical_name: str, uploaded_name: str) -> Path:
    candidates = [
        HERE / "data_validation" / canonical_name,
        HERE / "scheduling" / canonical_name,
        HERE / canonical_name,
        HERE / uploaded_name,
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]


ROOM_VALIDATOR_SOURCE = locate_script(
    "independent_room_allocation_validator_v220.py",
    "independent_room_allocation_validator_v220.py",
)

INV_VALIDATOR_SOURCE = locate_script(
    "independent_invigilator_validator_v220.py",
    "independent_invigilator_validator_v220.py",
)

ALLOCATOR_SOURCE = locate_script(
    "room_allocator_v220.py",
    "room_allocator_v220.py",
)


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def make_room_project(root: Path, scenario: str) -> Path:
    data = root / "output_v2" / "full" / "v2.2.0"
    sched = data / "scheduling"
    meta = data / "metadata"

    sched.mkdir(parents=True)
    meta.mkdir(parents=True)

    # --------------------------------------------------------
    # SCENARIO-SPECIFIC SOURCE EXAMS AND ROOMS
    # --------------------------------------------------------
    if scenario == "student_overlap":
        exams = [
            {
                "ExamID": "1",
                "CourseID": "101",
                "ExamDate": DATE,
                "StartDateTime": START,
                "EndDateTime": END,
            },
            {
                "ExamID": "2",
                "CourseID": "102",
                "ExamDate": DATE,
                "StartDateTime": START,
                "EndDateTime": END,
            },
        ]

        students = [
            {
                "EnrollmentID": "1",
                "StudentID": "501",
                "ExamID": "1",
                "StartDateTime": START,
                "EffectiveEndDateTime": END,
            },
            {
                "EnrollmentID": "2",
                "StudentID": "501",
                "ExamID": "2",
                "StartDateTime": START,
                "EffectiveEndDateTime": END,
            },
        ]

        rooms = [
            {
                "RoomID": "11",
                "IsActive": "1",
                "RoomType": "STANDARD",
            },
            {
                "RoomID": "12",
                "IsActive": "1",
                "RoomType": "STANDARD",
            },
        ]

        room_capacity = [
            {
                "RoomCapacityID": "1",
                "RoomID": "11",
                "Capacity": "10",
                "EffectiveFrom": "2026-01-01",
                "EffectiveTo": "",
            },
            {
                "RoomCapacityID": "2",
                "RoomID": "12",
                "Capacity": "10",
                "EffectiveFrom": "2026-01-01",
                "EffectiveTo": "",
            },
        ]

        allocations = [
            {
                "RoomAllocationID": "1",
                "ExamID": "1",
                "RoomID": "11",
                "StartDateTime": START,
                "EndDateTime": END,
                "AllocatedStudentCount": "1",
                "AssignedCapacity": "10",
            },
            {
                "RoomAllocationID": "2",
                "ExamID": "2",
                "RoomID": "12",
                "StartDateTime": START,
                "EndDateTime": END,
                "AllocatedStudentCount": "1",
                "AssignedCapacity": "10",
            },
        ]

        student_rooms = [
            {
                "EnrollmentID": "1",
                "StudentID": "501",
                "ExamID": "1",
                "RoomID": "11",
                "StartDateTime": START,
                "StudentEffectiveEndDateTime": END,
            },
            {
                "EnrollmentID": "2",
                "StudentID": "501",
                "ExamID": "2",
                "RoomID": "12",
                "StartDateTime": START,
                "StudentEffectiveEndDateTime": END,
            },
        ]

    else:
        student_count = (
            2 if scenario == "room_capacity" else 1
        )

        exams = [
            {
                "ExamID": "1",
                "CourseID": "101",
                "ExamDate": DATE,
                "StartDateTime": START,
                "EndDateTime": END,
            }
        ]

        students = [
            {
                "EnrollmentID": str(index + 1),
                "StudentID": str(501 + index),
                "ExamID": "1",
                "StartDateTime": START,
                "EffectiveEndDateTime": END,
            }
            for index in range(student_count)
        ]

        room_type = (
            "STANDARD"
            if scenario == "accommodation_ignored"
            else "ACCESSIBLE"
        )

        rooms = [
            {
                "RoomID": "11",
                "IsActive": "1",
                "RoomType": room_type,
            }
        ]

        room_capacity = [
            {
                "RoomCapacityID": "1",
                "RoomID": "11",
                "Capacity": (
                    "1" if scenario == "room_capacity" else "10"
                ),
                "EffectiveFrom": "2026-01-01",
                "EffectiveTo": "",
            }
        ]

        allocations = [
            {
                "RoomAllocationID": "1",
                "ExamID": "1",
                "RoomID": "11",
                "StartDateTime": START,
                "EndDateTime": END,
                "AllocatedStudentCount": str(student_count),
                "AssignedCapacity": (
                    "1" if scenario == "room_capacity" else "10"
                ),
            }
        ]

        student_rooms = [
            {
                "EnrollmentID": str(index + 1),
                "StudentID": str(501 + index),
                "ExamID": "1",
                "RoomID": "11",
                "StartDateTime": START,
                "StudentEffectiveEndDateTime": END,
            }
            for index in range(student_count)
        ]

    # --------------------------------------------------------
    # WRITE COMMON SOURCE TABLES
    # --------------------------------------------------------
    write_csv(
        sched / "ExamTimetable.csv",
        [
            "ExamID",
            "CourseID",
            "ExamDate",
            "StartDateTime",
            "EndDateTime",
        ],
        exams,
    )

    write_csv(
        sched / "TimetableStudentAllocation.csv",
        [
            "EnrollmentID",
            "StudentID",
            "ExamID",
            "StartDateTime",
            "EffectiveEndDateTime",
        ],
        students,
    )

    write_csv(
        data / "Room.csv",
        [
            "RoomID",
            "RoomCode",
            "Building",
            "Floor",
            "RoomType",
            "IsActive",
        ],
        [
            {
                "RoomID": row["RoomID"],
                "RoomCode": f"ROOM-{row['RoomID']}",
                "Building": "A",
                "Floor": "1",
                "RoomType": row["RoomType"],
                "IsActive": row["IsActive"],
            }
            for row in rooms
        ],
    )

    write_csv(
        data / "RoomCapacity.csv",
        [
            "RoomCapacityID",
            "RoomID",
            "Capacity",
            "EffectiveFrom",
            "EffectiveTo",
        ],
        room_capacity,
    )

    closures = []

    if scenario == "room_unavailable":
        closures = [
            {
                "RoomClosureID": "1",
                "RoomID": "11",
                "ClosureStart": "2026-11-16 09:30:00",
                "ClosureEnd": "2026-11-16 10:00:00",
                "ClosureStatus": "ACTIVE",
            }
        ]

    write_csv(
        data / "RoomClosure.csv",
        [
            "RoomClosureID",
            "RoomID",
            "ClosureStart",
            "ClosureEnd",
            "ClosureStatus",
        ],
        closures,
    )

    write_csv(
        data / "RoomEquipment.csv",
        [
            "RoomEquipmentID",
            "RoomID",
            "EquipmentID",
            "Quantity",
            "EffectiveFrom",
            "EffectiveTo",
        ],
        [],
    )

    write_csv(
        data / "Equipment.csv",
        [
            "EquipmentID",
            "EquipmentName",
            "EquipmentCategory",
            "IsActive",
        ],
        [],
    )

    write_csv(
        data / "ExamRequiredEquipment.csv",
        [
            "ExamRequiredEquipmentID",
            "ExamID",
            "EquipmentID",
            "QuantityRequired",
            "IsMandatory",
        ],
        [],
    )

    accommodation_rows = []

    if scenario == "accommodation_ignored":
        accommodation_rows = [
            {
                "AccommodationID": "1",
                "StudentID": "501",
                "AccommodationType": "ACCESSIBLE_ROOM",
                "ExtensionPercentage": "",
                "RequiresSeparateRoom": "0",
                "EffectiveFrom": "2026-01-01",
                "EffectiveTo": "",
                "AccommodationStatus": "ACTIVE",
            }
        ]

    write_csv(
        data / "Accommodation.csv",
        [
            "AccommodationID",
            "StudentID",
            "AccommodationType",
            "ExtensionPercentage",
            "RequiresSeparateRoom",
            "EffectiveFrom",
            "EffectiveTo",
            "AccommodationStatus",
        ],
        accommodation_rows,
    )

    write_csv(
        meta / "StudentSpecialEquipmentRequirement.csv",
        [
            "AccommodationID",
            "StudentID",
            "EquipmentID",
            "EquipmentName",
            "QuantityRequired",
            "RequirementSource",
        ],
        [],
    )

    # --------------------------------------------------------
    # WRITE ROOM ALLOCATION OUTPUTS
    # --------------------------------------------------------
    write_csv(
        sched / "RoomAllocation.csv",
        [
            "RoomAllocationID",
            "ExamID",
            "CourseID",
            "RoomID",
            "StartDateTime",
            "EndDateTime",
            "AllocatedStudentCount",
            "AssignedCapacity",
        ],
        [
            {
                "RoomAllocationID": row["RoomAllocationID"],
                "ExamID": row["ExamID"],
                "CourseID": next(
                    exam_row["CourseID"]
                    for exam_row in exams
                    if exam_row["ExamID"] == row["ExamID"]
                ),
                "RoomID": row["RoomID"],
                "StartDateTime": row["StartDateTime"],
                "EndDateTime": row["EndDateTime"],
                "AllocatedStudentCount": row["AllocatedStudentCount"],
                "AssignedCapacity": row["AssignedCapacity"],
            }
            for row in allocations
        ],
    )

    write_csv(
        sched / "RoomStudentAllocation.csv",
        [
            "EnrollmentID",
            "StudentID",
            "ExamID",
            "RoomID",
            "StartDateTime",
            "StudentEffectiveEndDateTime",
        ],
        student_rooms,
    )

    write_csv(
        sched / "RoomEquipmentReservation.csv",
        [
            "CourseID",
            "EquipmentID",
            "ReservedQuantity",
            "ReservationStart",
            "ReservationEnd",
            "ReservationPolicy",
        ],
        [],
    )

    exception_rows = []

    write_csv(
        sched / "RoomAllocationExceptions.csv",
        [
            "ExceptionID",
            "ExamID",
            "CourseID",
            "ReasonCode",
            "UnassignedStudentCount",
            "Details",
        ],
        exception_rows,
    )

    return root


def make_invigilator_project(root: Path) -> Path:
    data = root / "output_v2" / "full" / "v2.2.0"
    sched = data / "scheduling"

    sched.mkdir(parents=True)

    write_csv(
        data / "Invigilator.csv",
        [
            "InvigilatorID",
            "InvigilatorCode",
            "FullName",
            "MaxDailyHours",
            "Status",
        ],
        [
            {
                "InvigilatorID": "7",
                "InvigilatorCode": "INV-007",
                "FullName": "Test Invigilator",
                "MaxDailyHours": "8",
                "Status": "ACTIVE",
            }
        ],
    )

    write_csv(
        data / "Availability.csv",
        [
            "AvailabilityID",
            "InvigilatorID",
            "AvailableFrom",
            "AvailableTo",
            "AvailabilityStatus",
        ],
        [
            {
                "AvailabilityID": "70",
                "InvigilatorID": "7",
                "AvailableFrom": "2026-11-16 08:00:00",
                "AvailableTo": "2026-11-16 17:00:00",
                "AvailabilityStatus": "AVAILABLE",
            }
        ],
    )

    write_csv(
        sched / "RoomAllocation.csv",
        [
            "RoomAllocationID",
            "ExamID",
            "CourseID",
            "RoomID",
            "StartDateTime",
            "EndDateTime",
            "AllocatedStudentCount",
        ],
        [
            {
                "RoomAllocationID": "1",
                "ExamID": "1",
                "CourseID": "101",
                "RoomID": "11",
                "StartDateTime": START,
                "EndDateTime": END,
                "AllocatedStudentCount": "10",
            },
            {
                "RoomAllocationID": "2",
                "ExamID": "2",
                "CourseID": "102",
                "RoomID": "12",
                "StartDateTime": "2026-11-16 09:30:00",
                "EndDateTime": "2026-11-16 11:00:00",
                "AllocatedStudentCount": "10",
            },
        ],
    )

    write_csv(
        sched / "InvigilatorAssignment.csv",
        [
            "AssignmentID",
            "RoomAllocationID",
            "ExamID",
            "RoomID",
            "InvigilatorID",
            "AvailabilityID",
            "StartDateTime",
            "EndDateTime",
            "DutyMinutes",
        ],
        [
            {
                "AssignmentID": "1",
                "RoomAllocationID": "1",
                "ExamID": "1",
                "RoomID": "11",
                "InvigilatorID": "7",
                "AvailabilityID": "70",
                "StartDateTime": START,
                "EndDateTime": END,
                "DutyMinutes": "90",
            },
            {
                "AssignmentID": "2",
                "RoomAllocationID": "2",
                "ExamID": "2",
                "RoomID": "12",
                "InvigilatorID": "7",
                "AvailabilityID": "70",
                "StartDateTime": "2026-11-16 09:30:00",
                "EndDateTime": "2026-11-16 11:00:00",
                "DutyMinutes": "90",
            },
        ],
    )

    write_csv(
        sched / "InvigilatorAllocationExceptions.csv",
        [
            "ExceptionID",
            "RoomAllocationID",
            "ReasonCode",
            "UnassignedRoomCount",
        ],
        [],
    )

    return root


def run_validator(
    source: Path,
    project_root: Path,
    target_dir: Path
) -> tuple[int, dict, str]:
    target_dir.mkdir(parents=True, exist_ok=True)

    script_path = target_dir / source.name
    shutil.copy2(source, script_path)

    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=60,
    )

    report_candidates = list(
        (
            project_root
            / "output_v2"
            / "full"
            / "v2.2.0"
            / "scheduling"
        ).glob("*independent_validation_v220.json")
    )

    report = {}

    if report_candidates:
        report = json.loads(
            report_candidates[0].read_text(encoding="utf-8")
        )

    return (
        completed.returncode,
        report,
        completed.stdout + "\n" + completed.stderr,
    )


def allocator_rejects_student_overlap() -> tuple[bool, str]:
    if not ALLOCATOR_SOURCE.exists():
        return (
            False,
            f"Allocator script not found: {ALLOCATOR_SOURCE}",
        )

    spec = importlib.util.spec_from_file_location(
        "room_allocator_v220_edge_test",
        str(ALLOCATOR_SOURCE),
    )

    if spec is None or spec.loader is None:
        return False, "Could not load room allocator module."

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    start = "2026-11-16 09:00:00"
    end = "2026-11-16 10:30:00"

    fixture = {
        "timetable": [
            {
                "ExamID": "1",
                "CourseID": "101",
                "ExamDate": DATE,
                "StartDateTime": start,
                "EndDateTime": end,
            },
            {
                "ExamID": "2",
                "CourseID": "102",
                "ExamDate": DATE,
                "StartDateTime": start,
                "EndDateTime": end,
            },
        ],
        "students": [
            {
                "EnrollmentID": "1",
                "StudentID": "501",
                "ExamID": "1",
                "StartDateTime": start,
                "EffectiveEndDateTime": end,
            },
            {
                "EnrollmentID": "2",
                "StudentID": "501",
                "ExamID": "2",
                "StartDateTime": start,
                "EffectiveEndDateTime": end,
            },
        ],
        "rooms": [{"RoomID": "11"}],
        "capacities": [],
        "closures": [],
        "room_equipment": [],
        "equipment": [],
        "exam_requirement": [],
        "exam_equipment": [],
        "accommodations": [],
        "special": [],
    }

    try:
        module.validate_inputs(fixture)
        return (
            False,
            "Allocator preflight accepted overlapping student exams.",
        )

    except ValueError as exc:
        message = str(exc)
        return ("STUDENT CONFLICT" in message, message)


def main() -> int:
    if not ROOM_VALIDATOR_SOURCE.exists():
        print(
            "ERROR: Room validator not found. "
            "Keep it in data_validation/ or beside this script."
        )
        return 2

    if not INV_VALIDATOR_SOURCE.exists():
        print(
            "ERROR: Invigilator validator not found. "
            "Keep it in data_validation/ or beside this script."
        )
        return 2

    if not ALLOCATOR_SOURCE.exists():
        print(
            "ERROR: Updated room_allocator_v220.py not found. "
            "Keep it in scheduling/ or beside this script."
        )
        return 2

    tests = []

    with tempfile.TemporaryDirectory(
        prefix="exam_v220_edge_tests_"
    ) as temp:
        base = Path(temp)

        # ----------------------------------------------------
        # POSITIVE CONTROL: VALID ROOM ALLOCATION
        # ----------------------------------------------------
        clean_project = base / "clean_control"
        make_room_project(clean_project, "clean")

        clean_rc, clean_report, _ = run_validator(
            ROOM_VALIDATOR_SOURCE,
            clean_project,
            clean_project / "data_validation",
        )

        clean_passed = (
            clean_report.get("status") == "PASSED"
            and clean_rc == 0
        )

        tests.append({
            "scenario": "Positive control: valid room allocation",
            "validator": "independent_room_allocation_validator_v220.py",
            "detected": clean_passed,
            "expected_result": "PASSED",
            "validator_status": clean_report.get(
                "status",
                "NO_REPORT"
            ),
            "error_samples": clean_report.get(
                "error_samples",
                []
            )[:5],
            "return_code": clean_rc,
        })

        # ----------------------------------------------------
        # ROOM-ALLOCATION NEGATIVE TESTS
        # ----------------------------------------------------
        room_cases = [
            (
                "student_overlap",
                "Student overlapping examinations",
                "student conflict",
            ),
            (
                "room_capacity",
                "Room capacity exceeded",
                "capacity",
            ),
            (
                "accommodation_ignored",
                "Accessible accommodation ignored",
                "accessible student assigned",
            ),
            (
                "room_unavailable",
                "Exam during room closure",
                "overlaps active closure",
            ),
        ]

        for index, (
            scenario,
            label,
            expected_text
        ) in enumerate(room_cases, start=1):

            project = base / f"room_case_{index}"
            make_room_project(project, scenario)

            rc, report, output = run_validator(
                ROOM_VALIDATOR_SOURCE,
                project,
                project / "data_validation",
            )

            errors_text = " ".join(
                report.get("error_samples", [])
            ).lower()

            detected = expected_text.lower() in errors_text

            allocator_detected = True
            allocator_message = ""

            if scenario == "student_overlap":
                (
                    allocator_detected,
                    allocator_message,
                ) = allocator_rejects_student_overlap()

                detected = detected and allocator_detected

            tests.append({
                "scenario": label,
                "validator": "independent_room_allocation_validator_v220.py",
                "detected": detected,
                "allocator_preflight_detected": (
                    allocator_detected
                    if scenario == "student_overlap"
                    else None
                ),
                "allocator_preflight_message": allocator_message,
                "validator_status": report.get(
                    "status",
                    "NO_REPORT"
                ),
                "expected_error": expected_text,
                "error_samples": report.get(
                    "error_samples",
                    []
                )[:5],
                "return_code": rc,
            })

        # ----------------------------------------------------
        # INVIGILATOR DOUBLE-BOOKING NEGATIVE TEST
        # ----------------------------------------------------
        project = base / "invigilator_double_booking"
        make_invigilator_project(project)

        rc, report, output = run_validator(
            INV_VALIDATOR_SOURCE,
            project,
            project / "data_validation",
        )

        errors_text = " ".join(
            report.get("errors", [])
        ).lower()

        detected = "double-booking" in errors_text

        tests.append({
            "scenario": "Invigilator double-booked",
            "validator": "independent_invigilator_validator_v220.py",
            "detected": detected,
            "validator_status": report.get(
                "status",
                "NO_REPORT"
            ),
            "expected_error": "double-booking",
            "error_samples": report.get(
                "errors",
                []
            )[:5],
            "return_code": rc,
        })

        # ----------------------------------------------------
        # PRINT AND SAVE TEST REPORT
        # ----------------------------------------------------
        print("\n" + "=" * 76)
        print(
            "EXAM SCHEDULING SYSTEM v2.2.0 — "
            "ISOLATED EDGE-CASE TESTS"
        )
        print("=" * 76)

        for item in tests:
            status = "PASS" if item["detected"] else "GAP"

            print(
                f"{status:4} | {item['scenario']}"
            )

            print(
                f"       Validator status: "
                f"{item['validator_status']}; "
                f"exit={item['return_code']}"
            )

            if item.get("allocator_preflight_detected") is not None:
                preflight_status = (
                    "DETECTED"
                    if item["allocator_preflight_detected"]
                    else "NOT DETECTED"
                )

                print(
                    f"       Allocator preflight: {preflight_status}"
                )

            if not item["detected"]:
                print(
                    f"       NOT DETECTED: "
                    f"{item.get('expected_error', 'expected result')}"
                )

                for sample in item["error_samples"]:
                    print(f"       Existing error: {sample}")

        detected_count = sum(
            1
            for item in tests
            if item["detected"]
        )

        summary = {
            "suite": "EXAM_SCHEDULING_SYSTEM_V220_EDGE_CASES",
            "status": (
                "PASSED"
                if detected_count == len(tests)
                else "GAPS_FOUND"
            ),
            "passed": detected_count,
            "total": len(tests),
            "tests": tests,
            "production_data_accessed": False,
            "sql_server_accessed": False,
            "sql_server_modified": False,
            "groundtruth_accessed": False,
            "temporary_fixture_root": (
                "TemporaryDirectory (automatically removed)"
            ),
        }

        report_path = (
            Path.cwd() / "edge_case_test_report_v220.json"
        )

        report_path.write_text(
            json.dumps(summary, indent=2),
            encoding="utf-8",
        )

        print("-" * 76)
        print(
            f"RESULT: {detected_count}/{len(tests)} "
            "test checks passed"
        )
        print(f"Suite status: {summary['status']}")
        print(f"Report: {report_path}")
        print(
            "Production dataset / SQL Server / GroundTruth: "
            "NOT ACCESSED"
        )
        print("=" * 76)

        return (
            0
            if detected_count == len(tests)
            else 1
        )


if __name__ == "__main__":
    try:
        raise SystemExit(main())

    except subprocess.TimeoutExpired as exc:
        print(
            f"ERROR: Validator timed out: {exc}",
            file=sys.stderr
        )
        raise SystemExit(2)

    except Exception as exc:
        print(
            f"ERROR: Edge-case test harness failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr
        )
        raise SystemExit(2)