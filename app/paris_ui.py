"""Interface du carnet papier — formulaire de pari et page de suivi.

La logique vit dans ``odds.paper`` ; ce module ne fait que la mettre à
l'écran, dans le langage visuel de la maquette (``app/theme.py``).

Deux partis pris d'affichage, qui suivent le pré-enregistrement :

- la mise proposée est toujours accompagnée de **ce qui l'a bornée** (Kelly,
  plafond de match, plafond d'exposition). Un chiffre seul inviterait à le
  suivre sans le comprendre ;
- le ROI n'est jamais montré sans son intervalle de confiance ni le rappel
  de prereg §2. Sur quelques dizaines de paris, il ne se distingue pas de
  zéro, et le taire reviendrait à laisser croire le contraire.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import buts_ui
import theme
from odds import paper
from odds.models.football import buts
from odds.analysis import (AGREGATS, AUTRE_INSTANT, fiabilite_buts,
                          tranche_fiabilite, tranche_fiabilite_buts)

LIB = {"1": "Domicile", "N": "Nul", "2": "Extérieur"}
MOIS_FR = [None, "janvier", "février", "mars", "avril", "mai", "juin",
           "juillet", "août", "septembre", "octobre", "novembre",
           "décembre"]
HORS_BOOK = set(AGREGATS) | set(AUTRE_INSTANT)


def _euros(x: float) -> str:
    return f"{x:,.2f} €".replace(",", " ")


def marque_paris(cles) -> list[str]:
    """Pastille « déjà misé » pour chaque match, à poser dans le tableau.

    Voir en un coup d'œil où l'on a déjà engagé quelque chose évite le
    doublon involontaire, qui fausserait l'exposition sans rien signaler.
    """
    try:
        d = paper.paris()
    except Exception:
        return ["" for _ in cles]
    if len(d) == 0:
        return ["" for _ in cles]

    # Un badge ne peut pas porter « total_over_2.5 · dom_over_1.5 » : on
    # montre le NOMBRE de paris engagés, le détail est dans le formulaire.
    par_match = d.groupby("fixture_key").size().to_dict()
    return [theme.badge(f"{par_match[k]} pari" + ("s" if par_match[k] > 1 else ""),
                        "info") if k in par_match else "" for k in cles]


# ===========================================================================
# Formulaire de pari, posé sous le détail d'un match
# ===========================================================================

# Marchés proposés au pari, par famille. Le 1X2 reste en tête : c'est le seul
# dont chaque bookmaker relevé donne un prix.
FAMILLES_PARI = {
    "Résultat du match (1 N 2)": ["1", "N", "2"],
    "Total du match": [f"total_{s}_{l}" for l in ("1.5", "2.5", "3.5")
                       for s in ("over", "under")],
    "Total par équipe": [f"{c}_{s}_{l}" for c in ("dom", "ext")
                         for l in ("0.5", "1.5", "2.5") for s in ("over", "under")],
    "Les deux équipes marquent": ["btts_oui", "btts_non"],
}


def _offres_1x2(books: pd.DataFrame, code: str) -> pd.DataFrame:
    col = {"1": "cote_1", "N": "cote_N", "2": "cote_2"}[code]
    return (books[["bookmaker", col]].dropna()
            .rename(columns={col: "cote"})
            .sort_values("cote", ascending=False))


def _offres_totaux(totaux: pd.DataFrame | None, fk: str, code: str) -> pd.DataFrame:
    """Prix relevés pour un total du match. Vide si le marché n'est pas collecté.

    Seule la ligne 2,5 est cotée par les sources accessibles. Les autres
    lignes, et tous les totaux par équipe, n'ont aucun prix : la cote devra
    être saisie à la main.
    """
    vide = pd.DataFrame(columns=["bookmaker", "cote"])
    if totaux is None or len(totaux) == 0:
        return vide
    morceaux = code.split("_")
    if len(morceaux) != 3 or morceaux[0] != "total" or morceaux[2] != "2.5":
        return vide
    d = totaux[(totaux.fixture_key == fk) & (totaux.selection == morceaux[1])
               & ~totaux.bookmaker.astype(str).str.startswith("_")]
    if len(d) == 0:
        return vide
    return (d[["bookmaker", "odds"]].rename(columns={"odds": "cote"})
            .sort_values("cote", ascending=False).reset_index(drop=True))


def formulaire_pari(ligne, det: pd.DataFrame, methode: str,
                    source: str | None = None,
                    totaux: pd.DataFrame | None = None) -> None:
    """Carte « Parier (papier) » pour le match sélectionné."""
    fk = ligne.fixture_key

    # Meilleur prix chez un bookmaker RÉEL. Les agrégats (_max_marche) disent
    # le meilleur prix du marché sans dire chez qui : on ne peut pas y miser.
    books = det[(det.fixture_key == fk) & (~det.bookmaker.isin(HORS_BOOK))]
    if len(books) == 0:
        theme.etat_vide("Aucun bookmaker réel relevé sur ce match : "
                        "impossible de nommer un prix à prendre.")
        return

    imp, contraint = buts_ui.matrice_du_match(ligne)

    with st.container(border=True):
        theme.titre_section("Parier (papier)")

        existants = paper.paris()
        existants = existants[existants.fixture_key == fk] if len(existants) else existants
        if len(existants):
            deja = ", ".join(
                f"{paper.libelle(r.issue, ligne.home_team, ligne.away_team)} "
                f"à {r.cote:.2f}" for r in existants.itertuples())
            st.info(f"**Déjà misé sur ce match :** {deja}.")

        f1, f2 = st.columns([1, 2])
        famille = f1.selectbox("Marché", list(FAMILLES_PARI),
                               key=f"pari_famille_{fk}")
        codes = FAMILLES_PARI[famille]

        # La probabilité vient du 1X2 dévigé pour le résultat, de la matrice
        # de score pour les buts. Les deux décrivent la MÊME distribution :
        # la matrice est ajustée pour reproduire ce 1X2.
        if famille.startswith("Résultat"):
            probas = {"1": float(ligne.p_1), "N": float(ligne.p_N),
                      "2": float(ligne.p_2)}
        else:
            probas = {c: buts.probabilite(imp.matrice, c) for c in codes}

        issue = f2.selectbox(
            "Pari", codes, key=f"pari_issue_{fk}_{famille}",
            format_func=lambda c: (
                f"{paper.libelle(c, ligne.home_team, ligne.away_team)} · "
                f"{100 * probas[c]:.1f} % · cote juste "
                f"{1 / probas[c]:.2f}" if probas[c] > 0 else
                paper.libelle(c, ligne.home_team, ligne.away_team)))

        offres = (_offres_1x2(books, issue) if issue in ("1", "N", "2")
                  else _offres_totaux(totaux, fk, issue))

        if not famille.startswith("Résultat"):
            if contraint:
                st.caption("Probabilité issue d'une matrice de score **calée sur "
                           "la cote over/under du marché** — calibration mesurée "
                           "équivalente à celle du marché (R9).")
            else:
                st.caption("⚠️ Probabilité **dérivée du 1X2 seul**, faute de cote "
                           "de totaux relevée : 2 à 3 points d'écart mesuré (R9). "
                           "Le CLV de ce pari ne pourra pas être calculé.")

        c2, c3 = st.columns(2)
        if len(offres):
            defaut = float(offres.cote.iloc[0])
            cote = c2.number_input(
                "Cote prise", min_value=1.01, max_value=1000.0, value=defaut,
                step=0.01, key=f"pari_cote_{fk}_{issue}",
                help="Pré-remplie avec le meilleur prix disponible chez un "
                     "bookmaker réel. Modifiable : c'est le prix que VOUS avez pris.")
            bookmaker = c3.selectbox(
                "Chez", offres.bookmaker.tolist(), key=f"pari_book_{fk}_{issue}",
                format_func=lambda b: f"{b} · "
                f"{float(offres.loc[offres.bookmaker == b, 'cote'].iloc[0]):.2f}")
        else:
            # Aucun prix relevé : on ne prétend pas en connaître un. La cote
            # est celle que l'utilisateur a réellement vue chez son book, et
            # le nom du book est saisi avec elle — sans quoi le carnet
            # porterait un prix sans origine.
            cote = c2.number_input(
                "Cote prise", min_value=1.01, max_value=1000.0,
                value=round(1 / probas[issue], 2) if probas[issue] > 0 else 2.0,
                step=0.01, key=f"pari_cote_{fk}_{issue}",
                help="Ce marché n'est coté par aucune source collectée. "
                     "La valeur proposée est la COTE JUSTE (espérance nulle) : "
                     "remplacez-la par le prix réellement affiché chez vous.")
            bookmaker = c3.text_input(
                "Chez", value="", placeholder="nom du bookmaker",
                key=f"pari_book_{fk}_{issue}",
                help="Saisi à la main : ce marché n'apparaît dans aucun de nos "
                     "relevés.") or None

        # --- proposition du moteur de prereg §4 ---------------------------
        p = probas[issue]
        nom_pari = paper.libelle(issue, ligne.home_team, ligne.away_team)
        est_1x2 = issue in ("1", "N", "2")
        b = paper.bankroll()

        # `tranche_fiabilite` est mesurée sur l'issue la plus probable du
        # 1X2 : l'appliquer à « telle équipe marque 2 buts » serait un
        # emprunt abusif. Les marchés de buts ont leur PROPRE table
        # (research/fiabilite_buts.py).
        #
        # La distinction entre « pas mesuré » et « mesuré, échantillon trop
        # mince » est essentielle : dans le premier cas le signal est absent
        # et vaut 1 (prereg 0001 §4), dans le second il vaut 0 et doit
        # bloquer la mise. Les confondre ferait miser le plus là où l'on
        # sait le moins — c'est exactement ce que cette table corrige.
        tranche = None
        if est_1x2:
            tranche = tranche_fiabilite(p, methode)
            n_hist = int(tranche.n)
        else:
            tranche = tranche_fiabilite_buts(issue, p, contraint)
            if tranche is not None:
                n_hist = int(tranche.n)
            elif len(fiabilite_buts()) == 0:
                n_hist = None          # table absente : rien de mesuré
            else:
                n_hist = 0             # tranche trop mince : mise bloquée

        prop = paper.proposer_mise(
            bankroll=b["courante"], p=p, cote=cote, exposition=b["exposition"],
            n_hist=n_hist, n_books=int(ligne.n_books),
            # `ev_robuste` ne qualifie que l'issue visée par l'écart de prix.
            # L'appliquer à une autre issue serait un emprunt abusif.
            ev_robuste=(bool(ligne.ev_robuste)
                        if issue == getattr(ligne, "issue_prix", None) else None),
            # Lue sur un prix (1X2, ou matrice contrainte par une cote de
            # totaux) ou dérivée du seul 1X2 ? R9 mesure l'écart.
            p_cotee=est_1x2 or contraint)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Kelly complet", f"{100 * prop['kelly']:+.1f} %",
                  "(p × cote − 1) / (cote − 1)", delta_color="off")
        m2.metric("f effectif", f"{100 * prop['f_effectif']:.2f} %",
                  f"f_base {paper.F_BASE:.2f} × confiance {prop['confiance']:.2f}",
                  delta_color="off")
        m3.metric("Mise proposée", _euros(prop["mise"]),
                  {"match": "plafond match", "exposition": "plafond exposition",
                   "kelly": "aucun avantage", "bankroll": "bankroll épuisée",
                   None: "sous les plafonds"}[prop["plafond"]],
                  delta_color="off")
        m4.metric("Exposition restante", _euros(b["exposition_restante"]),
                  f"sur {_euros(b['exposition_max'])}", delta_color="off")

        if tranche is not None:
            st.caption(
                f"Fiabilité mesurée à ce niveau de probabilité : l'événement "
                f"s'est produit **{100 * float(tranche.reussite):.1f} %** du "
                f"temps (± {100 * float(tranche.ic95):.1f} pts, "
                f"n = {int(tranche.n):,}) pour une probabilité annoncée de "
                f"{100 * float(tranche.p_moyenne):.1f} %.".replace(",", " "))
        elif not est_1x2 and n_hist == 0:
            st.error("Aucune tranche mesurée à ce niveau de probabilité pour "
                     "ce marché : l'échantillon historique est trop mince. Le "
                     "moteur ne propose rien tant qu'on n'a rien mesuré.")

        if prop["plafond"] == "kelly":
            st.warning(prop["motif"])
        else:
            st.caption(prop["motif"])

        s1, s2 = st.columns([1, 2], vertical_alignment="bottom")
        mise = s1.number_input(
            "Mise réelle (€)", min_value=0.0, value=float(prop["mise"]),
            step=0.50, key=f"pari_mise_{fk}_{issue}",
            help="Pré-remplie avec la proposition du moteur. L'écart entre "
                 "proposé et misé est conservé : sans lui, le suivi mesurerait "
                 "un moteur qui n'a pas été suivi.")
        if s2.button("Enregistrer le pari", type="primary",
                     disabled=(mise <= 0), key=f"pari_ok_{fk}_{issue}",
                     use_container_width=True):
            paper.enregistrer(
                fixture_key=fk, kickoff=str(ligne.kickoff),
                home_team=ligne.home_team, away_team=ligne.away_team,
                issue=issue, cote=float(cote), p_modele=p, mise=float(mise),
                bookmaker=bookmaker, league=str(ligne.league), source=source,
                methode=methode, mise_proposee=prop["mise"],
                bankroll_avant=b["courante"], kelly_=prop["kelly"],
                f_effectif=prop["f_effectif"], plafond=prop["plafond"])
            st.success(f"Pari enregistré : **{nom_pari}** à {cote:.2f} "
                       f"chez {bookmaker or 'book non précisé'}, {_euros(mise)}.")
            st.rerun()

        if mise <= 0:
            st.caption("Mise à zéro : rien à enregistrer. Le moteur ne propose "
                       "rien à ce prix, mais vous pouvez saisir un montant.")


# ===========================================================================
# Page « Mes paris »
# ===========================================================================

def _tuiles_bankroll(b: dict) -> None:
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Bankroll", _euros(b["courante"]),
              f"initiale {_euros(b['initiale'])}", delta_color="off")
    k2.metric("Profit", f"{b['profit']:+,.2f} €".replace(",", " "),
              f"{100 * b['profit'] / b['initiale']:+.2f} %"
              if b["initiale"] else "", delta_color="off")
    k3.metric("Exposition en cours", _euros(b["exposition"]),
              f"plafond {_euros(b['exposition_max'])}", delta_color="off")
    k4.metric("Drawdown", f"{100 * b['drawdown']:.1f} %",
              f"pic {_euros(b['pic'])}", delta_color="off",
              help="Écart au plus haut atteint par la bankroll. "
                   "prereg §4 : 20 % déclenche un arrêt et un audit.")


def _reglement(en_attente: pd.DataFrame) -> None:
    """Saisie du score, par match. Un score règle tous les paris du match.

    Le règlement ne se fait plus pari par pari mais **par match**, et c'est
    ce qui rend les marchés de buts utilisables : « 2–1 » suffit à solder le
    1X2, les totaux, les totaux par équipe et le BTTS, chaque marché
    décidant lui-même par le prédicat qui a servi à le coter. Saisir un
    verdict par pari, sur sept marchés, serait à la fois fastidieux et
    faillible.
    """
    theme.titre_section("Matchs à régler — saisir le score")
    st.caption("Le score est saisi à la main, délibérément : les noms "
               "d'équipe diffèrent entre The Odds API et football-data, et un "
               "rapprochement approximatif inscrirait des gains faux dans un "
               "historique censé trancher une question. Une saisie règle "
               "**tous les paris du match**, quel que soit leur marché.")

    matchs = (en_attente.sort_values("kickoff")
              .groupby("fixture_key", as_index=False)
              .agg(home_team=("home_team", "first"),
                   away_team=("away_team", "first"),
                   kickoff=("kickoff", "first"),
                   n_paris=("id", "size"), mise=("mise", "sum")))

    saisie = pd.DataFrame({
        "fixture_key": matchs.fixture_key,
        "Match": matchs.home_team + " – " + matchs.away_team,
        "Coup d'envoi": matchs.kickoff.str[:16],
        "Paris": matchs.n_paris,
        "Mise": matchs.mise,
        "Buts dom.": pd.Series([pd.NA] * len(matchs), dtype="Int64"),
        "Buts ext.": pd.Series([pd.NA] * len(matchs), dtype="Int64"),
        "Reporté": False,
    })
    edite = st.data_editor(
        saisie, hide_index=True, use_container_width=True,
        disabled=["fixture_key", "Match", "Coup d'envoi", "Paris", "Mise"],
        column_config={
            "fixture_key": None,
            "Paris": st.column_config.NumberColumn(width="small"),
            "Mise": st.column_config.NumberColumn(format="%.2f €"),
            "Buts dom.": st.column_config.NumberColumn(
                min_value=0, max_value=30, step=1, format="%d"),
            "Buts ext.": st.column_config.NumberColumn(
                min_value=0, max_value=30, step=1, format="%d"),
            "Reporté": st.column_config.CheckboxColumn(
                help="Match reporté ou paris remboursés : les mises "
                     "reviennent, le profit est nul."),
        }, key="reglement")

    complet = edite["Buts dom."].notna() & edite["Buts ext."].notna()
    a_regler = edite[complet & ~edite["Reporté"]]
    a_annuler = edite[edite["Reporté"]]
    n = len(a_regler) + len(a_annuler)

    if st.button(f"Enregistrer {n} match(s)", type="primary", disabled=n == 0):
        regles = 0
        # `iterrows` et non `itertuples` : ce dernier renomme positionnellement
        # les colonnes dont le nom n'est pas un identifiant Python (« Buts
        # dom. »), et un tel accès se décalerait en silence à la première
        # colonne ajoutée.
        for _, r in a_regler.iterrows():
            regles += paper.regler_match(r["fixture_key"], int(r["Buts dom."]),
                                         int(r["Buts ext."]))
        for _, r in a_annuler.iterrows():
            regles += paper.annuler_match(r["fixture_key"])
        # st.data_editor mémorise les modifications par INDICE de ligne. Les
        # matchs réglés quittant la liste, une saisie résiduelle s'appliquerait
        # au match qui a pris leur place — c'est-à-dire au mauvais. On vide
        # donc l'état de l'éditeur avant de redessiner.
        st.session_state.pop("reglement", None)
        st.success(f"{regles} pari(s) réglé(s) sur {n} match(s).")
        st.rerun()


def _bilan(d: pd.DataFrame, libelle_periode: str) -> None:
    bi = paper.bilan(d)

    theme.titre_section(f"Bilan — {libelle_periode}")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Paris réglés", f"{bi['n_regles']}",
              f"{bi['n_en_attente']} en attente", delta_color="off")
    k2.metric("Taux de réussite",
              "—" if pd.isna(bi["taux_reussite"]) else f"{100 * bi['taux_reussite']:.1f} %",
              f"{bi['n_gagnes']} gagné" + ("s" if bi["n_gagnes"] > 1 else ""),
              delta_color="off")
    k3.metric("ROI", "—" if pd.isna(bi["roi"]) else f"{100 * bi['roi']:+.1f} %",
              "—" if pd.isna(bi["roi_ic95"]) else f"± {100 * bi['roi_ic95']:.1f} pts",
              delta_color="off",
              help="Profit rapporté aux mises, avec son intervalle à 95 %.")
    k4.metric("CLV moyen",
              "—" if pd.isna(bi["clv_moyen"]) else f"{bi['clv_moyen']:+.2f} %",
              "—" if pd.isna(bi["clv_ic95"]) else f"± {bi['clv_ic95']:.2f} pts",
              delta_color="off",
              help="Écart entre la cote prise et la dernière cote observée "
                   "avant le coup d'envoi. C'est le critère de prereg §5.")

    # --- ce que ces chiffres permettent de dire, et ce qu'ils interdisent ---
    if bi["n_regles"] == 0:
        st.info("Aucun pari réglé sur cette période.")
    elif not bi["roi_interpretable"]:
        borne = (f" — l'intervalle à 95 % va de "
                 f"{100 * (bi['roi'] - bi['roi_ic95']):+.1f} % à "
                 f"{100 * (bi['roi'] + bi['roi_ic95']):+.1f} %"
                 if not pd.isna(bi["roi_ic95"]) else "")
        seuil = f"{paper.N_MIN_ROI:,}".replace(",", " ")
        manque = f"{bi['n_manquants_roi']:,}".replace(",", " ")
        st.warning(
            f"**Ce ROI ne veut encore rien dire.** prereg 0001 §2 fixe à "
            f"{seuil} paris le seuil sous lequel aucune affirmation sur le "
            f"ROI n'est recevable ; il en manque {manque}{borne}. Sur cette "
            "taille d'échantillon, un ROI positif et un ROI négatif sont "
            "également compatibles avec une sélection sans aucune valeur.")

    if bi["n_clv"] > 0:
        signe = "au-dessus" if bi["clv_moyen"] > 0 else "en dessous"
        st.caption(
            f"CLV mesuré sur {bi['n_clv']} pari(s) : en moyenne "
            f"{abs(bi['clv_moyen']):.2f} % {signe} de la clôture, "
            f"{100 * bi['clv_positif']:.0f} % des paris pris à un meilleur prix "
            "que la clôture. C'est le seul de ces chiffres qui soit lisible "
            "sur quelques dizaines de paris — il ne dépend pas des résultats.")
    else:
        st.caption("Aucun CLV disponible : il se calcule dès que le match a "
                   "commencé, à partir de notre propre collecte horaire.")


def _courbes(d: pd.DataFrame, b: dict) -> None:
    regles = d[d.resultat.notna()].sort_values(["regle_a", "id"])
    g1, g2 = st.columns(2)

    with g1:
        theme.titre_section("Bankroll")
        if len(regles) == 0:
            theme.etat_vide("Pas encore de pari réglé.")
        else:
            courbe = pd.DataFrame({
                "pari": range(len(regles) + 1),
                "bankroll": [b["initiale"]] + list(
                    b["initiale"] + regles.profit.cumsum()),
            })
            base = alt.Chart(courbe)
            depart = alt.Chart(pd.DataFrame({"y": [b["initiale"]]})).mark_rule(
                strokeDash=[6, 4], color="#52525b").encode(y="y:Q")
            ligne = base.mark_line(color=theme.BLEU, point=True).encode(
                x=alt.X("pari:Q", title="Paris réglés"),
                y=alt.Y("bankroll:Q", title="Bankroll (€)",
                        scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("pari:Q"), alt.Tooltip("bankroll:Q", format=".2f")])
            st.altair_chart((depart + ligne).properties(height=260),
                            use_container_width=True)

    with g2:
        theme.titre_section("Distribution du CLV")
        avec = d[d.clv.notna()]
        if len(avec) == 0:
            theme.etat_vide("Le CLV apparaît dès qu'un match a commencé.")
        else:
            hist = alt.Chart(avec).mark_bar().encode(
                x=alt.X("clv:Q", bin=alt.Bin(maxbins=20),
                        title="CLV (%) — cote prise vs clôture"),
                y=alt.Y("count()", title="Paris"),
                color=alt.condition(alt.datum.clv > 0,
                                    alt.value(theme.EMERAUDE), alt.value(theme.ROUGE)))
            zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(
                strokeDash=[6, 4], color="#52525b").encode(x="x:Q")
            st.altair_chart((hist + zero).properties(height=260),
                            use_container_width=True)


def _historique(d: pd.DataFrame) -> None:
    regles = d[d.resultat.notna()]
    theme.titre_section("Paris réglés")
    if len(regles) == 0:
        theme.etat_vide("Aucun pari réglé sur cette période.")
        return

    TON = {"gagné": "pos", "perdu": "neg", "annulé": "outline"}
    vue = pd.DataFrame({
        "N°": regles.id,
        "Coup d'envoi": regles.kickoff.str[:16],
        "Match": regles.home_team + " – " + regles.away_team,
        "Pari": [paper.libelle(c, d, e) for c, d, e in
                 zip(regles.issue, regles.home_team, regles.away_team)],
        "Cote": regles.cote.map("{:.2f}".format),
        "Chez": regles.bookmaker.fillna("—"),
        "Mise": regles.mise.map("{:.2f}".format),
        "Score": [("—" if pd.isna(d) else f"{int(d)}–{int(e)}")
                  for d, e in zip(regles.buts_dom, regles.buts_ext)],
        "Statut": [theme.badge(s, TON.get(s, "outline")) for s in regles.statut],
        "Profit": [theme.badge(f"{v:+.2f}", "pos" if v > 0 else
                               ("neg" if v < 0 else "neu")) for v in regles.profit],
        "Clôture": regles.cote_cloture.map(
            lambda v: "—" if pd.isna(v) else f"{v:.2f}"),
        "CLV": [("—" if pd.isna(v) else
                 theme.badge(f"{v:+.2f} %", "pos" if v > 0 else "neg"))
                for v in regles.clv],
    })
    theme.tableau(vue, html=["Statut", "Profit", "CLV"],
                  aligne_droite=["N°", "Cote", "Mise", "Score", "Profit",
                                 "Clôture", "CLV"],
                  classes={"Coup d'envoi": "od-mono", "Chez": "od-muted"})


def page() -> None:
    """Page complète « Mes paris »."""
    st.title("Mes paris")
    st.caption("Carnet papier. prereg 0001 §5 fixe ce mode : mêmes calculs, "
               "mêmes plafonds, même suivi de bankroll simulée — seul le "
               "passage d'ordre est absent.")

    # Le CLV se renseigne tout seul, depuis notre collecte. Sans résultat,
    # sans crédit d'API, et gelé une fois trouvé.
    try:
        n = paper.capturer_clotures()
        if n:
            st.toast(f"{n} cote(s) de clôture capturée(s).")
    except Exception as e:                      # base de collecte absente
        st.caption(f"⚠️ Capture du CLV indisponible : {e}")

    b = paper.bankroll()
    _tuiles_bankroll(b)

    if b["reexamen"]:
        st.error(
            f"**Drawdown de {100 * b['drawdown']:.1f} % — seuil de réexamen "
            f"atteint.** prereg 0001 §4 : « 20 % → arrêt et audit ». Le même "
            "paragraphe interdit d'abaisser `f_base` en réaction : à ce stade "
            "le drawdown est déjà encaissé, la baisse ne protège de rien et "
            "biaise le suivi.")

    tout = paper.paris()
    if len(tout) == 0:
        theme.etat_vide("Aucun pari enregistré. Rendez-vous sur « Matchs par "
                        "date », choisissez un match, et misez depuis le détail.")
        _reglages(b)
        return

    en_attente = tout[tout.resultat.isna()]
    if len(en_attente):
        _reglement(en_attente)
    else:
        st.success("Aucun pari en attente de résultat.")

    # --- période -----------------------------------------------------------
    st.divider()
    mois = pd.Timestamp.now().to_period("M")
    choix = st.radio("Période", ["Ce mois-ci", "Tout l'historique"],
                     horizontal=True, key="periode_paris")
    if choix == "Ce mois-ci":
        d = paper.paris(depuis=mois.start_time, jusqua=mois.end_time)
        libelle = f"{MOIS_FR[mois.month]} {mois.year}"
    else:
        d, libelle = tout, "tout l'historique"

    _bilan(d, libelle)
    _courbes(d, b)
    _historique(d)
    _reglages(b)


def _reglages(b: dict) -> None:
    with st.expander("Réglages du carnet"):
        st.markdown(
            f"""
Les valeurs de staking viennent de **prereg 0001 §4** et sont volontairement
non modifiables ici : elles ont été fixées avant tout résultat, et les rendre
réglables depuis l'interface reviendrait à les choisir après coup.

| Paramètre | Valeur |
|---|---|
| `f_base` | {paper.F_BASE:.2f} |
| Plafond par match | {100 * paper.PLAFOND_MATCH:.0f} % de bankroll |
| Plafond d'exposition simultanée | {100 * paper.PLAFOND_EXPOSITION:.0f} % de bankroll |
| Drawdown de réexamen | {100 * paper.DRAWDOWN_REEXAMEN:.0f} % |
| `confiance()` | `{paper.CONFIANCE_VERSION}` |
| Pénalité « probabilité dérivée » | ×{paper.CONFIANCE_PENALITE_DERIVEE:.1f} (prereg 0003 §5) |

La fonction `confiance()` est définie et versionnée dans `src/odds/paper.py`.
Sa version **v2** — qui divise la confiance par deux lorsque la probabilité est
*dérivée* plutôt que lue sur un prix — est enregistrée dans
`prereg/0003-marches-de-buts.md` §5, avant tout pari sur un marché de buts.
""")
        nouvelle = st.number_input(
            "Bankroll initiale (€)", min_value=1.0, value=float(b["initiale"]),
            step=50.0,
            help="Ne change pas l'historique des paris : seulement le point "
                 "de départ de la courbe et l'assiette des plafonds.")
        if st.button("Mettre à jour la bankroll initiale"):
            paper.definir_bankroll_initiale(nouvelle)
            st.rerun()
