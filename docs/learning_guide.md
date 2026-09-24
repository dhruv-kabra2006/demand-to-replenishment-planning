# Work through the project in 2–3 days

This repository contains a working starting point. Run it, inspect it, and make one change yourself before using it in an interview.

## Day 1: Understand and verify the data (3–4 hours)

1. Open `Inventory_Project.ipynb` locally or in Google Colab. Download the source spreadsheet using `python download_data.py`, or from the linked UCI page.
2. Run the cleaning section. Inspect a cancelled invoice, a non-merchandise code, a positive sales transaction, and a day with no recorded sales.
3. Explain why missing customer IDs do not prevent SKU-level sales aggregation, and why zero recorded sales does not prove zero demand.
4. Inspect the first 20 rows of `results/abc_training.csv`. Write two sentences explaining why selling revenue differs from inventory value and profit.
5. Choose one SKU and plot its daily sales. Find one unusual spike. Do not remove it just to improve a metric; document whether it might represent a bulk order or data issue.

**Checkpoint:** You can explain what a row means, every cleaning rule, the date split, and how SKUs were chosen.

## Day 2: Forecasts and inventory trade-offs (4–5 hours)

1. Compare the four forecast methods. Calculate one forecast by hand from the preceding observations.
2. Explain `shift(1)` and why using the current day's sales would leak the answer into a prediction.
3. Calculate MAE and WAPE for five SKU-days using a calculator or Excel and compare with the code.
4. For one SKU, calculate the baseline reorder point and buffered reorder point. Write down which inputs are observed and which are assumed.
5. Read `simulate()` slowly. Follow a five-day example with paper inventory balances: opening stock, receipts, requested units, fulfilled units, closing stock, and open orders.
6. Compare 3-, 7-, and 14-day lead times in `results/lead_time_summary.csv`. Explain the cost/service implication without claiming real retailer savings.

**Checkpoint:** You can distinguish forecast accuracy, cycle service level, and unit fill rate. The 1.645 input does not guarantee 95% unit fill rate.

## Day 3: Own one improvement and practice the story (2–3 hours)

1. Pick one substantive extension: report weekly aggregate accuracy, investigate a bulk-order SKU, or evaluate more service buffers. Keep the holdout period untouched while choosing a method; use a separate earlier validation period for tuning.
2. Run the five logic tests and regenerate outputs. Explain any changed result.
3. Write a 150-word project summary in your own words: business question, source, method, finding, and one limitation.
4. Use the README resume bullets only when you can defend them. Keep the project separate from employment experience.

## A 45-second interview explanation

“I used public retail transactions to build a SKU-level inventory planning analysis in Python. I cleaned the sales records, segmented SKUs by revenue, and evaluated four demand forecasts on a later period. Forecast error remained high, which showed the limits of simple methods for this data. I then compared reorder policies with equal starting inventory and tested different lead times. A safety-stock buffer improved simulated unit fill rate but required more inventory. Since the dataset has no stock records or supplier inputs, I clearly separated recorded sales from assumptions and simulated outcomes.”

## Resources

- [Dataset and attribution](https://archive.ics.uci.edu/dataset/352/online+retail)
- [Pandas getting started](https://pandas.pydata.org/docs/getting_started/index.html)
- [Google Colab](https://colab.research.google.com/)
- [Forecasting: Principles and Practice](https://otexts.com/fpp3/) for forecast evaluation and benchmarks
- The detailed calculation assumptions are in the repository README and `analysis.py`.
