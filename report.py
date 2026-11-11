"""Regenerate project figures from the CSV outputs produced by analysis.py."""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent / "results"
plt.rcParams.update({"figure.facecolor": "white", "axes.spines.top": False,
                     "axes.spines.right": False, "font.size": 9})


def save(fig, name):
    fig.tight_layout()
    fig.savefig(ROOT / name, dpi=180, bbox_inches="tight")
    plt.close(fig)


accuracy = pd.read_csv(ROOT / "forecast_accuracy.csv")
fig, ax = plt.subplots(figsize=(8.5, 4.2))
labels = {"forecast_7d":"7-day mean", "forecast_28d":"28-day mean",
          "seasonal_naive_7d":"Same weekday, 1 week", "weekday_mean_4w":"Four-week weekday mean",
          "croston_sba":"Croston SBA"}
vals = accuracy.wape*100
bars = ax.bar([labels.get(x,x) for x in accuracy.method], vals, color="#245c7c")
ax.bar_label(bars, fmt="%.1f%%", padding=3)
ax.set_ylabel("Holdout WAPE (%)"); ax.set_title("One-day-ahead holdout forecast accuracy")
ax.tick_params(axis="x", labelrotation=18)
ax.text(.5,-.27,"20 highest Jan–Sep training-revenue SKUs · Oct–Nov 2011",ha="center",transform=ax.transAxes)
save(fig,"forecast_comparison.png")

backtest = pd.read_csv(ROOT / "rolling_backtest_summary.csv").sort_values("wape")
fig, ax = plt.subplots(figsize=(8.5,4.2))
bars=ax.bar([labels.get(x,x) for x in backtest.method],backtest.wape*100,color="#497b67")
ax.bar_label(bars,fmt="%.1f%%",padding=3); ax.set_ylabel("Pooled rolling-origin WAPE (%)")
ax.set_title("Four 28-day rolling-origin validation windows"); ax.tick_params(axis="x",labelrotation=18)
save(fig,"rolling_backtest_comparison.png")

profiles=pd.read_csv(ROOT/"demand_profiles.csv")
counts=profiles.demand_profile.value_counts().reindex(["smooth","intermittent","erratic","lumpy"],fill_value=0)
fig,ax=plt.subplots(figsize=(6.5,4)); bars=ax.bar(counts.index,counts.values,color=["#497b67","#d3a54a","#6587a0","#9a718f"])
ax.bar_label(bars); ax.set_ylabel("Selected SKUs"); ax.set_title("Training-period demand profile")
save(fig,"demand_profile_mix.png")

summary=pd.read_csv(ROOT/"policy_summary.csv").set_index("policy").loc[["no_safety_stock","95pct_normal_buffer"]]
fig,axes=plt.subplots(1,2,figsize=(9,3.7)); names=["No buffer","Normal-theory buffer"]
for ax,col,title,fmt in [(axes[0],"simulated_fill_rate","Simulated unit fill rate","%.1f%%"),(axes[1],"avg_on_hand_sum","Average ending inventory summed across SKUs","%.0f")]:
    values=summary[col].to_numpy()*(100 if col=="simulated_fill_rate" else 1)
    bars=ax.bar(names,values,color=["#9aaabe","#245c7c"]); ax.bar_label(bars,fmt=fmt,padding=3); ax.set_title(title)
    ax.tick_params(axis="x",labelrotation=10)
axes[0].set_ylabel("Share of observed demand filled (%)")
fig.suptitle("Illustrative reorder-point scenarios · assumed 7-day lead time")
save(fig,"policy_tradeoff.png")

sensitivity=pd.read_csv(ROOT/"lead_time_summary.csv")
fig,axes=plt.subplots(1,2,figsize=(9,3.8))
for policy,name,color in [("no_safety_stock","No buffer","#9aaabe"),("95pct_normal_buffer","Normal-theory buffer","#245c7c")]:
    rows=sensitivity[sensitivity.policy==policy]
    axes[0].plot(rows.lead_days_assumed,rows.simulated_fill_rate*100,marker="o",label=name,color=color)
    axes[1].plot(rows.lead_days_assumed,rows.avg_on_hand_sum,marker="o",label=name,color=color)
for ax in axes: ax.set_xlabel("Assumed supplier lead time (days)"); ax.set_xticks([3,7,14]); ax.legend(fontsize=8)
axes[0].set_ylabel("Simulated unit fill rate (%)"); axes[1].set_ylabel("Average on-hand units summed across SKUs")
fig.suptitle("Lead-time sensitivity · common initial stock and September warm-up")
save(fig,"lead_time_sensitivity.png")

optimized=pd.read_csv(ROOT/"optimized_policies.csv")
base=summary.copy()
fig,axes=plt.subplots(1,2,figsize=(9,3.8))
comp=pd.DataFrame({"policy":["No buffer","Normal buffer","Optimized ROP"],
                   "fill_rate":[base.loc["no_safety_stock","simulated_fill_rate"],base.loc["95pct_normal_buffer","simulated_fill_rate"],optimized.filled_units.sum()/optimized.requested_units.sum()],
                   "on_hand":[base.loc["no_safety_stock","avg_on_hand_sum"],base.loc["95pct_normal_buffer","avg_on_hand_sum"],optimized.average_ending_on_hand.sum()]})
for ax,col,title,scale,fmt in [(axes[0],"fill_rate","Simulated unit fill rate",100,"%.1f%%"),(axes[1],"on_hand","Average ending inventory summed across SKUs",1,"%.0f")]:
    values=comp[col]*scale; bars=ax.bar(comp.policy,values,color=["#9aaabe","#245c7c","#497b67"])
    ax.bar_label(bars,fmt=fmt,padding=3); ax.set_title(title); ax.tick_params(axis="x",labelrotation=12)
axes[0].set_ylabel("Share of observed demand filled (%)")
fig.suptitle("Fixed policies evaluated on Oct–Nov holdout")
save(fig,"optimized_policy_tradeoff.png")
print(f"Regenerated six charts in {ROOT}")

# Refresh the workbook from the same CSVs so it cannot silently lag behind the analysis.
workbook_tables = {
    "Forecast accuracy":"forecast_accuracy.csv",
    "Rolling backtest":"rolling_backtest_summary.csv",
    "Selected methods":"selected_methods.csv",
    "Holdout selection":"selected_holdout_accuracy.csv",
    "Demand profiles":"demand_profiles.csv",
    "Policy summary":"policy_summary.csv",
    "Lead time":"lead_time_summary.csv",
    "ROP validation":"policy_optimization_validation.csv",
    "Optimized policies":"optimized_policies.csv",
    "ABC training":"abc_training.csv",
}
with pd.ExcelWriter(ROOT / "inventory_recommendations.xlsx", engine="openpyxl") as writer:
    for sheet, filename in workbook_tables.items():
        pd.read_csv(ROOT / filename).to_excel(writer, sheet_name=sheet, index=False)
print("Refreshed inventory_recommendations.xlsx")
