"""Demand forecasting and illustrative replenishment analysis for UCI Online Retail.

Run `python analysis.py --input 'data/Online Retail.xlsx'`. The source records sales,
not unconstrained demand, inventory positions, supplier lead times, or purchase costs.
Inventory outputs are therefore scenario simulations, not measured retailer outcomes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

TRAIN_START = pd.Timestamp("2011-01-01")
TEST_START = pd.Timestamp("2011-10-01")
TEST_END = pd.Timestamp("2011-12-01")  # exclusive
LEAD_DAYS = 7
LEAD_TIME_SCENARIOS = (3, 7, 14)
WARMUP_START = pd.Timestamp("2011-09-01")
ORDER_COST_GBP = 20.0
ANNUAL_HOLDING_RATE = 0.25
PURCHASE_TO_SELLING_PRICE = 0.60
SHORTAGE_COST_MULTIPLE = 2.0
SERVICE_Z = 1.645
POLICY_CANDIDATE_QUANTILES = (0.50, 0.75, 0.90, 0.95, 0.98)
BACKTEST_ORIGINS = tuple(pd.Timestamp(f"2011-{month:02d}-01") for month in range(5, 9))
BACKTEST_HORIZON = 28


def clean_transactions(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    required = {"InvoiceNo", "StockCode", "InvoiceDate", "Quantity", "UnitPrice"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    df = raw.copy()
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], errors="coerce")
    for column in ("Quantity", "UnitPrice"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    invoice = df["InvoiceNo"].astype("string").str.strip()
    code = df["StockCode"].astype("string").str.upper().str.strip()
    valid = (
        df["InvoiceDate"].notna() & invoice.notna()
        & ~invoice.str.upper().str.startswith("C", na=True)
        & code.str.fullmatch(r"\d{5}[A-Z]{0,2}", na=False)
        & df["Quantity"].gt(0) & df["UnitPrice"].gt(0)
        & df["InvoiceDate"].ge(TRAIN_START) & df["InvoiceDate"].lt(TEST_END)
    )
    clean = df.loc[valid, ["InvoiceDate", "Quantity", "UnitPrice"]].copy()
    clean["StockCode"] = code.loc[valid].astype(str)
    clean["Date"] = clean["InvoiceDate"].dt.normalize()
    clean["SalesValue"] = clean["Quantity"] * clean["UnitPrice"]
    audit = {"raw_rows": int(len(raw)), "retained_rows": int(len(clean)),
             "excluded_rows": int(len(raw) - len(clean)),
             "unique_skus": int(clean.StockCode.nunique()),
             "train_start": str(TRAIN_START.date()), "test_start": str(TEST_START.date()),
             "test_end_exclusive": str(TEST_END.date())}
    if clean.empty:
        raise ValueError("No valid transaction rows after filtering")
    return clean, audit


def selected_skus(clean: pd.DataFrame, count: int = 20) -> tuple[pd.DataFrame, list[str]]:
    train = clean[clean.Date < TEST_START]
    sales = train.groupby("StockCode", as_index=False).agg(
        units=("Quantity", "sum"), sales_value=("SalesValue", "sum"))
    sales = sales.sort_values(["sales_value", "StockCode"], ascending=[False, True])
    sales["revenue_share"] = sales.sales_value / sales.sales_value.sum()
    sales["cumulative_share"] = sales.revenue_share.cumsum()
    sales["ABC"] = np.select([sales.cumulative_share <= .80, sales.cumulative_share <= .95],
                             ["A", "B"], default="C")
    return sales, sales.head(count).StockCode.tolist()


def daily_panel(clean: pd.DataFrame, skus: list[str]) -> pd.DataFrame:
    grouped = clean[clean.StockCode.isin(skus)].groupby(["Date", "StockCode"])["Quantity"].sum()
    dates = pd.date_range(TRAIN_START, TEST_END - pd.Timedelta(days=1), freq="D")
    index = pd.MultiIndex.from_product([dates, skus], names=["Date", "StockCode"])
    return grouped.reindex(index, fill_value=0).rename("units").reset_index()


def forecast_value(history: np.ndarray, method: str) -> float:
    """One-step forecast from history only. Croston SBA uses nonzero intervals."""
    x = np.asarray(history, dtype=float)
    if len(x) == 0:
        return 0.0
    if method == "forecast_7d":
        return float(x[-7:].mean()) if len(x) >= 7 else float(x.mean())
    if method == "forecast_28d":
        return float(x[-28:].mean()) if len(x) >= 28 else float(x.mean())
    if method == "seasonal_naive_7d":
        return float(x[-7]) if len(x) >= 7 else float(x.mean())
    if method == "weekday_mean_4w":
        return float(np.mean([x[-lag] for lag in (7, 14, 21, 28)])) if len(x) >= 28 else float(x.mean())
    if method == "croston_sba":
        nz = np.flatnonzero(x > 0)
        if len(nz) == 0:
            return 0.0
        alpha = 0.1
        sizes = x[nz]
        intervals = np.diff(np.r_[-1, nz]).astype(float)
        z, p = float(sizes[0]), float(intervals[0])
        for size, interval in zip(sizes[1:], intervals[1:]):
            z = alpha * size + (1 - alpha) * z
            p = alpha * interval + (1 - alpha) * p
        return max(0.0, (1 - alpha / 2) * z / p)
    raise ValueError(f"Unknown forecast method: {method}")


FORECAST_METHODS = ("forecast_7d", "forecast_28d", "seasonal_naive_7d", "weekday_mean_4w", "croston_sba")


def forecast_evaluation(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = panel.sort_values(["StockCode", "Date"]).copy()
    rows = []
    for sku, group in df.groupby("StockCode", sort=False):
        dates = group.Date.to_numpy()
        values = group.units.to_numpy(dtype=float)
        for index, date in enumerate(dates):
            if pd.Timestamp(date) < TEST_START:
                continue
            history = values[:index]
            row = {"Date": pd.Timestamp(date), "StockCode": sku, "units": values[index]}
            for method in FORECAST_METHODS:
                row[method] = forecast_value(history, method)
            rows.append(row)
    forecasts = pd.DataFrame(rows)
    metrics = []
    for method in FORECAST_METHODS:
        error = (forecasts.units - forecasts[method]).abs()
        metrics.append({"method": method, "test_sku_days": len(forecasts),
                        "actual_units": int(forecasts.units.sum()),
                        "mae_units_per_sku_day": float(error.mean()),
                        "wape": float(error.sum() / forecasts.units.sum())})
    return forecasts, pd.DataFrame(metrics)


def rolling_origin_backtest(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    records = []
    for sku, group in panel.sort_values(["StockCode", "Date"]).groupby("StockCode", sort=False):
        series = group.set_index("Date").units
        for origin in BACKTEST_ORIGINS:
            end = origin + pd.Timedelta(days=BACKTEST_HORIZON)
            history = series.loc[series.index < origin].to_numpy(dtype=float)
            actual = series.loc[(series.index >= origin) & (series.index < end)].to_numpy(dtype=float)
            if len(actual) != BACKTEST_HORIZON:
                continue
            extended = list(history)
            for step, value in enumerate(actual):
                for method in FORECAST_METHODS:
                    records.append({"sku": sku, "origin": origin.date().isoformat(),
                                    "date": (origin + pd.Timedelta(days=step)).date().isoformat(),
                                    "horizon_day": step + 1, "method": method,
                                    "actual_units": value,
                                    "forecast_units": forecast_value(np.asarray(extended), method)})
                extended.append(value)  # rolling one-day-ahead, never multi-step leakage
    detail = pd.DataFrame(records)
    if detail.empty:
        raise ValueError("No complete rolling-origin validation windows were generated")
    summary_rows = []
    for method, frame in detail.groupby("method"):
        error = (frame.actual_units-frame.forecast_units).abs()
        summary_rows.append({"method": method, "origins": frame.origin.nunique(),
                             "sku_days": len(frame), "actual_units": frame.actual_units.sum(),
                             "mae_units_per_sku_day": error.mean(),
                             "wape": error.sum()/frame.actual_units.sum()})
    summary = pd.DataFrame(summary_rows)
    by_sku_rows = []
    for (sku, method), frame in detail.groupby(["sku", "method"]):
        actual = frame.actual_units.sum()
        by_sku_rows.append({"sku": sku, "method": method,
                            "rolling_wape": (frame.actual_units-frame.forecast_units).abs().sum()/actual
                            if actual else np.nan})
    by_sku = pd.DataFrame(by_sku_rows)
    selected = (by_sku.sort_values(["sku", "rolling_wape", "method"])
                .drop_duplicates("sku").rename(columns={"method": "selected_method"}))
    return detail, summary, selected


def apply_selected_methods(forecasts: pd.DataFrame, selected: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    joined = forecasts.merge(selected[["sku", "selected_method"]], left_on="StockCode", right_on="sku")
    joined["selected_forecast"] = [row[method] for _, row in joined.iterrows()
                                   for method in [row.selected_method]]
    err = (joined.units - joined.selected_forecast).abs()
    summary = pd.DataFrame([{"method": "per_sku_selected_from_rolling_backtest",
                             "test_sku_days": len(joined), "actual_units": int(joined.units.sum()),
                             "mae_units_per_sku_day": float(err.mean()),
                             "wape": float(err.sum()/joined.units.sum())}])
    return joined, summary


def classify_demand(panel: pd.DataFrame) -> pd.DataFrame:
    train = panel[panel.Date < TEST_START]
    rows = []
    for sku, group in train.groupby("StockCode"):
        x = group.units.to_numpy(dtype=float)
        nonzero = x[x > 0]
        adi = len(x) / len(nonzero) if len(nonzero) else np.inf
        cv2 = (float(np.square(nonzero.std(ddof=1) / nonzero.mean()))
               if len(nonzero) > 1 and nonzero.mean() else 0.0)
        if adi <= 1.32 and cv2 <= .49:
            profile = "smooth"
        elif adi > 1.32 and cv2 <= .49:
            profile = "intermittent"
        elif adi <= 1.32:
            profile = "erratic"
        else:
            profile = "lumpy"
        rows.append({"sku": sku, "training_days": len(x), "nonzero_days": len(nonzero),
                     "adi": adi, "cv_squared": cv2, "demand_profile": profile})
    return pd.DataFrame(rows)


def simulate(demand: np.ndarray, rop: int, quantity: int, lead_days: int,
             initial_on_hand: int | None = None, warmup_days: int = 0) -> dict:
    """Daily lost-sales simulation, receipt at start of due day and review at day end."""
    demand = np.asarray(demand, dtype=float)
    if demand.ndim != 1 or not np.isfinite(demand).all() or (demand < 0).any():
        raise ValueError("Demand must be a finite nonnegative one-dimensional series")
    if not np.equal(demand, np.floor(demand)).all():
        raise ValueError("Demand must be measured in whole units")
    if quantity < 1 or lead_days < 1 or rop < 0 or not 0 <= warmup_days < len(demand):
        raise ValueError("Require positive order quantity/lead time, nonnegative ROP, and measured days")
    on_hand = rop + quantity if initial_on_hand is None else initial_on_hand
    if on_hand < 0:
        raise ValueError("Initial inventory must be nonnegative")
    pipeline: dict[int, int] = {}
    supplied = total = stockout_days = on_hand_sum = orders = 0
    for day, raw in enumerate(demand):
        on_hand += pipeline.pop(day, 0)
        requested = int(raw)
        fulfilled = min(on_hand, requested)
        on_hand -= fulfilled
        measured = day >= warmup_days
        if measured:
            total += requested
            supplied += fulfilled
            stockout_days += int(fulfilled < requested)
            on_hand_sum += on_hand
        position = on_hand + sum(pipeline.values())
        while position <= rop:
            pipeline[day + lead_days] = pipeline.get(day + lead_days, 0) + quantity
            position += quantity
            orders += int(measured)
    return {"requested_units": total, "filled_units": supplied, "unfilled_units": total-supplied,
            "days_with_shortage": stockout_days, "simulated_fill_rate": supplied/total if total else 1.0,
            "average_ending_on_hand": on_hand_sum/(len(demand)-warmup_days), "orders": orders}


def eoq_quantity(mean_daily: float, purchase_cost: float) -> tuple[int, float]:
    annual_demand = max(mean_daily, 0.0) * 365
    holding_cost_per_unit_year = max(purchase_cost * ANNUAL_HOLDING_RATE, .01)
    q = max(1, int(round(np.sqrt(2 * annual_demand * ORDER_COST_GBP / holding_cost_per_unit_year))))
    return q, holding_cost_per_unit_year


def empirical_lead_time_demand(history: np.ndarray, lead_days: int) -> np.ndarray:
    x = np.asarray(history, dtype=float)
    if lead_days < 1 or len(x) < lead_days:
        raise ValueError("History must contain at least one complete lead-time window")
    # All overlapping historical windows preserve short-range dependence better than iid resampling.
    return np.convolve(x, np.ones(lead_days), mode="valid")


def policy_cost(result: dict, daily_holding_cost: float, shortage_cost: float) -> dict:
    measured_days = max(1, result.get("measured_days", 1))
    holding = result["average_ending_on_hand"] * measured_days * daily_holding_cost
    ordering = result["orders"] * ORDER_COST_GBP
    shortage = result["unfilled_units"] * shortage_cost
    return {"holding_cost_gbp": holding, "ordering_cost_gbp": ordering,
            "shortage_cost_gbp": shortage, "total_relevant_cost_gbp": holding+ordering+shortage}


def simulate_with_costs(demand: np.ndarray, rop: int, quantity: int, lead_days: int,
                        initial_on_hand: int, warmup_days: int = 0,
                        daily_holding_cost: float = 0.0, shortage_cost: float = 0.0) -> dict:
    result = simulate(demand, rop, quantity, lead_days, initial_on_hand, warmup_days)
    result["measured_days"] = len(demand)-warmup_days
    result.update(policy_cost(result, daily_holding_cost, shortage_cost))
    result.pop("measured_days")
    return result


def optimize_policies(panel: pd.DataFrame, clean: pd.DataFrame, skus: list[str], lead_days: int = LEAD_DAYS):
    rows, selected = [], []
    prices = clean[clean.Date < pd.Timestamp("2011-07-01")].groupby("StockCode").UnitPrice.median()
    warm_start, valid_start, valid_end = pd.Timestamp("2011-07-01"), pd.Timestamp("2011-08-01"), pd.Timestamp("2011-09-01")
    final_warmup = int((TEST_START - WARMUP_START).days)
    for sku in skus:
        ts = panel[panel.StockCode == sku].set_index("Date").units
        history = ts.loc[ts.index < warm_start].to_numpy(dtype=float)
        if len(history) < lead_days or sku not in prices:
            continue
        purchase = float(prices[sku]) * PURCHASE_TO_SELLING_PRICE
        q, hold_unit_year = eoq_quantity(float(history.mean()), purchase)
        daily_hold = hold_unit_year / 365
        shortage_cost = max(purchase * SHORTAGE_COST_MULTIPLE, .01)
        ltd = empirical_lead_time_demand(history, lead_days)
        candidates = sorted(set(int(np.ceil(np.quantile(ltd, qtl))) for qtl in POLICY_CANDIDATE_QUANTILES))
        validation_demand = ts.loc[(ts.index >= warm_start) & (ts.index < valid_end)].to_numpy(dtype=float)
        warm_days = int((valid_start - warm_start).days)
        common_initial = max(candidates, default=0) + q
        for rop in candidates:
            result = simulate_with_costs(validation_demand, rop, q, lead_days, common_initial,
                                         warm_days, daily_hold, shortage_cost)
            rows.append({"sku": sku, "lead_days": lead_days, "candidate_rop": rop,
                         "validation_start": str(valid_start.date()), "validation_end_exclusive": str(valid_end.date()),
                         "validation_quantile": next((qtl for qtl in POLICY_CANDIDATE_QUANTILES
                             if int(np.ceil(np.quantile(ltd, qtl))) == rop), np.nan),
                         "order_quantity_eoq": q, **result})
        sku_rows = [r for r in rows if r["sku"] == sku]
        best = min(sku_rows, key=lambda r: (r["total_relevant_cost_gbp"], r["candidate_rop"]))
        selected.append({"sku": sku, "policy": "optimized_empirical_rop", "lead_days_assumed": lead_days,
                         "reorder_point_units": best["candidate_rop"], "order_quantity_eoq_units": q,
                         "common_initial_on_hand": common_initial,
                         "estimated_purchase_price_gbp": purchase,
                         "annual_holding_cost_per_unit_gbp": hold_unit_year,
                         "shortage_cost_per_unfilled_unit_gbp": shortage_cost,
                         "validation_total_cost_gbp": best["total_relevant_cost_gbp"]})
    candidates_df = pd.DataFrame(rows)
    policies_df = pd.DataFrame(selected)
    # Evaluate fixed selected policies on test with September as warm-up, common start inventory.
    final_rows = []
    for row in selected:
        sku = row["sku"]
        demand = panel[(panel.StockCode == sku) & (panel.Date >= WARMUP_START) & (panel.Date < TEST_END)].units.to_numpy(dtype=float)
        result = simulate_with_costs(demand, int(row["reorder_point_units"]), int(row["order_quantity_eoq_units"]),
                                     lead_days, int(row["common_initial_on_hand"]), final_warmup,
                                     float(row["annual_holding_cost_per_unit_gbp"])/365,
                                     float(row["shortage_cost_per_unfilled_unit_gbp"]))
        final_rows.append({**row, **result})
    return candidates_df, pd.DataFrame(final_rows)


def plan_policies(panel: pd.DataFrame, clean: pd.DataFrame, skus: list[str], lead_days: int = LEAD_DAYS) -> pd.DataFrame:
    prices = clean[clean.Date < WARMUP_START].groupby("StockCode").UnitPrice.median()
    out = []
    warmup_days = int((TEST_START-WARMUP_START).days)
    for sku in skus:
        ts = panel[panel.StockCode == sku].set_index("Date").units
        train = ts[ts.index < WARMUP_START]
        evaluation = ts[(ts.index >= WARMUP_START) & (ts.index < TEST_END)]
        if sku not in prices:
            continue
        mean, std = float(train.mean()), float(train.std(ddof=1))
        purchase = float(prices[sku])*PURCHASE_TO_SELLING_PRICE
        q, _ = eoq_quantity(mean, purchase)
        baseline_rop = max(0, int(np.ceil(mean*lead_days)))
        safety = int(np.ceil(SERVICE_Z*std*np.sqrt(lead_days)))
        common_initial = baseline_rop+q
        for label, rop in (("no_safety_stock", baseline_rop), ("95pct_normal_buffer", baseline_rop+safety)):
            out.append({"sku": sku, "policy": label, "train_daily_mean": mean,
                        "train_daily_std": std, "lead_days_assumed": lead_days,
                        "common_initial_on_hand": common_initial, "warmup_days": warmup_days,
                        "safety_stock_units": 0 if label == "no_safety_stock" else safety,
                        "reorder_point_units": rop, "order_quantity_eoq_units": q,
                        "estimated_purchase_price_gbp": purchase,
                        **simulate(evaluation.to_numpy(), rop, q, lead_days, common_initial, warmup_days)})
    return pd.DataFrame(out)


def run(input_path: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = pd.read_excel(input_path, engine="openpyxl")
    clean, audit = clean_transactions(raw)
    abc, skus = selected_skus(clean)
    audit.update({"training_period_skus": int(len(abc)), "selected_skus": len(skus)})
    panel = daily_panel(clean, skus)
    forecasts, accuracy = forecast_evaluation(panel)
    backtest, backtest_summary, selected_methods = rolling_origin_backtest(panel)
    selected_holdout, selected_accuracy = apply_selected_methods(forecasts, selected_methods)
    profiles = classify_demand(panel)
    scenarios = pd.concat([plan_policies(panel, clean, skus, lead) for lead in LEAD_TIME_SCENARIOS], ignore_index=True)
    policies = scenarios[scenarios.lead_days_assumed == LEAD_DAYS].copy()
    validation_candidates, optimized = optimize_policies(panel, clean, skus)
    # Persistent outputs are deterministic tables; generated charts/workbook refreshed by report.py.
    outputs = {
        "abc_training.csv": (abc, False), "forecast_accuracy.csv": (accuracy, False),
        "policy_scenarios.csv": (policies, False), "lead_time_scenarios.csv": (scenarios, False),
        "holdout_forecasts.csv": (forecasts, False), "rolling_backtest.csv": (backtest, False),
        "rolling_backtest_summary.csv": (backtest_summary, False), "selected_methods.csv": (selected_methods, False),
        "selected_holdout_forecasts.csv": (selected_holdout, False), "selected_holdout_accuracy.csv": (selected_accuracy, False),
        "demand_profiles.csv": (profiles, False), "policy_optimization_validation.csv": (validation_candidates, False),
        "optimized_policies.csv": (optimized, False),
    }
    for filename, (frame, _) in outputs.items():
        frame.to_csv(output_dir/filename, index=False)
    (output_dir/"audit.json").write_text(json.dumps(audit, indent=2)+"\n")
    summary = policies.groupby("policy").agg(requested_units=("requested_units","sum"), filled_units=("filled_units","sum"),
        unfilled_units=("unfilled_units","sum"), avg_on_hand_sum=("average_ending_on_hand","sum"), orders=("orders","sum"))
    summary["simulated_fill_rate"] = summary.filled_units/summary.requested_units
    summary.to_csv(output_dir/"policy_summary.csv")
    sensitivity = scenarios.groupby(["lead_days_assumed","policy"]).agg(requested_units=("requested_units","sum"),
        filled_units=("filled_units","sum"), unfilled_units=("unfilled_units","sum"), avg_on_hand_sum=("average_ending_on_hand","sum"))
    sensitivity["simulated_fill_rate"] = sensitivity.filled_units/sensitivity.requested_units
    sensitivity.to_csv(output_dir/"lead_time_summary.csv")
    return {"audit":audit,"accuracy":accuracy,"policies":policies,"summary":summary,"abc":abc,
            "forecasts":forecasts,"sensitivity":sensitivity,"backtest":backtest,
            "backtest_summary":backtest_summary,"selected_methods":selected_methods,
            "selected_holdout":selected_holdout,"selected_accuracy":selected_accuracy,"profiles":profiles,
            "validation_candidates":validation_candidates,"optimized_policy":optimized}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/Online Retail.xlsx"))
    parser.add_argument("--output", type=Path, default=Path("results"))
    args = parser.parse_args()
    run(args.input, args.output)
