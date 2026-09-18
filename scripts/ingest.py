import warnings; warnings.filterwarnings("ignore")
from pathlib import Path
import pandas as pd
from odds.data.footballdata import load_all

df = load_all(verbose=True)
out = Path("research/data/matches.parquet")
df.to_parquet(out, index=False)
print(f"\n=== {len(df):,} matchs  ->  {out}  ({out.stat().st_size/1e6:.1f} Mo)")
print(f"periode : {df['date'].min().date()}  ->  {df['date'].max().date()}")
print(f"sources : {df['odds_source'].value_counts(dropna=False).to_dict()}")
