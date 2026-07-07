import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.policy_engine import DEFAULT_WINDOWS, MealPolicy, evaluate_payment_policy

KST = ZoneInfo("Asia/Seoul")

def dt(day: int, hhmm: str):
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 7, day, h, m, tzinfo=KST)

class PolicyEngineTests(unittest.TestCase):
    def setUp(self):
        self.policy = MealPolicy(DEFAULT_WINDOWS, daily_limit=20_000, weekend_allowed=False)

    def assertCode(self, when, amount, balance, spent_today, code):
        result = evaluate_payment_policy(amount=amount, balance=balance, spent_today=spent_today, policy=self.policy, now=when)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, code)

    def test_lunch_boundaries_inclusive(self):
        for hhmm in ["11:00", "12:30", "14:00"]:
            with self.subTest(hhmm=hhmm):
                result = evaluate_payment_policy(amount=9000, balance=50000, spent_today=0, policy=self.policy, now=dt(7, hhmm))
                self.assertTrue(result.ok)
                self.assertEqual(result.meal_window, "중식")

    def test_dinner_boundaries_inclusive(self):
        for hhmm in ["17:30", "18:45", "20:30"]:
            with self.subTest(hhmm=hhmm):
                result = evaluate_payment_policy(amount=11000, balance=50000, spent_today=0, policy=self.policy, now=dt(7, hhmm))
                self.assertTrue(result.ok)
                self.assertEqual(result.meal_window, "석식")

    def test_out_of_window_cases(self):
        for hhmm in ["10:59", "14:01", "17:29", "20:31", "23:59"]:
            with self.subTest(hhmm=hhmm):
                self.assertCode(dt(7, hhmm), 9000, 50000, 0, "OUT_OF_WINDOW")

    def test_lunch_meal_limit(self):
        self.assertCode(dt(7, "12:00"), 10001, 50000, 0, "MEAL_LIMIT")

    def test_dinner_meal_limit(self):
        self.assertCode(dt(7, "18:00"), 12001, 50000, 0, "MEAL_LIMIT")

    def test_daily_limit(self):
        self.assertCode(dt(7, "12:00"), 9000, 50000, 12000, "DAILY_LIMIT")

    def test_insufficient_balance(self):
        self.assertCode(dt(7, "12:00"), 9000, 8000, 0, "INSUFFICIENT")

    def test_weekend_blocked(self):
        self.assertCode(dt(11, "12:00"), 9000, 50000, 0, "WEEKEND_BLOCKED")

    def test_weekend_allowed(self):
        policy = MealPolicy(DEFAULT_WINDOWS, daily_limit=None, weekend_allowed=True)
        result = evaluate_payment_policy(amount=9000, balance=50000, spent_today=0, policy=policy, now=dt(11, "12:00"))
        self.assertTrue(result.ok)

if __name__ == "__main__":
    unittest.main()
