"""H1 — TEST FINAL. Le jeu de test est touché UNE SEULE FOIS.

Configuration GELEE sur validation, aucune modification autorisee ici :
    demi-vie 365 j, ridge 1.0, refit 30 j, devig Shin
Poids de melange GELES sur validation : w1 = 1.1258, w2 = -0.0826
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

from odds.pit.walk_forward import walk_forward
from odds.market.devig import devig_matrix
from odds.backtest.metrics import brier, log_loss, brier_par_match, log_loss_par_match, bootstrap_blocs

DEMI_VIE, RIDGE, REFIT = 365, 1.0, 30
W1, W2 = 1.1258, -0.0826
TEST_DEB = pd.Timestamp("2024-01-01")

df = pd.read_parquet("research/data/matches.parquet")
df = df[df.odds_source == "pinnacle_closing"].copy()

res = walk_forward(df, demi_vie_jours=DEMI_VIE, ridge=RIDGE, refit_jours=REFIT,
                   predire_depuis=TEST_DEB)
P = res[["dc_h", "dc_d", "dc_a"]].to_numpy()
M = devig_matrix(res[["psc_h", "psc_d", "psc_a"]].to_numpy(float), "shin")
Y = np.column_stack([(res.result == r).to_numpy() for r in ("H", "D", "A")]).astype(float)
B = np.tile(Y.mean(0), (len(Y), 1))
blocs = (res.league_code + "|" + res.season.astype(str)).to_numpy()

print("=" * 72)
print("H1 — RESULTAT SUR LE JEU DE TEST (touche une fois)")
print("=" * 72)
print(f"n = {len(res):,} matchs   {res.date.min().date()} -> {res.date.max().date()}")
print(f"config gelee : demi-vie {DEMI_VIE} j, ridge {RIDGE}, refit {REFIT} j, devig Shin\n")

z = W1 * np.log(np.clip(M, 1e-12, 1)) + W2 * np.log(np.clip(P, 1e-12, 1))
z -= z.max(axis=1, keepdims=True)
Pb = np.exp(z); Pb /= Pb.sum(axis=1, keepdims=True)

print(f"{'':28s} {'Brier':>10s} {'log loss':>10s}")
for nom, p in (("marche (Pinnacle+Shin)", M), ("Dixon-Coles", P),
               ("melange (poids geles)", Pb), ("taux de base", B)):
    print(f"  {nom:26s} {brier(p,Y):10.6f} {log_loss(p,Y):10.6f}")

print(f"\n--- Test pre-enregistre H1 : Brier(DC) - Brier(marche) < 0 ? ---")
d, lo, hi = bootstrap_blocs(brier_par_match(P, Y), brier_par_match(M, Y), blocs, n_iter=2000)
print(f"  Brier    DC - marche = {d:+.6f}   IC95 [{lo:+.6f}, {hi:+.6f}]")
d2, lo2, hi2 = bootstrap_blocs(log_loss_par_match(P, Y), log_loss_par_match(M, Y), blocs, n_iter=2000)
print(f"  log loss DC - marche = {d2:+.6f}   IC95 [{lo2:+.6f}, {hi2:+.6f}]")
print(f"\n  >>> H1 {'ACCEPTEE' if hi < 0 else 'REJETEE'} : "
      f"{'le modele bat le marche' if hi < 0 else 'le marche reste strictement meilleur'}")

print(f"\n--- Melange, poids geles sur validation (hors echantillon) ---")
d3, lo3, hi3 = bootstrap_blocs(brier_par_match(Pb, Y), brier_par_match(M, Y), blocs, n_iter=2000)
v = "apport reel" if hi3 < 0 else ("degrade" if lo3 > 0 else "non concluant")
print(f"  Brier melange - marche = {d3:+.6f}   IC95 [{lo3:+.6f}, {hi3:+.6f}]  -> {v}")

print(f"\n--- H2 : l'ecart est-il plus favorable sur les petits championnats ? ---")
res = res.assign(b_dc=brier_par_match(P, Y), b_m=brier_par_match(M, Y))
res["marge"] = 100 * ((1/res.psc_h + 1/res.psc_d + 1/res.psc_a) - 1)
g = (res.groupby(["league_code", "country"])
       .agg(n=("date","size"), marge=("marge","mean"), b_dc=("b_dc","mean"), b_m=("b_m","mean"))
       .reset_index())
g["ecart"] = g.b_dc - g.b_m
g = g[g.n >= 500].sort_values("ecart")
print(g.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
print(f"\n  championnats ou DC bat le marche : {(g.ecart < 0).sum()} / {len(g)}")
c = np.corrcoef(g.marge, g.ecart)[0,1]
print(f"  correlation (marge du book, ecart DC-marche) = {c:+.3f}")
print("  une correlation POSITIVE signifie : plus la marge est elevee,")
print("  PLUS le modele est distance -> H2 contredite, pas seulement rejetee")
