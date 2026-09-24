"""Reproducible retail demand and illustrative inventory policy analysis.

Run: python analysis.py --input 'data/Online Retail.xlsx'
No actual inventory, supplier cost, or lost-sales data is present in UCI Online Retail.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


TRAIN_START = pd.Timestamp("2011-01-01")
TEST_START = pd.Timestamp("2011-10-01")
TEST_END = pd.Timestamp("2011-12-01")  # exclusive; excludes partial December
LEAD_DAYS = 7  # hypothetical fixed lead time
LEAD_TIME_SCENARIOS = (3, 7, 14)
WARMUP_START = pd.Timestamp("2011-09-01")
ORDER_COST_GBP = 20.0  # hypothetical cost per purchase order
ANNUAL_HOLDING_RATE = 0.25  # hypothetical share of estimated unit purchase cost
PURCHASE_TO_SELLING_PRICE = 0.60  # hypothetical proxy, not observed purchase price
SERVICE_Z = 1.645  # one-sided 95% normal quantile; assumption, not guaranteed fill rate


def clean_transactions(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    required = {"InvoiceNo", "StockCode", "InvoiceDate", "Quantity", "UnitPrice"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    df = raw.copy()
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], errors="coerce")
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")
    df["UnitPrice"] = pd.to_numeric(df["UnitPrice"], errors="coerce")
    invoice = df["InvoiceNo"].astype("string").str.strip()
    code = df["StockCode"].astype("string").str.upper().str.strip()
    # Retain merchandise-like numeric stock codes; exclude postage, fees, and other codes.
    valid = (
        df["InvoiceDate"].notna()
        & invoice.notna()
        & ~invoice.str.upper().str.startswith("C", na=True)
        & code.str.fullmatch(r"\d{5}[A-Z]{0,2}", na=False)
        & df["Quantity"].gt(0)
        & df["UnitPrice"].gt(0)
        & df["InvoiceDate"].ge(TRAIN_START)
        & df["InvoiceDate"].lt(TEST_END)
    )
    clean = df.loc[valid, ["InvoiceDate", "Quantity", "UnitPrice"]].copy()
    clean["StockCode"] = code.loc[valid].astype(str)
    clean["Date"] = clean["InvoiceDate"].dt.normalize()
    clean["SalesValue"] = clean["Quantity"] * clean["UnitPrice"]
    audit = {"raw_rows": int(len(raw)), "retained_rows": int(len(clean)),
             "excluded_rows": int(len(raw) - len(clean)),
             "unique_skus": int(clean.StockCode.nunique()),
             "train_start": str(TRAIN_START.date()),
             "test_start": str(TEST_START.date()),
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
    # Classification uses observed selling revenue, not inventory value or profit.
    sales["ABC"] = np.select(
        [sales.cumulative_share <= .80, sales.cumulative_share <= .95],
        ["A", "B"], default="C")
    return sales, sales.head(count).StockCode.tolist()


def daily_panel(clean: pd.DataFrame, skus: list[str]) -> pd.DataFrame:
    grouped = clean[clean.StockCode.isin(skus)].groupby(
        ["Date", "StockCode"])["Quantity"].sum()
    all_dates = pd.date_range(TRAIN_START, TEST_END - pd.Timedelta(days=1), freq="D")
    index = pd.MultiIndex.from_product([all_dates, skus], names=["Date", "StockCode"])
    return grouped.reindex(index, fill_value=0).rename("units").reset_index()


def forecast_evaluation(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    # Shift before rolling prevents current-day outcomes from entering predictions.
    df = panel.sort_values(["StockCode", "Date"]).copy()
    for window in (7, 28):
        df[f"forecast_{window}d"] = df.groupby("StockCode")["units"].transform(
            lambda x: x.shift(1).rolling(window, min_periods=window).mean())
    df["seasonal_naive_7d"] = df.groupby("StockCode")["units"].shift(7)
    df["weekday_mean_4w"] = df.groupby("StockCode")["units"].transform(
        lambda x: sum(x.shift(lag) for lag in (7, 14, 21, 28)) / 4)
    test = df[(df.Date >= TEST_START) & (df.Date < TEST_END)].copy()
    rows = []
    for method in ("forecast_7d", "forecast_28d", "seasonal_naive_7d", "weekday_mean_4w"):
        # WAPE across SKU-days; ratio of sums, not mean of per-SKU percentages.
        t = test.dropna(subset=[method])
        rows.append({"method": method, "test_sku_days": len(t),
                     "actual_units": int(t.units.sum()),
                     "mae_units_per_sku_day": float((t.units - t[method]).abs().mean()),
                     "wape": float((t.units - t[method]).abs().sum() / t.units.sum())})
    return test, pd.DataFrame(rows)


def simulate(demand: np.ndarray, rop: int, quantity: int, lead_days: int,
             initial_on_hand: int | None = None, warmup_days: int = 0) -> dict:
    """Daily lost-sales simulation; receipts arrive at start of promised day.

    Supply an identical initial_on_hand to compare policies fairly. State evolves
    during warm-up, but only post-warm-up days contribute to reported metrics.
    """
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
    supplied = total = stockouts = on_hand_sum = orders = 0
    for day, raw in enumerate(demand):
        on_hand += pipeline.pop(day, 0)
        requested = int(raw)
        fulfilled = min(on_hand, requested)
        on_hand -= fulfilled
        measured = day >= warmup_days
        if measured:
            total += requested
            supplied += fulfilled
            stockouts += int(fulfilled < requested)
        position = on_hand + sum(pipeline.values())
        while position <= rop:
            pipeline[day + lead_days] = pipeline.get(day + lead_days, 0) + quantity
            position += quantity
            orders += int(measured)
        if measured:
            on_hand_sum += on_hand
    return {"requested_units": total, "filled_units": supplied,
            "unfilled_units": total - supplied, "days_with_shortage": stockouts,
            "simulated_fill_rate": supplied / total if total else 1.0,
            "average_ending_on_hand": on_hand_sum / (len(demand) - warmup_days),
            "orders": orders}


def plan_policies(panel: pd.DataFrame, clean: pd.DataFrame, skus: list[str],
                  lead_days: int = LEAD_DAYS) -> pd.DataFrame:
    prices = clean[clean.Date < WARMUP_START].groupby("StockCode").UnitPrice.median()
    out = []
    for sku in skus:
        ts = panel[panel.StockCode == sku].set_index("Date").units
        train = ts[ts.index < WARMUP_START]
        evaluation = ts[(ts.index >= WARMUP_START) & (ts.index < TEST_END)]
        warmup_days = int((TEST_START - WARMUP_START).days)
        if sku not in prices:
            raise ValueError(f"SKU {sku} has no price history before the warm-up period")
        mean, std = float(train.mean()), float(train.std(ddof=1))
        estimated_purchase = float(prices[sku]) * PURCHASE_TO_SELLING_PRICE
        annual_holding = max(estimated_purchase * ANNUAL_HOLDING_RATE, .01)
        annual_demand = mean * 365
        eoq = max(1, int(round(np.sqrt(2 * annual_demand * ORDER_COST_GBP / annual_holding))))
        base_rop = max(0, int(np.ceil(mean * lead_days)))
        # sqrt(L) assumes independent daily demand; stress test this assumption.
        safety = int(np.ceil(SERVICE_Z * std * np.sqrt(lead_days)))
        for label, rop in (("no_safety_stock", base_rop),
                           ("95pct_normal_buffer", base_rop + safety)):
            out.append({"sku": sku, "policy": label, "train_daily_mean": mean,
                        "train_daily_std": std, "lead_days_assumed": lead_days,
                        "common_initial_on_hand": base_rop + eoq,
                        "warmup_days": warmup_days,
                        "safety_stock_units": 0 if label == "no_safety_stock" else safety,
                        "reorder_point_units": rop, "order_quantity_eoq_units": eoq,
                        "estimated_purchase_price_gbp": estimated_purchase,
                        **simulate(evaluation.to_numpy(), rop, eoq, lead_days,
                                   initial_on_hand=base_rop + eoq, warmup_days=warmup_days)})
    return pd.DataFrame(out)


def run(input_path: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = pd.read_excel(input_path, engine="openpyxl")
    clean, audit = clean_transactions(raw)
    abc, skus = selected_skus(clean)
    audit["training_period_skus"] = int(len(abc))
    audit["selected_skus"] = len(skus)
    panel = daily_panel(clean, skus)
    forecasts, accuracy = forecast_evaluation(panel)
    scenarios = pd.concat([plan_policies(panel, clean, skus, lead_days=lead)
                           for lead in LEAD_TIME_SCENARIOS], ignore_index=True)
    policies = scenarios[scenarios.lead_days_assumed == LEAD_DAYS].copy()
    abc.to_csv(output_dir / "abc_training.csv", index=False)
    accuracy.to_csv(output_dir / "forecast_accuracy.csv", index=False)
    policies.to_csv(output_dir / "policy_scenarios.csv", index=False)
    scenarios.to_csv(output_dir / "lead_time_scenarios.csv", index=False)
    forecasts.to_csv(output_dir / "holdout_forecasts.csv", index=False)
    import json
    (output_dir / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    summary = policies.groupby("policy").agg(
        requested_units=("requested_units", "sum"),
        filled_units=("filled_units", "sum"),
        unfilled_units=("unfilled_units", "sum"),
        avg_on_hand_sum=("average_ending_on_hand", "sum"),
        orders=("orders", "sum"))
    summary["simulated_fill_rate"] = summary.filled_units / summary.requested_units
    summary.to_csv(output_dir / "policy_summary.csv")
    sensitivity = scenarios.groupby(["lead_days_assumed", "policy"]).agg(
        requested_units=("requested_units", "sum"), filled_units=("filled_units", "sum"),
        unfilled_units=("unfilled_units", "sum"),
        avg_on_hand_sum=("average_ending_on_hand", "sum"))
    sensitivity["simulated_fill_rate"] = sensitivity.filled_units / sensitivity.requested_units
    sensitivity.to_csv(output_dir / "lead_time_summary.csv")
    print("Audit:", audit)
    print("\nForecast comparison (test period):\n", accuracy.to_string(index=False))
    print("\nPolicy comparison (illustrative, test period):\n", summary.to_string())
    return {"audit": audit, "accuracy": accuracy, "policies": policies,
            "summary": summary, "abc": abc, "forecasts": forecasts,
            "sensitivity": sensitivity}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/Online Retail.xlsx"))
    parser.add_argument("--output", type=Path, default=Path("results"))
    args = parser.parse_args()
    run(args.input, args.output)
