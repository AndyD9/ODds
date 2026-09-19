"""Matchs à une date donnée : consensus, price shopping, verdict, totaux.

C'est le point d'entrée du tableau de bord. Il renvoie un ``MatchsDuJour``
typé plutôt qu'un dictionnaire : les colonnes que l'interface lit
(``p_1``, ``n_books_ou``, ``p_over25``…) sont un contrat, et un contrat
s'écrit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from odds.analysis import fiabilite, sources
from odds.analysis.sources import AUTRE_INSTANT, HORS_CONSENSUS
from odds.market import commission
from odds.market.devig import devig_matrix
from odds.market.vocabulaire import selection_totaux


@dataclass
class MatchsDuJour:
    """Résultat de ``matchs_a_la_date``.

    ``source`` vaut ``"collecte"``, ``"historique"`` ou ``None`` quand la
    date n'a aucun match. ``fournisseur`` précise l'origine des cotes
    (``odds-api``, ``football-data``, ``pinnacle-closing``).

    ``resume`` : une ligne par match, consensus et verdict. ``detail`` : une
    ligne par (match, bookmaker). ``totaux`` : cotes over/under 2,5 au format
    long, pour le meilleur prix et le formulaire de pari.
    """
    source: str | None = None
    fournisseur: str | None = None
    resume: pd.DataFrame = field(default_factory=pd.DataFrame)
    detail: pd.DataFrame = field(default_factory=pd.DataFrame)
    totaux: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def vide(self) -> bool:
        return self.source is None


# --------------------------------------------------------------------------
# Marché des totaux (over/under 2,5)
# --------------------------------------------------------------------------
# Le seul marché de buts réellement coté qu'on puisse obtenir : les totaux
# par équipe sont un marché additionnel réservé aux offres payantes.
#
# Il vaut pourtant bien plus que lui-même. Une matrice de score calée sur le
# 1X2 SEUL sous-estime les buts de façon systématique (research/RESULTS.md
# R9) ; contrainte en plus par ce prix, elle rejoint la calibration du
# marché — y compris sur les totaux par équipe, que personne ne cote. Un
# crédit dépensé ici améliore donc des marchés qu'on ne peut pas observer.

OVER25, UNDER25 = selection_totaux(2.5, "over"), selection_totaux(2.5, "under")

_VIDE_TOTAUX = pd.DataFrame(columns=["fixture_key", "p_over25", "n_books_ou"])


def _consensus_totaux(long: pd.DataFrame, methode: str) -> pd.DataFrame:
    """Probabilité dévigée de « 3 buts ou plus », médiane des books réels."""
    if len(long) == 0:
        return _VIDE_TOTAUX.copy()
    long = long[long.selection.isin((OVER25, UNDER25))
                & ~long.bookmaker.isin(HORS_CONSENSUS)]
    if len(long) == 0:
        return _VIDE_TOTAUX.copy()
    large = long.pivot_table(index=["fixture_key", "bookmaker"],
                             columns="selection", values="odds", aggfunc="first")
    if not {OVER25, UNDER25} <= set(large.columns):
        return _VIDE_TOTAUX.copy()
    large = large.dropna(subset=[OVER25, UNDER25])
    large = large[(large[[OVER25, UNDER25]] > 1.0).all(axis=1)]
    if len(large) == 0:
        return _VIDE_TOTAUX.copy()

    p = devig_matrix(large[[OVER25, UNDER25]].to_numpy(float), methode)
    t = large.reset_index()[["fixture_key", "bookmaker"]].assign(p_over=p[:, 0])
    return (t.groupby("fixture_key")
             .agg(p_over25=("p_over", "median"), n_books_ou=("bookmaker", "nunique"))
             .reset_index())



def matchs_a_la_date(jour, methode: str = "shin") -> MatchsDuJour:
    """Tous les matchs d'une date, avec l'analyse calculée automatiquement.

    Renvoie ``source``, ``resume`` (une ligne par match) et ``detail``
    (une ligne par match x bookmaker).
    """
    jour = pd.Timestamp(jour)

    long = sources._long_depuis_collecte(jour)
    source, fournisseur = "collecte", None
    if len(long):
        fournisseur = (str(long.source.iloc[0]) if "source" in long.columns
                       and pd.notna(long.source.iloc[0]) else "football-data")
    else:
        long = sources._long_depuis_historique(jour)
        source, fournisseur = "historique", "pinnacle-closing"
    if len(long) == 0:
        return MatchsDuJour()

    # --- dévig, un livre à la fois ----------------------------------------
    large = long.pivot_table(
        index=["fixture_key", "bookmaker"], columns="selection",
        values="odds", aggfunc="first")
    large = large.dropna(subset=["home", "draw", "away"])
    large = large[(large[["home", "draw", "away"]] > 1.0).all(axis=1)]
    if len(large) == 0:
        return MatchsDuJour(source, fournisseur)

    cotes = large[["home", "draw", "away"]].to_numpy(float)
    p = devig_matrix(cotes, methode)

    detail = large.reset_index()[["fixture_key", "bookmaker"]].copy()
    detail[["cote_1", "cote_N", "cote_2"]] = cotes
    detail[["p_1", "p_N", "p_2"]] = p
    detail["marge"] = 100.0 * ((1.0 / cotes).sum(axis=1) - 1.0)

    # --- cote NETTE : ce qu'on encaisse vraiment ---------------------------
    # Une bourse d'échange prend sa part sur le gain, pas dans le prix : ses
    # cotes brutes sont donc structurellement les plus hautes et rafleraient
    # tout price shopping. On garde la cote brute pour l'afficher — c'est
    # celle que l'utilisateur lira chez son livre — et on compare en net.
    detail["commission"] = [commission.taux(b) for b in detail.bookmaker]
    for sel in ("1", "N", "2"):
        detail[f"net_{sel}"] = 1.0 + (detail[f"cote_{sel}"] - 1.0) * (
            1.0 - detail.commission)

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
    for sel in ("1", "N", "2"):
        col, ncol = f"cote_{sel}", f"net_{sel}"
        # Le meilleur prix est celui qui PAIE le plus, pas celui qui
        # s'affiche le plus haut : l'argmax porte sur la cote nette.
        idx = dispo.groupby("fixture_key")[ncol].idxmax()
        b = dispo.loc[idx, ["fixture_key", col, ncol, "bookmaker", "commission"]].rename(
            columns={col: f"best_{sel}", ncol: f"net_best_{sel}",
                     "bookmaker": f"book_{sel}", "commission": f"comm_{sel}"})
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
    for sel in ("1", "N", "2"):
        ncol = f"net_{sel}"
        p_loo, second, n_soutien = [], [], []
        for fk, best_book, best_net in zip(cons.fixture_key, cons[f"book_{sel}"],
                                           cons[f"net_best_{sel}"]):
            g = dispo[dispo.fixture_key == fk]
            autres = g[g.bookmaker != best_book]
            reels = autres[~autres.bookmaker.isin(HORS_CONSENSUS)]
            src = reels if len(reels) else autres
            p_loo.append(float(np.median(src[f"p_{sel}"])) if len(src) else np.nan)
            second.append(float(autres[ncol].max()) if len(autres) else np.nan)
            n_soutien.append(int((g[ncol] >= best_net * 0.99).sum()))
        cons[f"p_loo_{sel}"] = p_loo
        cons[f"second_{sel}"] = second
        cons[f"soutien_{sel}"] = n_soutien
        cons[f"ecart_{sel}"] = 100.0 * (np.array(p_loo) * cons[f"net_best_{sel}"] - 1.0)
        cons[f"prime_{sel}"] = 100.0 * (cons[f"net_best_{sel}"] / np.array(second) - 1.0)

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
    # Cote brute pour l'afficher, cote nette pour tout ce qui se calcule :
    # espérance, Kelly, mise proposée. Les deux coïncident hors exchange.
    cons["cote_nette_prix"] = cons[["net_best_1", "net_best_N",
                                    "net_best_2"]].to_numpy()[lig, j]
    cons["commission_prix"] = cons[["comm_1", "comm_N", "comm_2"]].to_numpy()[lig, j]
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
    bornes = _ev_toutes_methodes(cons, large, dispo)
    cons[bornes.columns] = bornes
    for sel in ("1", "N", "2"):
        cons[f"ev_robuste_{sel}"] = cons[f"ev_min_{sel}"] > 0
    cons["ev_min"] = cons[["ev_min_1", "ev_min_N", "ev_min_2"]].to_numpy()[lig, j]
    cons["ev_max"] = cons[["ev_max_1", "ev_max_N", "ev_max_2"]].to_numpy()[lig, j]
    cons["ev_robuste"] = cons.ev_min > 0

    # --- marché des totaux, s'il a été collecté ----------------------------
    totaux = (sources._totaux_depuis_collecte(jour) if source == "collecte"
              else sources._totaux_depuis_historique(jour))
    tot = _consensus_totaux(totaux, methode)
    cons = cons.merge(tot, on="fixture_key", how="left") if len(tot) else \
        cons.assign(p_over25=np.nan, n_books_ou=0)
    cons["n_books_ou"] = cons.n_books_ou.fillna(0).astype(int)

    cons["verdict"] = [_verdict(r) for _, r in cons.iterrows()]

    cons = cons.sort_values("kickoff").reset_index(drop=True)
    try:
        cons = fiabilite.annoter_confiance(cons, methode)
    except FileNotFoundError:
        # L'historique peut légitimement manquer (installation neuve). Toute
        # AUTRE erreur doit remonter : un except nu masquerait un bug.
        pass
    return MatchsDuJour(source, fournisseur, cons, detail, totaux)


def _ev_toutes_methodes(cons: pd.DataFrame, large: pd.DataFrame,
                        dispo: pd.DataFrame) -> pd.DataFrame:
    """EV minimale et maximale de CHAQUE issue, sur les 4 méthodes de dévig.

    Sur la cote NETTE, comme l'écart : les bornes doivent encadrer
    ``ecart_prix``, sans quoi le verdict « fragile » se prononcerait sur un
    autre chiffre que celui qu'on affiche.

    Les trois issues, et pas seulement celle visée par le prix : une règle
    de sélection qui retient le favori (prereg 0006) a besoin de la même
    garantie de robustesse, et la calculer ici ne coûte qu'une colonne — le
    prix de cette fonction est le filtrage par match, pas la médiane.
    """
    cotes = large[["home", "draw", "away"]].to_numpy(float)
    cles = large.reset_index()[["fixture_key", "bookmaker"]]

    par_methode = []
    for m in ("shin", "power", "odds_ratio", "proportional"):
        t = cles.copy()
        t[["p_1", "p_N", "p_2"]] = devig_matrix(cotes, m)
        par_methode.append(t)

    colonnes = {f"ev_{b}_{sel}": [] for sel in ("1", "N", "2") for b in ("min", "max")}
    for i, fk in enumerate(cons.fixture_key):
        for sel in ("1", "N", "2"):
            best_book = cons[f"book_{sel}"].iloc[i]
            best_cote = cons[f"net_best_{sel}"].iloc[i]
            evs = []
            for t in par_methode:
                g = t[(t.fixture_key == fk) & (t.bookmaker != best_book)]
                g = g[~g.bookmaker.isin(HORS_CONSENSUS)]
                if len(g) == 0:
                    continue
                evs.append(100.0 * (float(np.median(g[f"p_{sel}"])) * best_cote - 1.0))
            colonnes[f"ev_min_{sel}"].append(min(evs) if evs else np.nan)
            colonnes[f"ev_max_{sel}"].append(max(evs) if evs else np.nan)
    return pd.DataFrame(colonnes, index=cons.index)


# Seuils du verdict. Fixés ici, pas au fil de l'affichage, pour être
# discutables et modifiables en un seul endroit.
SEUIL_EV_MINI = 1.0        # en % — en deçà, le bruit domine
SEUIL_PRIME_ISOLEE = 2.0   # en % au-dessus du 2e meilleur prix = anomalie isolée
SOUTIEN_MINI = 2           # nombre de books à 1 % du meilleur prix
N_BOOKS_MINI = 6           # consensus indigent en dessous


# Le seul verdict qui autorise à parler de « valeur » : écart d'au moins
# SEUIL_EV_MINI, porté par SOUTIEN_MINI livres au moins, stable sur les quatre
# méthodes de dévig, sur un consensus d'au moins N_BOOKS_MINI books.
VERDICT_VALEUR = "Écart soutenu"


def pari_a_valeur(resume: pd.DataFrame):
    """Le pari du jour à la plus forte valeur **soutenue**, ou ``None``.

    C'est la ligne qu'on met en avant quand il faut choisir un pari plutôt
    qu'un autre : pas le plus probable — au prix juste, miser sur le favori
    a une espérance nulle — mais celui dont le prix bat le consensus des
    autres livres, et de façon qui ne soit pas du bruit. Un écart isolé ou
    fragile ne compte pas, si grand soit-il : c'est le filtre qui sépare une
    valeur d'une cote périmée.
    """
    if len(resume) == 0 or "verdict" not in resume.columns:
        return None
    ecart = pd.to_numeric(resume.ecart_prix, errors="coerce")
    c = resume[(resume.verdict == VERDICT_VALEUR) & np.isfinite(ecart)]
    if len(c) == 0:
        return None
    return c.loc[c.ecart_prix.idxmax()]


# ---------------------------------------------------------------------------
# « Sûr et payant » — prereg 0006
# ---------------------------------------------------------------------------
# Le seuil de probabilité est la borne basse du niveau « Élevée » de la
# table de confiance (``fiabilite.NIVEAUX``) : c'est le même chiffre que la
# page affiche déjà à côté de chaque pronostic, pas un seuil de plus.
#
# Il était de 0,80 à l'écriture de la règle, et 0,80 × 1,25 = 1 en faisait
# exactement « espérance >= 0 sur un gros favori ». Mesuré avant d'écrire :
# zéro candidat sur 144 matchs. Abaissé le jour même à 0,70 (prereg 0006,
# journal) : la cote juste vaut alors 1/0,70 = 1,43, le plancher de 1,25 ne
# lie plus, c'est l'écart positif chez un livre réel qui lie. Le prix de ce
# point : 74,5 % de réussite mesurée au lieu de 83,6 % — un pari sur quatre
# perd au lieu d'un sur cinq, et la page le dit.
SEUIL_P_SUR = dict((nom, seuil) for seuil, nom in fiabilite.NIVEAUX)["Élevée"]
SEUIL_COTE_SURE = 1.25


def paris_surs(resume: pd.DataFrame, p_min: float = SEUIL_P_SUR,
               cote_min: float = SEUIL_COTE_SURE) -> pd.DataFrame:
    """Les favoris nets à ``p_min`` ou plus, payés ``cote_min`` ou mieux.

    Quatre conditions, toutes nécessaires :

    1. l'issue est **le favori du marché** — la table de fiabilité mesure la
       fréquence de l'issue la plus probable, l'appliquer à une autre serait
       un emprunt abusif (``fiabilite_historique``) ;
    2. sa probabilité de consensus atteint ``p_min`` ;
    3. la meilleure cote **nette de commission** atteint ``cote_min`` ;
    4. le prix bat le consensus des autres livres (``ecart > 0``) et se prend
       chez un bookmaker réel, pas sur un agrégat de marché.

    Renvoie les colonnes du résumé, plus celles de l'issue retenue
    (``issue_sure``, ``p_sure``, ``cote_sure``, ``cote_sure_nette``,
    ``book_sur``, ``ecart_sur``, ``soutien_sur``, ``prime_sur``,
    ``ev_min_sur``/``ev_max_sur``, ``ev_robuste_sur`` et ``verdict_sur``),
    triées par probabilité décroissante — le plus sûr d'abord.

    ``verdict_sur`` est le verdict ordinaire appliqué à cette issue-là. Il
    n'écarte rien : un favori bien payé mais soutenu par un seul livre passe
    la règle et sort « écart isolé ». La règle dit ce qui est sûr et payant ;
    le verdict dit ce que le prix vaut. Les deux s'affichent ensemble.
    """
    vides = ["issue_sure", "p_sure", "cote_sure", "cote_sure_nette",
             "book_sur", "ecart_sur", "soutien_sur", "prime_sur",
             "ev_min_sur", "ev_max_sur", "ev_robuste_sur", "verdict_sur"]
    if len(resume) == 0 or "issue_probable" not in resume.columns:
        return resume.head(0).assign(**{c: pd.Series(dtype=object) for c in vides})

    lig = np.arange(len(resume))
    j = np.array([{"1": 0, "N": 1, "2": 2}[s] for s in resume.issue_probable])

    def colonne(prefixe):
        return resume[[f"{prefixe}_1", f"{prefixe}_N",
                       f"{prefixe}_2"]].to_numpy()[lig, j]

    d = resume.assign(
        issue_sure=resume.issue_probable.to_numpy(),
        p_sure=resume.p_probable.to_numpy(),
        cote_sure=colonne("best"),
        cote_sure_nette=colonne("net_best"),
        book_sur=colonne("book"),
        ecart_sur=colonne("ecart"),
        soutien_sur=colonne("soutien"),
        prime_sur=colonne("prime"),
        ev_min_sur=colonne("ev_min"),
        ev_max_sur=colonne("ev_max"),
        ev_robuste_sur=colonne("ev_robuste"))

    garde = (
        (d.p_sure >= p_min)
        & (pd.to_numeric(d.cote_sure_nette, errors="coerce") >= cote_min)
        & (pd.to_numeric(d.ecart_sur, errors="coerce") > 0)
        # Un agrégat dit qu'un prix existe quelque part sans dire chez qui :
        # on ne peut pas y miser, donc il ne peut pas être « payant ».
        & ~d.book_sur.astype(str).isin(HORS_CONSENSUS))
    d = d[garde].sort_values("p_sure", ascending=False).reset_index(drop=True)
    d["verdict_sur"] = [
        _verdict(pd.Series({"n_books": r.n_books, "ecart_prix": r.ecart_sur,
                            "prime_prix": r.prime_sur, "soutien_prix": r.soutien_sur,
                            "ev_robuste": r.ev_robuste_sur}))
        for r in d.itertuples()]
    return d


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
