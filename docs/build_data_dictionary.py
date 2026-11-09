
from pathlib import Path
from collections import defaultdict
import pandas as pd

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


# ============================================================
# EXAM SCHEDULING SYSTEM
# SQL SERVER DATA DICTIONARY GENERATOR
#
# Reads actual SQL Server metadata exports.
# Does not modify the database.
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "docs" / "schema"
OUTPUT = ROOT / "docs" / "data_dictionary.xlsx"

FILES = {
    "columns": SCHEMA_DIR / "columns.csv",
    "keys": SCHEMA_DIR / "keys.csv",
    "foreign_keys": SCHEMA_DIR / "foreign_keys.csv",
    "checks": SCHEMA_DIR / "check_constraints.csv",
}


# ============================================================
# 1. BUSINESS DEFINITIONS
# ============================================================

TABLE_DESCRIPTIONS = {
    "Student": "Stores learner master records.",
    "Course": "Stores academic course master records.",
    "Enrollment": "Associates students with courses.",
    "Exam": "Stores examinations associated with courses.",
    "ExamRequirement": "Stores examination duration and requirements.",
    "ExamEnrollment": "Connects course enrollments to examinations.",
    "Room": "Stores examination room master records.",
    "RoomCapacity": "Stores effective-dated room capacity records.",
    "RoomClosure": "Records periods when rooms cannot be used.",
    "RoomEquipment": "Records equipment available in rooms.",
    "Equipment": "Stores equipment master records.",
    "ExamRequiredEquipment": "Connects examinations to required equipment.",
    "Invigilator": "Stores invigilator master records and workload limits.",
    "Availability": "Stores invigilator availability periods.",
    "Accommodation": "Stores student examination accommodations.",
    "ScheduleAssignment": "Stores examination scheduling assignments.",
    "SchedulingRun": "Stores individual scheduling executions.",
    "AssignmentStudent": "Connects students to examination assignments.",
    "AssignmentInvigilator": "Connects invigilators to assignments.",
    "AssignmentEvent": "Stores assignment event history.",
    "SchedulingException": "Stores scheduling exceptions and reason codes.",
    "GroundTruth": "Stores independent evaluation labels and expected outcomes.",
}

COLUMN_DESCRIPTIONS = {
    "StudentCode": "Business identifier for a student.",
    "CourseCode": "Business identifier for a course.",
    "ExamCode": "Business identifier for an examination.",
    "RoomCode": "Business identifier for a room.",
    "InvigilatorCode": "Business identifier for an invigilator.",
    "AssignmentCode": "Business identifier for a schedule assignment.",
    "StudentID": "Reference to a student record.",
    "CourseID": "Reference to a course record.",
    "ExamID": "Reference to an examination record.",
    "RoomID": "Reference to a room record.",
    "InvigilatorID": "Reference to an invigilator record.",
    "EnrollmentID": "Reference to a student-course enrollment.",
    "ExamEnrollmentID": "Reference to an examination enrollment.",
    "SchedulingRunID": "Reference to a scheduling execution.",
    "EquipmentID": "Reference to equipment.",
    "AssignmentID": "Reference to a schedule assignment.",
    "DurationMinutes": "Examination duration in minutes.",
    "ExtensionPercentage": "Additional examination time as a percentage.",
    "MaxDailyHours": "Maximum permitted invigilator workload in hours.",
    "Capacity": "Room seating capacity.",
    "AssignedCapacity": "Capacity recorded for an assignment.",
    "Quantity": "Number of equipment units.",
    "QuantityRequired": "Number of equipment units required.",
    "SeatNumber": "Seat identifier within an assignment.",
    "StartTime": "Start timestamp.",
    "EndTime": "End timestamp.",
    "ExamWindowStart": "Earliest permitted examination start.",
    "ExamWindowEnd": "Latest permitted examination end.",
    "AvailableFrom": "Availability period start.",
    "AvailableTo": "Availability period end.",
    "EffectiveFrom": "Date from which a record is effective.",
    "EffectiveTo": "Last effective date.",
    "ClosureStart": "Room closure start timestamp.",
    "ClosureEnd": "Room closure end timestamp.",
    "RandomSeed": "Seed used for reproducible execution.",
    "AlgorithmVersion": "Scheduling algorithm version.",
    "ExpectedOutcome": "Expected evaluation outcome.",
    "ExpectedReasonCode": "Expected reason code for an evaluation scenario.",
    "IssueType": "Classification of an identified issue.",
    "ReasonCode": "Machine-readable scheduling exception code.",
    "EventDetails": "Event details stored as JSON.",
    "Configuration": "Scheduling configuration stored as JSON.",
    "RequiredEquipment": "Required equipment representation stored as JSON.",
    "Credits": "Academic credit value.",
    "Floor": "Room floor number.",
}

UNIT_HINTS = {
    "DurationMinutes": "minutes",
    "ExtensionPercentage": "percent",
    "MaxDailyHours": "hours/day",
    "Capacity": "seats",
    "AssignedCapacity": "seats",
    "Quantity": "units",
    "QuantityRequired": "units",
    "Credits": "academic credits",
    "Floor": "floor number",
    "RandomSeed": "integer",
}


# ============================================================
# 2. GENERAL UTILITIES
# ============================================================

def clean(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def as_bool(value):
    """Safely interpret SQL Server metadata boolean values."""

    if isinstance(value, bool):
        return value

    if pd.isna(value):
        return False

    if isinstance(value, (int, float)):
        return value != 0

    return str(value).strip().lower() in (
        "1", "true", "yes", "y"
    )


def load_csv(name):
    path = FILES[name]

    if not path.exists():
        raise FileNotFoundError(
            f"Required metadata file not found: {path}"
        )

    return pd.read_csv(path)


def validate_metadata(columns, keys, fks, checks):

    required = {
        "columns": {
            "schema_name", "table_name", "column_id",
            "column_name", "data_type", "max_length",
            "precision", "scale", "is_nullable",
            "is_identity", "is_computed", "default_definition"
        },
        "keys": {
            "schema_name", "table_name", "key_name",
            "key_type", "column_name", "key_ordinal"
        },
        "foreign_keys": {
            "foreign_key_name", "child_schema", "child_table",
            "child_column", "parent_schema", "parent_table",
            "parent_column", "column_ordinal",
            "delete_referential_action_desc",
            "update_referential_action_desc",
            "is_disabled", "is_not_trusted"
        },
        "checks": {
            "schema_name", "table_name", "constraint_name",
            "definition", "is_disabled", "is_not_trusted"
        }
    }

    frames = {
        "columns": columns,
        "keys": keys,
        "foreign_keys": fks,
        "checks": checks
    }

    for name, frame in frames.items():
        missing = required[name] - set(frame.columns)

        if missing:
            raise ValueError(
                f"{name}.csv is missing columns: {sorted(missing)}"
            )

        if frame.empty:
            raise ValueError(f"{name}.csv is empty.")

    if columns.duplicated(
        ["schema_name", "table_name", "column_name"]
    ).any():
        raise ValueError("Duplicate column metadata detected.")

    if keys.duplicated(
        ["schema_name", "table_name", "key_name", "key_ordinal"]
    ).any():
        raise ValueError("Duplicate key-column metadata detected.")

    if fks.duplicated(
        ["foreign_key_name", "column_ordinal",
         "child_schema", "child_table"]
    ).any():
        raise ValueError("Duplicate foreign-key metadata detected.")

    print("Metadata validation: PASS")


# ============================================================
# 3. SQL DATA TYPE FORMATTING
# ============================================================

def sql_type(row):

    dtype = clean(row.data_type).lower()

    length = int(row.max_length)
    precision = int(row.precision)
    scale = int(row.scale)

    if dtype in (
        "varchar", "nvarchar", "char",
        "nchar", "varbinary", "binary"
    ):

        if length == -1:
            return f"{dtype}(MAX)"

        if dtype in ("nvarchar", "nchar"):
            length //= 2

        return f"{dtype}({length})"

    if dtype in ("decimal", "numeric"):
        return f"{dtype}({precision},{scale})"

    if dtype in ("datetime2", "time", "datetimeoffset"):
        return f"{dtype}({scale})"

    if dtype == "float":
        return f"float({precision})"

    return dtype


# ============================================================
# 4. BUILD KEY AND UNIQUENESS METADATA
# ============================================================

def build_key_metadata(keys):

    key_groups = {}
    primary_keys = {}
    unique_lookup = defaultdict(list)

    grouped = keys.groupby(
        ["schema_name", "table_name", "key_name", "key_type"],
        sort=True
    )

    for (schema, table, key_name, key_type), group in grouped:

        ordered = group.sort_values("key_ordinal")

        key_columns = ordered["column_name"].astype(str).tolist()

        key_groups[(schema, table, key_name)] = {
            "key_type": key_type,
            "columns": key_columns
        }

        if key_type == "PRIMARY KEY":
            primary_keys[(schema, table)] = key_columns

        if key_type in (
            "PRIMARY KEY",
            "UNIQUE CONSTRAINT",
            "UNIQUE INDEX"
        ):

            for column in key_columns:

                unique_lookup[(schema, table, column)].append({
                    "key_name": key_name,
                    "key_type": key_type,
                    "columns": key_columns
                })

    return key_groups, primary_keys, unique_lookup


def get_unique_description(schema, table, column, lookup):

    entries = lookup.get((schema, table, column), [])

    if not entries:
        return "No unique key/index identified in exported metadata."

    descriptions = []

    for entry in entries:

        name = entry["key_name"]
        kind = entry["key_type"]
        cols = entry["columns"]

        if kind == "PRIMARY KEY":

            descriptions.append(
                f"PRIMARY KEY: {name}"
            )

        elif kind == "UNIQUE CONSTRAINT":

            if len(cols) == 1:
                descriptions.append(
                    f"Unique column constraint: {name}"
                )
            else:
                descriptions.append(
                    f"Part of composite unique constraint "
                    f"(not individually unique): {name}; "
                    f"columns = {' + '.join(cols)}"
                )

        elif kind == "UNIQUE INDEX":

            if len(cols) == 1:
                descriptions.append(
                    f"Unique index: {name}; filter predicate "
                    f"not included in exported metadata. "
                    f"Verify its scope in SQL Server."
                )
            else:
                descriptions.append(
                    f"Part of composite unique index "
                    f"(not individually unique): {name}; "
                    f"columns = {' + '.join(cols)}. "
                    f"Filter predicate not included in export."
                )

    return "; ".join(descriptions)


# ============================================================
# 5. FOREIGN KEY METADATA
# ============================================================

def build_foreign_key_metadata(fks):

    fk_lookup = defaultdict(list)

    for row in fks.itertuples(index=False):

        key = (
            row.child_schema,
            row.child_table,
            row.child_column
        )

        fk_lookup[key].append(
            f"{row.parent_schema}.{row.parent_table}.{row.parent_column}"
        )

    return fk_lookup


def get_fk_relationship_cardinality(
    child_schema,
    child_table,
    child_columns,
    key_groups
):

    child_columns = list(child_columns)

    for (schema, table, key_name), details in key_groups.items():

        if schema != child_schema or table != child_table:
            continue

        if details["columns"] != child_columns:
            continue

        kind = details["key_type"]

        if kind in ("PRIMARY KEY", "UNIQUE CONSTRAINT"):
            return (
                "1:1",
                f"Child FK columns are protected by {kind}: {key_name}"
            )

        if kind == "UNIQUE INDEX":
            return (
                "Conditional 1:1",
                f"Unique index {key_name} exists, but its filter "
                f"predicate is unavailable. Verify SQL Server definition."
            )

    return (
        "1:N",
        "No matching unique child foreign-key constraint was identified."
    )


# ============================================================
# 6. CHECK CONSTRAINT LOOKUP
# ============================================================

def get_check_definitions(schema, table, column, checks):

    relevant = checks[
        (checks["schema_name"] == schema) &
        (checks["table_name"] == table)
    ]

    if relevant.empty:
        return "No CHECK constraint identified for this table."

    definitions = []

    for row in relevant.itertuples(index=False):

        definition = clean(row.definition)

        # Preserve the actual SQL definition rather than
        # assuming every quoted value represents an enum.

        definitions.append(
            f"{row.constraint_name}: {definition}"
        )

    return " | ".join(definitions)


# ============================================================
# 7. DATA DICTIONARY
# ============================================================

def build_data_dictionary(
    columns,
    checks,
    primary_keys,
    fk_lookup,
    unique_lookup
):

    rows = []

    ordered_columns = columns.sort_values(
        ["schema_name", "table_name", "column_id"]
    )

    for row in ordered_columns.itertuples(index=False):

        schema = row.schema_name
        table = row.table_name
        column = row.column_name

        nullable = as_bool(row.is_nullable)
        identity = as_bool(row.is_identity)
        computed = as_bool(row.is_computed)

        pk_columns = primary_keys.get(
            (schema, table), []
        )

        is_pk = column in pk_columns

        fk_targets = fk_lookup.get(
            (schema, table, column), []
        )

        unique_description = get_unique_description(
            schema, table, column, unique_lookup
        )

        roles = []

        if is_pk:
            roles.append("PRIMARY KEY")

        if fk_targets:
            roles.append("FOREIGN KEY")

        if unique_description.startswith(
            ("Unique column", "Part of composite", "Unique index")
        ):
            roles.append("UNIQUE KEY / INDEX")

        if identity:
            requirement = "System-generated identity"
        elif computed:
            requirement = "Computed"
        elif nullable:
            requirement = "Optional"
        else:
            requirement = "Required"

        description = COLUMN_DESCRIPTIONS.get(
            column,
            f"Database field {column} belonging to {table}."
        )

        rows.append({

            "Schema": schema,
            "Table": table,

            "Table Description": TABLE_DESCRIPTIONS.get(
                table, "No business description defined."
            ),

            "Column Order": row.column_id,
            "Column": column,
            "SQL Data Type": sql_type(row),

            "Required / Optional": requirement,
            "Nullable": nullable,
            "Identity": identity,
            "Computed": computed,

            "Default": clean(row.default_definition),

            "Key Role": "; ".join(roles),

            "Referenced Table/Column": "; ".join(fk_targets),

            "Allowed Values / Constraint": get_check_definitions(
                schema, table, column, checks
            ),

            "Unit": UNIT_HINTS.get(column, ""),

            "Unique": unique_description,

            "Business Definition": description,

            "Validation Notes": (
                "Apply database PK, FK, unique-key and CHECK constraints. "
                "Additional scheduling rules require application validation."
            ),

            "Effective Date / Lifecycle Notes": (
                "Review date ordering, effective periods and lifecycle "
                "transitions where relevant."
                if any(
                    term in column.lower()
                    for term in (
                        "effective", "status", "from", "to",
                        "start", "end", "created", "resolved"
                    )
                )
                else ""
            )
        })

    return pd.DataFrame(rows)


# ============================================================
# 8. TABLE CATALOG
# ============================================================

def build_table_catalog(columns, primary_keys):

    rows = []

    for (schema, table), group in columns.groupby(
        ["schema_name", "table_name"],
        sort=True
    ):

        rows.append({

            "Schema": schema,
            "Table": table,

            "Description": TABLE_DESCRIPTIONS.get(
                table, "No business description defined."
            ),

            "Column Count": len(group),

            "Primary Key": ", ".join(
                primary_keys.get((schema, table), [])
            ),

            "Identity Columns": ", ".join(
                group.loc[
                    group["is_identity"].apply(as_bool),
                    "column_name"
                ].astype(str)
            ),

            "Lifecycle / Effective-Date Fields": ", ".join(
                group.loc[
                    group["column_name"].str.contains(
                        "Status|Effective|CreatedAt|ResolvedAt|Start|End",
                        case=False,
                        regex=True
                    ),
                    "column_name"
                ].astype(str)
            )
        })

    return pd.DataFrame(rows)


# ============================================================
# 9. RELATIONSHIP REGISTER
# ============================================================

def build_relationships(fks, columns, key_groups):

    rows = []

    grouped = fks.groupby(
        ["child_schema", "child_table", "foreign_key_name"],
        sort=True
    )

    for (child_schema, child_table, fk_name), group in grouped:

        group = group.sort_values("column_ordinal")
        first = group.iloc[0]

        child_columns = group["child_column"].astype(str).tolist()
        parent_columns = group["parent_column"].astype(str).tolist()

        nullable_flags = []

        for col in child_columns:

            match = columns[
                (columns["schema_name"] == child_schema) &
                (columns["table_name"] == child_table) &
                (columns["column_name"] == col)
            ]

            if not match.empty:
                nullable_flags.append(
                    as_bool(match.iloc[0]["is_nullable"])
                )

        parent_cardinality, cardinality_note = (
            get_fk_relationship_cardinality(
                child_schema,
                child_table,
                child_columns,
                key_groups
            )
        )

        rows.append({

            "Foreign Key": fk_name,

            "Child Table": f"{child_schema}.{child_table}",

            "Child Column(s)": ", ".join(child_columns),

            "Parent Table": (
                f"{first['parent_schema']}.{first['parent_table']}"
            ),

            "Parent Column(s)": ", ".join(parent_columns),

            "Relationship (Child to Parent)": "N:1",

            "Relationship (Parent to Child)": parent_cardinality,

            "Optional on Child": (
                "Yes" if any(nullable_flags) else "No"
            ),

            "Delete Action": first["delete_referential_action_desc"],

            "Update Action": first["update_referential_action_desc"],

            "Enabled": not as_bool(first["is_disabled"]),

            "Trusted": not as_bool(first["is_not_trusted"]),

            "Notes": cardinality_note
        })

    return pd.DataFrame(rows)


# ============================================================
# 10. KEY REGISTER
# ============================================================

def build_key_register(keys):

    rows = []

    grouped = keys.groupby(
        ["schema_name", "table_name", "key_name", "key_type"],
        sort=True
    )

    for (schema, table, name, key_type), group in grouped:

        ordered = group.sort_values("key_ordinal")

        cols = ordered["column_name"].astype(str).tolist()

        rows.append({

            "Schema": schema,
            "Table": table,
            "Key Name": name,
            "Key Type": key_type,
            "Columns": ", ".join(cols),
            "Column Count": len(cols),

            "Uniqueness Scope": (
                "Single column" if len(cols) == 1
                else "Composite key"
            ),

            "Metadata Limitation": (
                "Index filter predicate not included in export."
                if key_type == "UNIQUE INDEX"
                else ""
            )
        })

    return pd.DataFrame(rows)


# ============================================================
# 11. CHECK CONSTRAINT REGISTER
# ============================================================

def build_constraint_register(checks):

    rows = []

    for row in checks.itertuples(index=False):

        rows.append({

            "Schema": row.schema_name,
            "Table": row.table_name,
            "Constraint Name": row.constraint_name,
            "Constraint Type": "CHECK",
            "Definition": row.definition,

            "Enabled": not as_bool(row.is_disabled),

            "Trusted": not as_bool(row.is_not_trusted),

            "Interpretation": (
                "Database-enforced CHECK constraint. "
                "Application-level rules may require additional validation."
            )
        })

    return pd.DataFrame(rows)


# ============================================================
# 12. OVERVIEW
# ============================================================

def build_overview(
    columns,
    keys,
    fks,
    checks,
    table_catalog,
    relationships,
    key_register
):

    key_column_count = len(keys)

    summary = [

        ["Project", "Exam Scheduling System"],
        ["Database", "ExamSchedulingDB"],
        ["Metadata Source", "Existing SQL Server metadata exports"],

        [
            "Schemas",
            ", ".join(sorted(columns["schema_name"].unique()))
        ],

        ["Tables", len(table_catalog)],
        ["Columns", len(columns)],

        [
            "Primary Key / Unique Key Definitions",
            len(key_register)
        ],

        ["Key Column Mappings", key_column_count],

        [
            "Primary Key Column Mappings",
            len(keys[keys["key_type"] == "PRIMARY KEY"])
        ],

        [
            "Unique Constraint Column Mappings",
            len(keys[keys["key_type"] == "UNIQUE CONSTRAINT"])
        ],

        [
            "Unique Index Column Mappings",
            len(keys[keys["key_type"] == "UNIQUE INDEX"])
        ],

        ["Foreign-Key Column Mappings", len(fks)],

        [
            "Foreign-Key Constraints",
            fks["foreign_key_name"].nunique()
        ],

        ["CHECK Constraints", len(checks)],

        [
            "Enabled Foreign-Key Mappings",
            int((~fks["is_disabled"].apply(as_bool)).sum())
        ],

        [
            "Untrusted Foreign-Key Mappings",
            int(fks["is_not_trusted"].apply(as_bool).sum())
        ],

        ["Workbook Generated", pd.Timestamp.now().isoformat()],

        [
            "Identity Design",
            "SQL Server identity keys remain unchanged. "
            "Application business codes are separate."
        ],

        [
            "Unique Index Limitation",
            "The provided key metadata does not contain filter predicates. "
            "Unique index scope must be verified from SQL Server."
        ],

        [
            "Application Rules",
            "Cross-table scheduling rules are not assumed to be "
            "enforced by database constraints."
        ],

        [
            "Ground Truth",
            "evaluation.GroundTruth is maintained separately "
            "from operational scheduling tables."
        ],

        [
            "Cardinality",
            "Derived from foreign keys and child-side unique constraints. "
            "Filtered-index uncertainty is explicitly documented."
        ]
    ]

    return pd.DataFrame(summary, columns=["Metric", "Value"])


# ============================================================
# 13. PROFESSIONAL EXCEL FORMATTING
# ============================================================

def format_workbook(path):

    workbook = load_workbook(path)

    for ws in workbook.worksheets:

        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        ws.sheet_view.showGridLines = False

        for cell in ws[1]:

            cell.font = Font(
                bold=True,
                color="FFFFFF",
                size=10
            )

            cell.fill = PatternFill(
                fill_type="solid",
                fgColor="17365D"
            )

            cell.alignment = Alignment(
                horizontal="center",
                vertical="center",
                wrap_text=True
            )

        ws.row_dimensions[1].height = 34

        for column_cells in ws.columns:

            column_letter = get_column_letter(
                column_cells[0].column
            )

            header = str(column_cells[0].value or "")

            if header in ("Definition", "Interpretation", "Unique"):
                width = 48

            elif header in (
                "Business Definition",
                "Validation Notes",
                "Effective Date / Lifecycle Notes",
                "Allowed Values / Constraint",
                "Notes",
                "Metadata Limitation"
            ):
                width = 48

            elif ws.title == "Data Dictionary":
                width = 25

            elif ws.title == "Relationships":
                width = 32

            else:
                width = min(max(len(header) + 3, 16), 36)

            ws.column_dimensions[column_letter].width = width

        for row in ws.iter_rows(min_row=2):

            for cell in row:

                cell.alignment = Alignment(
                    vertical="top",
                    wrap_text=True
                )

    workbook.save(path)


# ============================================================
# 14. MAIN EXECUTION
# ============================================================

def main():

    print("\n========================================")
    print("EXAM SCHEDULING DATA DICTIONARY")
    print("========================================")

    # Load actual metadata.

    print("\n[1/8] Loading SQL Server metadata...")

    columns = load_csv("columns")
    keys = load_csv("keys")
    fks = load_csv("foreign_keys")
    checks = load_csv("checks")

    print("Columns metadata:", len(columns))
    print("Key metadata:", len(keys))
    print("Foreign-key mappings:", len(fks))
    print("CHECK constraints:", len(checks))

    # Validate source metadata.

    print("\n[2/8] Validating metadata...")

    validate_metadata(columns, keys, fks, checks)

    # Build keys.

    print("\n[3/8] Building key and uniqueness mappings...")

    key_groups, primary_keys, unique_lookup = (
        build_key_metadata(keys)
    )

    print("Key definitions:", len(key_groups))
    print("Primary-key tables:", len(primary_keys))
    print("Columns with unique metadata:", len(unique_lookup))

    # Build foreign keys.

    print("\n[4/8] Building foreign-key mappings...")

    fk_lookup = build_foreign_key_metadata(fks)

    print("Foreign-key column mappings:", len(fk_lookup))

    # Build workbook datasets.

    print("\n[5/8] Building workbook sheets...")

    dictionary = build_data_dictionary(
        columns,
        checks,
        primary_keys,
        fk_lookup,
        unique_lookup
    )

    table_catalog = build_table_catalog(
        columns,
        primary_keys
    )

    relationships = build_relationships(
        fks,
        columns,
        key_groups
    )

    key_register = build_key_register(keys)

    constraints = build_constraint_register(checks)

    overview = build_overview(
        columns,
        keys,
        fks,
        checks,
        table_catalog,
        relationships,
        key_register
    )

    print("Data dictionary rows:", len(dictionary))
    print("Table rows:", len(table_catalog))
    print("Relationship rows:", len(relationships))
    print("Key definitions:", len(key_register))
    print("Constraint rows:", len(constraints))

    # Export.

    print("\n[6/8] Exporting Excel workbook...")

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with pd.ExcelWriter(
        OUTPUT,
        engine="openpyxl"
    ) as writer:

        overview.to_excel(
            writer,
            sheet_name="Overview",
            index=False
        )

        dictionary.to_excel(
            writer,
            sheet_name="Data Dictionary",
            index=False
        )

        table_catalog.to_excel(
            writer,
            sheet_name="Tables",
            index=False
        )

        relationships.to_excel(
            writer,
            sheet_name="Relationships",
            index=False
        )

        key_register.to_excel(
            writer,
            sheet_name="Keys",
            index=False
        )

        constraints.to_excel(
            writer,
            sheet_name="Constraints",
            index=False
        )

    # Format.

    print("\n[7/8] Applying workbook formatting...")

    format_workbook(OUTPUT)

    # Reopen and validate.

    print("\n[8/8] Verifying generated workbook...")

    workbook = load_workbook(
        OUTPUT,
        read_only=True
    )

    expected_sheets = [
        "Overview",
        "Data Dictionary",
        "Tables",
        "Relationships",
        "Keys",
        "Constraints"
    ]

    if workbook.sheetnames != expected_sheets:
        raise RuntimeError(
            f"Unexpected worksheet list: {workbook.sheetnames}"
        )

    expected_counts = {
        "Data Dictionary": len(columns),
        "Tables": len(table_catalog),
        "Relationships": len(relationships),
        "Keys": len(key_register),
        "Constraints": len(constraints)
    }

    for sheet, expected in expected_counts.items():

        actual = workbook[sheet].max_row - 1

        if actual != expected:
            workbook.close()

            raise RuntimeError(
                f"{sheet}: expected {expected} rows, got {actual}"
            )

    workbook.close()

    # Final report.

    print("\n========================================")
    print("DATA DICTIONARY GENERATED SUCCESSFULLY")
    print("========================================")

    print(f"Output: {OUTPUT}")
    print(f"File size: {OUTPUT.stat().st_size:,} bytes")

    print(f"Tables: {len(table_catalog)}")
    print(f"Columns: {len(dictionary)}")
    print(f"Relationships: {len(relationships)}")
    print(f"Key definitions: {len(key_register)}")
    print(f"CHECK constraints: {len(constraints)}")

    print("\nWorksheets:")

    for sheet in expected_sheets:
        print(f"  PASS - {sheet}")

    print("\nWorkbook verification: PASS")

    print("========================================")


if __name__ == "__main__":
    main()
