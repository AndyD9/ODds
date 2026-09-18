"""Prereg 0002 — etapes 2 et 3.

Etape 2 : MESURE de l'ecart de calibration cote precoce vs cloture, par
          championnat. Aucune hypothese, aucun modele.
Etape 3 : TEST de H5 sur la VALIDATION uniquement. Configuration DC gelee.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

from odds.pit.walk_forward import walk_forward
from odds.market.devig import devig_matrix
from odds.backtest.metrics import brier, log_loss, brier_par_match, log_loss_par_match, bootstrap_blocs

VALID_DEB, VALID_FIN = pd.Timestamp("2022-01-01"), pd.Timestamp("2024-01-01")

df = pd.read_parquet("research/data/matches.parquet")
df = df[(df.odds_source == "pinnacle_closing")
        & df[["ps_h", "ps_d", "ps_a"]].notna().all(axis=1)].copy()

def probas(d, pref):
    return devig_matrix(d[[f"{pref}_h", f"{pref}_d", f"{pref}_a"]].to_numpy(float), "shin")

def cible(d):
    return np.column_stack([(d.result == r).to_numpy() for r in ("H", "D", "A")]).astype(float)

# ---------------------------------------------------------------- etape 2
print("=" * 74)
print("ETAPE 2 — MESURE : de combien la ligne s'ameliore-t-elle entre")
print("          la cote precoce et la cloture ? (train + validation)")
print("=" * 74)
tv = df[df.date < VALID_FIN]
Yt, Pre, Clo = cible(tv), probas(tv, "ps"), probas(tv, "psc")
print(f"n = {len(tv):,}   marge precoce {100*((1/tv[['ps_h','ps_d','ps_a']].to_numpy(float)).sum(1).mean()-1):.2f} %"
      f"   marge cloture {100*((1/tv[['psc_h','psc_d','psc_a']].to_numpy(float)).sum(1).mean()-1):.2f} %")
print(f"\n  Brier    cote precoce {brier(Pre,Yt):.6f}   cloture {brier(Clo,Yt):.6f}   ecart {brier(Pre,Yt)-brier(Clo,Yt):+.6f}")
print(f"  log loss cote precoce {log_loss(Pre,Yt):.6f}   cloture {log_loss(Clo,Yt):.6f}   ecart {log_loss(Pre,Yt)-log_loss(Clo,Yt):+.6f}")

blocs_t = (tv.league_code + "|" + tv.season.astype(str)).to_numpy()
d, lo, hi = bootstrap_blocs(brier_par_match(Pre, Yt), brier_par_match(Clo, Yt), blocs_t, n_iter=2000)
print(f"\n  H6 (controle) Brier precoce - cloture = {d:+.6f}  IC95 [{lo:+.6f}, {hi:+.6f}]")
print(f"  >>> H6 {'CONFIRMEE' if lo > 0 else 'REJETEE'} : la cloture est "
      f"{'bien' if lo > 0 else 'PAS'} meilleure que la cote precoce")

t = tv.assign(b_pre=brier_par_match(Pre, Yt), b_clo=brier_par_match(Clo, Yt))
g = (t.groupby(["league_code", "country"])
       .agg(n=("date","size"), b_pre=("b_pre","mean"), b_clo=("b_clo","mean")).reset_index())
g["info_tardive"] = g.b_pre - g.b_clo
print("\n=== CARTE DE L'INFORMATION TARDIVE (Brier precoce - Brier cloture) ===")
print("    eleve = beaucoup d'information arrive tard ; faible = prix precoce deja efficient\n")
print(g.sort_values("info_tardive", ascending=False)
       .to_string(index=False, float_format=lambda v: f"{v:.5f}"))

# ---------------------------------------------------------------- etape 3
print("\n" + "=" * 74)
print("ETAPE 3 — TEST DE H5 : Dixon-Coles bat-il la cote precoce ?")
print("          VALIDATION uniquement. Config DC gelee (365 j, ridge 1.0, refit 30 j).")
print("=" * 74)
res = walk_forward(df, demi_vie_jours=365, ridge=1.0, refit_jours=30,
                   predire_depuis=VALID_DEB, predire_jusqua=VALID_FIN)
Y, DC = cible(res), res[["dc_h","dc_d","dc_a"]].to_numpy()
PRE, CLO = probas(res, "ps"), probas(res, "psc")
blocs = (res.league_code + "|" + res.season.astype(str)).to_numpy()

print(f"\nn = {len(res):,} (validation)\n")
print(f"{'':26s} {'Brier':>10s} {'log loss':>10s}")
for nom, p in (("cloture", CLO), ("cote precoce", PRE), ("Dixon-Coles", DC)):
    print(f"  {nom:24s} {brier(p,Y):10.6f} {log_loss(p,Y):10.6f}")

d5, lo5, hi5 = bootstrap_blocs(brier_par_match(DC, Y), brier_par_match(PRE, Y), blocs, n_iter=2000)
l5, llo5, lhi5 = bootstrap_blocs(log_loss_par_match(DC, Y), log_loss_par_match(PRE, Y), blocs, n_iter=2000)
print(f"\n  Brier    DC - precoce = {d5:+.6f}   IC95 [{lo5:+.6f}, {hi5:+.6f}]")
print(f"  log loss DC - precoce = {l5:+.6f}   IC95 [{llo5:+.6f}, {lhi5:+.6f}]")
print(f"\n  >>> H5 {'ACCEPTEE' if hi5 < 0 else 'REJETEE'} : "
      f"{'DC bat la cote precoce' if hi5 < 0 else 'la cote precoce reste meilleure que DC'}")
