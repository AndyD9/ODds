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
import sys
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
    "ODDS_API_MARKETS": ("Marchés", False, "h2h,totals"),
    "ODDS_API_BUDGET_JOUR": ("Budget de crédits par jour", False, "14"),
    "COMMISSION_EXCHANGE": ("Commission des bourses d'échange, en % du gain "
                            "net (vide = taux par défaut de chaque bourse)",
                            False, None),
    # --- hébergement (decisions/0009) — tout facultatif : vide = mode local
    "SUPABASE_URL": ("URL du projet Supabase (copie distante de l'état)", False, None),
    "SUPABASE_SERVICE_KEY": ("Clé de service Supabase", True, None),
    "SUPABASE_BUCKET": ("Seau Storage qui reçoit les fichiers d'état", False, "etat"),
    "ODDS_INVITES": ("Invités de l'application hébergée : paires nom:clé séparées "
                     "par des virgules (hébergé : section [invites] des secrets)",
                     True, None),
    "ODDS_PROPRIETAIRE": ("Nom d'utilisateur du propriétaire : son carnet est le "
                          "carnet local historique", False, None),
    "ODDS_URL": ("Adresse publique de l'application, pour composer les liens "
                 "d'invitation", False, None),
}


# Secrets masqués à l'affichage mais dont l'absence n'est pas un manque : sans
# eux, l'outil tourne en mode local (decisions/0009).
SECRETS_FACULTATIFS = {"SUPABASE_SERVICE_KEY", "ODDS_INVITES"}


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


def _secrets_streamlit():
    """Le coffre ``st.secrets``, seulement si Streamlit est déjà chargé.

    Sur Community Cloud la configuration vit dans ``st.secrets``, pas dans
    un .env. On ne l'importe jamais pour autant depuis la CLI : le module
    n'est consulté que s'il est déjà en mémoire, donc depuis l'application.
    Sans fichier de secrets, ``st.secrets`` lève ; c'est « rien ».

    Point de passage unique — les tests le neutralisent ici, et ici
    seulement : ce module vit hors du dossier de l'application, que le
    harnais de Streamlit réimporte à chaque exécution.
    """
    st = sys.modules.get("streamlit")
    if st is None:
        return None
    try:
        return st.secrets
    except Exception:
        return None


def _depuis_secrets(cle: str) -> str | None:
    coffre = _secrets_streamlit()
    if coffre is None:
        return None
    try:
        val = coffre.get(cle)
    except Exception:
        return None
    return str(val) if val not in (None, "") else None


def section_secrets(nom: str) -> dict:
    """Une section ``[nom]`` des secrets Streamlit, en dictionnaire. Vide sinon."""
    coffre = _secrets_streamlit()
    if coffre is None:
        return {}
    try:
        section = coffre.get(nom)
    except Exception:
        return {}
    return dict(section) if section else {}


def diagnostic_secrets() -> str:
    """Ce que l'application arrive à lire des secrets Streamlit — noms seulement.

    Jamais une valeur : cette phrase s'affiche à l'écran. Trois issues :
    Streamlit absent, lecture impossible (et pourquoi — une valeur sans
    guillemets suffit à invalider tout le fichier), ou la liste des clés
    de premier niveau et des sections trouvées.
    """
    st = sys.modules.get("streamlit")
    if st is None:
        return "Streamlit n'est pas chargé : pas de secrets."
    try:
        contenu = st.secrets.to_dict()
    except Exception as e:                    # noqa: BLE001 — c'est le message qu'on veut
        return f"lecture des secrets impossible — {type(e).__name__} : {str(e)[:300]}"
    if not contenu:
        return "secrets lus, mais vides."
    cles = sorted(k for k, v in contenu.items() if not isinstance(v, dict))
    sections = sorted(k for k, v in contenu.items() if isinstance(v, dict))
    return ("secrets lus — clés : " + (", ".join(cles) or "aucune")
            + " ; sections : " + (", ".join(f"[{s}]" for s in sections) or "aucune"))


def get(cle: str, defaut: str | None = None) -> str | None:
    """Environnement du processus, puis .env, puis secrets Streamlit, puis défaut."""
    val = os.environ.get(cle) or _depuis_fichier().get(cle) or _depuis_secrets(cle)
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
        brut = os.environ.get(cle) or fichier.get(cle) or _depuis_secrets(cle)
        origine = ("environnement" if os.environ.get(cle)
                   else "fichier .env" if fichier.get(cle)
                   else "secrets Streamlit" if _depuis_secrets(cle)
                   else "défaut")
        val = get(cle)
        requis = secret and cle not in SECRETS_FACULTATIFS
        affiche = ("(non renseigné)" if not brut and secret
                   else _masquer(brut) if (brut and secret)
                   else val or "(non réglé)")
        # Un réglage facultatif sans valeur n'est pas « manquant » : il a un
        # comportement par défaut, décrit dans .env.example. Seul un secret
        # requis peut manquer.
        out.append({"réglage": cle, "description": desc, "valeur": affiche,
                    "origine": origine, "requis": requis,
                    "ok": bool(val) or not requis})
    return out


def cout_par_passe() -> int:
    """Crédits consommés par une passe complète, d'après la configuration.

    Le tarif The Odds API est de 1 crédit par championnat, par marché et par
    région. /events et /sports sont gratuits.
    """
    return (max(1, len(get_liste("ODDS_API_SPORTS")))
            * max(1, len(get_liste("ODDS_API_MARKETS")))
            * max(1, len(get_liste("ODDS_API_REGIONS"))))
