from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from data_generation import dataset_generator as base


NEW_DATASET_VERSION = "1.1.0"
NEW_RANDOM_SEED = 20261108
EDGE_CASE_PERCENT = 0.08

EDGE_CASE_CATEGORIES = (
    "STUDENT_CONFLICT",
    "TIGHT_CAPACITY",
    "EQUIPMENT_SCARCITY",
    "ACCESSIBILITY",
    "SEPARATE_ROOM",
    "EXTENDED_TIME",
    "ROOM_CLOSURE",
    "INVIGILATOR_AVAILABILITY",
)


def _course_exam_map(data: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)

    for exam in data["Exam"]:
        result[exam["CourseCode"]].append(exam["ExamCode"])

    for codes in result.values():
        codes.sort()

    return dict(result)


def _rebalance_exam_sittings(data: dict, seed: int) -> None:
    """
    Assign each course enrollment independently to one of its exam sittings.

    The old student-number modulo rule placed students into the same
    sitting index across all courses. This created artificial conflict
    cohorts. Independent seeded assignment creates more realistic
    student conflicts while preserving valid references.
    """
    rng = random.Random(seed + 101)
    course_exams = _course_exam_map(data)

    for enrollment in data["ExamEnrollment"]:
        candidates = course_exams.get(enrollment["CourseCode"], [])

        if not candidates:
            raise ValueError(
                f"No exam sittings exist for course "
                f"{enrollment['CourseCode']}"
            )

        enrollment["ExamCode"] = rng.choice(candidates)

    data["ExamEnrollment"].sort(
        key=lambda row: (
            row["ExamCode"],
            row["StudentCode"],
        )
    )


def _participants_by_exam(data: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)

    for row in data["ExamEnrollment"]:
        if row["ParticipationStatus"] == "REGISTERED":
            result[row["ExamCode"]].append(row["StudentCode"])

    return dict(result)


def _conflict_degree(data: dict) -> dict[str, int]:
    student_exams: dict[str, set[str]] = defaultdict(set)

    for row in data["ExamEnrollment"]:
        if row["ParticipationStatus"] == "REGISTERED":
            student_exams[row["StudentCode"]].add(row["ExamCode"])

    neighbors: dict[str, set[str]] = defaultdict(set)

    for exams in student_exams.values():
        for exam in exams:
            neighbors[exam].update(exams - {exam})

    return {
        exam["ExamCode"]: len(neighbors[exam["ExamCode"]])
        for exam in data["Exam"]
    }


def _set_accommodation(
    data: dict,
    student_code: str,
    kind: str,
) -> None:
    rows = [
        row
        for row in data["Accommodation"]
        if row["StudentCode"] == student_code
    ]

    replacement = {
        "StudentCode": student_code,
        "AccommodationType": kind,
        "ExtensionPercentage": (
            50 if kind == "EXTENDED_TIME" else None
        ),
        "RequiresSeparateRoom": kind == "SEPARATE_ROOM",
        "EffectiveFrom": datetime(2026, 1, 1).date(),
        "EffectiveTo": None,
        "AccommodationStatus": "ACTIVE",
    }

    if rows:
        rows[0].update(replacement)

        for duplicate in rows[1:]:
            data["Accommodation"].remove(duplicate)
    else:
        data["Accommodation"].append(replacement)


def _select_scarce_equipment(data: dict) -> str:
    """
    Select valid equipment from actual master data.

    Equipment must:
    - Exist in the Equipment master table.
    - Be stocked by at least one room.
    - Not be the common projector.
    - Have relatively limited room coverage.
    """
    master_codes = {
        row["EquipmentCode"]
        for row in data["Equipment"]
    }

    coverage = Counter(
        row["EquipmentCode"]
        for row in data["RoomEquipment"]
        if row["EquipmentCode"] in master_codes
    )

    candidates = [
        code
        for code in master_codes
        if code != "EQ-001" and coverage[code] > 0
    ]

    if not candidates:
        raise ValueError(
            "Cannot create equipment-scarcity edge cases: "
            "no non-projector equipment is stocked in any room."
        )

    return min(
        candidates,
        key=lambda code: (coverage[code], code),
    )


def _add_exam_equipment(
    data: dict,
    exam_code: str,
    equipment_code: str,
) -> None:
    requirement = next(
        row
        for row in data["ExamRequirement"]
        if row["ExamCode"] == exam_code
    )

    items = json.loads(
        requirement["RequiredEquipment"] or "[]"
    )

    already_exists = any(
        item["equipment_code"] == equipment_code
        for item in items
    )

    if not already_exists:
        items.append({
            "equipment_code": equipment_code,
            "quantity_required": 1,
            "is_mandatory": True,
        })

        items.sort(
            key=lambda item: item["equipment_code"]
        )

        requirement["RequiredEquipment"] = json.dumps(
            items,
            sort_keys=True,
        )

        data["ExamRequiredEquipment"].append({
            "ExamCode": exam_code,
            "EquipmentCode": equipment_code,
            "QuantityRequired": 1,
            "IsMandatory": True,
        })


def _inject_edge_cases(
    data: dict,
    config: dict,
    seed: int,
) -> dict:
    rng = random.Random(seed + 202)

    exam_count = len(data["Exam"])

    edge_count = max(
        1,
        round(exam_count * EDGE_CASE_PERCENT),
    )

    if edge_count % len(EDGE_CASE_CATEGORIES) != 0:
        edge_count = (
            edge_count // len(EDGE_CASE_CATEGORIES)
        ) * len(EDGE_CASE_CATEGORIES)

    per_category = (
        edge_count // len(EDGE_CASE_CATEGORIES)
    )

    if per_category == 0:
        raise ValueError(
            "At least eight exams are required for edge-case coverage."
        )

    exam_codes = [
        row["ExamCode"]
        for row in data["Exam"]
    ]

    participants = _participants_by_exam(data)

    if any(
        not participants.get(code)
        for code in exam_codes
    ):
        raise ValueError(
            "Every exam must have registered participants "
            "before edge-case injection."
        )

    selected: dict[str, list[str]] = {}
    used: set[str] = set()

    # 1. Student conflict cases
    degrees = _conflict_degree(data)

    conflict_candidates = sorted(
        exam_codes,
        key=lambda code: (
            -degrees.get(code, 0),
            code,
        ),
    )

    selected["STUDENT_CONFLICT"] = (
        conflict_candidates[:per_category]
    )

    used.update(selected["STUDENT_CONFLICT"])

    # 2. Tight capacity cases
    capacity_candidates = sorted(
        (
            code
            for code in exam_codes
            if code not in used
        ),
        key=lambda code: (
            -len(participants[code]),
            code,
        ),
    )

    selected["TIGHT_CAPACITY"] = (
        capacity_candidates[:per_category]
    )

    used.update(selected["TIGHT_CAPACITY"])

    # 3. Remaining categories
    remaining = sorted(
        set(exam_codes) - used
    )

    rng.shuffle(remaining)

    for category in EDGE_CASE_CATEGORIES[2:]:
        selected[category] = remaining[:per_category]
        del remaining[:per_category]
        used.update(selected[category])

    # 4. Equipment scarcity
    scarce_equipment_code = _select_scarce_equipment(data)

    for exam_code in selected["EQUIPMENT_SCARCITY"]:
        _add_exam_equipment(
            data,
            exam_code,
            scarce_equipment_code,
        )

    # 5. Accessibility
    req_by_code = {
        row["ExamCode"]: row
        for row in data["ExamRequirement"]
    }

    for exam_code in selected["ACCESSIBILITY"]:
        req_by_code[exam_code]["AccessibilityRequired"] = True

        student_code = participants[exam_code][0]

        _set_accommodation(
            data,
            student_code,
            "ACCESSIBLE_ROOM",
        )

    # 6. Separate-room accommodation
    for exam_code in selected["SEPARATE_ROOM"]:
        student_code = participants[exam_code][0]

        _set_accommodation(
            data,
            student_code,
            "SEPARATE_ROOM",
        )

    # 7. Extended-time accommodation
    for exam_code in selected["EXTENDED_TIME"]:
        student_code = participants[exam_code][0]

        _set_accommodation(
            data,
            student_code,
            "EXTENDED_TIME",
        )

    # 8. Room closures
    room_codes = [
        row["RoomCode"]
        for row in data["Room"]
    ]

    closure_rooms = room_codes[
        :max(3, per_category)
    ]

    for index, room_code in enumerate(
        closure_rooms[:per_category]
    ):
        day = 16 + (index % 5)

        start = datetime(
            2026,
            11,
            day,
            8,
            0,
        )

        data["RoomClosure"].append({
            "RoomCode": room_code,
            "ClosureStart": start,
            "ClosureEnd": start + timedelta(hours=3),
            "ClosureReason": (
                "EDGE_CASE: limited maintenance window during exams"
            ),
            "ClosureStatus": "ACTIVE",
        })

    # 9. Invigilator availability pressure
    invigilators = [
        row["InvigilatorCode"]
        for row in data["Invigilator"]
    ]

    restricted_staff = set(
        invigilators[
            :max(1, len(invigilators) // 10)
        ]
    )

    for row in data["Availability"]:
        if (
            row["InvigilatorCode"] in restricted_staff
            and row["AvailableFrom"].date()
            == datetime(2026, 11, 18).date()
        ):
            row["AvailabilityStatus"] = "UNAVAILABLE"
            row["AvailabilityReason"] = (
                "EDGE_CASE: constrained staffing day"
            )

    # 10. Evaluation-only ground truth
    reason_by_category = {
        "STUDENT_CONFLICT": "STUDENT_CONFLICT",
        "TIGHT_CAPACITY": "NO_ROOM_CAPACITY",
        "EQUIPMENT_SCARCITY": "NO_EQUIPMENT",
        "ACCESSIBILITY": "ACCOMMODATION_CONFLICT",
        "SEPARATE_ROOM": "ACCOMMODATION_CONFLICT",
        "EXTENDED_TIME": "NO_VALID_TIMESLOT",
        "ROOM_CLOSURE": "ROOM_CLOSED",
        "INVIGILATOR_AVAILABILITY": "NO_INVIGILATOR",
    }

    description_by_category = {
        "STUDENT_CONFLICT": (
            "Shared-student conflict must be avoided by "
            "assigning a non-overlapping interval."
        ),
        "TIGHT_CAPACITY": (
            "Large registered cohort requires capacity-safe "
            "allocation, potentially across multiple rooms."
        ),
        "EQUIPMENT_SCARCITY": (
            "Mandatory specialized equipment is stocked "
            "by only a subset of rooms."
        ),
        "ACCESSIBILITY": (
            "Exam requires an accessible room and includes "
            "a participant with an accessibility accommodation."
        ),
        "SEPARATE_ROOM": (
            "A registered participant requires a separate "
            "room allocation."
        ),
        "EXTENDED_TIME": (
            "A registered participant requires extended time; "
            "the full effective duration must be respected."
        ),
        "ROOM_CLOSURE": (
            "Some rooms are closed during part of the exam window; "
            "an eligible alternative must be selected."
        ),
        "INVIGILATOR_AVAILABILITY": (
            "A subset of invigilators is unavailable on a "
            "scheduling day; available staff must be selected."
        ),
    }

    original_ground_truth = list(data["GroundTruth"])

    edge_ground_truth = []

    for category in EDGE_CASE_CATEGORIES:
        for index, exam_code in enumerate(
            selected[category],
            start=1,
        ):
            edge_ground_truth.append({
                "DatasetVersion": config["dataset"]["version"],
                "ScenarioCode": (
                    f"EDGE_{category}_{index:02d}"
                ),
                "EntityType": "EXAM",
                "EntityCode": exam_code,
                "IssueType": category,
                "ExpectedOutcome": "ACCEPT",
                "ExpectedReasonCode": reason_by_category[category],
                "Severity": (
                    "MEDIUM"
                    if category in {
                        "TIGHT_CAPACITY",
                        "ROOM_CLOSURE",
                        "INVIGILATOR_AVAILABILITY",
                    }
                    else "HIGH"
                ),
                "Description": description_by_category[category],
            })

    # Additional negative test labels remain evaluation-only.
    negative_scenarios = [
        (
            "NEG_INVALID_REQUIREMENT",
            "INVALID_REQUIREMENT",
            "REJECT",
            "INVALID_REQUIREMENT",
            "A malformed or out-of-range exam requirement "
            "must be rejected before scheduling.",
        ),
        (
            "NEG_NO_ELIGIBLE_STUDENTS",
            "NO_ELIGIBLE_STUDENTS",
            "UNASSIGNED",
            "NO_ELIGIBLE_STUDENTS",
            "An exam with no eligible registered participants "
            "must not receive an assignment.",
        ),
        (
            "NEG_NO_VALID_TIMESLOT",
            "NO_VALID_TIMESLOT",
            "UNASSIGNED",
            "NO_VALID_TIMESLOT",
            "An exam with no interval satisfying all hard "
            "constraints must remain unassigned.",
        ),
        (
            "NEG_NO_EQUIPMENT",
            "NO_EQUIPMENT",
            "UNASSIGNED",
            "NO_EQUIPMENT",
            "An exam with unavailable mandatory equipment "
            "must remain unassigned.",
        ),
    ]

    for index, (
        scenario_code,
        issue_type,
        outcome,
        reason,
        description,
    ) in enumerate(negative_scenarios):
        edge_ground_truth.append({
            "DatasetVersion": config["dataset"]["version"],
            "ScenarioCode": scenario_code,
            "EntityType": "EXAM",
            "EntityCode": exam_codes[index],
            "IssueType": issue_type,
            "ExpectedOutcome": outcome,
            "ExpectedReasonCode": reason,
            "Severity": "HIGH",
            "Description": description,
        })

    data["GroundTruth"] = (
        original_ground_truth + edge_ground_truth
    )

    summary = {
        "dataset_version": config["dataset"]["version"],
        "total_exams": exam_count,
        "edge_case_exam_count": len(used),
        "edge_case_percentage": round(
            len(used) / exam_count * 100,
            2,
        ),
        "normal_exam_count": exam_count - len(used),
        "edge_case_categories": {
            category: {
                "count": len(selected[category]),
                "exam_codes": selected[category],
            }
            for category in EDGE_CASE_CATEGORIES
        },
        "original_negative_ground_truth_count": (
            len(original_ground_truth)
        ),
        "edge_case_ground_truth_count": edge_count,
        "additional_negative_test_labels": (
            len(negative_scenarios)
        ),
        "ground_truth_total": len(data["GroundTruth"]),
        "student_sitting_assignment": (
            "Independent deterministic assignment per "
            "student-course enrollment; no shared modulo cohort rule."
        ),
        "scarce_equipment_code": scarce_equipment_code,
        "scarce_equipment_room_coverage": sum(
            1
            for row in data["RoomEquipment"]
            if row["EquipmentCode"] == scarce_equipment_code
        ),
    }

    return summary


def _validate_edge_case_injection(
    data: dict,
    summary: dict,
) -> None:
    expected = summary["edge_case_exam_count"]

    codes = [
        row["EntityCode"]
        for row in data["GroundTruth"]
        if row["ScenarioCode"].startswith("EDGE_")
    ]

    if (
        len(codes) != expected
        or len(set(codes)) != expected
    ):
        raise ValueError(
            "Edge-case ground truth must map one-to-one "
            "to unique exam records."
        )

    if not (
        5 <= summary["edge_case_percentage"] <= 10
    ):
        raise ValueError(
            "Edge-case exam percentage must remain "
            "between 5% and 10%."
        )

    category_counts = Counter(
        row["IssueType"]
        for row in data["GroundTruth"]
        if row["ScenarioCode"].startswith("EDGE_")
    )

    if set(category_counts) != set(EDGE_CASE_CATEGORIES):
        raise ValueError(
            "One or more required edge-case categories are missing."
        )

    if len(set(category_counts.values())) != 1:
        raise ValueError(
            "Edge-case categories must be evenly represented."
        )


def main() -> None:
    config = base.load_config()

    config["dataset"]["version"] = NEW_DATASET_VERSION
    config["dataset"]["random_seed"] = NEW_RANDOM_SEED

    if not config["generation"].get(
        "anomaly_injection_enabled",
        False,
    ):
        raise ValueError(
            "Negative ground-truth scenario generation must be enabled."
        )

    if not config["generation"].get(
        "ground_truth_separate",
        False,
    ):
        raise ValueError(
            "Ground truth must remain separate from scheduler input data."
        )

    profile_name = "full"

    if profile_name not in config["profiles"]:
        raise ValueError(
            "The dataset configuration must contain the full profile."
        )

    output_dir = (
        base.OUTPUT_ROOT
        / profile_name
        / f"v{NEW_DATASET_VERSION}"
    )

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            "Refusing to overwrite existing dataset output: "
            f"{output_dir}"
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 68)
    print("BALANCED EXAM SCHEDULING DATASET GENERATOR")
    print("=" * 68)
    print(f"Profile: {profile_name}")
    print(f"Version: {NEW_DATASET_VERSION}")
    print(f"Seed: {NEW_RANDOM_SEED}")

    data = base.generate_dataset(
        config,
        profile_name,
    )

    _rebalance_exam_sittings(
        data,
        NEW_RANDOM_SEED,
    )

    summary = _inject_edge_cases(
        data,
        config,
        NEW_RANDOM_SEED,
    )

    # Validate baseline ground truth separately.
    # The existing generator expects its original five records.
    validation_data = dict(data)

    validation_data["GroundTruth"] = [
        row
        for row in data["GroundTruth"]
        if not row["ScenarioCode"].startswith("EDGE_")
        and not row["ScenarioCode"].startswith("NEG_INVALID_")
        and not row["ScenarioCode"].startswith("NEG_NO_")
    ]

    # Intentional in-window closures are excluded from the
    # baseline validator and checked separately below.
    validation_data["RoomClosure"] = [
        row
        for row in data["RoomClosure"]
        if not row["ClosureReason"].startswith("EDGE_CASE:")
    ]

    base.validate_dataset(
        validation_data,
        config,
        profile_name,
    )

    _validate_edge_case_injection(
        data,
        summary,
    )

    room_codes = {
        row["RoomCode"]
        for row in data["Room"]
    }

    for closure in data["RoomClosure"]:
        if closure["RoomCode"] not in room_codes:
            raise ValueError(
                "Edge-case room closure references an unknown room."
            )

        if closure["ClosureEnd"] <= closure["ClosureStart"]:
            raise ValueError(
                "Edge-case room closure has an invalid interval."
            )

        if closure["ClosureStatus"] not in {
            "ACTIVE",
            "COMPLETED",
            "CANCELLED",
        }:
            raise ValueError(
                "Edge-case room closure has an invalid status."
            )

    # GroundTruth is deliberately excluded from scheduler input data.
    baseline_data = {
        key: value
        for key, value in data.items()
        if key != "GroundTruth"
    }

    ground_truth_data = {
        "GroundTruth": data["GroundTruth"]
    }

    formats = set(
        config["dataset"]["output_format"]
    )

    if "csv" in formats:
        base.write_csv_files(
            baseline_data,
            output_dir / "csv",
        )

        base.write_csv_files(
            ground_truth_data,
            output_dir / "ground_truth" / "csv",
        )

    if "json" in formats:
        base.write_json_files(
            baseline_data,
            output_dir / "json",
        )

        base.write_json_files(
            ground_truth_data,
            output_dir / "ground_truth" / "json",
        )

    if "sql" in formats:
        base.write_sql_file(
            baseline_data,
            output_dir / "sql",
        )

        base.write_ground_truth_sql_file(
            data["GroundTruth"],
            output_dir / "ground_truth" / "sql",
        )

    (output_dir / "edge_case_summary.json").write_text(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    comparison = base.write_manifest(
        output_dir=output_dir,
        config=config,
        profile_name=profile_name,
        data=data,
        previous_manifest=None,
    )

    print("\nDATASET VALIDATION: PASS")
    print(f"Total exams: {summary['total_exams']}")
    print(f"Normal exams: {summary['normal_exam_count']}")

    print(
        f"Edge-case exams: "
        f"{summary['edge_case_exam_count']} "
        f"({summary['edge_case_percentage']}%)"
    )

    print(
        f"Ground-truth records: "
        f"{summary['ground_truth_total']}"
    )

    for category, details in (
        summary["edge_case_categories"].items()
    ):
        print(
            f"  {category}: {details['count']}"
        )

    print(
        f"Scarce equipment: "
        f"{summary['scarce_equipment_code']}"
    )

    print(
        f"Rooms stocking scarce equipment: "
        f"{summary['scarce_equipment_room_coverage']}"
    )

    print(f"Output: {output_dir}")
    print(f"Checksum comparison: {comparison}")

    print(
        "SQL files were generated for review only; "
        "no database changes were made."
    )


if __name__ == "__main__":
    main()