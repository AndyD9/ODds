"""Noyau d'analyse — partagé par la CLI et le tableau de bord.

Périmètre assumé (research/RESULTS.md R8) : cet outil **ne produit aucun
signal de pari**. Il a été établi qu'un modèle de comptage sur données
publiques ne bat ni la clôture ni le prix précoce, dans aucun des 23
championnats testés. Ce que l'outil fait, et qui reste utile :

- retirer correctement la marge d'un livre de cotes (ce que 1/cote ne fait
  pas, et ce que la normalisation proportionnelle fait mal) ;
- mesurer la calibration réelle du marché ;
- cartographier marge et information tardive par championnat.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from odds.market.devig import METHODS, devig, devig_matrix, overround, shin_z

RACINE = Path(__file__).resolve().parents[2]
PARQUET = RACINE / "research" / "data" / "matches.parquet"

ISSUES_1X2 = ("Domicile", "Nul", "Extérieur")


# --------------------------------------------------------------------------
# Données
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def charger(chemin: str | None = None) -> pd.DataFrame:
    p = Path(chemin) if chemin else PARQUET
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


# --------------------------------------------------------------------------
# Matchs à une date donnée — bascule automatique de source
# --------------------------------------------------------------------------
# Deux sources, un seul point d'entrée :
#   - date dans le futur / récente  -> collecte propre (odds_history.db)
#   - date passée                   -> historique (matches.parquet)
# On privilégie toujours la collecte quand elle couvre la date, parce qu'elle
# porte plusieurs bookmakers et notre propre horodatage.

BDD_COLLECTE = RACINE / "research" / "data" / "odds_history.db"

# Livres agrégés : utiles pour le price shopping, mais ce ne sont pas des
# bookmakers réels et ils ne doivent pas entrer dans le consensus.
AGREGATS = ("_max_marche", "_moyenne_marche")

# Cotes relevées à un AUTRE instant. Ce n'est pas un bookmaker concurrent,
# c'est le même book plus tôt. L'inclure gonflerait artificiellement la
# dispersion et ferait apparaître comme "meilleur prix" une cote qui n'était
# plus disponible au moment considéré.
AUTRE_INSTANT = ("pinnacle_precoce",)

HORS_CONSENSUS = AGREGATS + AUTRE_INSTANT

BENCHMARKS = ("betfair_exchange", "pinnacle_closing", "pinnacle")


# Ordre de préférence entre sources collectées. The Odds API d'abord : elle
# est continue, porte ~24 bookmakers dont Pinnacle et Betfair Exchange, là où
# football-data ne publie que deux fois par semaine et a perdu Pinnacle.
# On ne MÉLANGE pas les deux : les noms d'équipe diffèrent d'une source à
# l'autre et un appariement approximatif créerait des doublons silencieux.
PREFERENCE_SOURCES = ("odds-api", "football-data")


def _long_depuis_collecte(jour: pd.Timestamp) -> pd.DataFrame:
    import sqlite3
    if not BDD_COLLECTE.exists():
        return pd.DataFrame()
    requete = """
        SELECT s.fixture_key, s.source, s.country, s.league, s.kickoff,
               s.home_team, s.away_team, s.bookmaker, s.selection,
               s.odds, s.observed_at
        FROM odds_snapshot s
        JOIN (
            SELECT fixture_key, bookmaker, selection, MAX(observed_at) AS vu
            FROM odds_snapshot WHERE market = '1X2'
            GROUP BY fixture_key, bookmaker, selection
        ) d
          ON s.fixture_key = d.fixture_key AND s.bookmaker = d.bookmaker
         AND s.selection = d.selection AND s.observed_at = d.vu
        WHERE s.market = '1X2' AND substr(s.kickoff, 1, 10) = ?
    """
    con = sqlite3.connect(BDD_COLLECTE)
    try:
        d = pd.read_sql(requete, con, params=(jour.strftime("%Y-%m-%d"),))
    finally:
        con.close()
    if len(d) == 0 or "source" not in d.columns:
        return d
    for src in PREFERENCE_SOURCES:
        sous = d[d.source == src]
        if len(sous):
            return sous.reset_index(drop=True)
    return d


def _long_depuis_historique(jour: pd.Timestamp) -> pd.DataFrame:
    df = charger()
    d = df[df.date.dt.normalize() == jour.normalize()]
    if len(d) == 0:
        return pd.DataFrame()
    blocs = []
    for prefixe, book in (("psc", "pinnacle_closing"), ("ps", "pinnacle_precoce"),
                          ("avgc", "_moyenne_marche"), ("maxc", "_max_marche")):
        cols = [f"{prefixe}_{x}" for x in ("h", "d", "a")]
        if not set(cols) <= set(d.columns):
            continue
        ok = d[d[cols].notna().all(axis=1)]
        if len(ok) == 0:
            continue
        for col, sel in zip(cols, ("home", "draw", "away")):
            blocs.append(pd.DataFrame({
                "fixture_key": ok.index.astype(str),
                "country": ok.country, "league": ok.league,
                "kickoff": ok.date.dt.strftime("%Y-%m-%d %H:%M"),
                "home_team": ok.home_team, "away_team": ok.away_team,
                "bookmaker": book, "selection": sel,
                "odds": ok[col].astype(float),
                "observed_at": pd.NA,
                "resultat": ok.result,
                "score": ok.home_goals.astype(str) + "–" + ok.away_goals.astype(str),
            }))
    return pd.concat(blocs, ignore_index=True) if blocs else pd.DataFrame()


def matchs_a_la_date(jour, methode: str = "shin") -> dict:
    """Tous les matchs d'une date, avec l'analyse calculée automatiquement.

    Renvoie ``source``, ``resume`` (une ligne par match) et ``detail``
    (une ligne par match x bookmaker).
    """
    jour = pd.Timestamp(jour)

    long = _long_depuis_collecte(jour)
    source, fournisseur = "collecte", None
    if len(long):
        fournisseur = (str(long.source.iloc[0]) if "source" in long.columns
                       and pd.notna(long.source.iloc[0]) else "football-data")
    else:
        long = _long_depuis_historique(jour)
        source, fournisseur = "historique", "pinnacle-closing"
    if len(long) == 0:
        return {"source": None, "fournisseur": None,
                "resume": pd.DataFrame(), "detail": pd.DataFrame()}

    # --- dévig, un livre à la fois ----------------------------------------
    large = long.pivot_table(
        index=["fixture_key", "bookmaker"], columns="selection",
        values="odds", aggfunc="first")
    large = large.dropna(subset=["home", "draw", "away"])
    large = large[(large[["home", "draw", "away"]] > 1.0).all(axis=1)]
    if len(large) == 0:
        return {"source": source, "fournisseur": fournisseur,
                "resume": pd.DataFrame(), "detail": pd.DataFrame()}

    cotes = large[["home", "draw", "away"]].to_numpy(float)
    p = devig_matrix(cotes, methode)

    detail = large.reset_index()[["fixture_key", "bookmaker"]].copy()
    detail[["cote_1", "cote_N", "cote_2"]] = cotes
    detail[["p_1", "p_N", "p_2"]] = p
    detail["marge"] = 100.0 * ((1.0 / cotes).sum(axis=1) - 1.0)

    meta_cols = ["fixture_key", "country", "league", "kickoff", "home_team", "away_team"]
    for c in ("resultat", "score", "observed_at"):
        if c in long.columns:
            meta_cols.append(c)
    meta = long[meta_cols].drop_duplicates("fixture_key")
    detail = detail.merge(meta, on="fixture_key", how="left")

    # --- consensus : médiane des bookmakers RÉELS -------------------------
    reels = detail[~detail.bookmaker.isin(HORS_CONSENSUS)]
    cons = (reels.groupby("fixture_key")
                 .agg(n_books=("bookmaker", "nunique"),
                      p_1=("p_1", "median"), p_N=("p_N", "median"), p_2=("p_2", "median"),
                      marge=("marge", "median"),
                      dispersion=("p_1", "std"))
                 .reset_index())
    s = cons[["p_1", "p_N", "p_2"]].sum(axis=1)
    cons[["p_1", "p_N", "p_2"]] = cons[["p_1", "p_N", "p_2"]].div(s, axis=0)
    cons["dispersion"] = 100.0 * cons.dispersion.fillna(0.0)

    # --- price shopping : meilleur prix disponible vs consensus -----------
    dispo = detail[~detail.bookmaker.isin(AUTRE_INSTANT)]
    for sel, col in (("1", "cote_1"), ("N", "cote_N"), ("2", "cote_2")):
        idx = dispo.groupby("fixture_key")[col].idxmax()
        b = dispo.loc[idx, ["fixture_key", col, "bookmaker"]].rename(
            columns={col: f"best_{sel}", "bookmaker": f"book_{sel}"})
        cons = cons.merge(b, on="fixture_key", how="left")
    cons = cons.merge(meta, on="fixture_key", how="left")

    # --- EV « leave-one-out » et soutien du meilleur prix ------------------
    #
    # Deux corrections indispensables pour que le chiffre veuille dire
    # quelque chose :
    #
    # 1) LEAVE-ONE-OUT. Comparer le meilleur prix à un consensus qui
    #    l'inclut est circulaire : le book généreux tire la médiane vers
    #    lui et masque son propre écart. On recalcule donc le consensus
    #    SANS le bookmaker qui offre ce prix.
    #
    # 2) SOUTIEN. Un prix isolé de 3 % au-dessus du deuxième meilleur n'est
    #    presque jamais une opportunité : c'est une cote périmée, une erreur,
    #    ou une limite de mise dérisoire. On mesure donc l'écart au deuxième
    #    meilleur prix, qui sépare l'anomalie isolée du désaccord réel.
    for sel, col in (("1", "cote_1"), ("N", "cote_N"), ("2", "cote_2")):
        p_loo, second, n_soutien = [], [], []
        for fk, best_book, best_cote in zip(cons.fixture_key, cons[f"book_{sel}"],
                                            cons[f"best_{sel}"]):
            g = dispo[dispo.fixture_key == fk]
            autres = g[g.bookmaker != best_book]
            reels = autres[~autres.bookmaker.isin(HORS_CONSENSUS)]
            src = reels if len(reels) else autres
            p_loo.append(float(np.median(src[f"p_{sel}"])) if len(src) else np.nan)
            second.append(float(autres[col].max()) if len(autres) else np.nan)
            n_soutien.append(int((g[col] >= best_cote * 0.99).sum()))
        cons[f"p_loo_{sel}"] = p_loo
        cons[f"second_{sel}"] = second
        cons[f"soutien_{sel}"] = n_soutien
        cons[f"ecart_{sel}"] = 100.0 * (np.array(p_loo) * cons[f"best_{sel}"] - 1.0)
        cons[f"prime_{sel}"] = 100.0 * (cons[f"best_{sel}"] / np.array(second) - 1.0)

    cons["meilleur_ecart"] = cons[["ecart_1", "ecart_N", "ecart_2"]].max(axis=1)

    # --- deux lectures distinctes, à ne jamais confondre -------------------
    #
    # 1) issue_probable : ce que le marché juge le plus probable.
    #    Lecture factuelle, PAS une recommandation. Au prix juste, miser sur
    #    le favori a une espérance nulle : le marché l'a déjà intégré.
    #
    # 2) issue_prix : l'issue dont le meilleur prix disponible s'écarte le
    #    plus du consensus. C'est du price shopping — une observation sur la
    #    dispersion des prix, pas une prédiction — et l'indicateur est biaisé
    #    à la hausse (le maximum sur N books retient la cote périmée).
    #
    # Les deux coïncident rarement.
    labels = np.array(["1", "N", "2"])
    probas = cons[["p_1", "p_N", "p_2"]].to_numpy()
    cons["issue_probable"] = labels[probas.argmax(axis=1)]
    cons["p_probable"] = probas.max(axis=1)

    ecarts = cons[["ecart_1", "ecart_N", "ecart_2"]].to_numpy()
    j = ecarts.argmax(axis=1)
    lig = np.arange(len(cons))
    cons["issue_prix"] = labels[j]
    cons["ecart_prix"] = ecarts[lig, j]
    cons["cote_prix"] = cons[["best_1", "best_N", "best_2"]].to_numpy()[lig, j]
    cons["book_prix"] = cons[["book_1", "book_N", "book_2"]].to_numpy()[lig, j]
    cons["prime_prix"] = cons[["prime_1", "prime_N", "prime_2"]].to_numpy()[lig, j]
    cons["soutien_prix"] = cons[["soutien_1", "soutien_N", "soutien_2"]].to_numpy()[lig, j]
    cons["p_prix"] = cons[["p_loo_1", "p_loo_N", "p_loo_2"]].to_numpy()[lig, j]
    cons["accord"] = cons.issue_probable == cons.issue_prix

    # --- robustesse de l'EV à la méthode de dévig --------------------------
    #
    # R3 a mesuré que sous 5 % de probabilité, les méthodes de dévig
    # divergent de 16,6 % EN RELATIF. Un écart de +7 % d'EV sur un outsider
    # est donc entièrement à l'intérieur du bruit de la méthode : il change
    # de signe selon qu'on retient Shin, power ou odds ratio.
    #
    # On recalcule donc l'EV sous les QUATRE méthodes. Si le signe ne tient
    # pas, le chiffre ne veut rien dire, quel que soit son niveau.
    cons[["ev_min", "ev_max"]] = _ev_toutes_methodes(cons, large, dispo)
    cons["ev_robuste"] = cons.ev_min > 0

    cons["verdict"] = [_verdict(r) for _, r in cons.iterrows()]

    cons = cons.sort_values("kickoff").reset_index(drop=True)
    return {"source": source, "fournisseur": fournisseur,
            "resume": cons, "detail": detail}


def _ev_toutes_methodes(cons: pd.DataFrame, large: pd.DataFrame,
                        dispo: pd.DataFrame) -> pd.DataFrame:
    """EV minimale et maximale de la sélection retenue, sur les 4 méthodes."""
    idx_sel = {"1": 0, "N": 1, "2": 2}
    cotes = large[["home", "draw", "away"]].to_numpy(float)
    cles = large.reset_index()[["fixture_key", "bookmaker"]]

    par_methode = {}
    for m in ("shin", "power", "odds_ratio", "proportional"):
        p = devig_matrix(cotes, m)
        t = cles.copy()
        t[["p_1", "p_N", "p_2"]] = p
        par_methode[m] = t

    bornes = []
    for fk, sel, best_book, best_cote in zip(
            cons.fixture_key, cons.issue_prix, cons.book_prix, cons.cote_prix):
        col = ["p_1", "p_N", "p_2"][idx_sel[sel]]
        evs = []
        for t in par_methode.values():
            g = t[(t.fixture_key == fk) & (t.bookmaker != best_book)]
            g = g[~g.bookmaker.isin(HORS_CONSENSUS)]
            if len(g) == 0:
                continue
            evs.append(100.0 * (float(np.median(g[col])) * best_cote - 1.0))
        bornes.append((min(evs), max(evs)) if evs else (np.nan, np.nan))
    return pd.DataFrame(bornes, columns=["ev_min", "ev_max"], index=cons.index)


# Seuils du verdict. Fixés ici, pas au fil de l'affichage, pour être
# discutables et modifiables en un seul endroit.
SEUIL_EV_MINI = 1.0        # en % — en deçà, le bruit domine
SEUIL_PRIME_ISOLEE = 2.0   # en % au-dessus du 2e meilleur prix = anomalie isolée
SOUTIEN_MINI = 2           # nombre de books à 1 % du meilleur prix
N_BOOKS_MINI = 6           # consensus indigent en dessous


def _verdict(r) -> str:
    """Traduit les chiffres en une conclusion unique et lisible.

    Rappel de cadrage : ce verdict ne prédit RIEN. Il dit seulement si le
    meilleur prix disponible s'écarte du consensus des autres bookmakers
    d'assez pour ne pas être du bruit, et si cet écart est soutenu par
    plusieurs opérateurs ou porté par un seul.
    """
    if r.n_books < N_BOOKS_MINI:
        return "Trop peu de books"
    if not np.isfinite(r.ecart_prix) or r.ecart_prix < SEUIL_EV_MINI:
        return "Rien à signaler"
    if r.prime_prix > SEUIL_PRIME_ISOLEE or r.soutien_prix < SOUTIEN_MINI:
        return "Écart isolé — prudence"
    if not r.get("ev_robuste", True):
        return "Fragile — dépend de la méthode"
    return "Écart soutenu"


def dates_disponibles() -> dict:
    """Dates couvertes par chaque source, pour guider le sélecteur."""
    import sqlite3
    out = {"collecte": [], "historique": (None, None)}
    if BDD_COLLECTE.exists():
        con = sqlite3.connect(BDD_COLLECTE)
        try:
            out["collecte"] = [r[0] for r in con.execute(
                "SELECT DISTINCT substr(kickoff,1,10) FROM odds_snapshot ORDER BY 1")]
        finally:
            con.close()
    df = charger()
    out["historique"] = (df.date.min().date(), df.date.max().date())
    return out
