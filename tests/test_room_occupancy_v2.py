
import unittest

from datetime import datetime

from scheduling.models_v2 import ExamBatch, RoomBooking
from scheduling.room_occupancy_v2 import (
    build_occupancy_intervals,
    calculate_peak_occupancy,
    validate_room_capacity,
)


class TestRoomOccupancyV2(unittest.TestCase):

    def setUp(self):
        self.start = datetime(2026, 11, 16, 8, 0)

    def make_booking(
        self,
        exam_id,
        course_id,
        start,
        normal_ids,
        extended_ids,
    ):
        all_ids = tuple(normal_ids) + tuple(extended_ids)

        batch = ExamBatch(
            exam_id=exam_id,
            course_id=course_id,
            student_ids=all_ids,
            extended_student_ids=tuple(extended_ids),
        )

        return RoomBooking(
            exam_id=exam_id,
            course_id=course_id,
            room_id=1,
            start_time=start,
            batch=batch,
        )

    def test_exact_0930_room_reuse(self):
        first = self.make_booking(
            exam_id=1,
            course_id=1,
            start=self.start,
            normal_ids=range(1, 31),
            extended_ids=range(31, 41),
        )

        second = self.make_booking(
            exam_id=2,
            course_id=2,
            start=datetime(2026, 11, 16, 9, 30),
            normal_ids=range(41, 71),
            extended_ids=(),
        )

        intervals = build_occupancy_intervals([first, second])

        peak, peak_time = calculate_peak_occupancy(
            intervals,
            room_id=1,
        )

        # At 09:30, the first batch has 10 extended-time students
        # remaining while the second batch starts with 30 students.
        self.assertEqual(peak, 40)

        # Room capacity of 40 is valid.
        violations = validate_room_capacity(
            [first, second],
            {1: 40},
        )

        self.assertEqual(violations, [])

    def test_insufficient_remaining_capacity(self):
        first = self.make_booking(
            exam_id=1,
            course_id=1,
            start=self.start,
            normal_ids=range(1, 31),
            extended_ids=range(31, 41),
        )

        second = self.make_booking(
            exam_id=2,
            course_id=2,
            start=datetime(2026, 11, 16, 9, 30),
            normal_ids=range(41, 81),
            extended_ids=(),
        )

        violations = validate_room_capacity(
            [first, second],
            {1: 40},
        )

        self.assertEqual(len(violations), 1)
        self.assertEqual(
            violations[0].code,
            "ROOM_CAPACITY_EXCEEDED",
        )

    def test_next_batch_cannot_start_before_0930(self):
        first = self.make_booking(
            exam_id=1,
            course_id=1,
            start=self.start,
            normal_ids=range(1, 31),
            extended_ids=range(31, 41),
        )

        second = self.make_booking(
            exam_id=2,
            course_id=2,
            start=datetime(2026, 11, 16, 9, 0),
            normal_ids=range(41, 61),
            extended_ids=(),
        )

        violations = validate_room_capacity(
            [first, second],
            {1: 40},
        )

        self.assertTrue(
            any(
                v.code == "ROOM_CAPACITY_EXCEEDED"
                for v in violations
            )
        )


if __name__ == "__main__":
    unittest.main()
