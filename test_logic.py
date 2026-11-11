"""Behavioral checks: run `python -m unittest test_logic.py`."""
import unittest

import numpy as np
import pandas as pd

from analysis import (
    classify_demand, clean_transactions, daily_panel, empirical_lead_time_demand,
    eoq_quantity, forecast_evaluation, forecast_value, optimize_policies,
    rolling_origin_backtest, simulate,
)


class DataAndForecastTests(unittest.TestCase):
    def test_cleaning_removes_cancelled_returns_and_non_merchandise(self):
        raw = pd.DataFrame({"InvoiceNo":["1","C2","3","4"],"StockCode":["12345"]*2+["POST","12345"],
            "InvoiceDate":["2011-02-01"]*4,"Quantity":[2,-2,1,0],"UnitPrice":[1,1,1,1]})
        clean, audit = clean_transactions(raw)
        self.assertEqual(audit["retained_rows"],1); self.assertEqual(int(clean.Quantity.sum()),2)

    def test_daily_panel_fills_zero_sales_days(self):
        clean=pd.DataFrame({"Date":pd.to_datetime(["2011-01-01"]),"StockCode":["12345"],"Quantity":[2]})
        panel=daily_panel(clean,["12345"])
        self.assertEqual(len(panel),334); self.assertEqual(panel.units.iloc[0],2); self.assertEqual(panel.units.iloc[1],0)

    def test_forecasts_use_only_prior_observations(self):
        hist=np.ones(35); hist[-1]=100
        self.assertEqual(forecast_value(hist,"forecast_7d"), (6+100)/7)
        self.assertAlmostEqual(forecast_value(hist,"weekday_mean_4w"),(1+1+1+1)/4)
        self.assertGreaterEqual(forecast_value(np.array([0,0,4,0,0,0,0,0]),"croston_sba"),0)

    def test_holdout_forecast_excludes_current_day(self):
        data=pd.DataFrame({"Date":pd.date_range("2011-01-01","2011-11-30"),"StockCode":"12345","units":1})
        data.loc[data.Date==pd.Timestamp("2011-10-01"),"units"]=999
        forecasts,_=forecast_evaluation(data)
        day=forecasts[forecasts.Date==pd.Timestamp("2011-10-01")].iloc[0]
        self.assertEqual(day.forecast_7d,1); self.assertEqual(day.forecast_28d,1)
        self.assertEqual(day.seasonal_naive_7d,1); self.assertEqual(day.weekday_mean_4w,1)

    def test_rolling_backtest_selects_from_validation_only(self):
        data=pd.DataFrame({"Date":pd.date_range("2011-01-01","2011-11-30"),"StockCode":"12345","units":2})
        detail,summary,selected=rolling_origin_backtest(data)
        first=detail[(detail.origin=="2011-05-01")&(detail.date=="2011-05-01")]
        self.assertTrue((first[first.method != "croston_sba"].forecast_units==2).all())
        self.assertEqual(detail.origin.nunique(),4); self.assertEqual(len(selected),1)
        self.assertIn("croston_sba",summary.method.tolist())

    def test_adi_cv2_classification(self):
        dates=pd.date_range("2011-01-01","2011-09-30")
        values=[np.ones(len(dates)),np.where(np.arange(len(dates))%3==0,1,0),
                np.where(np.arange(len(dates))%3==0,1,0),np.where(np.arange(len(dates))%2==0,1,10)]
        panel=pd.concat([pd.DataFrame({"Date":dates,"StockCode":str(i),"units":v}) for i,v in enumerate(values)])
        result=classify_demand(panel).set_index("sku")
        self.assertEqual(result.loc["0","demand_profile"],"smooth")
        self.assertEqual(result.loc["1","demand_profile"],"intermittent")
        self.assertEqual(result.loc["3","demand_profile"],"erratic")


class InventoryPolicyTests(unittest.TestCase):
    def test_inventory_balance_and_fixed_lead_time(self):
        result=simulate([5,5,5,5],rop=0,quantity=5,lead_days=2)
        self.assertEqual(result["requested_units"],result["filled_units"]+result["unfilled_units"])
        self.assertEqual(result["filled_units"],10)

    def test_warmup_evolves_state_but_excludes_metrics(self):
        result=simulate([5,5,5,5],rop=0,quantity=5,lead_days=2,initial_on_hand=5,warmup_days=2)
        self.assertEqual(result["requested_units"],10); self.assertEqual(result["filled_units"],5)
        self.assertEqual(result["orders"],1)

    def test_invalid_order_quantity_is_rejected(self):
        with self.assertRaises(ValueError): simulate([1,2],rop=2,quantity=0,lead_days=7)

    def test_empirical_lead_time_demand_uses_overlapping_windows(self):
        np.testing.assert_array_equal(empirical_lead_time_demand([1,2,3,4],2),[3,5,7])

    def test_eoq_uses_annual_holding_cost(self):
        quantity, annual_holding=eoq_quantity(mean_daily=10,purchase_cost=4)
        self.assertEqual(annual_holding,1.0)
        self.assertEqual(quantity, int(round(np.sqrt(2*(10*365)*20/1))))

    def test_policy_optimization_is_reproducible(self):
        dates=pd.date_range("2011-01-01","2011-11-30")
        panel=pd.DataFrame({"Date":dates,"StockCode":"12345","units":np.where(dates.dayofweek<5,2,0)})
        clean=pd.DataFrame({"Date":pd.to_datetime(["2011-01-01"]),"StockCode":["12345"],"UnitPrice":[10.]})
        candidates,policies=optimize_policies(panel,clean,["12345"])
        self.assertFalse(candidates.empty); self.assertEqual(len(policies),1)
        self.assertTrue((candidates.validation_end_exclusive=="2011-09-01").all())
        self.assertTrue((candidates.total_relevant_cost_gbp>=0).all())


if __name__=="__main__": unittest.main()
