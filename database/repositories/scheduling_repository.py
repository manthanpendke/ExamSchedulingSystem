
"""Read-only SQL Server repository for the scheduling engine.

Loads operational scheduling inputs into domain models.
Does not read evaluation.GroundTruth or modify the database.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from database.connection import get_connection
from scheduling.models import (
    Exam,
    EquipmentRequirement,
    Invigilator,
    InvigilatorAvailability,
    Room,
    RoomCapacityPeriod,
    RoomClosure,
    RoomEquipment,
    StudentAccommodation,
    StudentParticipant,
)


class SchedulingRepository:
    """Loads scheduling input data from the existing SQL Server database."""

    def __init__(self, connection_factory=get_connection):
        self.connection_factory = connection_factory

    @staticmethod
    def _dict_rows(cursor):
        columns = [column[0] for column in cursor.description]
        return [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]

    def load_exams(self, cursor) -> list[Exam]:
        """Load READY exams, registered participants and requirements."""

        cursor.execute("""
            SELECT
                e.ExamID,
                e.ExamCode,
                e.CourseID,
                e.ExamWindowStart,
                e.ExamWindowEnd,
                er.DurationMinutes,
                er.AccessibilityRequired
            FROM dbo.Exam AS e
            INNER JOIN dbo.ExamRequirement AS er
                ON er.ExamID = e.ExamID
            WHERE e.ExamStatus = 'READY'
            ORDER BY e.ExamID;
        """)

        exam_rows = self._dict_rows(cursor)

        cursor.execute("""
            SELECT
                ee.ExamEnrollmentID,
                ee.ExamID,
                ee.CourseID,
                en.EnrollmentID,
                en.StudentID,
                en.EffectiveFrom AS EnrollmentEffectiveFrom,
                en.EffectiveTo AS EnrollmentEffectiveTo,
                s.StudentCode
            FROM dbo.ExamEnrollment AS ee
            INNER JOIN dbo.Exam AS e
                ON e.ExamID = ee.ExamID
            INNER JOIN dbo.Enrollment AS en
                ON en.EnrollmentID = ee.EnrollmentID
            INNER JOIN dbo.Student AS s
                ON s.StudentID = en.StudentID
            WHERE
                e.ExamStatus = 'READY'
                AND ee.ParticipationStatus = 'REGISTERED'
                AND en.EnrollmentStatus = 'ENROLLED'
                AND s.Status = 'ACTIVE'
                AND ee.CourseID = en.CourseID
                AND ee.CourseID = e.CourseID
            ORDER BY ee.ExamID, s.StudentID;
        """)

        participant_rows = self._dict_rows(cursor)

        cursor.execute("""
            SELECT
                StudentID,
                AccommodationType,
                ExtensionPercentage,
                RequiresSeparateRoom,
                EffectiveFrom,
                EffectiveTo,
                AccommodationStatus
            FROM dbo.Accommodation
            WHERE AccommodationStatus = 'ACTIVE'
            ORDER BY StudentID, AccommodationID;
        """)

        accommodation_rows = self._dict_rows(cursor)

        accommodations_by_student = defaultdict(list)

        for row in accommodation_rows:
            accommodations_by_student[row["StudentID"]].append(
                StudentAccommodation(
                    accommodation_type=row["AccommodationType"],
                    extension_percentage=(
                        Decimal(str(row["ExtensionPercentage"]))
                        if row["ExtensionPercentage"] is not None
                        else None
                    ),
                    requires_separate_room=bool(
                        row["RequiresSeparateRoom"]
                    ),
                    effective_from=row["EffectiveFrom"],
                    effective_to=row["EffectiveTo"],
                    status=row["AccommodationStatus"],
                )
            )

        participants_by_exam = defaultdict(list)

        for row in participant_rows:
            participants_by_exam[row["ExamID"]].append(
                StudentParticipant(
                    exam_enrollment_id=row["ExamEnrollmentID"],
                    student_id=row["StudentID"],
                    student_code=row["StudentCode"],
                    seat_number=f"SEAT-{row['StudentID']}",
                    accommodations=tuple(
                        accommodations_by_student[row["StudentID"]]
                    ),
                    enrollment_effective_from=(
                        row["EnrollmentEffectiveFrom"]
                    ),
                    enrollment_effective_to=(
                        row["EnrollmentEffectiveTo"]
                    ),
                )
            )

        cursor.execute("""
            SELECT
                ExamID,
                EquipmentID,
                QuantityRequired,
                IsMandatory
            FROM dbo.ExamRequiredEquipment
            ORDER BY ExamID, EquipmentID;
        """)

        equipment_rows = self._dict_rows(cursor)
        equipment_by_exam = defaultdict(list)

        for row in equipment_rows:
            equipment_by_exam[row["ExamID"]].append(
                EquipmentRequirement(
                    equipment_id=row["EquipmentID"],
                    quantity_required=row["QuantityRequired"],
                    mandatory=bool(row["IsMandatory"]),
                )
            )

        exams = []

        for row in exam_rows:
            exam_id = row["ExamID"]

            exams.append(
                Exam(
                    exam_id=exam_id,
                    exam_code=row["ExamCode"],
                    course_id=row["CourseID"],
                    window_start=row["ExamWindowStart"],
                    window_end=row["ExamWindowEnd"],
                    base_duration_minutes=row["DurationMinutes"],
                    accessibility_required=bool(
                        row["AccessibilityRequired"]
                    ),
                    participants=tuple(
                        participants_by_exam[exam_id]
                    ),
                    equipment_requirements=tuple(
                        equipment_by_exam[exam_id]
                    ),
                )
            )

        return exams

    def load_rooms(self, cursor) -> list[Room]:
        """Load rooms, effective capacities, equipment and closures."""

        cursor.execute("""
            SELECT
                RoomID,
                RoomCode,
                IsActive,
                RoomType
            FROM dbo.Room
            ORDER BY RoomID;
        """)

        room_rows = self._dict_rows(cursor)

        cursor.execute("""
            SELECT
                RoomID,
                Capacity,
                EffectiveFrom,
                EffectiveTo
            FROM dbo.RoomCapacity
            ORDER BY RoomID, EffectiveFrom;
        """)

        capacity_rows = self._dict_rows(cursor)

        cursor.execute("""
            SELECT
                RoomID,
                EquipmentID,
                Quantity,
                EffectiveFrom,
                EffectiveTo
            FROM dbo.RoomEquipment
            ORDER BY RoomID, EquipmentID;
        """)

        equipment_rows = self._dict_rows(cursor)

        cursor.execute("""
            SELECT
                RoomID,
                ClosureStart,
                ClosureEnd,
                ClosureStatus
            FROM dbo.RoomClosure
            ORDER BY RoomID, ClosureStart;
        """)

        closure_rows = self._dict_rows(cursor)

        capacities_by_room = defaultdict(list)
        equipment_by_room = defaultdict(list)
        closures_by_room = defaultdict(list)

        for row in capacity_rows:
            capacities_by_room[row["RoomID"]].append(
                RoomCapacityPeriod(
                    capacity=row["Capacity"],
                    effective_from=row["EffectiveFrom"],
                    effective_to=row["EffectiveTo"],
                )
            )

        for row in equipment_rows:
            equipment_by_room[row["RoomID"]].append(
                RoomEquipment(
                    equipment_id=row["EquipmentID"],
                    quantity=row["Quantity"],
                    effective_from=row["EffectiveFrom"],
                    effective_to=row["EffectiveTo"],
                )
            )

        for row in closure_rows:
            closures_by_room[row["RoomID"]].append(
                RoomClosure(
                    start=row["ClosureStart"],
                    end=row["ClosureEnd"],
                    status=row["ClosureStatus"],
                )
            )

        return [
            Room(
                room_id=row["RoomID"],
                room_code=row["RoomCode"],
                is_active=bool(row["IsActive"]),
                is_accessible=row["RoomType"] == "ACCESSIBLE",
                capacity_periods=tuple(
                    capacities_by_room[row["RoomID"]]
                ),
                equipment=tuple(
                    equipment_by_room[row["RoomID"]]
                ),
                closures=tuple(
                    closures_by_room[row["RoomID"]]
                ),
            )
            for row in room_rows
        ]

    def load_invigilators(self, cursor) -> list[Invigilator]:
        """Load active invigilators and their availability intervals."""

        cursor.execute("""
            SELECT
                InvigilatorID,
                InvigilatorCode,
                MaxDailyHours,
                Status
            FROM dbo.Invigilator
            WHERE Status = 'ACTIVE'
            ORDER BY InvigilatorID;
        """)

        invigilator_rows = self._dict_rows(cursor)

        cursor.execute("""
            SELECT
                InvigilatorID,
                AvailableFrom,
                AvailableTo,
                AvailabilityStatus
            FROM dbo.Availability
            ORDER BY InvigilatorID, AvailableFrom;
        """)

        availability_rows = self._dict_rows(cursor)
        availability_by_invigilator = defaultdict(list)

        for row in availability_rows:
            availability_by_invigilator[
                row["InvigilatorID"]
            ].append(
                InvigilatorAvailability(
                    start=row["AvailableFrom"],
                    end=row["AvailableTo"],
                    status=row["AvailabilityStatus"],
                )
            )

        return [
            Invigilator(
                invigilator_id=row["InvigilatorID"],
                invigilator_code=row["InvigilatorCode"],
                max_daily_hours=Decimal(
                    str(row["MaxDailyHours"])
                ),
                status=row["Status"],
                availability=tuple(
                    availability_by_invigilator[
                        row["InvigilatorID"]
                    ]
                ),
            )
            for row in invigilator_rows
        ]

    def load_all(self) -> dict:
        """Load scheduler inputs in one read-only database transaction.

        Uses the database's configured/default isolation level.
        Ground truth is deliberately not queried.
        """

        connection = self.connection_factory()
        cursor = None

        try:
            connection.autocommit = False
            cursor = connection.cursor()

            exams = self.load_exams(cursor)
            rooms = self.load_rooms(cursor)
            invigilators = self.load_invigilators(cursor)

            # End the read transaction without making database changes.
            connection.rollback()

            return {
                "exams": exams,
                "rooms": rooms,
                "invigilators": invigilators,
                "loaded_at": datetime.now(),
                "source": "ExamSchedulingDB_v110",
            }

        except Exception:
            connection.rollback()
            raise

        finally:
            if cursor is not None:
                cursor.close()
            connection.close()
