"""Données historiques, dévig d'un livre, calibration, cartographies.

Tout ce qui se calcule sur le parquet football-data et ne dépend ni de la
collecte ni d'une date : le socle que les autres modules d'analyse
partagent.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from odds import chemins
from odds.market.devig import METHODS, devig, devig_matrix, overround, shin_z

ISSUES_1X2 = ("Domicile", "Nul", "Extérieur")

# --------------------------------------------------------------------------
# Données
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def charger(chemin: str | None = None) -> pd.DataFrame:
    p = Path(chemin) if chemin else chemins.PARQUET
    if not p.exists():
        raise FileNotFoundError(
            f"{p} introuvable. Lancez d'abord :  uv run odds ingest"
        )
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"])
    df["saison_annee"] = df["date"].dt.year
    return df


def avec_cloture(df: pd.DataFrame) -> pd.DataFrame:
    return df[df.odds_source == "pinnacle_closing"]


def avec_precoce(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df.odds_source == "pinnacle_closing")
              & df[["ps_h", "ps_d", "ps_a"]].notna().all(axis=1)]


# --------------------------------------------------------------------------
# Dévig d'un livre unique
# --------------------------------------------------------------------------

def analyser_livre(cotes: list[float], libelles: list[str] | None = None) -> dict:
    """Retire la marge d'un livre par les 4 méthodes et compare.

    Renvoie un dict avec le tableau par méthode et les indicateurs du livre.
    """
    c = np.asarray(cotes, dtype=float)
    if libelles is None:
        libelles = list(ISSUES_1X2) if len(c) == 3 else [f"Issue {i+1}" for i in range(len(c))]

    ov = overround(c)
    lignes = []
    for m in ("shin", "power", "odds_ratio", "proportional"):
        p = devig(c, m)
        lignes.append(pd.Series(p, index=libelles, name=m))
    tableau = pd.DataFrame(lignes).T
    tableau["cote"] = c
    tableau["implicite_brute"] = 1.0 / c

    ecart = tableau["proportional"] - tableau["shin"]
    return {
        "libelles": libelles,
        "cotes": c,
        "overround": ov,
        "marge_pct": 100.0 * (ov - 1.0),
        "z_shin": shin_z(c) if ov > 1 else 0.0,
        "probabilites": tableau,
        "cote_juste_shin": 1.0 / tableau["shin"].to_numpy(),
        "biais_proportionnel_pts": 100.0 * ecart,
        "biais_proportionnel_rel": 100.0 * ecart / tableau["shin"],
    }


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------

def probabilites_marche(df: pd.DataFrame, prefixe: str = "psc",
                        methode: str = "shin") -> np.ndarray:
    cols = [f"{prefixe}_h", f"{prefixe}_d", f"{prefixe}_a"]
    return devig_matrix(df[cols].to_numpy(float), methode)


def cible(df: pd.DataFrame) -> np.ndarray:
    return np.column_stack([(df.result == r).to_numpy() for r in ("H", "D", "A")]).astype(float)


def courbe_calibration(p: np.ndarray, y: np.ndarray, n_bins: int = 12) -> pd.DataFrame:
    """Fréquence observée contre probabilité annoncée, toutes issues confondues."""
    pf, yf = p.ravel(), y.ravel()
    bornes = np.quantile(pf, np.linspace(0, 1, n_bins + 1))
    bornes = np.unique(bornes)
    idx = np.clip(np.digitize(pf, bornes[1:-1]), 0, len(bornes) - 2)
    out = []
    for b in range(len(bornes) - 1):
        m = idx == b
        if m.sum() < 30:
            continue
        out.append({
            "bin": b,
            "annonce": float(pf[m].mean()),
            "observe": float(yf[m].mean()),
            "n": int(m.sum()),
            "ecart_pts": 100.0 * float(yf[m].mean() - pf[m].mean()),
        })
    return pd.DataFrame(out)


def ece(courbe: pd.DataFrame) -> float:
    """Expected calibration error, pondéré par l'effectif des bins."""
    w = courbe.n / courbe.n.sum()
    return float((w * (courbe.observe - courbe.annonce).abs()).sum())


# --------------------------------------------------------------------------
# Cartographies
# --------------------------------------------------------------------------

def carte_marges(df: pd.DataFrame, n_min: int = 500) -> pd.DataFrame:
    """Marge Pinnacle moyenne par championnat. Proxy d'efficience."""
    d = avec_cloture(df).copy()
    d["marge"] = 100.0 * ((1 / d.psc_h + 1 / d.psc_d + 1 / d.psc_a) - 1.0)
    g = (d.groupby(["league_code", "country", "league"])
           .agg(n=("date", "size"), marge=("marge", "mean"),
                depuis=("date", "min"), jusqua=("date", "max")).reset_index())
    return g[g.n >= n_min].sort_values("marge").reset_index(drop=True)


def carte_information_tardive(df: pd.DataFrame, n_min: int = 300) -> pd.DataFrame:
    """Brier(cote précoce) - Brier(clôture), par championnat.

    Élevé = beaucoup d'information arrive tard, miser tôt est risqué.
    Faible = le prix précoce est déjà quasi définitif.
    """
    d = avec_precoce(df)
    if len(d) == 0:
        return pd.DataFrame()
    y = cible(d)
    b_pre = np.sum((probabilites_marche(d, "ps") - y) ** 2, axis=1)
    b_clo = np.sum((probabilites_marche(d, "psc") - y) ** 2, axis=1)
    t = d.assign(b_pre=b_pre, b_clo=b_clo)
    g = (t.groupby(["league_code", "country", "league"])
           .agg(n=("date", "size"), brier_precoce=("b_pre", "mean"),
                brier_cloture=("b_clo", "mean")).reset_index())
    g["information_tardive"] = g.brier_precoce - g.brier_cloture
    return g[g.n >= n_min].sort_values("information_tardive", ascending=False).reset_index(drop=True)


def comparer_methodes(df: pd.DataFrame) -> pd.DataFrame:
    """Brier et log loss du marché selon la méthode de dévig."""
    d = avec_cloture(df)
    y = cible(d)
    lignes = []
    for m in sorted(METHODS):
        p = probabilites_marche(d, "psc", m)
        lignes.append({
            "methode": m,
            "brier": float(np.mean(np.sum((p - y) ** 2, axis=1))),
            "log_loss": float(-np.mean(np.sum(y * np.log(np.clip(p, 1e-15, 1)), axis=1))),
            "ece": ece(courbe_calibration(p, y)),
        })
    base = np.tile(y.mean(0), (len(y), 1))
    lignes.append({"methode": "(taux de base)",
                   "brier": float(np.mean(np.sum((base - y) ** 2, axis=1))),
                   "log_loss": float(-np.mean(np.sum(y * np.log(np.clip(base, 1e-15, 1)), axis=1))),
                   "ece": np.nan})
    return pd.DataFrame(lignes).sort_values("brier").reset_index(drop=True)

