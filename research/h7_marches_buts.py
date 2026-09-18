"""H7 — que valent les probabilités de marchés de buts, et d'où doivent-elles venir ?

Trois sources possibles pour « 3 buts ou plus » ou « cette équipe en met 2 » :

  marché      la cote over/under 2,5 de clôture, dévigée. N'existe que pour
              le total du match, sur les grands championnats, depuis 2019-20.
  implicite   matrice de score ajustée pour reproduire le 1X2 dévigé.
              Disponible partout, mais dérivée d'une hypothèse.
  DC          Dixon-Coles point-in-time (odds.pit.walk_forward), réajusté
              en glissant, sans aucune information postérieure au match.

Ce que le script établit, et qui décide de ce que l'interface a le droit
d'afficher :

  1. de combien la dérivation s'écarte du vrai prix, là où le vrai prix
     existe — c'est le coût de la dérivation ;
  2. si DC apporte quelque chose sur le total du match, où le marché est
     liquide (R8 dit que non sur le 1X2 ; ce n'est pas transposable) ;
  3. ce que valent les deux sources sur les totaux PAR ÉQUIPE, où aucun
     prix de marché ne peut les départager.

Stratification obligatoire. Trois régimes coexistent dans l'historique et
les agréger produirait un chiffre qui ne décrit rien :

  - 2012 → 2019 : 1X2 Pinnacle, aucun over/under en amont ;
  - 2019-20 → 2026-01 : 43 207 matchs avec les deux ;
  - après 2026-01-14 : Pinnacle a disparu du flux (RESULTS R1).

Et transversalement, les 16 championnats « extra » (40 % de l'historique)
n'ont JAMAIS d'over/under : c'est le terrain de H2, et il est invérifiable
par un prix.

    uv run python research/h7_marches_buts.py
"""
import warnings; warnings.filterwarnings("ignore")
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from odds.backtest.metrics import bootstrap_blocs
from odds.data.footballdata import LEAGUES_MAIN
from odds.market.devig import devig_matrix
from odds.models.football.buts import MARCHES, probabilite, matrice_implicite
from odds.models.football.dixon_coles import score_matrix

DONNEES = Path("research/data")
CACHE_IMPLICITE = DONNEES / "h7_implicite.parquet"
CACHE_DC = DONNEES / "h7_dc.parquet"

# Marchés évalués. `total_over_2.5` est le seul que le marché cote : c'est
# le seul point où les trois sources peuvent être confrontées.
MARCHES_TESTES = ["total_over_1.5", "total_over_2.5", "total_over_3.5",
                  "dom_over_0.5", "dom_over_1.5", "ext_over_0.5",
                  "ext_over_1.5", "btts_oui"]


def _brier(p, y):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def _par_match(p, y):
    return (np.asarray(p, float) - np.asarray(y, float)) ** 2


def _ece(p, y, n_bins=12):
    p, y = np.asarray(p, float), np.asarray(y, float)
    bornes = np.unique(np.quantile(p, np.linspace(0, 1, n_bins + 1)))
    idx = np.clip(np.digitize(p, bornes[1:-1]), 0, len(bornes) - 2)
    tot, poids = 0.0, 0.0
    for b in range(len(bornes) - 1):
        m = idx == b
        if m.sum() < 30:
            continue
        tot += m.sum() * abs(y[m].mean() - p[m].mean())
        poids += m.sum()
    return tot / poids if poids else np.nan


# ===========================================================================
# 1. Matrices implicites au marché
# ===========================================================================

def calculer_implicite(df: pd.DataFrame) -> pd.DataFrame:
    """lambda, mu pour chaque match, ajustés sur les prix de marché.

    Deux variantes : le 1X2 seul (partout), et 1X2 + over/under (là où la
    cote de totaux existe, ce qui libère rho).
    """
    p = devig_matrix(df[["psc_h", "psc_d", "psc_a"]].to_numpy(float), "shin")

    a_ou = df[["psc_o25", "psc_u25"]].notna().all(axis=1).to_numpy()
    p_ou = np.full(len(df), np.nan)
    if a_ou.any():
        p_ou[a_ou] = devig_matrix(
            df.loc[a_ou, ["psc_o25", "psc_u25"]].to_numpy(float), "shin")[:, 0]

    lignes = []
    t0 = time.time()
    for i in range(len(df)):
        seul = matrice_implicite(*p[i])
        ligne = {"lam": seul.lam, "mu": seul.mu, "rho": seul.rho,
                 "ecart_max": seul.ecart_max, "fiable": seul.fiable,
                 "p_marche_over25": p_ou[i],
                 "lam_ou": np.nan, "mu_ou": np.nan, "rho_ou": np.nan,
                 "ecart_max_ou": np.nan, "fiable_ou": False}
        if a_ou[i]:
            try:
                deux = matrice_implicite(*p[i], p_over=float(p_ou[i]))
                ligne.update(lam_ou=deux.lam, mu_ou=deux.mu, rho_ou=deux.rho,
                             ecart_max_ou=deux.ecart_max, fiable_ou=deux.fiable)
            except ValueError:
                pass
        lignes.append(ligne)
        if i and i % 20000 == 0:
            print(f"    {i:,}/{len(df):,}  ({time.time() - t0:.0f} s)", flush=True)
    out = pd.DataFrame(lignes, index=df.index)
    return pd.concat([df[["date", "league_code", "season", "home_goals",
                          "away_goals"]], out], axis=1)


def _probas_depuis_lambdas(lam, mu, rho, codes) -> dict:
    """Probabilités des marchés testés, une matrice de score par match."""
    sortie = {c: np.full(len(lam), np.nan) for c in codes}
    for i, (l, m, r) in enumerate(zip(lam, mu, rho)):
        if not np.isfinite(l) or not np.isfinite(m):
            continue
        M = score_matrix(float(l), float(m), float(r))
        for c in codes:
            sortie[c][i] = probabilite(M, c)
    return sortie


# ===========================================================================
# 2. Dixon-Coles point-in-time
# ===========================================================================

def calculer_dc(df: pd.DataFrame) -> pd.DataFrame:
    from odds.pit.walk_forward import walk_forward
    t0 = time.time()
    out = walk_forward(df, demi_vie_jours=365.0, refit_jours=30, verbose=True)
    print(f"  walk-forward : {len(out):,} prédictions en {time.time() - t0:.0f} s")
    return out[["date", "league_code", "season", "home_team", "away_team",
                "home_goals", "away_goals", "dc_lam", "dc_mu", "rho",
                "equipe_inconnue"]]


# ===========================================================================
# main
# ===========================================================================

def main() -> int:
    df = pd.read_parquet(DONNEES / "matches.parquet")
    df["date"] = pd.to_datetime(df.date)
    clo = df[df.odds_source == "pinnacle_closing"].reset_index(drop=True)
    print(f"historique : {len(df):,} matchs · {len(clo):,} à clôture Pinnacle")
    print(f"dont avec over/under 2,5 de clôture : "
          f"{clo[['psc_o25', 'psc_u25']].notna().all(axis=1).sum():,}\n")

    # --- matrices implicites ---------------------------------------------
    if CACHE_IMPLICITE.exists():
        imp = pd.read_parquet(CACHE_IMPLICITE)
        print(f"implicite : {len(imp):,} lignes reprises du cache")
    else:
        print("implicite : ajustement des matrices (~4 min)…", flush=True)
        imp = calculer_implicite(clo)
        imp.to_parquet(CACHE_IMPLICITE, index=False)
    print(f"  matrices non fiables (Poisson ne reproduit pas le 1X2) : "
          f"{(~imp.fiable).sum():,} soit {100 * (~imp.fiable).mean():.2f} %")

    # --- Dixon-Coles ------------------------------------------------------
    if CACHE_DC.exists():
        dc = pd.read_parquet(CACHE_DC)
        print(f"DC : {len(dc):,} prédictions reprises du cache")
    else:
        print("\nDC : walk-forward sur tout l'historique…", flush=True)
        dc = calculer_dc(df)
        dc.to_parquet(CACHE_DC, index=False)

    # --- assemblage -------------------------------------------------------
    cle = ["date", "league_code", "home_goals", "away_goals"]
    imp = imp.assign(_i=np.arange(len(imp)))
    t = clo[["date", "league_code", "season", "home_team", "away_team",
             "home_goals", "away_goals"]].copy()
    for c in ("lam", "mu", "rho", "fiable", "p_marche_over25",
              "lam_ou", "mu_ou", "rho_ou", "fiable_ou"):
        t[c] = imp[c].to_numpy()

    t = t.merge(dc[["date", "league_code", "home_team", "away_team",
                    "dc_lam", "dc_mu", "rho", "equipe_inconnue"]]
                .rename(columns={"rho": "dc_rho"}),
                on=["date", "league_code", "home_team", "away_team"], how="left")
    print(f"\nappariement marché x DC : {t.dc_lam.notna().sum():,} matchs des "
          f"{len(t):,} à clôture Pinnacle")

    # --- probabilités par source -----------------------------------------
    print("\ncalcul des probabilités par marché…", flush=True)
    p_imp = _probas_depuis_lambdas(t.lam, t.mu, t.rho, MARCHES_TESTES)
    p_ou = _probas_depuis_lambdas(t.lam_ou, t.mu_ou, t.rho_ou, MARCHES_TESTES)
    p_dc = _probas_depuis_lambdas(t.dc_lam, t.dc_mu, t.dc_rho, MARCHES_TESTES)

    buts_d, buts_e = t.home_goals.to_numpy(), t.away_goals.to_numpy()
    realise = {c: MARCHES[c].predicat(buts_d, buts_e).astype(float)
               for c in MARCHES_TESTES}

    t["majeur"] = t.league_code.isin(LEAGUES_MAIN)
    t["periode"] = np.where(t.date < "2019-07-01", "2012-2019", "2019-2026")
    blocs = (t.league_code + "|" + t.season.astype(str)).to_numpy()

    # =====================================================================
    print("\n" + "=" * 78)
    print("1. CE QUE COÛTE LA DÉRIVATION — P(3 buts ou plus) dérivée vs cotée")
    print("=" * 78)
    m = t.p_marche_over25.notna().to_numpy()
    d = p_imp["total_over_2.5"][m] - t.p_marche_over25.to_numpy()[m]
    print(f"n = {m.sum():,} matchs (grands championnats, 2019-20 → 2026-01)")
    print(f"  écart moyen        {100 * d.mean():+.2f} pts")
    print(f"  écart absolu moyen {100 * np.abs(d).mean():.2f} pts")
    print(f"  écart médian abs.  {100 * np.median(np.abs(d)):.2f} pts")
    print(f"  90e centile abs.   {100 * np.quantile(np.abs(d), 0.9):.2f} pts")
    print(f"  corrélation        {np.corrcoef(p_imp['total_over_2.5'][m], t.p_marche_over25[m])[0,1]:.4f}")

    # =====================================================================
    print("\n" + "=" * 78)
    print("2. QUI PRÉDIT LE MIEUX — Brier par marché, par strate")
    print("=" * 78)
    sources = {"marché (over/under coté)": None, "implicite 1X2": p_imp,
               "implicite 1X2+O/U": p_ou, "Dixon-Coles": p_dc}
    lignes = []
    for (per, maj), g in t.groupby(["periode", "majeur"]):
        idx = g.index.to_numpy()
        for code in MARCHES_TESTES:
            y = realise[code][idx]
            for nom, src in sources.items():
                if src is None:
                    if code != "total_over_2.5":
                        continue
                    p = t.p_marche_over25.to_numpy()[idx]
                else:
                    p = src[code][idx]
                ok = np.isfinite(p)
                if ok.sum() < 500:
                    continue
                lignes.append({
                    "période": per, "champ.": "majeurs" if maj else "extra",
                    "marché": code, "source": nom, "n": int(ok.sum()),
                    "brier": _brier(p[ok], y[ok]), "ece": _ece(p[ok], y[ok]),
                    "taux_reel": float(y[ok].mean()), "p_moyenne": float(p[ok].mean()),
                })
    r = pd.DataFrame(lignes)
    for code in MARCHES_TESTES:
        sous = r[r["marché"] == code]
        if len(sous) == 0:
            continue
        print(f"\n--- {code} — {MARCHES[code].pour('domicile', 'extérieur')}")
        print(sous.drop(columns="marché").to_string(
            index=False, float_format=lambda v: f"{v:.4f}"))

    # =====================================================================
    print("\n" + "=" * 78)
    print("3. COMPARAISONS DIRECTES (bootstrap par blocs championnat-saison)")
    print("=" * 78)
    print("Brier plus BAS = meilleur. IC95 entièrement négatif = A bat B.\n")

    def comparer(nom_a, pa, nom_b, pb, code, masque, etiquette):
        y = realise[code]
        ok = masque & np.isfinite(pa) & np.isfinite(pb)
        if ok.sum() < 500:
            print(f"  {etiquette:34s} {code:16s} n trop faible ({ok.sum()})")
            return
        d, lo, hi = bootstrap_blocs(_par_match(pa[ok], y[ok]),
                                    _par_match(pb[ok], y[ok]), blocs[ok], n_iter=1000)
        verdict = (f"{nom_a} MEILLEUR" if hi < 0 else
                   f"{nom_b} meilleur" if lo > 0 else "non concluant")
        print(f"  {etiquette:34s} {code:16s} n={ok.sum():>6,}  "
              f"{d:+.6f}  IC95 [{lo:+.6f}, {hi:+.6f}]  {verdict}")

    maj = t.majeur.to_numpy()
    avec_ou = t.p_marche_over25.notna().to_numpy()
    avec_dc = np.isfinite(t.dc_lam.to_numpy())

    print("Là où le marché cote le total (grands championnats, 2019+) :")
    comparer("marché", t.p_marche_over25.to_numpy(), "implicite", p_imp["total_over_2.5"],
             "total_over_2.5", avec_ou, "marché - implicite")
    comparer("marché", t.p_marche_over25.to_numpy(), "DC", p_dc["total_over_2.5"],
             "total_over_2.5", avec_ou & avec_dc, "marché - DC")
    comparer("implicite", p_imp["total_over_2.5"], "DC", p_dc["total_over_2.5"],
             "total_over_2.5", avec_ou & avec_dc, "implicite - DC")

    print("\nLà où AUCUN prix n'existe — totaux par équipe :")
    for code in ("dom_over_1.5", "ext_over_1.5", "dom_over_0.5", "btts_oui"):
        comparer("implicite", p_imp[code], "DC", p_dc[code], code, avec_dc,
                 "implicite - DC (tous champ.)")
    print()
    for code in ("dom_over_1.5", "ext_over_1.5"):
        comparer("implicite", p_imp[code], "DC", p_dc[code], code,
                 avec_dc & ~maj, "implicite - DC (extra seuls)")

    print("\nEt quand la cote de totaux contraint la matrice :")
    for code in ("dom_over_1.5", "ext_over_1.5", "btts_oui"):
        comparer("impl.+O/U", p_ou[code], "implicite 1X2", p_imp[code], code,
                 avec_ou, "impl.+O/U - impl. 1X2")

    r.to_csv("research/h7_marches_buts.csv", index=False)
    print("\ntableau complet -> research/h7_marches_buts.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
