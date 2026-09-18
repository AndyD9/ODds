"""Client The Odds API — https://the-odds-api.com

Pourquoi cette source (research/RESULTS.md R1, R7) : football-data a cessé de
publier Pinnacle après le 2026-01-14 et ne publie ses fixtures que deux fois
par semaine. Cette API fournit une couverture **continue**, et ramène
Pinnacle et Betfair Exchange — le benchmark perdu.

Économie de crédits, offre gratuite à 500/mois :

- ``/sports`` et ``/events``  : **gratuits et illimités** ;
- ``/odds``                   : **1 crédit par championnat x marché x région**,
                                et un appel renvoie TOUS les matchs à venir
                                du championnat.

D'où la stratégie appliquée ici : interroger d'abord ``/events`` (gratuit)
pour savoir quels championnats ont réellement des matchs proches, puis ne
dépenser des crédits que sur ceux-là. Un championnat sans match imminent ne
coûte rien.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from odds import config

BASE = "https://api.the-odds-api.com/v4"

# Bookmakers dont la lecture nous intéresse en priorité. Les autres sont
# collectés aussi : le filtrage se fait à l'analyse, pas à l'ingestion.
BENCHMARKS = ("pinnacle", "betfair_ex_eu", "matchbook")


class BudgetEpuise(RuntimeError):
    """Levée avant tout appel payant qui dépasserait le budget du jour."""


def _cle() -> str:
    c = config.get("ODDS_API_KEY")
    if not c:
        raise RuntimeError(
            "ODDS_API_KEY absente. Voir :  uv run odds config --init")
    return c


def _get(chemin: str, **params) -> tuple[list, dict]:
    r = requests.get(f"{BASE}{chemin}", params={"apiKey": _cle(), **params}, timeout=60)
    entetes = {
        "utilises": r.headers.get("x-requests-used"),
        "restants": r.headers.get("x-requests-remaining"),
        "cout": r.headers.get("x-requests-last"),
    }
    if r.status_code == 401:
        raise RuntimeError("Clé refusée (401). Vérifiez ODDS_API_KEY dans .env.")
    if r.status_code == 429:
        raise BudgetEpuise("Quota The Odds API épuisé (429).")
    r.raise_for_status()
    return r.json(), entetes


# --- endpoints gratuits ----------------------------------------------------

def lister_sports(actifs_seulement: bool = True) -> pd.DataFrame:
    """GRATUIT. Championnats disponibles."""
    d, _ = _get("/sports")
    df = pd.DataFrame(d)
    return df[df.active] if actifs_seulement and "active" in df else df


def evenements(sport: str) -> pd.DataFrame:
    """GRATUIT. Matchs à venir d'un championnat, sans cotes."""
    d, _ = _get(f"/sports/{sport}/events")
    if not d:
        return pd.DataFrame(columns=["id", "sport_key", "commence_time",
                                     "home_team", "away_team"])
    df = pd.DataFrame(d)
    df["commence_time"] = pd.to_datetime(df.commence_time, utc=True)
    return df


def championnats_avec_matchs(sports: list[str], heures: int = 36) -> pd.DataFrame:
    """GRATUIT. Quels championnats ont un match dans les N prochaines heures.

    C'est l'étape qui rend l'offre gratuite viable : elle évite de dépenser
    un crédit sur un championnat qui ne joue pas.
    """
    limite = datetime.now(timezone.utc) + timedelta(hours=heures)
    lignes = []
    for s in sports:
        try:
            ev = evenements(s)
        except Exception as e:
            lignes.append({"sport": s, "n_total": 0, "n_proches": 0,
                           "prochain": pd.NaT, "erreur": str(e)[:120]})
            continue
        proches = ev[ev.commence_time <= limite] if len(ev) else ev
        lignes.append({
            "sport": s,
            "n_total": len(ev),
            "n_proches": len(proches),
            "prochain": ev.commence_time.min() if len(ev) else pd.NaT,
            "erreur": None,
        })
    d = pd.DataFrame(lignes)
    return d.sort_values(["n_proches", "prochain"], ascending=[False, True])


# --- endpoint payant -------------------------------------------------------

def cotes(sport: str, regions: str = "eu", markets: str = "h2h") -> tuple[pd.DataFrame, dict]:
    """PAYANT : 1 crédit par marché et par région.

    Renvoie les cotes au format long, une ligne par
    (match, bookmaker, marché, sélection).
    """
    d, entetes = _get(f"/sports/{sport}/odds", regions=regions,
                      markets=markets, oddsFormat="decimal")
    return _normaliser(d, sport), entetes


def _normaliser(evts: list, sport: str) -> pd.DataFrame:
    """Aplatit la réponse imbriquée vers notre format long.

    Point de vigilance : l'API nomme les issues par le NOM DE L'ÉQUIPE, pas
    par home/away. Une correspondance approximative introduirait des
    inversions domicile/extérieur silencieuses — on exige donc une
    correspondance exacte et on lève sinon.
    """
    lignes = []
    for e in evts:
        dom, ext = e["home_team"], e["away_team"]
        for b in e.get("bookmakers", []):
            for m in b.get("markets", []):
                for o in m.get("outcomes", []):
                    nom = o["name"]
                    if m["key"] == "h2h":
                        if nom == dom:
                            sel = "home"
                        elif nom == ext:
                            sel = "away"
                        elif nom == "Draw":
                            sel = "draw"
                        else:
                            raise ValueError(
                                f"issue non reconnue {nom!r} pour {dom} – {ext} "
                                f"({sport}) : correspondance domicile/extérieur "
                                "impossible, risque d'inversion")
                    else:
                        sel = nom.lower()
                        if o.get("point") is not None:
                            sel = f"{sel}_{o['point']}"
                    lignes.append({
                        "event_id": e["id"],
                        "sport": sport,
                        "kickoff": e["commence_time"],
                        "home_team": dom,
                        "away_team": ext,
                        "bookmaker": b["key"],
                        "market": "1X2" if m["key"] == "h2h" else m["key"],
                        "selection": sel,
                        "odds": float(o["price"]),
                        "book_updated_at": b.get("last_update"),
                    })
    if not lignes:
        return pd.DataFrame()
    d = pd.DataFrame(lignes)
    d["kickoff"] = (pd.to_datetime(d.kickoff, utc=True)
                      .dt.tz_convert(None).dt.strftime("%Y-%m-%d %H:%M"))
    d["book_updated_at"] = (pd.to_datetime(d.book_updated_at, utc=True, errors="coerce")
                              .dt.tz_convert(None).dt.strftime("%Y-%m-%d %H:%M:%S"))
    return d


# --- compteur de crédits ---------------------------------------------------

def credits() -> dict:
    """GRATUIT. Lit le quota via les en-têtes de ``/sports``.

    ``/sports`` ne compte pas dans le quota : on obtient donc le compteur
    autoritatif sans rien dépenser. Inutile de se fier à la dernière valeur
    stockée, qui peut dater.
    """
    _, h = _get("/sports")
    utilises = int(h["utilises"] or 0)
    restants = int(h["restants"] or 0)
    total = utilises + restants
    return {"utilises": utilises, "restants": restants, "total": total,
            "part_utilisee": (utilises / total) if total else 0.0}


def projection(restants: int, par_jour: float, maintenant=None) -> dict:
    """Combien de temps le quota tient-il au rythme observé ?

    Le quota The Odds API se réinitialise mensuellement. On compare donc
    l'autonomie au nombre de jours restant avant la fin du mois.
    """
    maintenant = maintenant or datetime.now(timezone.utc)
    debut_mois_suivant = (maintenant.replace(day=1) + timedelta(days=32)).replace(day=1)
    jours_restants = (debut_mois_suivant.date() - maintenant.date()).days

    autonomie = (restants / par_jour) if par_jour > 0 else float("inf")
    besoin = par_jour * jours_restants
    return {
        "jours_restants_mois": jours_restants,
        "conso_par_jour": par_jour,
        "autonomie_jours": autonomie,
        "besoin_fin_de_mois": besoin,
        "suffisant": restants >= besoin,
        "epuisement": (maintenant + timedelta(days=autonomie)).date()
                      if autonomie != float("inf") and autonomie < 400 else None,
    }
