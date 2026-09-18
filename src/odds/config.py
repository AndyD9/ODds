"""Configuration locale, lue depuis .env.

Volontairement sans dépendance : le format .env est trivial et n'en justifie
pas une.

Règles de sûreté appliquées ici :

- une valeur déjà présente dans l'environnement du processus l'emporte sur
  le fichier (permet de surcharger ponctuellement sans éditer .env) ;
- ``resume()`` ne renvoie JAMAIS une clé en clair, seulement un masque ;
- rien dans ce module n'écrit une valeur secrète dans un log.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
FICHIER_ENV = RACINE / ".env"
FICHIER_EXEMPLE = RACINE / ".env.example"

# clé -> (description, secret ?, valeur par défaut)
REGLAGES = {
    "ODDS_API_KEY": ("Clé The Odds API", True, None),
    "ODDS_API_SPORTS": ("Championnats interrogés", False,
                        "soccer_epl,soccer_france_ligue_one,soccer_spain_la_liga,"
                        "soccer_italy_serie_a,soccer_germany_bundesliga"),
    "ODDS_API_REGIONS": ("Région des bookmakers", False, "eu"),
    "ODDS_API_MARKETS": ("Marchés", False, "h2h"),
    "ODDS_API_BUDGET_JOUR": ("Budget de crédits par jour", False, "14"),
}


def _parser(texte: str) -> dict[str, str]:
    out = {}
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, val = ligne.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[cle.strip()] = val
    return out


@lru_cache(maxsize=1)
def _depuis_fichier() -> dict[str, str]:
    if not FICHIER_ENV.exists():
        return {}
    return _parser(FICHIER_ENV.read_text(encoding="utf-8"))


def recharger() -> None:
    """À appeler après modification de .env dans un processus long."""
    _depuis_fichier.cache_clear()


def get(cle: str, defaut: str | None = None) -> str | None:
    """Environnement du processus, puis .env, puis valeur par défaut."""
    val = os.environ.get(cle) or _depuis_fichier().get(cle)
    if val:
        return val
    if defaut is not None:
        return defaut
    reglage = REGLAGES.get(cle)
    return reglage[2] if reglage else None


def get_liste(cle: str) -> list[str]:
    v = get(cle) or ""
    return [x.strip() for x in v.split(",") if x.strip()]


def est_configure(cle: str) -> bool:
    return bool(get(cle))


def _masquer(valeur: str) -> str:
    if len(valeur) <= 8:
        return "*" * len(valeur)
    return f"{valeur[:4]}{'*' * (len(valeur) - 8)}{valeur[-4:]}"


def resume() -> list[dict]:
    """État de la configuration. Les secrets sont masqués, jamais renvoyés."""
    out = []
    fichier = _depuis_fichier()
    for cle, (desc, secret, _) in REGLAGES.items():
        brut = os.environ.get(cle) or fichier.get(cle)
        origine = ("environnement" if os.environ.get(cle)
                   else "fichier .env" if fichier.get(cle)
                   else "défaut")
        val = get(cle)
        affiche = ("(non renseigné)" if not brut and secret
                   else _masquer(brut) if (brut and secret)
                   else val or "(vide)")
        out.append({"réglage": cle, "description": desc, "valeur": affiche,
                    "origine": origine, "requis": secret, "ok": bool(val)})
    return out


def cout_par_passe() -> int:
    """Crédits consommés par une passe complète, d'après la configuration.

    Le tarif The Odds API est de 1 crédit par championnat, par marché et par
    région. /events et /sports sont gratuits.
    """
    return (max(1, len(get_liste("ODDS_API_SPORTS")))
            * max(1, len(get_liste("ODDS_API_MARKETS")))
            * max(1, len(get_liste("ODDS_API_REGIONS"))))
