import unittest

from app.services.geo import distance_m, gps_far_flag

class GeoTests(unittest.TestCase):
    def test_same_point_is_not_far(self):
        self.assertFalse(gps_far_flag(37.5665, 126.9780, 37.5665, 126.9780))

    def test_far_point_flags_true(self):
        self.assertTrue(gps_far_flag(37.5665, 126.9780, 37.57, 126.99, threshold_m=500))

    def test_distance_is_positive(self):
        self.assertGreater(distance_m(37.5665, 126.9780, 37.57, 126.99), 0)

if __name__ == "__main__":
    unittest.main()
