
import csv
from pathlib import Path

from database.connection import get_connection


OUTPUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "schema"


QUERIES = {
    "columns.csv": """
        SELECT
            s.name AS schema_name,
            t.name AS table_name,
            c.column_id,
            c.name AS column_name,
            ty.name AS data_type,
            c.max_length,
            c.precision,
            c.scale,
            c.is_nullable,
            c.is_identity,
            c.is_computed,
            dc.definition AS default_definition
        FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        JOIN sys.columns c ON c.object_id = t.object_id
        JOIN sys.types ty ON ty.user_type_id = c.user_type_id
        LEFT JOIN sys.default_constraints dc
            ON dc.object_id = c.default_object_id
        WHERE t.is_ms_shipped = 0
        ORDER BY s.name, t.name, c.column_id;
    """,

    "keys.csv": """
        SELECT
            s.name AS schema_name,
            t.name AS table_name,
            i.name AS key_name,
            CASE
                WHEN i.is_primary_key = 1 THEN 'PRIMARY KEY'
                WHEN i.is_unique_constraint = 1 THEN 'UNIQUE CONSTRAINT'
                ELSE 'UNIQUE INDEX'
            END AS key_type,
            c.name AS column_name,
            ic.key_ordinal
        FROM sys.indexes i
        JOIN sys.tables t ON t.object_id = i.object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        JOIN sys.index_columns ic
            ON ic.object_id = i.object_id
            AND ic.index_id = i.index_id
        JOIN sys.columns c
            ON c.object_id = ic.object_id
            AND c.column_id = ic.column_id
        WHERE i.is_primary_key = 1
           OR i.is_unique_constraint = 1
           OR (i.is_unique = 1 AND i.is_primary_key = 0
               AND i.is_unique_constraint = 0)
        ORDER BY s.name, t.name, i.name, ic.key_ordinal;
    """,

    "foreign_keys.csv": """
        SELECT
            fk.name AS foreign_key_name,
            ps.name AS child_schema,
            pt.name AS child_table,
            pc.name AS child_column,
            rs.name AS parent_schema,
            rt.name AS parent_table,
            rc.name AS parent_column,
            fkc.constraint_column_id AS column_ordinal,
            fk.is_disabled,
            fk.is_not_trusted,
            fk.delete_referential_action_desc,
            fk.update_referential_action_desc
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc
            ON fkc.constraint_object_id = fk.object_id
        JOIN sys.tables pt ON pt.object_id = fk.parent_object_id
        JOIN sys.schemas ps ON ps.schema_id = pt.schema_id
        JOIN sys.columns pc
            ON pc.object_id = pt.object_id
            AND pc.column_id = fkc.parent_column_id
        JOIN sys.tables rt ON rt.object_id = fk.referenced_object_id
        JOIN sys.schemas rs ON rs.schema_id = rt.schema_id
        JOIN sys.columns rc
            ON rc.object_id = rt.object_id
            AND rc.column_id = fkc.referenced_column_id
        ORDER BY ps.name, pt.name, fk.name, fkc.constraint_column_id;
    """,

    "check_constraints.csv": """
        SELECT
            s.name AS schema_name,
            t.name AS table_name,
            cc.name AS constraint_name,
            cc.definition,
            cc.is_disabled,
            cc.is_not_trusted
        FROM sys.check_constraints cc
        JOIN sys.tables t ON t.object_id = cc.parent_object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        ORDER BY s.name, t.name, cc.name;
    """,
}


def export_query(cursor, filename, query):
    cursor.execute(query)
    columns = [column[0] for column in cursor.description]
    rows = cursor.fetchall()

    output_path = OUTPUT_DIR / filename

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows(rows)

    print(f"{filename}: {len(rows)} rows exported")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    connection = get_connection()

    try:
        cursor = connection.cursor()

        print("Exporting SQL Server schema metadata...")
        print(f"Output directory: {OUTPUT_DIR}")
        print()

        for filename, query in QUERIES.items():
            export_query(cursor, filename, query)

        print()
        print("SCHEMA METADATA EXPORT SUCCESSFUL")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
