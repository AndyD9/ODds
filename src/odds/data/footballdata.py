"""Chargement des données football-data.co.uk.

Source retenue pour l'étape 1 (PLAN §7.2, option A actée). Deux formats
distincts, normalisés vers un schéma unique :

- fichiers "main"  : un CSV par (championnat, saison), ~120 colonnes,
                     grands championnats européens ;
- fichiers "extra" : un CSV par pays, toutes saisons, 25 colonnes,
                     petits championnats — ceux de PLAN §2.

Les deux formats portent les cotes de CLÔTURE Pinnacle (PSCH/PSCD/PSCA),
ce qui permet de tester H2 (petits championnats) contre exactement le même
benchmark que les grands (prereg 0001, §6).

IMPORTANT : aucun repli silencieux d'une source de cotes vers une autre. La
colonne ``odds_source`` enregistre l'origine de chaque ligne. L'analyse
primaire n'utilise que les lignes Pinnacle (prereg 0001, §1).
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pandas as pd
import requests

BASE_MAIN = "https://www.football-data.co.uk/mmz4281"
BASE_EXTRA = "https://www.football-data.co.uk/new"

CACHE = Path(__file__).resolve().parents[3] / "research" / "data" / "raw"

# --- championnats -----------------------------------------------------------
# code -> (pays, nom, niveau)
LEAGUES_MAIN = {
    "E0": ("England", "Premier League", 1),
    "E1": ("England", "Championship", 2),
    "E2": ("England", "League One", 3),
    "E3": ("England", "League Two", 4),
    "SC0": ("Scotland", "Premiership", 1),
    "SC1": ("Scotland", "Championship", 2),
    "D1": ("Germany", "Bundesliga", 1),
    "D2": ("Germany", "2. Bundesliga", 2),
    "I1": ("Italy", "Serie A", 1),
    "I2": ("Italy", "Serie B", 2),
    "SP1": ("Spain", "La Liga", 1),
    "SP2": ("Spain", "Segunda", 2),
    "F1": ("France", "Ligue 1", 1),
    "F2": ("France", "Ligue 2", 2),
    "N1": ("Netherlands", "Eredivisie", 1),
    "B1": ("Belgium", "Pro League", 1),
    "P1": ("Portugal", "Primeira Liga", 1),
    "T1": ("Turkey", "Super Lig", 1),
    "G1": ("Greece", "Super League", 1),
}

# Les "extra" : exactement les championnats visés en PLAN §2 / §22.
LEAGUES_EXTRA = {
    "DNK": ("Denmark", "Superliga"),
    "SWE": ("Sweden", "Allsvenskan"),
    "NOR": ("Norway", "Eliteserien"),
    "FIN": ("Finland", "Veikkausliiga"),
    "AUT": ("Austria", "Bundesliga"),
    "SWZ": ("Switzerland", "Super League"),
    "POL": ("Poland", "Ekstraklasa"),
    "ROU": ("Romania", "Liga I"),
    "IRL": ("Ireland", "Premier Division"),
    "CHN": ("China", "Super League"),
    "JPN": ("Japan", "J1 League"),
    "MEX": ("Mexico", "Liga MX"),
    "USA": ("USA", "MLS"),
    "BRA": ("Brazil", "Serie A"),
    "ARG": ("Argentina", "Primera Division"),
    "RUS": ("Russia", "Premier League"),
}

SEASONS_MAIN = [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(2012, 2027)]

SCHEMA = [
    "date", "country", "league", "league_code", "season", "tier",
    "home_team", "away_team", "home_goals", "away_goals", "result",
    "psc_h", "psc_d", "psc_a", "ps_h", "ps_d", "ps_a",
    "avgc_h", "avgc_d", "avgc_a",
    "maxc_h", "maxc_d", "maxc_a", "odds_source", "source_file",
]


def _fetch(url: str, dest: Path, pause: float = 0.3) -> bytes | None:
    """Télécharge avec cache disque. Renvoie None si la ressource n'existe pas."""
    if dest.exists():
        return dest.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, timeout=60)
    time.sleep(pause)
    if resp.status_code == 404 or len(resp.content) < 200:
        return None
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return resp.content


def _read_csv(raw: bytes) -> pd.DataFrame:
    """Lit un CSV football-data : encodage latin-1, BOM possible, lignes vides."""
    df = pd.read_csv(
        io.BytesIO(raw), encoding="latin-1", on_bad_lines="skip", low_memory=False
    )
    df.columns = [c.lstrip("﻿").replace("\xef\xbb\xbf", "").strip() for c in df.columns]
    return df


def _parse_dates(s: pd.Series) -> pd.Series:
    """dd/mm/yy et dd/mm/yyyy coexistent dans les fichiers."""
    out = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    manque = out.isna()
    if manque.any():
        out.loc[manque] = pd.to_datetime(
            s[manque], format="%d/%m/%y", errors="coerce"
        )
    manque = out.isna()
    if manque.any():
        out.loc[manque] = pd.to_datetime(s[manque], dayfirst=True, errors="coerce")
    return out


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    return pd.to_numeric(df[name], errors="coerce") if name in df.columns else pd.Series(
        [pd.NA] * len(df), dtype="Float64"
    )


def _finalise(out: pd.DataFrame) -> pd.DataFrame:
    """Qualifie la source de cotes et nettoie."""
    pinnacle = out[["psc_h", "psc_d", "psc_a"]].notna().all(axis=1)
    marche = out[["avgc_h", "avgc_d", "avgc_a"]].notna().all(axis=1)
    out["odds_source"] = pd.NA
    out.loc[marche, "odds_source"] = "market_avg_closing"
    out.loc[pinnacle, "odds_source"] = "pinnacle_closing"

    out = out[out["date"].notna()]
    out = out[out["home_goals"].notna() & out["away_goals"].notna()]
    for c in ("home_goals", "away_goals"):
        out[c] = out[c].astype(int)
    out = out[out["result"].isin(["H", "D", "A"])]
    return out[SCHEMA].sort_values("date").reset_index(drop=True)


def load_main(code: str, season: str) -> pd.DataFrame | None:
    """Un championnat principal, une saison."""
    raw = _fetch(f"{BASE_MAIN}/{season}/{code}.csv", CACHE / "main" / f"{code}_{season}.csv")
    if raw is None:
        return None
    df = _read_csv(raw)
    if "HomeTeam" not in df.columns:
        return None
    country, league, tier = LEAGUES_MAIN[code]
    out = pd.DataFrame(
        {
            "date": _parse_dates(df["Date"]),
            "country": country,
            "league": league,
            "league_code": code,
            "season": f"20{season[:2]}-{season[2:]}",
            "tier": tier,
            "home_team": df["HomeTeam"].astype("string").str.strip(),
            "away_team": df["AwayTeam"].astype("string").str.strip(),
            "home_goals": _col(df, "FTHG"),
            "away_goals": _col(df, "FTAG"),
            "result": df.get("FTR", pd.Series([pd.NA] * len(df))).astype("string"),
            "psc_h": _col(df, "PSCH"), "psc_d": _col(df, "PSCD"), "psc_a": _col(df, "PSCA"),
            # cote PRECOCE (relevé de milieu de semaine), pas l'ouverture stricte
            "ps_h": _col(df, "PSH"), "ps_d": _col(df, "PSD"), "ps_a": _col(df, "PSA"),
            "avgc_h": _col(df, "AvgCH"), "avgc_d": _col(df, "AvgCD"), "avgc_a": _col(df, "AvgCA"),
            "maxc_h": _col(df, "MaxCH"), "maxc_d": _col(df, "MaxCD"), "maxc_a": _col(df, "MaxCA"),
            "odds_source": pd.NA,
            "source_file": f"main/{code}_{season}",
        }
    )
    return _finalise(out)


def load_extra(code: str) -> pd.DataFrame | None:
    """Un championnat "extra", toutes saisons dans un seul fichier."""
    raw = _fetch(f"{BASE_EXTRA}/{code}.csv", CACHE / "extra" / f"{code}.csv")
    if raw is None:
        return None
    df = _read_csv(raw)
    if "Home" not in df.columns:
        return None
    country, league = LEAGUES_EXTRA[code]
    out = pd.DataFrame(
        {
            "date": _parse_dates(df["Date"]),
            "country": country,
            "league": (
                df["League"].astype("string").str.strip()
                if "League" in df
                else league
            ),
            "league_code": code,
            "season": df["Season"].astype("string"),
            "tier": 1,
            "home_team": df["Home"].astype("string").str.strip(),
            "away_team": df["Away"].astype("string").str.strip(),
            "home_goals": _col(df, "HG"),
            "away_goals": _col(df, "AG"),
            "result": df.get("Res", pd.Series([pd.NA] * len(df))).astype("string"),
            "psc_h": _col(df, "PSCH"), "psc_d": _col(df, "PSCD"), "psc_a": _col(df, "PSCA"),
            # les fichiers "extra" ne portent PAS de cote précoce
            "ps_h": _col(df, "PSH"), "ps_d": _col(df, "PSD"), "ps_a": _col(df, "PSA"),
            "avgc_h": _col(df, "AvgCH"), "avgc_d": _col(df, "AvgCD"), "avgc_a": _col(df, "AvgCA"),
            "maxc_h": _col(df, "MaxCH"), "maxc_d": _col(df, "MaxCD"), "maxc_a": _col(df, "MaxCA"),
            "odds_source": pd.NA,
            "source_file": f"extra/{code}",
        }
    )
    return _finalise(out)


def load_all(verbose: bool = True) -> pd.DataFrame:
    """Charge tout, met en cache, renvoie un DataFrame unique."""
    frames = []
    for code in LEAGUES_MAIN:
        for season in SEASONS_MAIN:
            d = load_main(code, season)
            if d is not None and len(d):
                frames.append(d)
        if verbose:
            n = sum(len(f) for f in frames)
            print(f"  main  {code:4s} cumul {n:6d} matchs", flush=True)
    for code in LEAGUES_EXTRA:
        d = load_extra(code)
        if d is not None and len(d):
            frames.append(d)
            if verbose:
                print(f"  extra {code:4s} {len(d):6d} matchs", flush=True)
    return pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)
