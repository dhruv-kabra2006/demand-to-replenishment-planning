"""Small invariants for the analysis; run with python -m unittest test_logic.py."""
import unittest

import pandas as pd

from analysis import clean_transactions, daily_panel, forecast_evaluation, simulate


class InventoryLogicTests(unittest.TestCase):
    def test_cleaning_removes_cancelled_and_non_merchandise(self):
        raw = pd.DataFrame({
            "InvoiceNo": ["1", "C2", "3", "4"],
            "StockCode": ["12345", "12345", "POST", "12345"],
            "InvoiceDate": ["2011-02-01"] * 4,
            "Quantity": [2, -2, 1, 0], "UnitPrice": [1, 1, 1, 1],
        })
        clean, audit = clean_transactions(raw)
        self.assertEqual(audit["retained_rows"], 1)
        self.assertEqual(int(clean.Quantity.sum()), 2)

    def test_forecast_excludes_current_day(self):
        data = pd.DataFrame({"Date": pd.date_range("2011-01-01", "2011-11-30"),
                             "StockCode": "12345", "units": 1})
        data.loc[data.Date == pd.Timestamp("2011-10-01"), "units"] = 999
        test, _ = forecast_evaluation(data)
        day = test[test.Date == pd.Timestamp("2011-10-01")].iloc[0]
        self.assertEqual(day.forecast_7d, 1)
        self.assertEqual(day.forecast_28d, 1)
        self.assertEqual(day.seasonal_naive_7d, 1)
        self.assertEqual(day.weekday_mean_4w, 1)

    def test_inventory_balances_and_fixed_lead_time(self):
        result = simulate([5, 5, 5, 5], rop=0, quantity=5, lead_days=2)
        self.assertEqual(result["requested_units"], result["filled_units"] + result["unfilled_units"])
        self.assertEqual(result["filled_units"], 10)

    def test_warmup_evolves_inventory_but_excludes_metrics(self):
        result = simulate([5, 5, 5, 5], rop=0, quantity=5, lead_days=2,
                          initial_on_hand=5, warmup_days=2)
        self.assertEqual(result["requested_units"], 10)
        self.assertEqual(result["filled_units"], 5)
        self.assertEqual(result["orders"], 1)

    def test_invalid_order_quantity_is_rejected(self):
        with self.assertRaises(ValueError):
            simulate([1, 2], rop=2, quantity=0, lead_days=7)


if __name__ == "__main__":
    unittest.main()
