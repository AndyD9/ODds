"""Horodatages — un format par usage, et l'invariant qui les rend comparables.

Toutes les dates stockées sont en **UTC, sans fuseau**, écrites dans l'un de
ces trois formats, qui partagent le même préfixe :

    FORMAT_JOUR     2026-09-18             filtres par date
    FORMAT_MINUTE   2026-09-18 18:30       coups d'envoi
    FORMAT_SECONDE  2026-09-18 18:30:00    observations, règlements

Conséquence, sur laquelle plusieurs requêtes s'appuient : l'ordre
lexicographique de ces chaînes est l'ordre chronologique, y compris entre
formats. ``'2026-09-18 17:59:59' <= '2026-09-18 18:30'`` est vrai parce que
le préfixe commun tranche avant que la longueur ne compte. Un ``T``
séparateur ou un suffixe de fuseau casserait cet invariant : c'est pour ça
que ce module existe, et que personne n'appelle ``strftime`` ailleurs.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

FORMAT_JOUR = "%Y-%m-%d"
FORMAT_MINUTE = "%Y-%m-%d %H:%M"
FORMAT_SECONDE = "%Y-%m-%d %H:%M:%S"


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _utc(ts) -> datetime | pd.Timestamp:
    if ts is None:
        return maintenant()
    t = pd.Timestamp(ts)
    return t.tz_convert("UTC") if t.tzinfo is not None else t


def jour(ts=None) -> str:
    return _utc(ts).strftime(FORMAT_JOUR)


def minute(ts=None) -> str:
    return _utc(ts).strftime(FORMAT_MINUTE)


def seconde(ts=None) -> str:
    return _utc(ts).strftime(FORMAT_SECONDE)


def serie_en_minutes(s: pd.Series) -> pd.Series:
    """Colonne de dates (avec ou sans fuseau) -> chaînes FORMAT_MINUTE en UTC."""
    t = pd.to_datetime(s, utc=True, errors="coerce")
    return t.dt.tz_convert(None).dt.strftime(FORMAT_MINUTE)


def serie_en_secondes(s: pd.Series) -> pd.Series:
    t = pd.to_datetime(s, utc=True, errors="coerce")
    return t.dt.tz_convert(None).dt.strftime(FORMAT_SECONDE)
