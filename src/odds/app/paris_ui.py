"""Interface du carnet papier — formulaire de pari et page de suivi.

La logique vit dans ``odds.paper`` ; ce module ne fait que la mettre à
l'écran, dans le langage visuel de la maquette (``odds/app/theme.py``).

Deux partis pris d'affichage, qui suivent le pré-enregistrement :

- la mise proposée est toujours accompagnée de **ce qui l'a bornée** (Kelly,
  plafond de match, plafond d'exposition). Un chiffre seul inviterait à le
  suivre sans le comprendre ;
- le ROI n'est jamais montré sans son intervalle de confiance ni le rappel
  de prereg §2. Sur quelques dizaines de paris, il ne se distingue pas de
  zéro, et le taire reviendrait à laisser croire le contraire.
"""

from __future__ import annotations

from html import escape

import altair as alt
import pandas as pd
import streamlit as st

from odds import paper
from odds.analysis import (AGREGATS, AUTRE_INSTANT, VERDICT_VALEUR, fiabilite_buts,
                           tranche_fiabilite, tranche_fiabilite_buts)
from odds.app import buts_ui, libelles, theme
from odds.market import commission
from odds.market.vocabulaire import selection_collectee
from odds.models.football import buts

LIB = {"1": "Domicile", "N": "Nul", "2": "Extérieur"}
MOIS_FR = [None, "janvier", "février", "mars", "avril", "mai", "juin",
           "juillet", "août", "septembre", "octobre", "novembre",
           "décembre"]
HORS_BOOK = set(AGREGATS) | set(AUTRE_INSTANT)

# Ce qu'un verdict non soutenu doit dire au moment de parier sur l'issue
# visée par l'écart de prix : la valeur affichée n'est alors pas une valeur.
AVERTISSEMENT_VERDICT = {
    "Écart isolé — prudence":
        "L'écart de prix sur cette issue est porté par un seul bookmaker, nettement "
        "au-dessus du deuxième meilleur prix : presque toujours une cote périmée ou "
        "erronée, ou une limite de mise dérisoire. Vérifiez qu'elle est encore affichée.",
    "Fragile — dépend de la méthode":
        "L'écart de prix sur cette issue change de signe selon la méthode de dévig "
        "(R3) : il mesure le choix de méthode, pas le marché. La confiance est divisée "
        "par deux, et cette « valeur » n'en est pas une.",
}


def _badge_valeur(v: float, decimales: int = 1) -> str:
    """Pastille d'espérance en % de la mise : verte si positive, rouge sinon."""
    if pd.isna(v):
        return "—"
    return theme.badge(f"{v:+.{decimales}f} %", "pos" if v > 0 else ("neg" if v < 0 else "neu"))


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


def _nettes(offres: pd.DataFrame) -> pd.DataFrame:
    """Ajoute la cote encaissée et trie dessus.

    Une bourse d'échange affiche presque toujours la cote la plus haute —
    elle ne prend pas sa marge dans le prix — et se rembourse sur le gain.
    Classer les offres sur la cote brute mettrait donc systématiquement
    l'exchange en tête, y compris quand il paie moins.
    """
    if len(offres) == 0:
        return offres.assign(nette=[], commission=[])
    o = offres.copy()
    o["commission"] = [commission.taux(b) for b in o.bookmaker]
    o["nette"] = 1.0 + (o.cote - 1.0) * (1.0 - o.commission)
    return o.sort_values("nette", ascending=False).reset_index(drop=True)


def _offres_1x2(books: pd.DataFrame, code: str) -> pd.DataFrame:
    col = {"1": "cote_1", "N": "cote_N", "2": "cote_2"}[code]
    return _nettes(books[["bookmaker", col]].dropna()
                   .rename(columns={col: "cote"}))


def _offres_totaux(totaux: pd.DataFrame | None, fk: str, code: str) -> pd.DataFrame:
    """Prix relevés pour un total du match. Vide si le marché n'est pas collecté.

    Seule la ligne 2,5 est cotée par les sources accessibles. Les autres
    lignes, et tous les totaux par équipe, n'ont aucun prix : la cote devra
    être saisie à la main.
    """
    vide = pd.DataFrame(columns=["bookmaker", "cote", "nette", "commission"])
    if totaux is None or len(totaux) == 0:
        return vide
    paire = selection_collectee(code)
    if paire is None or paire[0] == "1X2":
        return vide
    d = totaux[(totaux.fixture_key == fk) & (totaux.selection == paire[1])
               & ~totaux.bookmaker.astype(str).str.startswith("_")]
    if len(d) == 0:
        return vide
    return _nettes(d[["bookmaker", "odds"]].rename(columns={"odds": "cote"}))


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

    imp, contraint, _ = buts_ui.matrice_du_match(ligne)
    n_books_ou = int(getattr(ligne, "n_books_ou", 0) or 0)

    with st.container(border=True):
        theme.titre_section("Parier (papier)")

        existants = paper.paris()
        existants = existants[existants.fixture_key == fk] if len(existants) else existants
        if len(existants):
            deja = ", ".join(
                f"{paper.libelle(r.issue, ligne.home_team, ligne.away_team)} "
                f"à {r.cote:.2f}"
                + (f" ({r.cote_nette:.2f} net)" if r.commission else "")
                for r in existants.itertuples())
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
        elif not imp.fiable:
            # La carte « Marchés de buts » a déjà refusé d'afficher ces
            # chiffres ; le formulaire ne peut pas être moins exigeant
            # qu'elle et proposer une mise sur une matrice qui ne
            # reproduit pas les prix qu'on lui a donnés.
            theme.reserve(
                "La matrice de score ne reproduit pas les prix de ce match "
                f"(écart {100 * imp.ecart_max:.2f} pts) : aucun pari sur un "
                "marché de buts n'est proposé. Le 1X2 reste disponible.", "grave")
            return
        else:
            probas = {c: buts.probabilite(imp.matrice, c) for c in codes}

        # La valeur de chaque issue AU MEILLEUR PRIX relevé, dans le menu
        # même : c'est là qu'on choisit un pari plutôt qu'un autre, et c'est
        # ce chiffre — pas la probabilité — qui départage.
        def _offres(c):
            return (_offres_1x2(books, c) if c in ("1", "N", "2")
                    else _offres_totaux(totaux, fk, c))

        # Deux prix par issue : celui qu'on lit chez le livre (brut) et celui
        # qu'on encaisse (net de commission). La valeur se calcule sur le
        # second, toujours.
        meilleures, meilleures_nettes = {}, {}
        for c in codes:
            o = _offres(c)
            meilleures[c] = float(o.cote.iloc[0]) if len(o) else None
            meilleures_nettes[c] = float(o.nette.iloc[0]) if len(o) else None

        def _valeur_au_mieux(c):
            """Espérance de l'issue au meilleur prix ENCAISSABLE, ou None."""
            if meilleures_nettes[c] is None or probas[c] <= 0:
                return None
            return paper.valeur(probas[c], meilleures_nettes[c])

        def _libelle_choix(c):
            nom = paper.libelle(c, ligne.home_team, ligne.away_team)
            if probas[c] <= 0:
                return nom
            txt = f"{nom} · {100 * probas[c]:.1f} % · cote juste {1 / probas[c]:.2f}"
            v = _valeur_au_mieux(c)
            if v is not None:
                txt += f" · valeur {100 * v:+.1f} % à {meilleures[c]:.2f}"
                if abs(meilleures_nettes[c] - meilleures[c]) > 5e-3:
                    txt += f" ({meilleures_nettes[c]:.2f} net)"
            return txt

        # Par défaut, l'issue visée par l'écart soutenu : c'est elle qui a
        # amené ici depuis la carte « à prendre », pas l'issue la plus probable.
        defaut_issue = 0
        if (famille.startswith("Résultat")
                and getattr(ligne, "verdict", None) == VERDICT_VALEUR
                and getattr(ligne, "issue_prix", None) in codes):
            defaut_issue = codes.index(ligne.issue_prix)
        issue = f2.selectbox("Pari", codes, index=defaut_issue,
                             key=f"pari_issue_{fk}_{famille}",
                             format_func=_libelle_choix)
        avec_valeur = [c for c in codes if (_valeur_au_mieux(c) or 0) > 0]
        if avec_valeur:
            # Une valeur positive sur l'issue visée par l'écart de prix n'en
            # est une que si le verdict la soutient : sinon on le dit dans la
            # même phrase, pas trois écrans plus bas.
            def _nom_qualifie(c):
                nom = paper.libelle(c, ligne.home_team, ligne.away_team)
                if (c in ("1", "N", "2") and c == getattr(ligne, "issue_prix", None)
                        and getattr(ligne, "verdict", None) in AVERTISSEMENT_VERDICT):
                    return f"{nom} (écart {'isolé' if 'isolé' in ligne.verdict else 'fragile'})"
                return nom
            f2.caption("À valeur positive au meilleur prix relevé : **"
                       + ", ".join(_nom_qualifie(c) for c in avec_valeur) + "**.")
        elif any(m is not None for m in meilleures.values()):
            f2.caption("Aucune issue de ce marché n'a de valeur positive au meilleur "
                       "prix relevé.")

        offres = _offres(issue)

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
            def _libelle_book(b):
                o = offres.loc[offres.bookmaker == b].iloc[0]
                txt = f"{libelles.bookmaker(b)} · {float(o.cote):.2f}"
                if o.commission:
                    txt += f" → {float(o.nette):.2f} net ({100 * o.commission:g} %)"
                return txt

            bookmaker = c3.selectbox(
                "Chez", offres.bookmaker.tolist(), key=f"pari_book_{fk}_{issue}",
                format_func=_libelle_book)
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

        # --- d'où vient ce pari -------------------------------------------
        # prereg 0006 §5 : les paris pris au titre de « sûr et payant » sont
        # suivis à part. La marque n'est posée que si l'issue inscrite est
        # bien celle de la carte qui a mené ici.
        origine = st.session_state.get("origine_pari") or {}
        note_regle = None
        if (origine.get("regle") == "0006" and origine.get("fixture_key") == fk
                and origine.get("issue") == issue):
            pm, cm = origine.get("seuils", (0.0, 0.0))
            note_regle = (f"prereg 0006 — sûr et payant (p ≥ {100 * pm:.0f} %, "
                          f"cote nette ≥ {cm:.2f})")
            st.caption(f"Pris au titre de la règle **sûr et payant** : "
                       f"probabilité ≥ {100 * pm:.0f} %, cote nette ≥ {cm:.2f}. "
                       "Le carnet le note, pour pouvoir juger cette règle "
                       "séparément.")

        # --- ce qu'on encaisse vraiment -----------------------------------
        # La cote saisie est celle affichée chez le livre ; sur une bourse
        # d'échange, la commission se prend sur le gain. Tout ce qui suit —
        # espérance, Kelly, mise, carnet — travaille sur la cote nette.
        taux_comm = commission.taux(bookmaker)
        cote_nette = commission.cote_nette(cote, taux_=taux_comm)
        if taux_comm:
            st.caption(
                f"**{libelles.bookmaker(bookmaker)}** est une bourse d'échange : "
                f"{100 * taux_comm:g} % du gain lui revient. La cote "
                f"{cote:.2f} paie donc comme un **{cote_nette:.2f}**, et c'est "
                "sur ce prix que l'espérance et la mise sont calculées.")

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

        # Qualité de donnée : le nombre de livres qui ont réellement fixé
        # cette probabilité. Pour le 1X2, et pour une matrice dérivée du
        # 1X2 seul, ce sont les livres du 1X2. Quand la matrice est calée sur
        # une cote de totaux, cette cote est une contrainte à part entière :
        # si un seul bookmaker la fournit, la probabilité repose sur un seul
        # prix, et la confiance doit le refléter — c'est précisément le cas
        # où l'écart affiché ne mesure que la marge de ce livre.
        n_books_pari = int(ligne.n_books)
        if not est_1x2 and contraint:
            n_books_pari = min(n_books_pari, n_books_ou)

        prop = paper.proposer_mise(
            bankroll=b["courante"], p=p, cote=cote_nette, exposition=b["exposition"],
            n_hist=n_hist, n_books=n_books_pari,
            # `ev_robuste` ne qualifie que l'issue visée par l'écart de prix.
            # L'appliquer à une autre issue serait un emprunt abusif.
            ev_robuste=(bool(ligne.ev_robuste)
                        if issue == getattr(ligne, "issue_prix", None) else None),
            # Lue sur un prix (1X2, ou matrice contrainte par une cote de
            # totaux) ou dérivée du seul 1X2 ? R9 mesure l'écart.
            p_cotee=est_1x2 or contraint)

        ev = paper.valeur(p, cote_nette)
        m0, m1, m2, m3, m4 = st.columns(5)
        # Le delta porte le signe : Streamlit le colore en vert ou en rouge,
        # ce qui fait de la valeur le seul chiffre coloré de la rangée.
        m0.metric("Valeur", f"{100 * ev:+.1f} %",
                  f"{100 * ev:+.2f} % de la mise en moyenne",
                  help="p × cote − 1 : espérance par euro misé, contre la probabilité "
                       "dévigée du consensus. Positive quand le prix bat la cote juste.")
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
            theme.reserve("Aucune tranche mesurée à ce niveau de probabilité "
                          "pour ce marché : l'échantillon historique est trop "
                          "mince. Le moteur ne propose rien tant qu'on n'a rien "
                          "mesuré.", "attention")

        # --- pourquoi ce pari, en une phrase ------------------------------
        prix = (f"{cote:.2f}" if not taux_comm
                else f"{cote:.2f} ({cote_nette:.2f} net)")
        if ev > 0:
            texte = (f"**Pourquoi ce pari :** à {prix}, il rend en moyenne "
                     f"**{100 * ev:+.1f} %** de la mise — le prix bat la cote juste "
                     f"{1 / p:.2f}. C'est ce qui le distingue d'un pari « sur le "
                     "favori » : la probabilité dit ce qui est probable, la valeur "
                     "dit ce qui vaut d'être pris.")
        else:
            texte = (f"**Pas de valeur à ce prix :** {prix} est au niveau de la "
                     f"cote juste {1 / p:.2f} ou en dessous, espérance "
                     f"**{100 * ev:+.1f} %**. Un pari probable n'est pas un pari "
                     "rentable ; le moteur ne propose rien, et c'est cohérent.")
            if taux_comm and paper.valeur(p, cote) > 0:
                texte += (" **Sans la commission, il en aurait :** c'est elle qui "
                          "mange l'écart, pas le prix.")
        # Pour le 1X2, le consensus recalculé SANS le livre au meilleur prix
        # est la mesure honnête (le livre généreux tire la médiane vers lui).
        p_loo = getattr(ligne, f"p_loo_{issue}", None) if est_1x2 else None
        if p_loo is not None and pd.notna(p_loo) and float(p_loo) > 0:
            ev_loo = paper.valeur(float(p_loo), cote_nette)
            texte += (f" Consensus recalculé sans le livre au meilleur prix : "
                      f"**{100 * ev_loo:+.1f} %**.")
        st.markdown(texte)

        verdict = getattr(ligne, "verdict", None)
        if est_1x2 and issue == getattr(ligne, "issue_prix", None):
            if verdict in AVERTISSEMENT_VERDICT:
                st.warning(AVERTISSEMENT_VERDICT[verdict])
            elif verdict == VERDICT_VALEUR:
                st.success(f"**Écart soutenu** : {int(ligne.soutien_prix)} livres au prix, "
                           "signe stable sur les quatre méthodes de dévig. C'est le pari "
                           "à valeur de ce match.")

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
                     width="stretch"):
            paper.enregistrer(
                fixture_key=fk, kickoff=str(ligne.kickoff),
                home_team=ligne.home_team, away_team=ligne.away_team,
                issue=issue, cote=float(cote), p_modele=p, mise=float(mise),
                bookmaker=bookmaker, commission=taux_comm,
                league=str(ligne.league), source=source,
                methode=methode, mise_proposee=prop["mise"],
                bankroll_avant=b["courante"], kelly_=prop["kelly"],
                f_effectif=prop["f_effectif"], plafond=prop["plafond"],
                note=note_regle)
            st.success(f"Pari enregistré : **{nom_pari}** à {prix} chez "
                       f"{libelles.bookmaker(bookmaker) if bookmaker else 'book non précisé'}"
                       f", {_euros(mise)}.")
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
        saisie, hide_index=True, width="stretch",
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
    k1, k2, k3, k4, k5 = st.columns(5)
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
    attendu = f"{bi['esperance']:+.2f} € attendus"
    if bi["n_en_attente"]:
        attendu += f" · {bi['esperance_en_attente']:+.2f} € en attente"
    k4.metric("Valeur annoncée",
              "—" if pd.isna(bi["valeur_moyenne"]) else f"{100 * bi['valeur_moyenne']:+.1f} %",
              attendu, delta_color="off",
              help="Σ mise × (p × cote − 1) rapporté aux mises : le ROI que le carnet "
                   "ANNONÇAIT en prenant ces paris. À comparer au ROI réalisé.")
    k5.metric("CLV moyen",
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

    if bi["n_regles"] > 0:
        st.caption(
            f"Le carnet annonçait **{bi['esperance']:+.2f} €** d'espérance sur ces "
            f"{bi['n_regles']} paris ({bi['n_valeur_positive']} à valeur positive) ; "
            f"il a rendu **{bi['profit']:+.2f} €**. L'écart entre les deux est la "
            "variance des résultats, pas un jugement sur la sélection : seule la "
            "valeur annoncée est connue au moment de parier, et seul le CLV dit "
            "ensuite si elle était réelle.")

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
                            width="stretch")

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
                            width="stretch")


def _couvertures(d: pd.DataFrame) -> None:
    """Les couvertures, une ligne par groupe : c'est le net qui compte.

    Le tableau des paris réglés montre chaque jambe, et une couverture y
    gagne sur une jambe et perd sur les autres par construction. Sans cette
    vue, le taux de réussite du carnet se dégrade mécaniquement à chaque
    couverture sans que rien n'ait été mal joué.
    """
    c = paper.couvertures(d)
    if len(c) == 0:
        return
    theme.titre_section("Couvertures — résultat net par groupe")
    TON = {"réglée": "info", "en attente": "outline", "annulé": "outline"}
    vue = pd.DataFrame({
        "Coup d'envoi": c.kickoff.str[:16],
        "Match": c.home_team + " – " + c.away_team,
        "Jambes": [" + ".join(paper.libelle(x, h, a) for x in issues)
                   for issues, h, a in zip(c.issues, c.home_team, c.away_team)],
        "Mise": c.mise.map("{:.2f}".format),
        "Pire cas accepté": c.pire.map("{:+.2f}".format),
        "Statut": [theme.badge(s, TON.get(s, "outline")) for s in c.statut],
        "Net": [("—" if pd.isna(v) else
                 theme.badge(f"{v:+.2f}", "pos" if v > 0 else ("neg" if v < 0 else "neu")))
                for v in c.profit],
    })
    theme.tableau(vue, html=["Statut", "Net"],
                  aligne_droite=["Mise", "Pire cas accepté", "Net"],
                  classes={"Coup d'envoi": "od-mono"})
    st.caption("Une couverture est jugée sur son net, jamais jambe par jambe : "
               "perdre la jambe non sortie fait partie du prix accepté en la prenant.")


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
        "Pari": [escape(paper.libelle(c, d, e))
                 + (" " + theme.badge("couv.", "info")
                    if isinstance(g, str) and g else "")
                 + (" " + theme.badge("sûr et payant", "outline")
                    if isinstance(n, str) and "0006" in n else "")
                 for c, d, e, g, n in zip(regles.issue, regles.home_team,
                                          regles.away_team,
                                          regles.groupe if "groupe" in regles.columns
                                          else [None] * len(regles),
                                          regles.note if "note" in regles.columns
                                          else [None] * len(regles))],
        # Sur une bourse, la cote du ticket et celle qui a payé diffèrent :
        # les deux sont là, sans quoi le profit de la ligne serait inexplicable.
        "Cote": [f"{c:.2f}" if not k else f"{c:.2f} → {n:.2f}"
                 for c, n, k in zip(regles.cote, regles.cote_nette,
                                    regles.commission)],
        "Valeur": [_badge_valeur(v) for v in regles.valeur],
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
    theme.tableau(vue, html=["Pari", "Valeur", "Statut", "Profit", "CLV"],
                  aligne_droite=["N°", "Cote", "Valeur", "Mise", "Score", "Profit",
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
    _couvertures(d)
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
