
from dataclasses import dataclass


@dataclass
class IDGenerator:
    academic_year: int = 2026

    def student(self, number: int) -> str:
        return f"STU-{number:06d}"

    def course(self, number: int) -> str:
        return f"CRS-{number:06d}"

    def exam(self, number: int) -> str:
        return f"EXAM-{self.academic_year}-{number:06d}"

    def room(self, number: int) -> str:
        return f"ROOM-{number:06d}"

    def invigilator(self, number: int) -> str:
        return f"INV-{number:06d}"

    def assignment(self, exam_id: str, room_id: str) -> str:
        return f"ASN-{exam_id}-{room_id}"


if __name__ == "__main__":
    ids = IDGenerator()

    print("Student:", ids.student(1))
    print("Course:", ids.course(1))
    print("Exam:", ids.exam(1))
    print("Room:", ids.room(1))
    print("Invigilator:", ids.invigilator(1))
    print(
        "Assignment:",
        ids.assignment(ids.exam(1), ids.room(1))
    )
