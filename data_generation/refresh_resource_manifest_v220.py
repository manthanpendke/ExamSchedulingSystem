from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

DATA = ROOT / "output_v2" / "full" / "v2.2.0"
SCHED = DATA / "scheduling"

MANIFEST = DATA / "manifest.json"

# Only these two resource files are approved to have changed.
MUTABLE_FILES = {
    "Room.csv",
    "RoomEquipment.csv",
}

# ============================================================
# EXPECTED RESOURCE CONFIGURATION
# ============================================================

EXPECTED_ROOM_TYPES = {
    "STANDARD": 52,
    "ACCESSIBLE": 38,
    "LAB": 10,
}

EXPECTED_EQUIPMENT_TOTALS = {
    "Projector": 100,
    "Desktop Computer": 2500,
    "Laboratory Kit": 1000,
    "Audio Equipment": 14,
    "Accessible Desk": 228,
}

EXPECTED_ROOM_COUNT = 100
EXPECTED_ROOM_EQUIPMENT_ROWS = 192

EXPECTED_LAB_KIT_ROOMS = 15
EXPECTED_ACCESSIBLE_DESK_ROOMS = 38

EVIDENCE_FILES = [
    SCHED / "accessible_room_augmentation_report_v220.json",
    SCHED / "lab_kit_redistribution_report_v220.json",
]


# ============================================================
# HELPERS
# ============================================================

def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def read_csv(path: Path):
    if not path.exists():
        raise FileNotFoundError(
            f"Required CSV file not found: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:

        reader = csv.DictReader(handle)

        if not reader.fieldnames:
            raise ValueError(
                f"CSV has no header: {path}"
            )

        return list(reader)


def read_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(
            f"Required JSON file not found: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as handle:

        return json.load(handle)


def is_active(value):
    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
    }


# ============================================================
# MANIFEST VALIDATION
# ============================================================

def validate_manifest_baselines(manifest):
    """
    Verify all original hashes except:
      - Room.csv
      - RoomEquipment.csv
      - GroundTruth.csv

    GroundTruth.csv is deliberately excluded from all access.
    """

    if manifest.get("version") != "2.2.0":
        raise ValueError(
            "Manifest version is not 2.2.0."
        )

    if manifest.get("database_modified") is not False:
        raise ValueError(
            "Manifest does not confirm database_modified=false."
        )

    table_entries = manifest.get("tables", {})

    if not table_entries:
        raise ValueError(
            "Manifest does not contain table entries."
        )

    verified_tables = 0
    skipped_approved_tables = []
    skipped_protected_tables = []

    for table_name, details in table_entries.items():

        file_name = details.get("file", "")

        base_name = Path(file_name).name

        # Protected file: never read or hash it.
        if (
            table_name == "GroundTruth"
            or base_name == "GroundTruth.csv"
        ):
            skipped_protected_tables.append(base_name)
            continue

        # These two files are verified separately.
        if base_name in MUTABLE_FILES:
            skipped_approved_tables.append(base_name)
            continue

        path = DATA / file_name

        if not path.exists():
            raise FileNotFoundError(
                f"Missing original dataset file: {path}"
            )

        expected_hash = details.get("sha256")

        if not expected_hash:
            raise ValueError(
                f"Missing original SHA256 hash for {file_name}"
            )

        actual_hash = sha256(path)

        if actual_hash != expected_hash:
            raise ValueError(
                f"Unexpected original dataset hash mismatch: {file_name}"
            )

        verified_tables += 1

    metadata_entries = manifest.get("metadata", {})

    if not metadata_entries:
        raise ValueError(
            "Manifest does not contain metadata entries."
        )

    verified_metadata = 0

    for _, details in metadata_entries.items():

        file_name = details.get("file", "")

        if Path(file_name).name == "GroundTruth.csv":
            raise ValueError(
                "GroundTruth.csv must not appear in metadata manifest."
            )

        path = DATA / file_name

        if not path.exists():
            raise FileNotFoundError(
                f"Missing metadata file: {path}"
            )

        expected_hash = details.get("sha256")

        if not expected_hash:
            raise ValueError(
                f"Missing metadata SHA256 hash: {file_name}"
            )

        if sha256(path) != expected_hash:
            raise ValueError(
                f"Metadata hash mismatch: {file_name}"
            )

        verified_metadata += 1

    return {
        "verified_tables": verified_tables,
        "verified_metadata": verified_metadata,
        "approved_tables": skipped_approved_tables,
        "protected_tables_skipped": skipped_protected_tables,
    }


# ============================================================
# ROOM VALIDATION
# ============================================================

def validate_rooms():
    rooms = read_csv(DATA / "Room.csv")

    if len(rooms) != EXPECTED_ROOM_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_ROOM_COUNT} rooms; "
            f"found {len(rooms)}."
        )

    room_types = Counter(
        row["RoomType"].strip().upper()
        for row in rooms
    )

    if dict(room_types) != EXPECTED_ROOM_TYPES:
        raise ValueError(
            "Unexpected room type distribution.\n"
            f"Expected: {EXPECTED_ROOM_TYPES}\n"
            f"Found: {dict(room_types)}"
        )

    room_ids = [
        str(row["RoomID"]).strip()
        for row in rooms
    ]

    if len(room_ids) != len(set(room_ids)):
        raise ValueError(
            "Duplicate RoomID values detected."
        )

    inactive_rooms = [
        row["RoomID"]
        for row in rooms
        if not is_active(row["IsActive"])
    ]

    if inactive_rooms:
        raise ValueError(
            "Expected all rooms active. "
            f"Inactive room IDs: {inactive_rooms[:20]}"
        )

    return {
        "rows": len(rooms),
        "room_types": dict(room_types),
        "all_active": True,
    }


# ============================================================
# ROOM EQUIPMENT VALIDATION
# ============================================================

def validate_room_equipment():
    equipment_rows = read_csv(
        DATA / "Equipment.csv"
    )

    room_equipment = read_csv(
        DATA / "RoomEquipment.csv"
    )

    if len(room_equipment) != EXPECTED_ROOM_EQUIPMENT_ROWS:
        raise ValueError(
            f"Expected {EXPECTED_ROOM_EQUIPMENT_ROWS} RoomEquipment rows; "
            f"found {len(room_equipment)}."
        )

    equipment_names = {}

    for row in equipment_rows:

        equipment_id = str(
            row["EquipmentID"]
        ).strip()

        equipment_name = row["EquipmentName"].strip()

        if equipment_id in equipment_names:
            raise ValueError(
                f"Duplicate EquipmentID: {equipment_id}"
            )

        equipment_names[equipment_id] = equipment_name

    totals = defaultdict(int)
    rooms_by_equipment = defaultdict(set)

    seen_pairs = set()

    for row in room_equipment:

        room_id = str(row["RoomID"]).strip()

        equipment_id = str(
            row["EquipmentID"]
        ).strip()

        quantity = int(row["Quantity"])

        if equipment_id not in equipment_names:
            raise ValueError(
                f"Unknown EquipmentID: {equipment_id}"
            )

        if quantity <= 0:
            raise ValueError(
                f"Non-positive equipment quantity: {row}"
            )

        pair = (room_id, equipment_id)

        if pair in seen_pairs:
            raise ValueError(
                f"Duplicate room/equipment pair: {pair}"
            )

        seen_pairs.add(pair)

        equipment_name = equipment_names[equipment_id]

        totals[equipment_name] += quantity

        rooms_by_equipment[equipment_name].add(
            room_id
        )

    actual_totals = dict(totals)

    if actual_totals != EXPECTED_EQUIPMENT_TOTALS:
        raise ValueError(
            "Equipment totals mismatch.\n"
            f"Expected: {EXPECTED_EQUIPMENT_TOTALS}\n"
            f"Found: {actual_totals}"
        )

    lab_rooms = len(
        rooms_by_equipment["Laboratory Kit"]
    )

    accessible_desk_rooms = len(
        rooms_by_equipment["Accessible Desk"]
    )

    if lab_rooms != EXPECTED_LAB_KIT_ROOMS:
        raise ValueError(
            "Laboratory Kit must be distributed across "
            f"{EXPECTED_LAB_KIT_ROOMS} rooms; found {lab_rooms}."
        )

    if accessible_desk_rooms != EXPECTED_ACCESSIBLE_DESK_ROOMS:
        raise ValueError(
            "Accessible Desk must be present in "
            f"{EXPECTED_ACCESSIBLE_DESK_ROOMS} rooms; "
            f"found {accessible_desk_rooms}."
        )

    return {
        "rows": len(room_equipment),
        "equipment_totals": actual_totals,
        "laboratory_kit_rooms": lab_rooms,
        "accessible_desk_rooms": accessible_desk_rooms,
    }


# ============================================================
# EVIDENCE VALIDATION
# ============================================================

def validate_evidence_reports():

    reports = []

    for path in EVIDENCE_FILES:

        if not path.exists():
            raise FileNotFoundError(
                f"Approved resource evidence report missing: {path}"
            )

        report = read_json(path)

        if not isinstance(report, dict):
            raise ValueError(
                f"Evidence report must contain a JSON object: {path}"
            )

        reports.append({
            "file": path.name,
            "sha256": sha256(path),
        })

    return reports


# ============================================================
# APPROVED MANIFEST UPDATE
# ============================================================

def update_manifest(
    manifest,
    room_result,
    equipment_result,
    evidence,
):
    entries_by_file = {
        Path(details.get("file", "")).name: details
        for details in manifest.get("tables", {}).values()
    }

    approved = manifest.setdefault(
        "approved_post_generation_changes",
        {},
    )

    timestamp = datetime.now().isoformat(
        timespec="seconds"
    )

    changes = [
        {
            "file": "Room.csv",
            "row_count": room_result["rows"],
            "reason": (
                "Approved accessible-room augmentation: "
                "28 standard rooms were converted to accessible rooms."
            ),
        },
        {
            "file": "RoomEquipment.csv",
            "row_count": equipment_result["rows"],
            "reason": (
                "Approved Lab Kit redistribution and accessible-room "
                "equipment updates. Total inventory independently verified."
            ),
        },
    ]

    for change in changes:

        file_name = change["file"]

        entry = entries_by_file.get(file_name)

        if entry is None:
            raise KeyError(
                f"Manifest has no table entry for {file_name}."
            )

        previous = approved.get(file_name, {})

        baseline_hash = previous.get(
            "baseline_sha256",
            entry.get("sha256"),
        )

        if not baseline_hash:
            raise ValueError(
                f"Original baseline hash missing for {file_name}."
            )

        current_hash = sha256(DATA / file_name)

        approved[file_name] = {
            "baseline_sha256": baseline_hash,
            "current_sha256": current_hash,
            "row_count": change["row_count"],
            "reason": change["reason"],
            "evidence_reports": evidence,
            "approved_refresh_timestamp": timestamp,
        }


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n" + "=" * 76)
    print("APPROVED RESOURCE MANIFEST REFRESH — V2.2.0")
    print("=" * 76)

    if not MANIFEST.exists():
        raise FileNotFoundError(
            f"Manifest not found: {MANIFEST}"
        )

    # Read original manifest.
    manifest = read_json(MANIFEST)

    # Verify all unchanged files against their original hashes.
    baseline_result = validate_manifest_baselines(
        manifest
    )

    print("\nOriginal manifest verification: PASSED")

    print(
        "Unchanged dataset tables verified:",
        baseline_result["verified_tables"],
    )

    print(
        "Metadata files verified:",
        baseline_result["verified_metadata"],
    )

    print(
        "Approved changed files:",
        baseline_result["approved_tables"],
    )

    print(
        "Protected files skipped:",
        baseline_result["protected_tables_skipped"],
    )

    # Verify approved resource files.
    room_result = validate_rooms()
    equipment_result = validate_room_equipment()

    print("\nRoom validation: PASSED")
    print("Room count:", room_result["rows"])
    print("Room types:", room_result["room_types"])

    print("\nRoom equipment validation: PASSED")
    print("RoomEquipment rows:", equipment_result["rows"])

    print(
        "Equipment totals:",
        equipment_result["equipment_totals"],
    )

    print(
        "Laboratory Kit rooms:",
        equipment_result["laboratory_kit_rooms"],
    )

    print(
        "Accessible Desk rooms:",
        equipment_result["accessible_desk_rooms"],
    )

    # Verify evidence reports.
    evidence = validate_evidence_reports()

    print("\nApproved resource evidence reports: PASSED")

    for item in evidence:
        print(" -", item["file"])

    # Prepare manifest update in memory.
    update_manifest(
        manifest,
        room_result,
        equipment_result,
        evidence,
    )

    # Create a unique backup before updating.
    backup_stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )

    backup_path = MANIFEST.with_name(
        "manifest.backup_before_approved_resource_refresh_"
        f"{backup_stamp}.json"
    )

    shutil.copy2(
        MANIFEST,
        backup_path,
    )

    # Atomic manifest update.
    temporary = MANIFEST.with_suffix(
        ".json.tmp"
    )

    temporary.write_text(
        json.dumps(manifest, indent=4),
        encoding="utf-8",
    )

    temporary.replace(MANIFEST)

    # Read-back verification.
    saved_manifest = read_json(MANIFEST)

    for file_name in MUTABLE_FILES:

        expected_hash = (
            saved_manifest[
                "approved_post_generation_changes"
            ][file_name]["current_sha256"]
        )

        actual_hash = sha256(
            DATA / file_name
        )

        if actual_hash != expected_hash:
            raise RuntimeError(
                f"Manifest read-back hash mismatch: {file_name}"
            )

    # Final summary.
    print("\n" + "=" * 76)
    print("RESOURCE MANIFEST REFRESH COMPLETED")
    print("=" * 76)

    print("Manifest:", MANIFEST)
    print("Backup:", backup_path)

    print("\nGroundTruth.csv: NOT READ")
    print("SQL Server: NOT ACCESSED")
    print("Production CSV files: NOT MODIFIED")

    print("\nFINAL STATUS: PASSED")

    return 0


if __name__ == "__main__":

    try:
        sys.exit(main())

    except Exception as exc:

        print("\nRESOURCE MANIFEST REFRESH FAILED")
        print(f"{type(exc).__name__}: {exc}")

        sys.exit(1)