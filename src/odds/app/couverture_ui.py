"""Couvrir plusieurs issues à l'écran — la carte « Couvrir (papier) ».

La logique vit dans ``odds.market.couverture`` et ``odds.paper`` ; ce module
la montre, et il montre d'abord ce que l'utilisateur oublie le plus
facilement : **une couverture ne crée pas d'espérance**. Chaque ligne du
tableau porte donc son espérance en face de son « gain si couvert », et la
couverture complète affiche la perte garantie qu'elle coûte.

Deux répartitions sont proposées, et elles ne se valent pas :

- la **proposition du moteur** — Kelly simultané, ``f_base × confiance``,
  plafonds de §4 sur la somme des jambes. C'est la seule que le moteur
  signe. Elle ne couvre que les issues qui battent leur réserve, et peut
  ne rien proposer du tout ;
- le **retour égal** (dutching), au choix de l'utilisateur : les issues
  cochées rendent la même somme. Fourni pour être compris et, si on y
  tient, enregistré — avec son espérance à côté, et ``mise_proposee`` à
  zéro sur les jambes que le moteur n'aurait pas prises.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from odds import paper
from odds.analysis import (AGREGATS, AUTRE_INSTANT, fiabilite_buts,
                           tranche_fiabilite, tranche_fiabilite_buts)
from odds.app import buts_ui, theme
from odds.market import commission
from odds.market import couverture as cv
from odds.market.vocabulaire import selection_collectee
from odds.models.football import buts

HORS_BOOK = set(AGREGATS) | set(AUTRE_INSTANT)

# Partitions proposées, dans l'ordre de lecture. Les lignes extrêmes du
# total (0,5 et 5,5) et les totaux par équipe à 3,5 sont écartées : leurs
# probabilités dérivées sont dans les queues de la matrice, là où R9 mesure
# le moins bien.
PARTITIONS_UI = ["1X2", "total_1.5", "total_2.5", "total_3.5",
                 "dom_0.5", "dom_1.5", "dom_2.5",
                 "ext_0.5", "ext_1.5", "ext_2.5", "btts"]


def _euros(x: float) -> str:
    return f"{x:,.2f} €".replace(",", " ")


def _le_mieux_payant(d: pd.DataFrame, col: str):
    """Ligne dont la cote NETTE est la plus haute — celle qui paie le plus.

    Sur la cote brute, une bourse d'échange gagne presque toujours : elle ne
    prend pas sa marge dans le prix. Elle la prend sur le gain, et c'est
    après commission que les prix se comparent.
    """
    net = [commission.cote_nette(c, b)
           for c, b in zip(d[col], d.bookmaker)]
    i = int(pd.Series(net, index=d.index).idxmax())
    return float(d.loc[i, col]), str(d.loc[i, "bookmaker"])


def _meilleurs_prix(codes, det_match: pd.DataFrame,
                    totaux: pd.DataFrame | None, fk: str) -> dict:
    """``code -> (cote affichée, bookmaker)`` du prix le mieux payant."""
    out = {}
    for code in codes:
        if code in ("1", "N", "2"):
            col = {"1": "cote_1", "N": "cote_N", "2": "cote_2"}[code]
            d = det_match[["bookmaker", col]].dropna()
            if len(d):
                out[code] = _le_mieux_payant(d, col)
            continue
        paire = selection_collectee(code)
        if paire is None or totaux is None or len(totaux) == 0:
            continue
        d = totaux[(totaux.fixture_key == fk) & (totaux.selection == paire[1])
                   & ~totaux.bookmaker.astype(str).str.startswith("_")]
        if len(d):
            out[code] = _le_mieux_payant(d, "odds")
    return out


def _tableau_couverture(cvr: cv.Couverture, libelles: dict) -> None:
    t = cvr.tableau(libelles)
    vue = pd.DataFrame({
        "Issue": t.issue,
        "Probabilité": (100 * t.p).map("{:.1f} %".format),
        "Cote": [("—" if pd.isna(c) else f"{c:.2f}") for c in t.cote],
        "Mise": [("—" if m == 0 else _euros(m)) for m in t.mise],
        "Si elle sort": [theme.badge(f"{v:+.2f} €", "pos" if v > 0 else
                                     ("neg" if v < 0 else "neu")) for v in t.profit],
    })
    theme.tableau(vue, html=["Si elle sort"],
                  aligne_droite=["Probabilité", "Cote", "Mise", "Si elle sort"])


def bloc_couverture(ligne, det: pd.DataFrame, methode: str,
                    source: str | None = None,
                    totaux: pd.DataFrame | None = None) -> None:
    """Carte « Couvrir plusieurs issues (papier) » du détail d'un match."""
    fk = ligne.fixture_key
    dom, ext = ligne.home_team, ligne.away_team
    books = det[(det.fixture_key == fk) & (~det.bookmaker.isin(HORS_BOOK))]
    imp, contraint, _ = buts_ui.matrice_du_match(ligne)
    n_books_ou = int(getattr(ligne, "n_books_ou", 0) or 0)

    with st.container(border=True):
        theme.titre_section("Couvrir plusieurs issues (papier)")
        st.caption(
            "Répartir la mise sur plusieurs issues **du même marché** pour "
            "perdre moins quand celle qu'on visait ne sort pas. La somme des "
            "espérances ne bouge pas : couvrir une issue sans valeur dilue "
            "l'avantage qu'on avait sur les autres et paie la marge une fois "
            "de plus. Chaque ligne affiche donc son espérance.")

        nom = st.selectbox(
            "Marché à couvrir", PARTITIONS_UI, key=f"cv_partition_{fk}",
            format_func=lambda n: cv.libelle_partition(n, dom, ext))
        codes = cv.PARTITIONS[nom]
        est_1x2 = nom == "1X2"
        libelles = {c: paper.libelle(c, dom, ext) for c in codes}

        if est_1x2:
            probas = {"1": float(ligne.p_1), "N": float(ligne.p_N),
                      "2": float(ligne.p_2)}
        elif not imp.fiable:
            theme.reserve("La matrice de score ne reproduit pas les prix de ce "
                          f"match (écart {100 * imp.ecart_max:.2f} pts) : aucun "
                          "marché de buts n'est proposé à la couverture. Le 1X2 "
                          "reste disponible.", "grave")
            return
        else:
            probas = {c: buts.probabilite(imp.matrice, c) for c in codes}
            if contraint:
                st.caption("Probabilités d'une matrice **calée sur la cote "
                           "over/under du marché** (R9 : calibration du marché).")
            else:
                st.caption("⚠️ Probabilités **dérivées du 1X2 seul** : 2 à 3 points "
                           "d'écart mesuré (R9), confiance divisée par deux, et "
                           "pas de CLV sur ces jambes.")

        # --- une ligne par issue : cote et bookmaker ------------------------
        prix = _meilleurs_prix(codes, books, totaux, fk)
        cotes_brutes, bookmakers = {}, {}
        for code in codes:
            c1, c2, c3 = st.columns([2, 1, 1.4])
            c1.markdown(f"**{libelles[code]}**  \n"
                        f"<span class='od-muted'>{100 * probas[code]:.1f} % · cote "
                        f"juste {1 / probas[code]:.2f}</span>" if probas[code] > 0
                        else f"**{libelles[code]}**", unsafe_allow_html=True)
            if code in prix:
                cote_def, book_def = prix[code]
                aide = f"Meilleur prix relevé chez un bookmaker réel : {book_def}."
            else:
                cote_def, book_def = (round(1 / probas[code], 2)
                                      if probas[code] > 0 else 2.0), ""
                aide = ("Aucun prix relevé pour ce marché : la valeur proposée est "
                        "la cote JUSTE (espérance nulle). Remplacez-la par le prix "
                        "réellement affiché chez vous.")
            cotes_brutes[code] = float(c2.number_input(
                "Cote", min_value=1.01, max_value=1000.0, value=float(cote_def),
                step=0.01, key=f"cv_cote_{fk}_{code}", help=aide,
                label_visibility="collapsed"))
            bookmakers[code] = c3.text_input(
                "Chez", value=book_def, placeholder="bookmaker",
                key=f"cv_book_{fk}_{code}", label_visibility="collapsed") or None

        # Le moteur ne voit que des cotes NETTES : répartition, espérance et
        # pire cas sont des euros, et une bourse en rend moins qu'elle
        # n'affiche. Le carnet, lui, garde les deux.
        commissions = {c: commission.taux(bookmakers.get(c)) for c in codes}
        cotes = {c: commission.cote_nette(cotes_brutes[c], taux_=commissions[c])
                 for c in codes}
        if any(commissions.values()):
            st.caption("Cotes ramenées au **net de commission** : "
                       + " · ".join(
                           f"{libelles[c]} {cotes_brutes[c]:.2f} → {cotes[c]:.2f}"
                           for c in codes if commissions[c])
                       + ". C'est ce qui est réparti, gagné et perdu.")

        booksum = sum(1.0 / c for c in cotes.values())
        b = paper.bankroll()
        plafond_match = b["plafond_match"]

        # --- ce que couvrir tout coûte -------------------------------------
        if booksum < 1.0:
            st.success(f"**Σ 1/cote = {booksum:.4f} < 1.** À ces prix, couvrir toutes "
                       f"les issues garantit {100 * (1 / booksum - 1):+.2f} % de la "
                       "mise quelle que soit l'issue. Vérifiez que chaque prix est "
                       "encore affiché : un sur-arbitrage tient rarement plus de "
                       "quelques minutes, et retient volontiers la cote périmée.")
        else:
            st.caption(f"Σ 1/cote = **{booksum:.4f}** : couvrir toutes les issues "
                       f"garantit une **perte de {100 * (1 - 1 / booksum):.2f} %** "
                       "de la mise. C'est la marge, payée d'avance.")

        # --- proposition du moteur -----------------------------------------
        if est_1x2:
            tranche = tranche_fiabilite(float(ligne.p_probable), methode)
            n_hist = int(tranche.n)
        else:
            tranche = tranche_fiabilite_buts(codes[0], probas[codes[0]], contraint)
            if tranche is not None:
                n_hist = int(tranche.n)
            elif len(fiabilite_buts()) == 0:
                n_hist = None
            else:
                n_hist = 0
        n_books_pari = int(ligne.n_books)
        if not est_1x2 and contraint:
            n_books_pari = min(n_books_pari, n_books_ou)

        signaux = dict(n_hist=n_hist, n_books=n_books_pari,
                       p_cotee=est_1x2 or contraint)
        prop = paper.proposer_couverture(
            bankroll=b["courante"], probas=probas, cotes=cotes,
            exposition=b["exposition"], partition=codes, **signaux)
        # `ev_robuste` ne qualifie que l'issue visée par l'écart de prix
        # (R3 : sous 5 % de probabilité, les méthodes de dévig divergent de
        # 16,6 % en relatif). Si Kelly retient précisément cette issue —
        # typiquement un nul à 23,00 sur un match déséquilibré —, la
        # fragilité de son écart doit peser sur la couverture.
        issue_prix = getattr(ligne, "issue_prix", None)
        if est_1x2 and issue_prix in prop["mises"] and not bool(ligne.ev_robuste):
            prop = paper.proposer_couverture(
                bankroll=b["courante"], probas=probas, cotes=cotes,
                exposition=b["exposition"], partition=codes,
                ev_robuste=False, **signaux)
            st.caption(f"⚠️ L'écart de prix sur « {libelles[issue_prix]} » change de "
                       "signe selon la méthode de dévig (R3) : confiance divisée "
                       "par deux sur cette couverture.")

        st.markdown("**Proposition du moteur** — Kelly simultané, "
                    f"f_base {paper.F_BASE:.2f} × confiance {prop['confiance']:.2f}, "
                    "plafonds de §4 sur la somme des jambes.")
        m1, m2, m3 = st.columns(3)
        m1.metric("Issues retenues",
                  ", ".join(libelles[c] for c in prop["mises"]) or "aucune",
                  delta_color="off")
        m2.metric("Mise totale proposée", _euros(prop["total"]),
                  {"match": "plafond match", "exposition": "plafond exposition",
                   "kelly": "aucun avantage", "bankroll": "bankroll épuisée",
                   None: "sous les plafonds"}[prop["plafond"]], delta_color="off")
        m3.metric("Exposition restante", _euros(b["exposition_restante"]),
                  f"sur {_euros(b['exposition_max'])}", delta_color="off")
        if prop["plafond"] == "kelly":
            st.warning(prop["motif"])
        else:
            st.caption(prop["motif"])
            sans_valeur = [c for c in prop["mises"] if probas[c] * cotes[c] < 1.0]
            if sans_valeur:
                st.info("Kelly retient **" + ", ".join(libelles[c] for c in sans_valeur)
                        + "** bien que cette issue ait une espérance négative "
                        "seule : la position sur les autres issues est assez grosse "
                        "pour que racheter de la variance vaille la marge payée. "
                        "Ce n'est pas de la valeur, c'est une assurance.")

        # --- toutes les couvertures à retour égal ---------------------------
        with st.expander(f"Toutes les couvertures à retour égal, pour "
                         f"{_euros(plafond_match)} (plafond par match)"):
            lignes = []
            for cvr in cv.toutes_les_couvertures(cotes, probas, plafond_match, codes):
                gain = cvr.meilleur
                perte = cvr.pire
                lignes.append({
                    "Issues couvertes": " + ".join(libelles[c] for c in cvr.codes),
                    "Répartition": " / ".join(f"{cvr.mises[c]:.2f}" for c in cvr.codes),
                    "Cote synth.": f"{cvr.cote_synthetique:.3f}",
                    "P(couvert)": f"{100 * cvr.p_couverte:.1f} %",
                    "Si couvert": theme.badge(f"{gain:+.2f} €", "pos" if gain > 0 else "neg"),
                    "Sinon": theme.badge(f"{perte:+.2f} €", "neg" if perte < 0 else "pos"),
                    "Espérance": theme.badge(f"{cvr.esperance:+.2f} €",
                                             "pos" if cvr.esperance > 0 else "neg"),
                })
            theme.tableau(pd.DataFrame(lignes), html=["Si couvert", "Sinon", "Espérance"],
                          aligne_droite=["Répartition", "Cote synth.", "P(couvert)",
                                         "Si couvert", "Sinon", "Espérance"])
            st.caption("« Cote synth. » est la cote à laquelle on achète la réunion des "
                       "issues couvertes. Une couverture de deux issues sur trois est "
                       "un pari « double chance » fabriqué à la main — au même prix.")

        # --- choisir et enregistrer ----------------------------------------
        st.markdown("**Enregistrer une couverture**")
        mode = st.radio("Répartition", ["Proposition du moteur", "Retour égal (dutching)"],
                        horizontal=True, key=f"cv_mode_{fk}", label_visibility="collapsed")
        if mode == "Proposition du moteur":
            cvr = prop["couverture"]
            if cvr is None:
                st.caption("Le moteur ne propose rien à ces prix : rien à enregistrer "
                           "dans ce mode.")
                return
            total = cvr.total
        else:
            choix = st.multiselect(
                "Issues à couvrir", list(codes), default=list(prop["mises"]) or [codes[0]],
                format_func=lambda c: libelles[c], key=f"cv_choix_{fk}_{nom}")
            total = st.number_input(
                "Mise totale (€)", min_value=0.0, value=float(prop["total"] or plafond_match),
                step=0.50, key=f"cv_total_{fk}_{nom}",
                help="Répartie à retour égal entre les issues cochées. Le plafond de "
                     f"§4 est {_euros(plafond_match)} par match.")
            if not choix or total <= 0:
                st.caption("Choisissez au moins une issue et une mise.")
                return
            cvr = cv.couvrir(choix, cotes, probas, total, codes)
            if total > plafond_match + 1e-9:
                st.warning(f"Mise totale au-dessus du plafond par match "
                           f"({_euros(plafond_match)}, prereg 0001 §4). Enregistrable, "
                           "mais l'écart à la proposition est conservé.")

        _tableau_couverture(cvr, libelles)
        e1, e2, e3 = st.columns(3)
        e1.metric("Mise totale", _euros(cvr.total), delta_color="off")
        e2.metric("Espérance", f"{cvr.esperance:+.2f} €",
                  f"{100 * cvr.esperance_relative:+.1f} % de la mise", delta_color="off")
        e3.metric("Pire cas", f"{cvr.pire:+.2f} €",
                  "quelle que soit l'issue" if cvr.complete else "si aucune issue couverte ne sort",
                  delta_color="off")
        if cvr.complete and cvr.pire < 0:
            theme.reserve("Couverture complète à perte garantie : ce n'est pas une "
                          "mise, c'est un don au bookmaker. Le moteur ne la propose "
                          "jamais ; elle reste enregistrable pour l'exercice.",
                          "grave")

        if st.button("Enregistrer la couverture", type="primary",
                     key=f"cv_ok_{fk}_{nom}_{mode}", width="stretch"):
            groupe = paper.enregistrer_couverture(
                fixture_key=fk, kickoff=str(ligne.kickoff), home_team=dom, away_team=ext,
                cv=cvr, bookmakers=bookmakers, cotes_brutes=cotes_brutes,
                commissions=commissions,
                mises_proposees={c: prop["mises"].get(c, 0.0) for c in cvr.codes},
                league=str(ligne.league), source=source, methode=methode,
                bankroll_avant=b["courante"], f_effectif=prop["f_effectif"],
                plafond=prop["plafond"])
            st.success(f"Couverture enregistrée ({len(cvr.codes)} jambes, "
                       f"{_euros(cvr.total)}) — groupe `{groupe}`.")
            st.rerun()
