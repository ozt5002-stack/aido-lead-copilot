# data/ - fictional data only

**Everything in `leads.csv` is invented.** The businesses, names, numbers, scores and pains do not describe any real business. Names are random combinations of generic words. Any resemblance to a real business is a coincidence.

- `leads.csv`: 300 fictional AIDO leads, written by `python scripts/generate_leads.py` (fixed seed, so every run writes the same file). Do not edit it by hand. Change the script and rerun it; `python scripts/generate_leads.py --check` tells you whether the file is up to date.
- Every row has `fictional=true`. Rows that consultants log through the chat are stored in the database, not here, with `fictional=false`.
- About a fifth of the leads have no diagnosis yet (empty score and stages, an early pipeline status). This is normal for a new lead. It is not the *needs a look* state, which only rows logged through the chat can get.
- Stages are computed by `app/stage.py` (the lesson 8 model): total 20-33 כבאי, 34-46 בנאי, 47-60 פקח; domain average 1.0-1.6 כבאי, 1.7-2.3 בנאי, 2.4-3.0 פקח.

The bakery files (`bakery_sales.csv`, `suppliers.csv`) were removed with the bakery tools in plan task 3; they are in the Git history.
