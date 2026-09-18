"""Table de fiabilité des marchés de buts — l'équivalent de
``analysis.fiabilite_historique``, mais par marché.

Pourquoi elle existe. Le moteur de mise (prereg 0001 §4) pondère par la
taille de l'échantillon historique derrière la tranche de probabilité du
pari, et « un signal absent vaut 1 ». Sans cette table, un pari sur « telle
équipe marque 2 buts » ne transmettait aucun ``n`` et sortait donc avec une
confiance PLUS élevée qu'un 1X2 sur le même match — le moteur aurait misé
davantage là où l'on sait moins. Le défaut se voyait à l'écran : 0,50 contre
0,16 sur Bayern – Union Berlin.

On mesure donc, marché par marché et tranche par tranche, à quelle fréquence
l'événement s'est réellement produit. Deux variantes, parce qu'elles ne
valent pas la même chose (RESULTS R9) :

  contraint = False   probabilité dérivée du 1X2 seul, sur tout l'historique
  contraint = True    matrice calée en plus sur la cote over/under 2,5

Sortie : ``research/data/fiabilite_buts.parquet``, lu par l'application.

    uv run python research/fiabilite_buts.py
"""
import warnings; warnings.filterwarnings("ignore")
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from odds.market.devig import devig_matrix
from odds.models.football.buts import MARCHES, matrice_implicite, probabilite

SORTIE = Path("research/data/fiabilite_buts.parquet")

# Bornes : plus fines au centre, où se trouvent la plupart des marchés de
# buts, et assez larges aux extrêmes pour garder un n exploitable.
BORNES = [0.0, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60,
          0.70, 0.80, 0.90, 0.95, 1.01]

N_MIN_TRANCHE = 200


def table(p: np.ndarray, y: np.ndarray) -> pd.DataFrame:
    t = (pd.DataFrame({"p": p, "ok": y, "bin": pd.cut(p, BORNES)})
           .groupby("bin", observed=True)
           .agg(n=("p", "size"), p_moyenne=("p", "mean"), reussite=("ok", "mean"))
           .reset_index())
    t["ic95"] = 1.96 * np.sqrt(t.reussite * (1 - t.reussite) / t.n)
    t["borne_inf"] = t.bin.apply(lambda b: b.left).astype(float)
    t["borne_sup"] = t.bin.apply(lambda b: b.right).astype(float)
    t["bin"] = t.bin.astype(str)
    return t[t.n >= N_MIN_TRANCHE]


def main() -> int:
    df = pd.read_parquet("research/data/matches.parquet")
    clo = df[df.odds_source == "pinnacle_closing"].reset_index(drop=True)
    p1x2 = devig_matrix(clo[["psc_h", "psc_d", "psc_a"]].to_numpy(float), "shin")

    a_ou = clo[["psc_o25", "psc_u25"]].notna().all(axis=1).to_numpy()
    p_ou = np.full(len(clo), np.nan)
    p_ou[a_ou] = devig_matrix(
        clo.loc[a_ou, ["psc_o25", "psc_u25"]].to_numpy(float), "shin")[:, 0]
    print(f"{len(clo):,} matchs · {a_ou.sum():,} avec cote de totaux", flush=True)

    codes = [c for c in MARCHES if c not in ("1", "N", "2")]
    probas = {False: {c: np.full(len(clo), np.nan) for c in codes},
              True: {c: np.full(len(clo), np.nan) for c in codes}}

    t0 = time.time()
    for i in range(len(clo)):
        m = matrice_implicite(*p1x2[i]).matrice
        for c in codes:
            probas[False][c][i] = probabilite(m, c)
        if a_ou[i]:
            try:
                m2 = matrice_implicite(*p1x2[i], p_over=float(p_ou[i])).matrice
            except ValueError:
                continue
            for c in codes:
                probas[True][c][i] = probabilite(m2, c)
        if i and i % 25000 == 0:
            print(f"  {i:,}/{len(clo):,}  ({time.time() - t0:.0f} s)", flush=True)

    bd, be = clo.home_goals.to_numpy(), clo.away_goals.to_numpy()
    lignes = []
    for contraint in (False, True):
        for c in codes:
            p = probas[contraint][c]
            ok = np.isfinite(p)
            if ok.sum() < 1000:
                continue
            y = MARCHES[c].predicat(bd, be).astype(float)
            t = table(p[ok], y[ok])
            lignes.append(t.assign(code=c, contraint=contraint))

    out = pd.concat(lignes, ignore_index=True)
    out.to_parquet(SORTIE, index=False)
    print(f"\n{len(out)} tranches -> {SORTIE}")
    print(out.groupby("contraint").agg(
        marches=("code", "nunique"), tranches=("code", "size"),
        n_total=("n", "sum")).to_string())

    print("\nexemple — « le domicile marque 2 buts ou plus », dérivé du 1X2 seul :")
    ex = out[(out.code == "dom_over_1.5") & ~out.contraint]
    print(ex[["bin", "n", "p_moyenne", "reussite", "ic95"]].to_string(
        index=False, float_format=lambda v: f"{v:.4f}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
