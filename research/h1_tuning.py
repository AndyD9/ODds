"""Réglage de xi (demi-vie) et du shrinkage, sur VALIDATION uniquement.

Le jeu de test n'est pas touché. Tout réglage d'hyperparamètre fait sur le
test rendrait le résultat final ininterprétable (prereg 0001 §3).
"""
import warnings; warnings.filterwarnings("ignore")
import time
import numpy as np, pandas as pd

from odds.pit.walk_forward import walk_forward
from odds.market.devig import devig_matrix
from odds.backtest.metrics import brier, log_loss

VALID_DEB, VALID_FIN = pd.Timestamp("2022-01-01"), pd.Timestamp("2024-01-01")

df = pd.read_parquet("research/data/matches.parquet")
df = df[df.odds_source == "pinnacle_closing"].copy()

def evalue(res):
    p = res[["dc_h", "dc_d", "dc_a"]].to_numpy()
    y = np.column_stack([(res.result == r).to_numpy() for r in ("H", "D", "A")]).astype(float)
    m = devig_matrix(res[["psc_h", "psc_d", "psc_a"]].to_numpy(float), "shin")
    return brier(p, y), log_loss(p, y), brier(m, y), log_loss(m, y), len(res)

lignes = []
grille = [(hl, rg) for hl in (120, 240, 365, 540, 730, 1095)
                   for rg in (0.1, 0.3, 1.0, 3.0, 10.0)]
print(f"{len(grille)} configurations\n")
print(f"{'demi-vie':>9s} {'ridge':>6s} {'n':>7s} {'Brier DC':>10s} {'Brier marche':>13s} {'ecart':>9s} {'LL DC':>9s} {'temps':>7s}")
for hl, rg in grille:
    t = time.time()
    res = walk_forward(df, demi_vie_jours=hl, ridge=rg, refit_jours=30,
                       predire_depuis=VALID_DEB, predire_jusqua=VALID_FIN)
    bd, ld, bm, lm, n = evalue(res)
    lignes.append(dict(demi_vie=hl, ridge=rg, n=n, brier_dc=bd, brier_marche=bm,
                       ecart=bd - bm, ll_dc=ld, ll_marche=lm))
    print(f"{hl:9d} {rg:6.1f} {n:7,d} {bd:10.6f} {bm:13.6f} {bd-bm:+9.6f} {ld:9.6f} {time.time()-t:6.1f}s", flush=True)

r = pd.DataFrame(lignes).sort_values("brier_dc")
r.to_csv("research/h1_tuning_validation.csv", index=False)
print("\n=== MEILLEURES CONFIGURATIONS (validation) ===")
print(r.head(8).to_string(index=False, float_format=lambda v: f"{v:.6f}"))
best = r.iloc[0]
print(f"\nretenu : demi-vie {best.demi_vie:.0f} j, ridge {best.ridge}")
print(f"Brier DC {best.brier_dc:.6f}  vs  marche {best.brier_marche:.6f}  ->  ecart {best.ecart:+.6f}")
print("ecart > 0 = le marche reste meilleur")
