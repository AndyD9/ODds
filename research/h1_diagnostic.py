"""Diagnostics sur VALIDATION. Exploratoire — le test reste intact.

Deux questions qui peuvent changer la lecture du résultat H1 :
  1. L'écart au marché est-il uniforme, ou existe-t-il des championnats où
     le modèle tient ? (préfigure H2)
  2. Le modèle apporte-t-il de l'information ORTHOGONALE au marché ?
     Un modèle moins bon seul peut rester utile en combinaison.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from scipy.optimize import minimize

from odds.pit.walk_forward import walk_forward
from odds.market.devig import devig_matrix
from odds.backtest.metrics import brier, log_loss, brier_par_match, bootstrap_blocs

df = pd.read_parquet("research/data/matches.parquet")
df = df[df.odds_source == "pinnacle_closing"].copy()

res = walk_forward(df, demi_vie_jours=365, ridge=1.0, refit_jours=30,
                   predire_depuis=pd.Timestamp("2022-01-01"),
                   predire_jusqua=pd.Timestamp("2024-01-01"))
P = res[["dc_h", "dc_d", "dc_a"]].to_numpy()
M = devig_matrix(res[["psc_h", "psc_d", "psc_a"]].to_numpy(float), "shin")
Y = np.column_stack([(res.result == r).to_numpy() for r in ("H", "D", "A")]).astype(float)

print(f"n = {len(res):,} (validation)   Brier DC {brier(P,Y):.6f}   marche {brier(M,Y):.6f}\n")

print("=== 1) ECART PAR CHAMPIONNAT (Brier DC - Brier marche ; negatif = DC gagne) ===")
res = res.assign(b_dc=brier_par_match(P, Y), b_m=brier_par_match(M, Y))
g = (res.groupby(["league_code", "country"])
       .agg(n=("date", "size"), b_dc=("b_dc", "mean"), b_m=("b_m", "mean")).reset_index())
g["ecart"] = g.b_dc - g.b_m
g = g[g.n >= 500].sort_values("ecart")
print(g.to_string(index=False, float_format=lambda v: f"{v:.5f}"))
print(f"\nchampionnats ou DC bat le marche : {(g.ecart < 0).sum()} / {len(g)}")

print("\n=== 2) LE MODELE APPORTE-T-IL DE L'INFORMATION ORTHOGONALE ? ===")
print("Melange log-lineaire : p ∝ marche^w1 * dc^w2, poids ajustes sur validation.\n")
lm, ld = np.log(np.clip(M, 1e-12, 1)), np.log(np.clip(P, 1e-12, 1))

def perte(w):
    z = w[0] * lm + w[1] * ld
    z -= z.max(axis=1, keepdims=True)
    p = np.exp(z); p /= p.sum(axis=1, keepdims=True)
    return log_loss(p, Y)

opt = minimize(perte, [1.0, 0.0], method="Nelder-Mead",
               options={"xatol": 1e-6, "fatol": 1e-10, "maxiter": 2000})
w1, w2 = opt.x
z = w1 * lm + w2 * ld; z -= z.max(axis=1, keepdims=True)
Pb = np.exp(z); Pb /= Pb.sum(axis=1, keepdims=True)

print(f"  poids marche w1 = {w1:.4f}")
print(f"  poids DC     w2 = {w2:.4f}   <- si ~0, le modele n'apporte rien")
print(f"  Brier    marche seul {brier(M,Y):.6f}   melange {brier(Pb,Y):.6f}   gain {brier(M,Y)-brier(Pb,Y):+.6f}")
print(f"  log loss marche seul {log_loss(M,Y):.6f}   melange {log_loss(Pb,Y):.6f}   gain {log_loss(M,Y)-log_loss(Pb,Y):+.6f}")

blocs = (res.league_code + "|" + res.season.astype(str)).to_numpy()
d, lo, hi = bootstrap_blocs(brier_par_match(Pb, Y), brier_par_match(M, Y), blocs, n_iter=1000)
verdict = "MELANGE MEILLEUR" if hi < 0 else ("melange moins bon" if lo > 0 else "non concluant")
print(f"\n  Brier melange - marche = {d:+.7f}  IC95 [{lo:+.7f}, {hi:+.7f}]  {verdict}")
print("  NB : poids ajustes sur ces memes donnees -> gain optimiste, a confirmer hors echantillon.")
