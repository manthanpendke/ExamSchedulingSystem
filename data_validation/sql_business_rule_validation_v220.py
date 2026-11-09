"""
Read-only SQL business-rule validation for Exam Scheduling System v2.2.0.
Does not modify data, disable triggers, or access evaluation/GroundTruth.
Run from project root:
    python .\data_validation\sql_business_rule_validation_v220.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.connection import get_connection


CHECKS = [
    (
        "Student has overlapping exam assignments",
        """
        WITH X AS (
          SELECT e.StudentID, a.AssignmentID, a.ExamID, a.SchedulingRunID,
                 a.StartTime, a.EndTime
          FROM dbo.AssignmentStudent ast
          JOIN dbo.ExamEnrollment ee ON ee.ExamEnrollmentID = ast.ExamEnrollmentID
                                   AND ee.ExamID = ast.ExamID
          JOIN dbo.Enrollment e ON e.EnrollmentID = ee.EnrollmentID
          JOIN dbo.ScheduleAssignment a ON a.AssignmentID = ast.AssignmentID
                                        AND a.ExamID = ast.ExamID
                                        AND a.SchedulingRunID = ast.SchedulingRunID
          WHERE ast.AllocationStatus = 'ALLOCATED'
            AND a.AssignmentStatus = 'CONFIRMED'
        )
        SELECT COUNT_BIG(*)
        FROM X x
        JOIN X y ON y.StudentID = x.StudentID
                AND y.SchedulingRunID = x.SchedulingRunID
                AND y.AssignmentID > x.AssignmentID
                AND y.ExamID <> x.ExamID
                AND x.StartTime < y.EndTime
                AND y.StartTime < x.EndTime;
        """,
        0,
    ),
    (
        "Room has overlapping confirmed assignments",
        """
        SELECT COUNT_BIG(*)
        FROM dbo.ScheduleAssignment a
        JOIN dbo.ScheduleAssignment b
          ON b.RoomID = a.RoomID
         AND b.SchedulingRunID = a.SchedulingRunID
         AND b.AssignmentID > a.AssignmentID
         AND b.AssignmentStatus = 'CONFIRMED'
         AND a.StartTime < b.EndTime
         AND b.StartTime < a.EndTime
        WHERE a.AssignmentStatus = 'CONFIRMED';
        """,
        0,
    ),
    (
        "Invigilator has overlapping duties",
        """
        SELECT COUNT_BIG(*)
        FROM dbo.AssignmentInvigilator ai
        JOIN dbo.ScheduleAssignment a
          ON a.AssignmentID = ai.AssignmentID
         AND a.ExamID = ai.ExamID
         AND a.SchedulingRunID = ai.SchedulingRunID
        JOIN dbo.AssignmentInvigilator bi
          ON bi.InvigilatorID = ai.InvigilatorID
         AND bi.AssignmentInvigilatorID > ai.AssignmentInvigilatorID
         AND bi.AssignmentStatus = 'ASSIGNED'
        JOIN dbo.ScheduleAssignment b
          ON b.AssignmentID = bi.AssignmentID
         AND b.ExamID = bi.ExamID
         AND b.SchedulingRunID = bi.SchedulingRunID
        WHERE ai.AssignmentStatus = 'ASSIGNED'
          AND a.AssignmentStatus = 'CONFIRMED'
          AND b.AssignmentStatus = 'CONFIRMED'
          AND a.StartTime < b.EndTime
          AND b.StartTime < a.EndTime;
        """,
        0,
    ),
    (
        "Assignment student count exceeds assigned capacity",
        """
        SELECT COUNT_BIG(*)
        FROM dbo.ScheduleAssignment a
        OUTER APPLY (
          SELECT COUNT_BIG(*) AS StudentCount
          FROM dbo.AssignmentStudent ast
          WHERE ast.AssignmentID = a.AssignmentID
            AND ast.ExamID = a.ExamID
            AND ast.SchedulingRunID = a.SchedulingRunID
            AND ast.AllocationStatus = 'ALLOCATED'
        ) x
        WHERE a.AssignmentStatus = 'CONFIRMED'
          AND x.StudentCount > a.AssignedCapacity;
        """,
        0,
    ),
    (
        "Separate-room accommodation shares an assignment with another student",
        """
        SELECT COUNT_BIG(*)
        FROM dbo.AssignmentStudent ast
        JOIN dbo.ExamEnrollment ee
          ON ee.ExamEnrollmentID = ast.ExamEnrollmentID
         AND ee.ExamID = ast.ExamID
        JOIN dbo.Enrollment en ON en.EnrollmentID = ee.EnrollmentID
        JOIN dbo.ScheduleAssignment sa
          ON sa.AssignmentID = ast.AssignmentID
         AND sa.ExamID = ast.ExamID
         AND sa.SchedulingRunID = ast.SchedulingRunID
        JOIN dbo.Accommodation ac
          ON ac.StudentID = en.StudentID
         AND ac.RequiresSeparateRoom = 1
         AND ac.AccommodationStatus = 'ACTIVE'
         AND CAST(sa.StartTime AS date) >= ac.EffectiveFrom
         AND (ac.EffectiveTo IS NULL OR CAST(sa.StartTime AS date) <= ac.EffectiveTo)
        WHERE ast.AllocationStatus = 'ALLOCATED'
          AND sa.AssignmentStatus = 'CONFIRMED'
          AND EXISTS (
            SELECT 1
            FROM dbo.AssignmentStudent other
            WHERE other.AssignmentID = ast.AssignmentID
              AND other.ExamID = ast.ExamID
              AND other.SchedulingRunID = ast.SchedulingRunID
              AND other.AssignmentStudentID <> ast.AssignmentStudentID
              AND other.AllocationStatus = 'ALLOCATED'
          );
        """,
        0,
    ),
    (
        "ExamEnrollment course does not match Exam and Enrollment",
        """
        SELECT COUNT_BIG(*)
        FROM dbo.ExamEnrollment ee
        JOIN dbo.Exam ex ON ex.ExamID = ee.ExamID
        JOIN dbo.Enrollment en ON en.EnrollmentID = ee.EnrollmentID
        WHERE ee.CourseID <> ex.CourseID
           OR ee.CourseID <> en.CourseID;
        """,
        0,
    ),
    (
        "Confirmed assignment falls outside its exam window",
        """
        SELECT COUNT_BIG(*)
        FROM dbo.ScheduleAssignment sa
        JOIN dbo.Exam ex ON ex.ExamID = sa.ExamID
        OUTER APPLY (
            SELECT MAX(ac.ExtensionPercentage) AS MaxExtensionPercentage
            FROM dbo.AssignmentStudent ast
            JOIN dbo.ExamEnrollment ee
              ON ee.ExamEnrollmentID = ast.ExamEnrollmentID
             AND ee.ExamID = ast.ExamID
            JOIN dbo.Enrollment en ON en.EnrollmentID = ee.EnrollmentID
            JOIN dbo.Accommodation ac ON ac.StudentID = en.StudentID
            WHERE ast.AssignmentID = sa.AssignmentID
              AND ast.ExamID = sa.ExamID
              AND ast.SchedulingRunID = sa.SchedulingRunID
              AND ast.AllocationStatus = 'ALLOCATED'
              AND ac.AccommodationStatus = 'ACTIVE'
              AND ac.AccommodationType = 'EXTENDED_TIME'
              AND ac.ExtensionPercentage > 0
              AND ac.EffectiveFrom <= CAST(sa.StartTime AS date)
              AND (ac.EffectiveTo IS NULL OR ac.EffectiveTo >= CAST(sa.StartTime AS date))
        ) ext
        WHERE sa.AssignmentStatus = 'CONFIRMED'
          AND (
              sa.StartTime < ex.ExamWindowStart
              OR sa.EndTime > DATEADD(
                  MINUTE,
                  CAST(CEILING(90.0 * COALESCE(ext.MaxExtensionPercentage, 0) / 100.0) AS int),
                  ex.ExamWindowEnd
              )
          );
        """,
        0,
    ),
    (
        "Assignment without exactly one assigned invigilator",
        """
        SELECT COUNT_BIG(*)
        FROM dbo.ScheduleAssignment sa
        OUTER APPLY (
          SELECT COUNT_BIG(*) AS InvigilatorCount
          FROM dbo.AssignmentInvigilator ai
          WHERE ai.AssignmentID = sa.AssignmentID
            AND ai.ExamID = sa.ExamID
            AND ai.SchedulingRunID = sa.SchedulingRunID
            AND ai.AssignmentStatus = 'ASSIGNED'
        ) x
        WHERE sa.AssignmentStatus = 'CONFIRMED'
          AND x.InvigilatorCount <> 1;
        """,
        0,
    ),
]


def main() -> int:
    conn = None
    failures = []
    try:
        conn = get_connection()
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute("SELECT DB_NAME();")
        print("=" * 76)
        print("EXAM SCHEDULING SYSTEM v2.2.0 - READ-ONLY BUSINESS-RULE VALIDATION")
        print("Database:", cur.fetchone()[0])
        print("No writes. No trigger changes. No evaluation/GroundTruth access.")
        print("=" * 76)

        for title, sql, expected in CHECKS:
            cur.execute(sql)
            value = int(cur.fetchone()[0])
            passed = value == expected
            print(f"[{'PASS' if passed else 'FAIL'}] {title}: {value:,} (expected {expected:,})")
            if not passed:
                failures.append((title, value, expected))

        # Coverage / accounting metrics; these are informational, not zero-error tests.
        print("\nALLOCATION ACCOUNTING")
        cur.execute("""
          SELECT
            (SELECT COUNT_BIG(*) FROM dbo.ExamEnrollment) AS exam_enrollments,
            (SELECT COUNT_BIG(*) FROM dbo.AssignmentStudent
             WHERE AllocationStatus = 'ALLOCATED') AS allocated_exam_enrollments,
            (SELECT COUNT_BIG(*) FROM dbo.SchedulingException) AS scheduling_exceptions,
            (SELECT COUNT_BIG(*) FROM dbo.ScheduleAssignment
             WHERE AssignmentStatus = 'CONFIRMED') AS confirmed_room_assignments,
            (SELECT COUNT_BIG(*) FROM dbo.AssignmentInvigilator
             WHERE AssignmentStatus = 'ASSIGNED') AS assigned_invigilator_duties;
        """)
        row = cur.fetchone()
        labels = (
            "Exam enrollments",
            "Allocated student-exam rows",
            "Scheduling exceptions",
            "Confirmed room assignments",
            "Assigned invigilator duties",
        )
        for label, value in zip(labels, row):
            print(f"  {label:<34} {int(value):,}")

        print("\n" + "=" * 76)
        if failures:
            print(f"BUSINESS-RULE RESULT: NEEDS REVIEW ({len(failures)} failed check(s))")
            print("Review each failed count; some may indicate genuine allocation exceptions.")
            return 1
        print(f"BUSINESS-RULE RESULT: PASSED ({len(CHECKS)}/{len(CHECKS)} checks)")
        print("No data was modified.")
        return 0
    except Exception as exc:
        print(f"VALIDATION ERROR: {type(exc).__name__}: {exc}")
        return 2
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
