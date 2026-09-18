"""Collecte propre de cotes, horodatée par nous.

Raison d'être (PLAN §7.2, option A ; research/RESULTS.md R1) : Pinnacle closing
n'est plus publié sur football-data.co.uk après le 2026-01-14. Les flux de
matchs à venir ne portent plus aucune colonne Pinnacle exploitable. Toute
mesure en avant exige donc un historique que nous constituons nous-mêmes.

Ce module ne coûte rien mais prend du temps : c'est la seule tâche du projet
qui devait démarrer avant d'en avoir besoin.

Principes :

- ``observed_at`` est NOTRE horodatage, en UTC. C'est la seule date qui
  permette un backtest honnête : elle dit quand l'information nous était
  réellement disponible (PLAN §4.3).
- Format long : une ligne par (match, bookmaker, marché, sélection, instant).
- Écriture seulement en cas de CHANGEMENT : une cote identique à la dernière
  observation n'est pas réécrite. L'historique reste une série de mouvements.

Benchmark retenu en avant : **Betfair Exchange (BFE)** — prix réellement
négociable, et le seul substitut sérieux à Pinnacle dans ce flux.
"""

from __future__ import annotations

import hashlib
import io
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

RACINE = Path(__file__).resolve().parents[3]
BASE_DONNEES = RACINE / "research" / "data" / "odds_history.db"

FLUX = {
    "main": "https://www.football-data.co.uk/fixtures.csv",
    "extra": "https://www.football-data.co.uk/new_league_fixtures.csv",
}

# préfixe de colonne -> nom de bookmaker
BOOKMAKERS = {
    "PS": "pinnacle",          # absent depuis 2026-01, conservé pour un éventuel retour
    "BFE": "betfair_exchange",  # benchmark retenu en avant
    "B365": "bet365",
    "BFD": "betfair_sportsbook",
    "BV": "betvictor",
    "BW": "bwin",
    "PP": "paddypower",
    "SKB": "skybet",
    "Max": "_max_marche",       # meilleur prix observé sur le marché
    "Avg": "_moyenne_marche",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS odds_snapshot (
    fixture_key  TEXT    NOT NULL,
    source       TEXT,
    book_updated_at TEXT,
    country      TEXT,
    league       TEXT,
    kickoff      TEXT,
    home_team    TEXT    NOT NULL,
    away_team    TEXT    NOT NULL,
    bookmaker    TEXT    NOT NULL,
    market       TEXT    NOT NULL,
    selection    TEXT    NOT NULL,
    odds         REAL    NOT NULL,
    observed_at  TEXT    NOT NULL,
    run_id       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cle ON odds_snapshot(fixture_key, bookmaker, market, selection);
CREATE INDEX IF NOT EXISTS idx_vu  ON odds_snapshot(observed_at);

CREATE TABLE IF NOT EXISTS collecte_run (
    run_id       TEXT PRIMARY KEY,
    demarre_a    TEXT NOT NULL,
    flux         TEXT,
    matchs       INTEGER,
    lignes_vues  INTEGER,
    lignes_ecrites INTEGER,
    erreur       TEXT,
    credits_utilises INTEGER DEFAULT 0,
    credits_restants INTEGER
);

-- Fraîcheur des flux amont. football-data ne publie ses fixtures que par
-- à-coups (milieu de semaine, puis vendredi pour le week-end). Sans cette
-- trace, une journée vide est indiscernable d'une panne de notre côté.
CREATE TABLE IF NOT EXISTS flux_etat (
    flux           TEXT PRIMARY KEY,
    last_modified  TEXT,
    vu_a           TEXT,
    n_matchs       INTEGER,
    date_min       TEXT,
    date_max       TEXT
);
"""


# Colonnes ajoutées après la première mise en service. SQLite n'a pas de
# "ADD COLUMN IF NOT EXISTS" : on compare au schéma existant.
MIGRATIONS = {
    "odds_snapshot": {"source": "TEXT", "book_updated_at": "TEXT"},
    "collecte_run": {"credits_utilises": "INTEGER DEFAULT 0",
                     "credits_restants": "INTEGER"},
}


def _migrer(con: sqlite3.Connection) -> None:
    for table, colonnes in MIGRATIONS.items():
        existantes = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for nom, typ in colonnes.items():
            if nom not in existantes:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {typ}")
    con.commit()


def _connexion(chemin: Path | None = None) -> sqlite3.Connection:
    p = chemin or BASE_DONNEES
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.executescript(SCHEMA)
    _migrer(con)
    return con


def _cle(country, league, kickoff, home, away) -> str:
    brut = f"{country}|{league}|{kickoff}|{home}|{away}".lower()
    return hashlib.sha1(brut.encode()).hexdigest()[:16]


# Dernier en-tête Last-Modified vu, renseigné par _lire_flux.
_DERNIER_LAST_MODIFIED: dict[str, str | None] = {}


def _lire_flux(url: str) -> pd.DataFrame:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    _DERNIER_LAST_MODIFIED[url] = r.headers.get("Last-Modified")
    d = pd.read_csv(io.BytesIO(r.content), encoding="latin-1", on_bad_lines="skip")
    # Le BOM UTF-8, lu en latin-1, apparait comme les caracteres "\xef\xbb\xbf"
    # et non comme U+FEFF : il faut retirer les deux formes.
    d.columns = [c.lstrip("\ufeff").replace("\xef\xbb\xbf", "").strip()
                 for c in d.columns]
    return d


def _normaliser(d: pd.DataFrame, flux: str) -> pd.DataFrame:
    """Passe du format large (une colonne par book x issue) au format long."""
    if flux == "main":
        d = d.rename(columns={"HomeTeam": "home_team", "AwayTeam": "away_team",
                              "Div": "league"})
        d["country"] = pd.NA
    elif flux == "extra":
        d = d.rename(columns={"Home": "home_team", "Away": "away_team",
                              "Country": "country", "League": "league"})
    else:
        raise ValueError(f"flux inconnu : {flux!r} (attendu 'main' ou 'extra')")

    # Un format d'entrée inattendu doit LEVER, pas renvoyer un tableau vide.
    # Un échec silencieux ici coûterait des mois de collecte sans que rien
    # ne le signale — c'est exactement ce qui s'est produit avec le BOM.
    manquantes = {"home_team", "away_team", "Date"} - set(d.columns)
    if manquantes:
        raise ValueError(
            f"flux {flux} : colonnes attendues absentes {sorted(manquantes)} ; "
            f"colonnes reçues : {sorted(d.columns)[:15]}"
        )

    heure = d["Time"].fillna("00:00") if "Time" in d.columns else "00:00"
    d["kickoff"] = pd.to_datetime(
        d["Date"].astype(str) + " " + heure.astype(str),
        dayfirst=True, errors="coerce"
    ).dt.strftime("%Y-%m-%d %H:%M")

    lignes = []
    marches = {
        "1X2": [("H", "home"), ("D", "draw"), ("A", "away")],
        "OU25": [(">2.5", "over"), ("<2.5", "under")],
    }
    for prefixe, book in BOOKMAKERS.items():
        for marche, issues in marches.items():
            for suffixe, selection in issues:
                col = f"{prefixe}{suffixe}"
                if col not in d.columns:
                    continue
                v = pd.to_numeric(d[col], errors="coerce")
                m = v.notna() & (v > 1.0)
                if not m.any():
                    continue
                lignes.append(pd.DataFrame({
                    "country": d.loc[m, "country"],
                    "league": d.loc[m, "league"],
                    "kickoff": d.loc[m, "kickoff"],
                    "home_team": d.loc[m, "home_team"].astype(str).str.strip(),
                    "away_team": d.loc[m, "away_team"].astype(str).str.strip(),
                    "bookmaker": book,
                    "market": marche,
                    "selection": selection,
                    "odds": v[m].astype(float),
                }))
    if not lignes:
        return pd.DataFrame()
    out = pd.concat(lignes, ignore_index=True)
    out = out[out.kickoff.notna()]
    out["fixture_key"] = [
        _cle(c, l, k, h, a) for c, l, k, h, a in
        zip(out.country, out.league, out.kickoff, out.home_team, out.away_team)
    ]
    return out


COLONNES_SNAPSHOT = ["fixture_key", "source", "country", "league", "kickoff",
                     "home_team", "away_team", "bookmaker", "market", "selection",
                     "odds", "book_updated_at", "observed_at", "run_id"]


def credits_utilises_aujourdhui(con: sqlite3.Connection) -> int:
    """Crédits The Odds API déjà consommés depuis minuit UTC."""
    jour = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = con.execute(
        "SELECT COALESCE(SUM(credits_utilises), 0) FROM collecte_run "
        "WHERE substr(demarre_a, 1, 10) = ?", (jour,)).fetchone()
    return int(r[0] or 0)


def _collecter_oddsapi(con, observed_at, run_id, connu, verbose):
    """Passe The Odds API, sous contrainte de budget.

    Le plan est établi avec ``/events``, GRATUIT : on ne dépense un crédit
    que sur un championnat qui joue réellement dans les 36 h.
    """
    from odds import config
    from odds.data import oddsapi

    sports = config.get_liste("ODDS_API_SPORTS")
    regions = config.get("ODDS_API_REGIONS") or "eu"
    markets = config.get("ODDS_API_MARKETS") or "h2h"
    budget = int(config.get("ODDS_API_BUDGET_JOUR") or 14)
    cout_unitaire = max(1, len(markets.split(","))) * max(1, len(regions.split(",")))

    deja = credits_utilises_aujourdhui(con)
    dispo = max(0, budget - deja)
    if dispo < cout_unitaire:
        if verbose:
            print(f"  oddsapi  budget du jour épuisé ({deja}/{budget} crédits) — passe ignorée")
        return 0, 0, 0, None, []

    plan = oddsapi.championnats_avec_matchs(sports, heures=36)   # gratuit
    candidats = plan[plan.n_proches > 0].sport.tolist()
    retenus = candidats[: dispo // cout_unitaire]
    if verbose:
        print(f"  oddsapi  {len(candidats)}/{len(sports)} championnats jouent sous 36 h ; "
              f"budget {deja}/{budget} -> {len(retenus)} interrogé(s)")
    if not retenus:
        return 0, 0, 0, None, []

    vues = ecrites = credits = 0
    restants = None
    erreurs = []
    for sport in retenus:
        try:
            d, entetes = oddsapi.cotes(sport, regions=regions, markets=markets)
        except Exception as e:
            erreurs.append(f"oddsapi/{sport}: {e}")
            if verbose:
                print(f"           {sport:32s} ERREUR {e}")
            continue
        credits += int(entetes.get("cout") or cout_unitaire)
        restants = entetes.get("restants")
        if len(d) == 0:
            continue

        d["fixture_key"] = "oa:" + d.event_id
        d["country"] = pd.NA
        d["league"] = d.sport
        d["observed_at"] = observed_at
        d["run_id"] = run_id
        d["source"] = "odds-api"

        change = [
            connu.get((k, b, m, sl)) != o
            for k, b, m, sl, o in
            zip(d.fixture_key, d.bookmaker, d.market, d.selection, d.odds)
        ]
        nouveau = d[change]
        if len(nouveau):
            nouveau[COLONNES_SNAPSHOT].to_sql("odds_snapshot", con,
                                              if_exists="append", index=False)
        vues += len(d)
        ecrites += len(nouveau)
        if verbose:
            print(f"           {sport:32s} {d.fixture_key.nunique():3d} matchs · "
                  f"{len(d):5d} cotes · {len(nouveau):5d} écrites")
    return vues, ecrites, credits, restants, erreurs


def _derniere_cote(con: sqlite3.Connection) -> dict:
    """Dernière cote connue par (match, book, marché, sélection)."""
    q = """
        SELECT fixture_key, bookmaker, market, selection, odds
        FROM odds_snapshot
        WHERE rowid IN (
            SELECT MAX(rowid) FROM odds_snapshot
            GROUP BY fixture_key, bookmaker, market, selection
        )
    """
    return {(r[0], r[1], r[2], r[3]): r[4] for r in con.execute(q)}


def collecter(chemin_bdd: Path | None = None, verbose: bool = True) -> dict:
    """Une passe de collecte. Idempotente : ne réécrit pas une cote inchangée."""
    maintenant = datetime.now(timezone.utc)
    observed_at = maintenant.strftime("%Y-%m-%d %H:%M:%S")
    # Résolution à la microseconde : deux passes dans la même seconde
    # (relance manuelle, agent qui se déclenche deux fois) violaient sinon la
    # clé primaire de collecte_run et faisaient échouer la collecte.
    run_id = maintenant.strftime("%Y%m%dT%H%M%S.%fZ")

    con = _connexion(chemin_bdd)
    connu = _derniere_cote(con)
    total_vu = total_ecrit = 0
    matchs = set()
    erreurs = []

    for flux, url in FLUX.items():
        try:
            d = _normaliser(_lire_flux(url), flux)
        except Exception as e:                      # réseau, format, parsing
            erreurs.append(f"{flux}: {e}")
            if verbose:
                print(f"  {flux:6s} ERREUR {e}")
            continue
        if len(d) == 0:
            if verbose:
                print(f"  {flux:6s} aucune cote exploitable")
            continue

        total_vu += len(d)
        matchs |= set(d.fixture_key)

        con.execute(
            "INSERT OR REPLACE INTO flux_etat VALUES (?,?,?,?,?,?)",
            (flux, _DERNIER_LAST_MODIFIED.get(url), observed_at, int(d.fixture_key.nunique()),
             str(d.kickoff.min())[:10], str(d.kickoff.max())[:10]),
        )
        d["observed_at"] = observed_at
        d["run_id"] = run_id

        change = [
            connu.get((k, b, m, s)) != o
            for k, b, m, s, o in
            zip(d.fixture_key, d.bookmaker, d.market, d.selection, d.odds)
        ]
        nouveau = d[change]
        nouveau = nouveau.assign(source="football-data", book_updated_at=pd.NA)
        if len(nouveau):
            nouveau[COLONNES_SNAPSHOT].to_sql(
                "odds_snapshot", con, if_exists="append", index=False)
        total_ecrit += len(nouveau)
        if verbose:
            print(f"  {flux:6s} {d.fixture_key.nunique():3d} matchs · "
                  f"{len(d):5d} cotes vues · {len(nouveau):5d} écrites "
                  f"({len(d)-len(nouveau)} inchangées)")

    # --- The Odds API, si configurée --------------------------------------
    credits = 0
    restants = None
    from odds import config
    if config.est_configure("ODDS_API_KEY"):
        try:
            v, e, credits, restants, errs = _collecter_oddsapi(
                con, observed_at, run_id, connu, verbose)
            total_vu += v
            total_ecrit += e
            erreurs.extend(errs)
        except Exception as exc:
            erreurs.append(f"oddsapi: {exc}")
            if verbose:
                print(f"  oddsapi  ERREUR {exc}")
    elif verbose:
        print("  oddsapi  non configurée (uv run odds config --init)")

    n_matchs = con.execute("SELECT COUNT(DISTINCT fixture_key) FROM odds_snapshot "
                           "WHERE run_id = ?", (run_id,)).fetchone()[0]
    con.execute(
        "INSERT INTO collecte_run (run_id, demarre_a, flux, matchs, lignes_vues, "
        "lignes_ecrites, erreur, credits_utilises, credits_restants) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (run_id, observed_at, ",".join(FLUX), max(len(matchs), n_matchs),
         total_vu, total_ecrit, "; ".join(erreurs) or None, credits,
         int(restants) if restants else None),
    )
    con.commit()
    con.close()
    return {"run_id": run_id, "observed_at": observed_at, "matchs": len(matchs),
            "vues": total_vu, "ecrites": total_ecrit, "erreurs": erreurs,
            "credits": credits, "credits_restants": restants}


def etat_flux(chemin_bdd: Path | None = None) -> pd.DataFrame:
    """Fraîcheur de chaque flux amont, et période qu'il couvre.

    Permet de distinguer « aucun match ce jour-là » de « la source n'a pas
    encore publié ». football-data met à jour ses fixtures deux fois par
    semaine environ ; entre deux publications, aucune date future n'apparaît.
    """
    con = _connexion(chemin_bdd)
    try:
        d = pd.read_sql("SELECT * FROM flux_etat", con)
    finally:
        con.close()
    if len(d) == 0:
        return d
    d["last_modified_dt"] = pd.to_datetime(d.last_modified, format="mixed",
                                           utc=True, errors="coerce")
    maintenant = pd.Timestamp.now(tz="UTC")
    d["age_heures"] = (maintenant - d.last_modified_dt).dt.total_seconds() / 3600
    # Deux publications par semaine : au-delà de ~4 jours, le flux est en retard.
    d["perime"] = d.age_heures > 96
    return d


def resume(chemin_bdd: Path | None = None) -> dict:
    con = _connexion(chemin_bdd)
    q = lambda s: con.execute(s).fetchone()
    n_lignes = q("SELECT COUNT(*) FROM odds_snapshot")[0]
    n_matchs = q("SELECT COUNT(DISTINCT fixture_key) FROM odds_snapshot")[0]
    n_runs = q("SELECT COUNT(*) FROM collecte_run")[0]
    bornes = q("SELECT MIN(observed_at), MAX(observed_at) FROM odds_snapshot")
    books = pd.read_sql(
        "SELECT bookmaker, COUNT(*) n, COUNT(DISTINCT fixture_key) matchs "
        "FROM odds_snapshot GROUP BY bookmaker ORDER BY n DESC", con)
    runs = pd.read_sql(
        "SELECT run_id, matchs, lignes_vues, lignes_ecrites, erreur "
        "FROM collecte_run ORDER BY demarre_a DESC LIMIT 10", con)
    con.close()
    return {"lignes": n_lignes, "matchs": n_matchs, "runs": n_runs,
            "depuis": bornes[0], "jusqua": bornes[1],
            "bookmakers": books, "derniers_runs": runs,
            "flux": etat_flux(chemin_bdd)}
