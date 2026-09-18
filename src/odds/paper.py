"""Carnet de paris papier et moteur de mise — prereg 0001 §4 et §5.

Le pré-enregistrement 0001 §5 fixe le mode d'exploitation : **papier
uniquement**, et exige que « le moteur de staking tourne intégralement en
mode papier : mêmes calculs, mêmes plafonds, même suivi de bankroll
simulée. Seul le passage d'ordre est absent. » Ce module est ce moteur.

Ce qu'il fait, et pourquoi c'est construit ainsi :

- **Les valeurs de §4 sont des constantes, pas des paramètres.** ``F_BASE``,
  les plafonds et le seuil de drawdown ont été fixés avant tout résultat.
  Les rendre réglables depuis l'interface reviendrait à les choisir après
  coup, ce que le pré-enregistrement existe précisément pour empêcher.

- **La mise est une proposition, jamais une décision.** L'utilisateur peut
  la modifier ; l'écart entre proposé et misé est conservé
  (``mise_proposee``), sans quoi le suivi mesurerait un moteur qui n'a pas
  été suivi.

- **Le règlement est manuel.** Les noms d'équipe diffèrent entre The Odds
  API et football-data ; ``analysis.py`` refuse déjà de les rapprocher, et
  un règlement approximatif inscrirait des gains faux dans un historique
  destiné à trancher une question. La saisie est un peu de travail, elle ne
  ment pas.

- **Le CLV, lui, est automatique.** Il ne demande aucun résultat : notre
  propre collecte horaire fournit la dernière cote observée avant le coup
  d'envoi. C'est le critère que §5 exige pour autoriser une mise réelle,
  et le seul qui soit lisible sur quelques dizaines de paris.

La base des paris est **distincte** de ``odds_history.db``. Cette dernière
est un cache reconstructible ; le carnet, non. Les mélanger ferait qu'un
« j'efface et je recollecte » détruirait l'historique de décisions.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from odds.models.football import buts

RACINE = Path(__file__).resolve().parents[2]
BASE_PARIS = RACINE / "research" / "data" / "paper.db"
BDD_COLLECTE = RACINE / "research" / "data" / "odds_history.db"

# ---------------------------------------------------------------------------
# prereg 0001 §4 — figé le 2026-09-18, avant tout résultat
# ---------------------------------------------------------------------------
F_BASE = 0.10
PLAFOND_MATCH = 0.01        # 1 % de bankroll par match
PLAFOND_EXPOSITION = 0.05   # 5 % de bankroll en simultané
DRAWDOWN_REEXAMEN = 0.20    # 20 % → arrêt et audit

# prereg 0001 §2 — aucune affirmation sur le ROI sous ce seuil.
N_MIN_ROI = 20_000

BANKROLL_DEFAUT = 1000.0

ISSUES = ("1", "N", "2")
LIBELLES = {"1": "Domicile", "N": "Nul", "2": "Extérieur"}

# Le carnet accepte tout marché du catalogue : 1X2, total du match, total par
# équipe, les deux équipes marquent. La colonne ``issue`` porte le CODE du
# marché (``"1"``, ``"total_over_2.5"``, ``"dom_over_1.5"``…) et ``marche``
# sa famille, pour regrouper sans réanalyser la chaîne.
CODES = tuple(buts.MARCHES)


def libelle(code: str, dom: str = "Domicile", ext: str = "Extérieur") -> str:
    """Libellé lisible d'un pari, noms d'équipe compris."""
    return buts.marche(code).pour(dom, ext)

# Ordre de préférence pour la cote de clôture servant au CLV. Les deux
# premiers sont des bourses d'échange — un prix réellement négociable, donc
# le seul substitut sérieux à Pinnacle (data/collect.py). Les noms diffèrent
# selon la source : ``betfair_ex_eu`` vient de The Odds API,
# ``betfair_exchange`` de football-data.
BENCHMARKS_CLOTURE = ("betfair_ex_eu", "betfair_exchange", "pinnacle",
                      "matchbook", "_moyenne_marche")

SELECTION = {"1": "home", "N": "draw", "2": "away"}


def selections_collectees(code: str) -> tuple[tuple[str, str], ...]:
    """Où retrouver ce marché dans la base de collecte, par ordre de préférence.

    Les deux sources ne nomment pas les totaux pareil : The Odds API écrit
    ``market='totals', selection='over_2.5'``, football-data écrit
    ``market='OU25', selection='over'`` et ne publie que la ligne 2,5.

    Renvoie un tuple vide pour les marchés qu'on ne collecte pas — totaux par
    équipe et BTTS, qui sont des marchés additionnels réservés aux offres
    payantes. Ces paris n'auront donc **pas de CLV**, et c'est une limite à
    afficher plutôt qu'à masquer : le CLV est le seul critère lisible sur
    quelques dizaines de paris (prereg §5), et il manquera précisément là où
    la probabilité est dérivée plutôt que lue.
    """
    if code in SELECTION:
        return (("1X2", SELECTION[code]),)
    morceaux = code.split("_")
    if len(morceaux) == 3 and morceaux[0] == "total":
        sens, ligne = morceaux[1], morceaux[2]
        paires = [("totals", f"{sens}_{ligne}")]
        if ligne == "2.5":
            paires.append(("OU25", sens))
        return tuple(paires)
    return ()


# ===========================================================================
# Moteur de mise
# ===========================================================================

def kelly(p: float, cote: float) -> float:
    """Fraction de Kelly complète : ``(p × cote − 1) / (cote − 1)``.

    Négative quand le prix est au niveau du prix juste ou en dessous : à ce
    prix, miser a une espérance nulle ou négative. Le signe est conservé tel
    quel — le tronquer à zéro ici masquerait l'information qui justifie de
    ne pas miser.
    """
    if cote <= 1.0:
        raise ValueError(f"cote invalide : {cote!r} (doit être > 1)")
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"probabilité invalide : {p!r}")
    return (p * cote - 1.0) / (cote - 1.0)


# Version de la fonction confiance() de prereg §4.
#
# ATTENTION — le pré-enregistrement exige que cette fonction soit « définie
# et versionnée AVANT le premier backtest avec staking ». Elle l'est ici,
# mais elle n'a pas encore de ligne dans prereg/0001. Tant que c'est le cas,
# elle vaut pour le suivi papier et ne peut justifier aucune affirmation.
CONFIANCE_VERSION = "v2-2026-09-18"

# Seuils repris de règles déjà fixées ailleurs, pour ne pas en inventer :
# 2 000 est le N_min d'affichage d'une cellule (prereg §2), 6 le nombre de
# bookmakers en deçà duquel analysis.py juge le consensus indigent.
CONFIANCE_N_HIST_PLEIN = 2_000
CONFIANCE_N_BOOKS_PLEIN = 6
CONFIANCE_PENALITE_FRAGILE = 0.5

# v2 — pénalité appliquée quand la probabilité du pari n'est PAS lue sur un
# prix mais dérivée d'une matrice de score calée sur le seul 1X2.
#
# research/RESULTS.md R9 mesure l'écart entre probabilité annoncée et
# fréquence observée : 0,7 point quand une cote de totaux contraint la
# matrice, 2 à 3 points quand elle est dérivée du 1X2 seul, avec un biais
# résiduel. La dégradation est réelle et mesurée ; le COEFFICIENT, lui, est
# une convention — celle déjà retenue pour un écart non robuste à la méthode
# de dévig, faute d'une façon défendable d'en dériver une autre.
CONFIANCE_PENALITE_DERIVEE = 0.5


def confiance(n_hist: int | None = None, n_books: int | None = None,
              ev_robuste: bool | None = None,
              p_cotee: bool | None = None) -> dict:
    """Facteur de confiance de prereg §4, décomposé.

    §4 la définit comme ``confiance(n, data_quality, incertitude_modèle)``
    sans en fixer la forme. Voici la forme retenue, en trois facteurs
    multiplicatifs dans [0, 1] :

    - ``n``  — taille de l'échantillon historique derrière la tranche de
      probabilité du pari, rapportée au N_min d'affichage de §2 ;
    - ``data_quality`` — nombre de bookmakers au consensus, rapporté au
      seuil d'indigence d'``analysis.py`` ;
    - ``incertitude`` — l'écart change-t-il de signe selon la méthode de
      dévig ? Si oui, il mesure le choix de méthode et non le marché
      (research/RESULTS.md R3) : la confiance est divisée par deux ;
    - ``source`` (v2) — la probabilité est-elle lue sur un prix, ou dérivée
      d'une matrice calée sur le seul 1X2 ? Dans le second cas la
      calibration mesurée se dégrade de 0,7 à 2-3 points (R9) et la
      confiance est divisée par deux.

    Un signal absent vaut 1 : on ne pénalise pas ce qu'on n'a pas mesuré.
    """
    f_n = 1.0 if n_hist is None else min(1.0, max(0.0, n_hist / CONFIANCE_N_HIST_PLEIN))
    f_books = (1.0 if n_books is None
               else min(1.0, max(0.0, n_books / CONFIANCE_N_BOOKS_PLEIN)))
    f_robuste = CONFIANCE_PENALITE_FRAGILE if ev_robuste is False else 1.0
    f_source = CONFIANCE_PENALITE_DERIVEE if p_cotee is False else 1.0
    return {"n": f_n, "data_quality": f_books, "incertitude": f_robuste,
            "source": f_source,
            "confiance": f_n * f_books * f_robuste * f_source,
            "version": CONFIANCE_VERSION}


def proposer_mise(bankroll: float, p: float, cote: float,
                  exposition: float = 0.0, **signaux) -> dict:
    """Mise proposée par prereg §4, avec la trace de ce qui l'a bornée.

    ``exposition`` est la somme des mises déjà engagées et non encore
    réglées : le plafond de 5 % porte sur l'exposition *simultanée*, il ne
    peut donc pas se calculer pari par pari.
    """
    if bankroll <= 0:
        return {"kelly": 0.0, "confiance": 0.0, "f_effectif": 0.0,
                "mise_theorique": 0.0, "mise": 0.0,
                "plafond": "bankroll", "motif": "Bankroll épuisée."}

    k = kelly(p, cote)
    c = confiance(**{x: signaux.get(x) for x in
                     ("n_hist", "n_books", "ev_robuste", "p_cotee")})
    f_effectif = F_BASE * c["confiance"]
    theorique = bankroll * k * f_effectif

    plafond_match = PLAFOND_MATCH * bankroll
    reste_exposition = max(0.0, PLAFOND_EXPOSITION * bankroll - exposition)

    if k <= 0:
        mise, plafond = 0.0, "kelly"
        motif = ("À cette cote, le prix est au niveau du prix juste ou en "
                 "dessous : l'espérance est nulle ou négative. Le moteur ne "
                 "propose rien.")
    elif theorique > plafond_match and plafond_match <= reste_exposition:
        mise, plafond = plafond_match, "match"
        motif = f"Plafonné à {100 * PLAFOND_MATCH:.0f} % de bankroll par match (§4)."
    elif theorique > reste_exposition:
        mise, plafond = reste_exposition, "exposition"
        motif = (f"Plafonné par l'exposition simultanée : "
                 f"{100 * PLAFOND_EXPOSITION:.0f} % de bankroll au total (§4).")
    else:
        mise, plafond = theorique, None
        motif = "Kelly fractionnaire, sous les deux plafonds."

    return {"kelly": k, "confiance": c["confiance"], "detail_confiance": c,
            "f_effectif": f_effectif, "mise_theorique": theorique,
            "mise": round(max(0.0, mise), 2), "plafond": plafond, "motif": motif}


# ===========================================================================
# Stockage
# ===========================================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS pari (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    place_a         TEXT NOT NULL,
    fixture_key     TEXT NOT NULL,
    source          TEXT,
    league          TEXT,
    kickoff         TEXT NOT NULL,
    home_team       TEXT NOT NULL,
    away_team       TEXT NOT NULL,
    issue           TEXT NOT NULL,
    marche          TEXT,
    cote            REAL NOT NULL,
    bookmaker       TEXT,
    p_modele        REAL NOT NULL,
    methode         TEXT,
    mise            REAL NOT NULL,
    mise_proposee   REAL,
    bankroll_avant  REAL,
    kelly           REAL,
    f_effectif      REAL,
    plafond         TEXT,
    cote_cloture    REAL,
    book_cloture    TEXT,
    resultat        TEXT,
    buts_dom        INTEGER,
    buts_ext        INTEGER,
    regle_a         TEXT,
    note            TEXT
);
CREATE INDEX IF NOT EXISTS idx_pari_match ON pari(fixture_key, issue);
CREATE INDEX IF NOT EXISTS idx_pari_kickoff ON pari(kickoff);

CREATE TABLE IF NOT EXISTS reglage (
    cle    TEXT PRIMARY KEY,
    valeur TEXT
);
"""


# Colonnes ajoutées avec l'ouverture aux marchés de buts. SQLite n'a pas de
# "ADD COLUMN IF NOT EXISTS" : on compare au schéma existant, comme dans
# data/collect.py.
MIGRATIONS = {"marche": "TEXT", "buts_dom": "INTEGER", "buts_ext": "INTEGER"}


def _migrer(con: sqlite3.Connection) -> None:
    """Amène un carnet existant au schéma courant, sans perte.

    Deux conversions, toutes deux irréversibles si on les rate — d'où leur
    caractère explicite :

    - ``marche`` est déduit du code déjà enregistré ; avant l'ouverture aux
      buts, tout pari était un 1X2 ;
    - ``resultat`` portait l'issue SURVENUE ("1", "N", "2") et se comparait
      au pari. Un score ne se compare pas ainsi : la colonne porte désormais
      le VERDICT ("gagne", "perdu", "annule"), calculé une fois pour toutes.
    """
    existantes = {r[1] for r in con.execute("PRAGMA table_info(pari)")}
    for nom, typ in MIGRATIONS.items():
        if nom not in existantes:
            con.execute(f"ALTER TABLE pari ADD COLUMN {nom} {typ}")

    con.execute("UPDATE pari SET marche = '1X2' WHERE marche IS NULL")
    con.execute("UPDATE pari SET resultat = CASE WHEN resultat = issue "
                "THEN 'gagne' ELSE 'perdu' END "
                "WHERE resultat IN ('1', 'N', '2')")
    con.commit()


def _connexion(chemin: Path | None = None) -> sqlite3.Connection:
    p = Path(chemin or BASE_PARIS)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.executescript(SCHEMA)
    _migrer(con)
    return con


def _maintenant() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def bankroll_initiale(chemin: Path | None = None) -> float:
    con = _connexion(chemin)
    try:
        r = con.execute("SELECT valeur FROM reglage WHERE cle = 'bankroll_initiale'"
                        ).fetchone()
    finally:
        con.close()
    return float(r[0]) if r else BANKROLL_DEFAUT


def definir_bankroll_initiale(montant: float, chemin: Path | None = None) -> None:
    if montant <= 0:
        raise ValueError("La bankroll initiale doit être strictement positive.")
    con = _connexion(chemin)
    try:
        con.execute("INSERT INTO reglage (cle, valeur) VALUES ('bankroll_initiale', ?) "
                    "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
                    (str(float(montant)),))
        con.commit()
    finally:
        con.close()


def enregistrer(fixture_key: str, kickoff: str, home_team: str, away_team: str,
                issue: str, cote: float, p_modele: float, mise: float,
                *, bookmaker: str | None = None, league: str | None = None,
                source: str | None = None, methode: str | None = None,
                mise_proposee: float | None = None,
                bankroll_avant: float | None = None,
                kelly_: float | None = None, f_effectif: float | None = None,
                plafond: str | None = None, note: str | None = None,
                chemin: Path | None = None) -> int:
    """Inscrit un pari papier. Renvoie son identifiant."""
    if issue not in buts.MARCHES:
        raise ValueError(
            f"marché invalide : {issue!r}. Attendu un code du catalogue "
            f"(1, N, 2, total_over_2.5, dom_over_1.5, btts_oui…)")
    if cote <= 1.0:
        raise ValueError(f"cote invalide : {cote!r} (doit être > 1)")
    if mise <= 0:
        raise ValueError(f"mise invalide : {mise!r} (doit être > 0)")

    con = _connexion(chemin)
    try:
        cur = con.execute(
            "INSERT INTO pari (place_a, fixture_key, source, league, kickoff, "
            "home_team, away_team, issue, marche, cote, bookmaker, p_modele, "
            "methode, mise, mise_proposee, bankroll_avant, kelly, f_effectif, "
            "plafond, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_maintenant(), fixture_key, source, league, kickoff, home_team,
             away_team, issue, buts.marche(issue).famille, float(cote),
             bookmaker, float(p_modele), methode, float(mise), mise_proposee,
             bankroll_avant, kelly_, f_effectif, plafond, note))
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


VERDICTS = ("gagne", "perdu", "annule")


def regler_match(fixture_key: str, buts_dom: int, buts_ext: int,
                 chemin: Path | None = None) -> int:
    """Règle TOUS les paris d'un match à partir du score. Renvoie leur nombre.

    C'est le seul point d'entrée du règlement, et c'est délibéré. Chaque
    marché sait lui-même s'il est gagné par un score donné
    (``buts.regler``), par le prédicat qui a servi à le coter. Saisir « 2–1 »
    une fois règle donc le 1X2, les totaux, les totaux par équipe et le BTTS
    sans qu'aucune règle ne soit réécrite ailleurs — et sans qu'un marché
    puisse être coté selon une définition et réglé selon une autre.

    Le score reste saisi à la main : les noms d'équipe diffèrent entre The
    Odds API et football-data, ``analysis.py`` refuse déjà de les rapprocher,
    et un règlement automatique approximatif inscrirait des gains faux dans
    un historique destiné à trancher une question.
    """
    buts_dom, buts_ext = int(buts_dom), int(buts_ext)
    if buts_dom < 0 or buts_ext < 0:
        raise ValueError(f"score invalide : {buts_dom}-{buts_ext}")

    con = _connexion(chemin)
    try:
        lignes = con.execute(
            "SELECT id, issue FROM pari WHERE fixture_key = ? AND resultat IS NULL",
            (fixture_key,)).fetchall()
        maintenant = _maintenant()
        for pari_id, code in lignes:
            verdict = "gagne" if buts.regler(code, buts_dom, buts_ext) else "perdu"
            con.execute(
                "UPDATE pari SET resultat = ?, buts_dom = ?, buts_ext = ?, "
                "regle_a = ? WHERE id = ?",
                (verdict, buts_dom, buts_ext, maintenant, int(pari_id)))
        con.commit()
        return len(lignes)
    finally:
        con.close()


def annuler_match(fixture_key: str, chemin: Path | None = None) -> int:
    """Match reporté : tous ses paris en attente sont remboursés."""
    con = _connexion(chemin)
    try:
        cur = con.execute(
            "UPDATE pari SET resultat = 'annule', regle_a = ? "
            "WHERE fixture_key = ? AND resultat IS NULL",
            (_maintenant(), fixture_key))
        con.commit()
        return int(cur.rowcount)
    finally:
        con.close()


def annuler(pari_id: int, chemin: Path | None = None) -> None:
    """Match reporté, pari remboursé : la mise revient, le profit est nul."""
    con = _connexion(chemin)
    try:
        cur = con.execute(
            "UPDATE pari SET resultat = 'annule', regle_a = ? WHERE id = ?",
            (_maintenant(), int(pari_id)))
        if cur.rowcount == 0:
            raise KeyError(f"pari {pari_id} introuvable")
        con.commit()
    finally:
        con.close()


def derregler(pari_id: int, chemin: Path | None = None) -> None:
    """Remet un pari en attente — pour corriger une saisie erronée."""
    con = _connexion(chemin)
    try:
        con.execute("UPDATE pari SET resultat = NULL, buts_dom = NULL, "
                    "buts_ext = NULL, regle_a = NULL WHERE id = ?",
                    (int(pari_id),))
        con.commit()
    finally:
        con.close()


def supprimer(pari_id: int, chemin: Path | None = None) -> None:
    con = _connexion(chemin)
    try:
        con.execute("DELETE FROM pari WHERE id = ?", (int(pari_id),))
        con.commit()
    finally:
        con.close()


# ===========================================================================
# Lecture et calculs dérivés
# ===========================================================================

def _derive(d: pd.DataFrame) -> pd.DataFrame:
    """Ajoute statut, retour, profit et CLV. Aucun accès disque."""
    if len(d) == 0:
        return d.assign(statut=pd.Series(dtype=str), retour=pd.Series(dtype=float),
                        profit=pd.Series(dtype=float), clv=pd.Series(dtype=float))

    # ``resultat`` porte le verdict, pas l'issue survenue : un score ne se
    # compare pas à un code de marché. Voir _migrer pour la conversion des
    # carnets antérieurs à l'ouverture aux marchés de buts.
    gagne = d.resultat.eq("gagne")
    annule = d.resultat.eq("annule")
    en_attente = d.resultat.isna()

    d = d.copy()
    d["statut"] = np.where(en_attente, "en attente",
                  np.where(annule, "annulé",
                  np.where(gagne, "gagné", "perdu")))
    # Un pari annulé est remboursé : la mise revient, le profit est nul.
    d["retour"] = np.where(en_attente, np.nan,
                  np.where(annule, d.mise,
                  np.where(gagne, d.mise * d.cote, 0.0)))
    d["profit"] = d.retour - d.mise

    # CLV : de combien le prix pris bat-il la clôture. Positif = on a pris
    # mieux que le marché final.
    with np.errstate(divide="ignore", invalid="ignore"):
        d["clv"] = np.where(d.cote_cloture.notna() & (d.cote_cloture > 0),
                            100.0 * (d.cote / d.cote_cloture - 1.0), np.nan)
    return d


def paris(chemin: Path | None = None, depuis=None, jusqua=None,
          statut: str | None = None) -> pd.DataFrame:
    """Le carnet, filtré sur la date de coup d'envoi."""
    con = _connexion(chemin)
    try:
        d = pd.read_sql("SELECT * FROM pari ORDER BY kickoff DESC, id DESC", con)
    finally:
        con.close()

    d = _derive(d)
    if len(d) == 0:
        return d
    jour = d.kickoff.str[:10]
    if depuis is not None:
        d = d[jour >= str(pd.Timestamp(depuis).date())]
    if jusqua is not None:
        d = d[jour <= str(pd.Timestamp(jusqua).date())]
    if statut is not None:
        d = d[d.statut == statut]
    return d.reset_index(drop=True)


def bankroll(chemin: Path | None = None) -> dict:
    """État de la bankroll simulée, plafonds de §4 compris.

    ``pic`` et ``drawdown`` sont calculés sur la suite des paris réglés dans
    l'ordre de règlement : c'est la seule séquence où la bankroll a
    réellement pris ces valeurs.
    """
    d = paris(chemin)
    initiale = bankroll_initiale(chemin)

    regles = d[d.resultat.notna()].sort_values(["regle_a", "id"])
    courbe = initiale + regles.profit.cumsum() if len(regles) else pd.Series(dtype=float)
    courante = float(courbe.iloc[-1]) if len(courbe) else initiale

    serie = pd.concat([pd.Series([initiale]), courbe], ignore_index=True)
    pic = float(serie.cummax().iloc[-1])
    drawdown = (pic - courante) / pic if pic > 0 else 0.0

    exposition = float(d.loc[d.resultat.isna(), "mise"].sum()) if len(d) else 0.0
    return {
        "initiale": initiale,
        "courante": courante,
        "profit": courante - initiale,
        "exposition": exposition,
        "exposition_max": PLAFOND_EXPOSITION * courante,
        "exposition_restante": max(0.0, PLAFOND_EXPOSITION * courante - exposition),
        "plafond_match": PLAFOND_MATCH * courante,
        "pic": pic,
        "drawdown": drawdown,
        "reexamen": drawdown >= DRAWDOWN_REEXAMEN,
        "courbe": serie,
    }


def bilan(d: pd.DataFrame) -> dict:
    """Bilan d'une sélection de paris.

    Le ROI est accompagné de son intervalle de confiance, et non livré seul :
    sur quelques dizaines de paris, il ne se distingue pas de zéro, et
    prereg §2 interdit d'en tirer la moindre affirmation sous 20 000.
    """
    regles = d[d.resultat.notna() & d.resultat.ne("annule")] if len(d) else d
    n = len(regles)
    mises = float(regles.mise.sum()) if n else 0.0
    profit = float(regles.profit.sum()) if n else 0.0
    roi = (profit / mises) if mises > 0 else float("nan")

    # Écart-type du rendement par pari, pondéré par la mise : c'est ce qui
    # donne la largeur de l'intervalle autour du ROI.
    if n > 1 and mises > 0:
        r = (regles.profit / regles.mise).to_numpy(float)
        ic95 = 1.96 * float(np.std(r, ddof=1)) / np.sqrt(n)
    else:
        ic95 = float("nan")

    avec_clv = d[d.clv.notna()] if len(d) else d
    return {
        "n": len(d),
        "n_regles": n,
        "n_en_attente": int(d.resultat.isna().sum()) if len(d) else 0,
        "n_gagnes": int((regles.statut == "gagné").sum()) if n else 0,
        "taux_reussite": float((regles.statut == "gagné").mean()) if n else float("nan"),
        "mises": mises,
        "retours": float(regles.retour.sum()) if n else 0.0,
        "profit": profit,
        "roi": roi,
        "roi_ic95": ic95,
        "roi_interpretable": n >= N_MIN_ROI,
        "n_manquants_roi": max(0, N_MIN_ROI - n),
        "n_clv": len(avec_clv),
        "clv_moyen": float(avec_clv.clv.mean()) if len(avec_clv) else float("nan"),
        "clv_median": float(avec_clv.clv.median()) if len(avec_clv) else float("nan"),
        "clv_positif": float((avec_clv.clv > 0).mean()) if len(avec_clv) else float("nan"),
        "clv_ic95": (1.96 * float(avec_clv.clv.std(ddof=1)) / np.sqrt(len(avec_clv))
                     if len(avec_clv) > 1 else float("nan")),
    }


# ===========================================================================
# CLV — capture de la ligne de clôture depuis notre propre collecte
# ===========================================================================

def _cloture_observee(fixture_key: str, issue: str,
                      bdd: Path | None = None) -> tuple[float, str] | None:
    """Dernière cote observée AVANT le coup d'envoi, au meilleur benchmark.

    Nuance à garder en tête : la collecte tourne toutes les heures. Notre
    « clôture » est donc la dernière observation dans l'heure précédant le
    coup d'envoi, pas le prix à la seconde du coup d'envoi.
    """
    chemin = Path(bdd or BDD_COLLECTE)
    if not chemin.exists():
        return None
    paires = selections_collectees(issue)
    if not paires:
        return None                 # marché non collecté : pas de CLV possible
    con = sqlite3.connect(chemin)
    try:
        for marche_, selection in paires:
            d = pd.read_sql(
                "SELECT bookmaker, odds, observed_at, kickoff FROM odds_snapshot "
                "WHERE fixture_key = ? AND market = ? AND selection = ? "
                "AND observed_at IS NOT NULL AND observed_at <= kickoff "
                "ORDER BY observed_at DESC",
                con, params=(fixture_key, marche_, selection))
            if len(d) == 0:
                continue
            for book in BENCHMARKS_CLOTURE:
                sous = d[d.bookmaker == book]
                if len(sous):
                    return float(sous.odds.iloc[0]), book
    finally:
        con.close()
    return None


def capturer_clotures(chemin: Path | None = None,
                      bdd: Path | None = None) -> int:
    """Renseigne la cote de clôture des paris dont le match a commencé.

    Appelable sans risque à chaque ouverture de la page : ne touche que les
    lignes encore vides, et gèle la valeur une fois trouvée — le CLV reste
    ainsi vérifiable même si la base de collecte est reconstruite.
    """
    con = _connexion(chemin)
    try:
        a_faire = pd.read_sql(
            "SELECT id, fixture_key, issue FROM pari "
            "WHERE cote_cloture IS NULL AND kickoff <= ?",
            con, params=(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),))
        n = 0
        for r in a_faire.itertuples():
            trouve = _cloture_observee(r.fixture_key, r.issue, bdd)
            if trouve is None:
                continue
            cote, book = trouve
            con.execute("UPDATE pari SET cote_cloture = ?, book_cloture = ? "
                        "WHERE id = ?", (cote, book, int(r.id)))
            n += 1
        con.commit()
        return n
    finally:
        con.close()
