"""État partagé — les fichiers d'état, copiés dans un seau Supabase Storage.

L'application hébergée (Streamlit Community Cloud) tourne sur un disque qui
ne survit pas à un redémarrage. Les deux bases de ``chemins.ETAT`` sont
pourtant ce qu'on ne peut pas reconstituer. Plutôt que de réécrire chaque
requête pour Postgres, on garde SQLite comme **format** et on en fait une
copie distante, fichier entier, à chaque écriture :

- au démarrage, ``demarrer()`` ramène les fichiers absents ou périmés ;
- après chaque écriture au carnet, ``paper`` appelle ``publier`` ;
- le collecteur, qui tourne ailleurs (GitHub Actions), tire la base de
  collecte avant sa passe et la pousse après ; l'application la rafraîchit
  quand l'empreinte distante change (``rafraichir``).

Ce qui rend l'approche tenable, et qui est écrit dans decisions/0009 :
**une seule instance écrit chaque fichier**. L'application écrit le carnet
et lui seul ; le collecteur écrit la base de collecte et elle seule. Une
deuxième instance de l'application ferait perdre des écritures ; c'est le
premier motif pour passer à Postgres.

Sans ``SUPABASE_URL`` et ``SUPABASE_SERVICE_KEY``, tout ici est inerte :
``actif()`` est faux, ``publier`` et ``rafraichir`` ne font rien. C'est le
mode local, et celui des tests.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

from odds import chemins, config

log = logging.getLogger(__name__)

#: fichiers d'état et dérivés lourds à copier, par nom distant.
FICHIERS: dict[str, Path] = {
    "paper.db": chemins.BASE_PARIS,
    "odds_history.db": chemins.BDD_COLLECTE,
    # Dérivés : régénérables par ``odds ingest``, mais l'ingestion retélécharge
    # 150 000 matchs — on n'inflige pas ça à chaque réveil de l'application.
    "matches.parquet": chemins.PARQUET,
    "fiabilite_buts.parquet": chemins.FIABILITE_BUTS,
}

#: empreintes distantes connues, pour ne télécharger qu'un fichier qui a changé.
EMPREINTES = chemins.ETAT / ".etat-distant.json"

DELAI = 60  # secondes — un fichier de quelques Mo sur une liaison lente


def actif() -> bool:
    return bool(config.get("SUPABASE_URL") and config.get("SUPABASE_SERVICE_KEY"))


def _seau() -> str:
    return config.get("SUPABASE_BUCKET") or "etat"


def _url(*parties: str) -> str:
    base = (config.get("SUPABASE_URL") or "").rstrip("/")
    return "/".join([base, "storage/v1"] + [p.strip("/") for p in parties])


def _entetes() -> dict[str, str]:
    cle = config.get("SUPABASE_SERVICE_KEY") or ""
    return {"Authorization": f"Bearer {cle}", "apikey": cle}


def _requete(methode: str, url: str, **kw) -> requests.Response:
    """Seul point de sortie réseau du module — les tests le bloquent ici."""
    r = requests.request(methode, url, headers={**_entetes(), **kw.pop("headers", {})},
                         timeout=DELAI, **kw)
    r.raise_for_status()
    return r


def _lire_empreintes() -> dict[str, str]:
    try:
        return json.loads(EMPREINTES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _ecrire_empreinte(nom: str, empreinte: str | None) -> None:
    e = _lire_empreintes()
    if empreinte is None:
        e.pop(nom, None)
    else:
        e[nom] = empreinte
    EMPREINTES.parent.mkdir(parents=True, exist_ok=True)
    EMPREINTES.write_text(json.dumps(e, indent=1, sort_keys=True), encoding="utf-8")


def distants() -> dict[str, str]:
    """Empreinte (ETag) de chaque fichier présent dans le seau."""
    r = _requete("POST", _url("object/list", _seau()),
                 json={"prefix": "", "limit": 100, "offset": 0})
    out = {}
    for objet in r.json():
        meta = objet.get("metadata") or {}
        empreinte = meta.get("eTag") or objet.get("updated_at") or ""
        out[objet["name"]] = str(empreinte).strip('"')
    return out


def publier(chemin: Path, nom: str | None = None) -> bool:
    """Copie ``chemin`` dans le seau, en remplaçant la version distante.

    Renvoie vrai si une copie a eu lieu. Inerte sans configuration, et
    silencieux sur un fichier absent : publier un carnet qui n'existe pas
    encore n'a pas de sens.
    """
    if not actif():
        return False
    chemin = Path(chemin)
    if not chemin.exists():
        return False
    nom = nom or chemin.name
    _requete("POST", _url("object", _seau(), nom), data=chemin.read_bytes(),
             headers={"Content-Type": "application/octet-stream", "x-upsert": "true"})
    try:
        _ecrire_empreinte(nom, distants().get(nom))
    except requests.RequestException as e:      # la copie est faite ; l'empreinte attendra
        log.warning("empreinte distante non relue après publication de %s : %s", nom, e)
    return True


def rafraichir(chemin: Path, nom: str | None = None, force: bool = False) -> bool:
    """Ramène la version distante si elle a changé depuis la dernière fois.

    Renvoie vrai si le fichier local a été remplacé. Un fichier absent du
    seau ne remplace jamais un fichier local : c'est le cas d'une première
    mise en service, où c'est le local qui a raison.
    """
    if not actif():
        return False
    chemin = Path(chemin)
    nom = nom or chemin.name
    empreinte = distants().get(nom)
    if empreinte is None:
        return False
    if not force and chemin.exists() and _lire_empreintes().get(nom) == empreinte:
        return False
    r = _requete("GET", _url("object/authenticated", _seau(), nom))
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_name(chemin.name + ".part")
    provisoire.write_bytes(r.content)
    provisoire.replace(chemin)       # atomique : jamais de base à moitié écrite
    _ecrire_empreinte(nom, empreinte)
    return True


def demarrer() -> list[str]:
    """Au réveil d'une instance : ramène chaque fichier connu s'il a changé.

    Renvoie les noms remplacés. Inerte sans configuration.
    """
    if not actif():
        return []
    remplaces = []
    for nom, chemin in FICHIERS.items():
        if rafraichir(chemin, nom):
            remplaces.append(nom)
    return remplaces


def pousser_tout() -> list[str]:
    """Première mise en service : pousse tout ce qui existe en local."""
    return [nom for nom, chemin in FICHIERS.items() if publier(chemin, nom)]
