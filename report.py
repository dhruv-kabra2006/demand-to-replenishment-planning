"""Build compact portfolio charts from the saved analysis outputs."""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

root = Path(__file__).resolve().parent / "results"
accuracy = pd.read_csv(root / "forecast_accuracy.csv")
scenarios = pd.read_csv(root / "policy_summary.csv")

fig, ax = plt.subplots(figsize=(8.5, 4.2))
names = ["7-day mean", "28-day mean", "Same day last week", "4-week weekday mean"]
vals = accuracy.wape * 100
bars = ax.bar(names, vals, color=["#9aaabe", "#245c7c", "#98b0a4", "#ab9aaf"], width=.55)
ax.bar_label(bars, fmt="%.1f%%", padding=4)
ax.set_ylabel("Holdout WAPE (%)")
ax.set_ylim(0, max(vals) * 1.18)
ax.set_title("Forecast accuracy | 20 highest training-revenue SKUs")
ax.text(.5, -.22, "Oct–Nov 2011 holdout; lower is better", ha="center",
        transform=ax.transAxes, fontsize=9)
fig.tight_layout()
fig.savefig(root / "forecast_comparison.png", dpi=160, bbox_inches="tight")
plt.close(fig)

sensitivity = pd.read_csv(root / "lead_time_summary.csv")
fig, axes = plt.subplots(1, 2, figsize=(9, 3.8))
for label, name, color in [("no_safety_stock", "No buffer", "#9aaabe"),
                           ("95pct_normal_buffer", "Normal-theory buffer", "#245c7c")]:
    rows = sensitivity[sensitivity.policy == label]
    axes[0].plot(rows.lead_days_assumed, rows.simulated_fill_rate * 100, marker="o", label=name, color=color)
    axes[1].plot(rows.lead_days_assumed, rows.avg_on_hand_sum, marker="o", label=name, color=color)
for ax in axes:
    ax.set_xlabel("Assumed supplier lead time (days)")
    ax.set_xticks([3, 7, 14])
axes[0].set_ylabel("Simulated unit fill rate (%)")
axes[1].set_ylabel("Sum of average on-hand units")
axes[0].legend(fontsize=8)
fig.suptitle("Lead-time sensitivity | common starting stock and 30-day warm-up")
fig.tight_layout()
fig.savefig(root / "lead_time_sensitivity.png", dpi=160, bbox_inches="tight")
plt.close(fig)

scenarios = scenarios.set_index("policy").loc[["no_safety_stock", "95pct_normal_buffer"]]
fig, axes = plt.subplots(1, 2, figsize=(9, 3.7))
labels = ["No buffer", "Normal-theory buffer"]
colors = ["#9aaabe", "#245c7c"]
b1 = axes[0].bar(labels, scenarios.simulated_fill_rate * 100, color=colors, width=.6)
axes[0].bar_label(b1, fmt="%.1f%%", padding=3)
axes[0].set_ylim(0, 110)
axes[0].set_title("Simulated unit fill rate")
axes[0].set_ylabel("Share of requested units (%)")
b2 = axes[1].bar(labels, scenarios.avg_on_hand_sum, color=colors, width=.6)
axes[1].bar_label(b2, fmt="%.0f", padding=3)
axes[1].set_ylim(0, scenarios.avg_on_hand_sum.max() * 1.2)
axes[1].set_title("Average ending inventory")
axes[1].set_ylabel("Units summed over 20 SKUs")
fig.suptitle("Illustrative reorder policy scenarios (assumed 7-day lead time)")
fig.tight_layout()
fig.savefig(root / "policy_tradeoff.png", dpi=160, bbox_inches="tight")
plt.close(fig)
