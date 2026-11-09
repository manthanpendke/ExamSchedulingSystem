
from database.connection import get_connection


EXPECTED_TRIGGERS = {
    "TR_ScheduleAssignment_RoomOverlap",
    "TR_AssignmentInvigilator_NoOverlap",
    "TR_AssignmentStudent_NoOverlap",
}


def verify_database():

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        print("\n========== DATABASE CONNECTION ==========")

        cursor.execute("""
            SELECT
                @@SERVERNAME,
                DB_NAME(),
                SUSER_SNAME()
        """)

        server, database, user = cursor.fetchone()

        print(f"Server   : {server}")
        print(f"Database : {database}")
        print(f"User     : {user}")

        if database != "ExamSchedulingDB":
            raise RuntimeError("Incorrect database connected.")

        # Verify table count
        cursor.execute("""
            SELECT COUNT(*)
            FROM sys.tables
        """)

        table_count = cursor.fetchone()[0]

        print(f"\nTotal tables: {table_count}")

        if table_count != 22:
            raise RuntimeError(
                f"Expected 22 tables, found {table_count}"
            )

        # Verify evaluation schema
        cursor.execute("""
            SELECT COUNT(*)
            FROM sys.schemas
            WHERE name = 'evaluation'
        """)

        evaluation_exists = cursor.fetchone()[0] == 1

        print(
            f"Evaluation schema: "
            f"{'PASS' if evaluation_exists else 'FAIL'}"
        )

        if not evaluation_exists:
            raise RuntimeError("Evaluation schema missing.")

        # Verify triggers
        cursor.execute("""
            SELECT name
            FROM sys.triggers
            WHERE is_disabled = 0
        """)

        actual_triggers = {
            row[0] for row in cursor.fetchall()
        }

        missing = EXPECTED_TRIGGERS - actual_triggers

        print("\n========== TRIGGER VALIDATION ==========")

        for trigger in sorted(EXPECTED_TRIGGERS):
            status = (
                "PASS"
                if trigger in actual_triggers
                else "FAIL"
            )
            print(f"{trigger}: {status}")

        if missing:
            raise RuntimeError(
                f"Missing or disabled triggers: {missing}"
            )

        # Verify foreign key health
        cursor.execute("""
            SELECT
                COUNT(*),
                SUM(CASE WHEN is_disabled = 1
                    THEN 1 ELSE 0 END),
                SUM(CASE WHEN is_not_trusted = 1
                    THEN 1 ELSE 0 END)
            FROM sys.foreign_keys
        """)

        total_fk, disabled_fk, untrusted_fk = cursor.fetchone()

        print("\n========== INTEGRITY VALIDATION ==========")
        print(f"Foreign keys : {total_fk}")
        print(f"Disabled FK  : {disabled_fk}")
        print(f"Untrusted FK : {untrusted_fk}")

        if disabled_fk or untrusted_fk:
            raise RuntimeError(
                "Foreign key integrity verification failed."
            )

        print("\n==========================================")
        print("DATABASE VERIFICATION SUCCESSFUL")
        print("==========================================")

    except Exception as error:
        print(f"\nDATABASE VERIFICATION FAILED: {error}")
        raise

    finally:
        if connection:
            connection.close()


if __name__ == "__main__":
    verify_database()
