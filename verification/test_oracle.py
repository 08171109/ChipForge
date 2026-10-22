import unittest
from verification.oracle import pixel, windows


class OracleChecks(unittest.TestCase):
    def test_threshold_and_unsigned_extremes(self):
        for value, expected in [(79, 0), (80, 0), (81, 255)]:
            self.assertEqual(pixel([0, value, 0, 0, 0, 0, 0, 0, 0]), expected)
        for value in (0, 128, 255):
            self.assertEqual(pixel([value]*9), 0)
            self.assertEqual(pixel([value]*9, 1), value)
            self.assertEqual(pixel([value]*9, 2), value)

    def test_blur_and_saturation(self):
        self.assertEqual(pixel([0, 0, 0, 0, 255, 0, 0, 0, 0], 1), 63)
        self.assertEqual(pixel([0, 255, 0, 255, 0, 255, 0, 255, 0], 2), 0)
        self.assertEqual(pixel([0, 0, 0, 0, 255, 0, 0, 0, 0], 2), 255)
        self.assertEqual(pixel([255]*9, 3), 0)

    def test_replicated_border_and_validation(self):
        self.assertEqual(list(windows([[7]])), [[7]*9])
        self.assertEqual(next(windows([[1, 2], [3, 4]])), [1, 1, 2, 1, 1, 2, 3, 3, 4])
        for values in ([0]*8, [256]*9, [-1]*9):
            with self.assertRaises(ValueError):
                pixel(values)


if __name__ == "__main__":
    unittest.main()

