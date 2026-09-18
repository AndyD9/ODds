"""H3 — quelle méthode de dévig calibre le mieux le marché ? (prereg 0001 §6)

Exécuté sur TRAIN + VALIDATION uniquement. Le jeu de test reste intact.
Établit au passage la valeur du benchmark que le modèle devra battre.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

from odds.market.devig import devig_matrix, METHODS
from odds.backtest.split import assign_split
from odds.backtest.metrics import brier, log_loss, brier_par_match, log_loss_par_match, bootstrap_blocs

df = pd.read_parquet("research/data/matches.parquet")
df = df[df.odds_source == "pinnacle_closing"].copy()
df["split"] = assign_split(df)
tv = df[df.split != "test"].reset_index(drop=True)

odds = tv[["psc_h", "psc_d", "psc_a"]].to_numpy(float)
y = np.column_stack([(tv.result == r).to_numpy() for r in ("H", "D", "A")]).astype(float)
blocs = (tv.league_code + "|" + tv.season.astype(str)).to_numpy()

print(f"n = {len(tv):,} matchs  ({tv.date.min().date()} -> {tv.date.max().date()})")
print(f"marge Pinnacle moyenne : {100*((1/odds).sum(1).mean()-1):.2f} %")
print(f"issues : H {y[:,0].mean():.1%}  D {y[:,1].mean():.1%}  A {y[:,2].mean():.1%}\n")

probs, res = {}, []
for m in sorted(METHODS):
    p = devig_matrix(odds, m)
    probs[m] = p
    res.append({"methode": m, "brier": brier(p, y), "log_loss": log_loss(p, y)})

base = np.tile(y.mean(0), (len(y), 1))
res.append({"methode": "(base rate)", "brier": brier(base, y), "log_loss": log_loss(base, y)})
res.append({"methode": "(uniforme)", "brier": brier(np.full_like(y, 1/3), y),
            "log_loss": log_loss(np.full_like(y, 1/3), y)})

r = pd.DataFrame(res).sort_values("brier")
print("=== CALIBRATION DU MARCHE SELON LA METHODE DE DEVIG ===")
print(r.to_string(index=False, float_format=lambda v: f"{v:.6f}"))

print("\n=== H3 : Shin vs proportionnelle (bootstrap par blocs championnat-saison) ===")
for metrique, fn in (("Brier", brier_par_match), ("log loss", log_loss_par_match)):
    for autre in ("proportional", "power", "odds_ratio"):
        if autre == "shin":
            continue
        d, lo, hi = bootstrap_blocs(fn(probs["shin"], y), fn(probs[autre], y), blocs, n_iter=1000)
        signe = "SHIN MEILLEUR" if hi < 0 else ("shin moins bon" if lo > 0 else "non concluant")
        print(f"  {metrique:9s}  shin - {autre:13s} = {d:+.7f}  IC95 [{lo:+.7f}, {hi:+.7f}]  {signe}")

print("\n=== OU LES METHODES DIVERGENT : erreur moyenne par plage de proba (proportionnelle) ===")
pp, ps = probs["proportional"], probs["shin"]
bins = [0, .05, .10, .20, .35, .50, .70, 1.01]
flat_p, flat_s = pp.ravel(), ps.ravel()
lab = pd.cut(flat_p, bins)
t = pd.DataFrame({"prop": flat_p, "shin": flat_s, "bin": lab}).groupby("bin", observed=True).agg(
    n=("prop", "size"), prop_moy=("prop", "mean"), shin_moy=("shin", "mean"))
t["ecart_pts"] = 100 * (t.prop_moy - t.shin_moy)
t["ecart_rel_%"] = 100 * (t.prop_moy - t.shin_moy) / t.prop_moy
print(t.to_string(float_format=lambda v: f"{v:.3f}"))
