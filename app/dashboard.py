"""Tableau de bord — probabilités de marché et marchés de buts.

Périmètre (prereg 0003 §1) : outil personnel à usage éducatif, suivi de paris
en **papier** uniquement. Ce qu'il montre est encadré par deux mesures : ni
Dixon-Coles ni aucune dérivation ne bat le prix de marché, sur le 1X2
(RESULTS R8) comme sur les buts (R9). Le prix reste la meilleure information
disponible ; l'outil sert à le lire correctement, pas à prétendre le battre.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import buts_ui  # noqa: E402  — marchés de buts
import paris_ui  # noqa: E402  — carnet papier
import theme  # noqa: E402  — habillage, doit suivre l'ajout du chemin

from odds.analysis import (AGREGATS, AUTRE_INSTANT, N_BOOKS_MINI, SEUIL_EV_MINI,
                           SEUIL_PRIME_ISOLEE, analyser_livre, avec_cloture,
                           carte_information_tardive, carte_marges, charger, cible,
                           comparer_methodes, courbe_calibration, dates_disponibles,
                           ece, fiabilite_historique, matchs_a_la_date,
                           probabilites_marche)

st.set_page_config(page_title="Analyse des probabilités de marché",
                   page_icon="📊", layout="wide")
theme.appliquer()

COULEURS = theme.COULEURS_METHODE


@st.cache_data(show_spinner="Chargement des données…")
def _donnees() -> pd.DataFrame:
    return charger()


@st.cache_data(show_spinner="Calcul…")
def _probas(cles: tuple, prefixe: str, methode: str) -> np.ndarray:
    df = _donnees()
    return probabilites_marche(df.loc[list(cles)], prefixe, methode)


try:
    df = _donnees()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

clo = avec_cloture(df)

st.sidebar.title("📊 Probabilités de marché")
page = st.sidebar.radio("Page", ["Matchs par date", "Mes paris",
                                 "Dévig d'un livre", "Calibration du marché",
                                 "Cartographie", "Explorateur de matchs",
                                 "Collecte en cours"])
st.sidebar.caption(
    f"{len(df):,} matchs · {len(clo):,} avec clôture Pinnacle\n\n"
    f"{clo.date.min().date()} → {clo.date.max().date()}"
)
st.sidebar.warning(
    "Outil personnel, **paris en papier uniquement**. Ni le modèle ni la "
    "dérivation ne battent le prix de marché — mesuré sur le 1X2 (R8) comme "
    "sur les buts (R9). Voir `research/RESULTS.md`.")


# --- compteur de crédits The Odds API --------------------------------------
# /sports ne compte pas dans le quota : le compteur est donc lu gratuitement.
# Le cache évite seulement d'ajouter une latence réseau à chaque rerun.
@st.cache_data(ttl=300, show_spinner=False)
def _credits():
    from odds import config
    if not config.est_configure("ODDS_API_KEY"):
        return None
    from odds.data.oddsapi import credits
    return credits()


try:
    _c = _credits()
except Exception as _e:
    _c = None
    st.sidebar.caption(f"⚠️ Compteur de crédits indisponible : {_e}")

if _c:
    st.sidebar.divider()
    st.sidebar.markdown("**Crédits The Odds API**")
    st.sidebar.progress(min(1.0, _c["part_utilisee"]))
    cg, cd = st.sidebar.columns(2)
    cg.metric("Restants", f"{_c['restants']:,}")
    cd.metric("Utilisés", f"{_c['utilises']:,}")
    st.sidebar.caption(f"sur {_c['total']:,} ce mois-ci · lecture gratuite")


# ==========================================================================
if page == "Matchs par date":
    st.title("Matchs par date")
    st.caption("Choisissez une date : l'analyse est calculée automatiquement pour tous les "
               "matchs du jour.")

    dispo = dates_disponibles()
    collecte_jours = sorted(dispo["collecte"])
    aujourdhui = pd.Timestamp.now().date()
    hist_max = pd.Timestamp(dispo["historique"][1]).date()

    # Par défaut : aujourd'hui s'il y a quelque chose à montrer, sinon la
    # date la plus récente effectivement couverte.
    couvertes = set(collecte_jours) | {str(hist_max)}
    defaut = (aujourdhui if str(aujourdhui) in couvertes
              else (pd.Timestamp(collecte_jours[-1]).date() if collecte_jours else hist_max))

    # La borne haute ne doit PAS se limiter aux données existantes : sinon
    # les dates à venir sont grisées dans le calendrier et l'utilisateur se
    # retrouve enfermé dans le passé sans explication.
    max_selectionnable = max(defaut, hist_max, aujourdhui + pd.Timedelta(days=21).to_pytimedelta())

    f1, f2 = st.columns([1, 2])
    jour = f1.date_input("Date", value=defaut,
                         min_value=pd.Timestamp(dispo["historique"][0]).date(),
                         max_value=max_selectionnable)
    if jour == aujourdhui:
        f1.caption("📅 Aujourd'hui")
    methode = f2.selectbox("Méthode de dévig", ["shin", "power", "odds_ratio", "proportional"])

    if collecte_jours:
        f2.caption("Cotes collectées disponibles pour : " + ", ".join(collecte_jours[-6:]))

    # --- fraîcheur du flux amont ------------------------------------------
    # Une journée vide vient presque toujours de la source, pas de nous :
    # football-data ne publie ses fixtures que deux fois par semaine environ.
    try:
        from odds.data.collect import etat_flux
        fx = etat_flux()
    except Exception:
        fx = pd.DataFrame()

    if len(fx):
        pub = fx.last_modified_dt.max()
        couv_max = fx.date_max.max()
        age = float(fx.age_heures.max())
        msg = (f"**Flux amont publié le {pub:%a %d %b %H:%M UTC}** "
               f"(il y a {age:.0f} h) — couvre jusqu'au {couv_max}.")
        if fx.perime.any():
            st.error(msg + " Le flux semble **en retard** : vérifiez `logs/collect.err`.")
        elif pd.Timestamp(couv_max).date() < pd.Timestamp.now().date():
            st.warning(
                msg + "\n\nfootball-data publie ses fixtures **par à-coups** : une fois en "
                "milieu de semaine, une fois avant le week-end. Entre deux publications, "
                "aucune date à venir n'apparaît. Le collecteur tourne toutes les heures et "
                "prendra la prochaine publication automatiquement.")
        else:
            st.caption(msg)

    with st.spinner("Calcul…"):
        r = matchs_a_la_date(jour, methode)

    if r["source"] is None:
        st.info(f"**Aucun match au {jour}.**")
        if jour >= aujourdhui and len(fx):
            st.markdown(
                f"Cette date est **au-delà de ce que la source a publié** "
                f"(couverture jusqu'au {fx.date_max.max()}).\n\n"
                "Ce n'est pas une panne : football-data ne publie ses fixtures que deux fois "
                "par semaine. Il n'existe donc pas de fenêtre glissante de « matchs du jour » "
                "en continu avec cette source gratuite.\n\n"
                "**Pour une couverture quotidienne réelle**, il faut une API de cotes dédiée "
                "(voir `PLAN.md` §7.2, option B) — la décision a été explicitement différée.")
        else:
            st.markdown(f"Historique disponible du {dispo['historique'][0]} "
                        f"au {dispo['historique'][1]}. Il se peut simplement qu'aucun match "
                        "n'ait été joué ce jour-là dans les 35 championnats suivis.")
        st.stop()

    res_tout, det = r["resume"], r["detail"]
    historique = r["source"] == "historique"

    # --- filtre championnat ------------------------------------------------
    ligues = sorted(res_tout.league.astype(str).unique())
    choisies = st.multiselect(
        f"Championnats ({len(ligues)} ce jour-là)", ligues, default=ligues,
        help="Vide = tous les championnats.")
    res = res_tout[res_tout.league.astype(str).isin(choisies)] if choisies else res_tout
    res = res.reset_index(drop=True)

    if historique:
        st.info(f"**Source : historique** — {len(res)} matchs affichés "
                f"sur {len(res_tout)} ce jour-là. Cotes de clôture Pinnacle, résultat connu.")
    else:
        fournisseur = r.get("fournisseur") or "football-data"
        nom = {"odds-api": "The Odds API", "football-data": "football-data.co.uk"}.get(
            fournisseur, fournisseur)
        st.success(f"**Source : collecte propre — {nom}** — {len(res)} matchs affichés "
                   f"sur {len(res_tout)} collectés, jusqu'à {int(res_tout.n_books.max())} "
                   "bookmakers par match. Dernière cote observée pour chacun.")
        if fournisseur == "odds-api":
            st.caption("Couverture limitée aux championnats de `ODDS_API_SPORTS` ayant un match "
                       "dans les 36 h — c'est ce qui tient dans le budget de crédits gratuit.")
        else:
            st.caption("⚠️ football-data ne publie ses fixtures que deux fois par semaine : "
                       "pour une date future, ce n'est pas nécessairement la totalité de la "
                       "journée. Configurez The Odds API pour une couverture continue "
                       "(`uv run odds config`).")

    if len(res) == 0:
        st.warning("Aucun championnat sélectionné.")
        st.stop()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Matchs", len(res))
    m2.metric("Marge médiane", f"{res.marge.median():.2f} %")
    m3.metric("Books médian", f"{int(res.n_books.median())}")
    m4.metric("Dispersion médiane", f"{res.dispersion.median():.2f} pts",
              help="Écart-type de P(1) entre bookmakers. Élevé = le marché est en désaccord.")

    # --- pronostic et confiance (section principale) -----------------------
    st.subheader("Pronostic le plus probable et confiance")
    st.caption("Lecture du marché, marge retirée. La colonne « réussite historique » indique "
               "à quelle fréquence ce niveau de probabilité s'est **réellement** vérifié sur "
               "les 150 626 matchs de l'historique. Usage descriptif et pédagogique.")

    NIV_ICONE = {"Très élevée": "🟢", "Élevée": "🔵", "Modérée": "🟡",
                 "Faible": "🟠", "Très faible": "🔴"}
    lib = {"1": "Domicile", "N": "Nul", "2": "Extérieur"}
    a_confiance = "confiance" in res.columns

    if a_confiance:
        res = res.sort_values("p_probable", ascending=False).reset_index(drop=True)
        issue_txt = [
            {"1": r.home_team, "N": "Match nul", "2": r.away_team}[r.issue_probable]
            for _, r in res.iterrows()]
        prono = pd.DataFrame({
            "Confiance": [theme.badge(c, theme.TONS_CONFIANCE.get(c, "outline"))
                          for c in res.confiance],
            "Heure": res.kickoff.str[11:16],
            "Champ.": [theme.badge(c) for c in res.league.astype(str)],
            "Domicile": res.home_team,
            "Extérieur": res.away_team,
            "Probabilités (1 · N · 2)": [theme.barre_1n2(a, b, c) for a, b, c
                                         in zip(res.p_1, res.p_N, res.p_2)],
            "Pronostic": issue_txt,
            "Marché %": (100 * res.p_probable).map("{:.1f}".format),
            "Réussite hist. %": (100 * res.reussite_hist).map("{:.1f}".format),
            "± pts": (100 * res.ic95_hist).map("{:.1f}".format),
            "Échec hist. %": (100 * res.echoue_hist).map("{:.1f}".format),
            "n hist.": res.n_hist.map("{:,}".format),
            "Books": res.n_books,
        })
        prono.insert(0, "Pari", paris_ui.marque_paris(res.fixture_key))
        colonnes_html = ["Pari", "Confiance", "Champ.",
                         "Probabilités (1 · N · 2)"]
        if historique and "score" in res.columns:
            juste = (res.resultat.map({"H": "1", "D": "N", "A": "2"})
                     == res.issue_probable)
            # Position relative : le tableau gagne et perd des colonnes selon
            # le contexte, des index en dur se décalent en silence.
            ou = prono.columns.get_loc("Marché %")
            prono.insert(ou, "Score", res.score.to_numpy())
            prono.insert(ou + 1, "Résultat", res.resultat.map(
                {"H": "Domicile", "D": "Nul", "A": "Extérieur"}).to_numpy())
            prono.insert(ou + 2, "Vu juste",
                         [theme.icone_oui_non(bool(j)) for j in juste])
            colonnes_html.append("Vu juste")

        with st.container(border=True):
            theme.titre_section("Matchs du jour")
            theme.tableau(
                prono, html=colonnes_html,
                aligne_droite=["Marché %", "Réussite hist. %", "± pts",
                               "Échec hist. %", "n hist.", "Books"],
                classes={"Heure": "od-mono"})

        meilleur = res.iloc[0]
        nom = {"1": meilleur.home_team, "N": "le match nul",
               "2": meilleur.away_team}[meilleur.issue_probable]
        st.info(
            f"**Le pronostic le plus sûr du jour : {nom}** "
            f"({meilleur.home_team} – {meilleur.away_team}), donné à "
            f"{100 * meilleur.p_probable:.1f} % par le marché. "
            f"Historiquement, ce niveau se vérifie **{100 * meilleur.reussite_hist:.1f} %** "
            f"du temps (n = {meilleur.n_hist:,}) — donc il échoue quand même "
            f"**{100 * meilleur.echoue_hist:.1f} %** des fois.")

        with st.expander("D'où vient le score de confiance"):
            st.markdown("""
Le score n'est pas une estimation : il est **mesuré** sur les 150 626 matchs de l'historique à
clôture Pinnacle. Pour chaque tranche de probabilité, on compte à quelle fréquence l'issue la
plus probable s'est réellement produite.

Deux enseignements de cette mesure :

- **Le marché est remarquablement calibré.** L'écart entre probabilité annoncée et fréquence
  observée ne dépasse jamais 2,2 points, sur aucune tranche.
- **Le favori du marché ne l'emporte que 50,4 % du temps**, toutes tranches confondues. « Le plus
  probable » est très loin de « probable ».
""")
            tbl = fiabilite_historique()
            ch = alt.Chart(tbl.assign(annonce=100 * tbl.p_moyenne,
                                      observe=100 * tbl.reussite)).mark_circle(
                size=120, color=theme.BLEU).encode(
                x=alt.X("annonce:Q", title="Probabilité annoncée (%)"),
                y=alt.Y("observe:Q", title="Réussite observée (%)"),
                size=alt.Size("n:Q", legend=None),
                tooltip=[alt.Tooltip("annonce:Q", format=".1f"),
                         alt.Tooltip("observe:Q", format=".1f"),
                         alt.Tooltip("n:Q", title="n")])
            diag = alt.Chart(pd.DataFrame({"x": [33, 95]})).mark_line(
                strokeDash=[6, 4], color="#52525b").encode(x="x:Q", y="x:Q")
            st.altair_chart((diag + ch).properties(height=300), use_container_width=True)
            st.dataframe(
                tbl.assign(p_moyenne=100 * tbl.p_moyenne, reussite=100 * tbl.reussite,
                           ic95=100 * tbl.ic95)[["bin", "n", "p_moyenne", "reussite", "ic95"]]
                   .rename(columns={"bin": "Tranche", "p_moyenne": "Annoncé %",
                                    "reussite": "Observé %", "ic95": "± pts"})
                   .style.format({"Annoncé %": "{:.1f}", "Observé %": "{:.1f}",
                                  "± pts": "{:.1f}", "n": "{:,}"}),
                use_container_width=True, hide_index=True)
    else:
        st.warning("Historique indisponible : le score de confiance ne peut pas être calculé. "
                   "Lancez `uv run odds ingest`.")

    # --- dispersion des prix (section secondaire) --------------------------
    st.divider()
    with st.expander("Dispersion des prix entre bookmakers (analyse secondaire)"):
        st.caption("Où le meilleur prix disponible s'écarte-t-il du consensus des autres "
                   "bookmakers ? C'est une observation sur le **désaccord entre opérateurs**, "
                   "sans rapport avec la probabilité qu'une issue se produise.")

        ORDRE = {"Écart soutenu": 0, "Écart isolé — prudence": 1,
                 "Fragile — dépend de la méthode": 2, "Trop peu de books": 3,
                 "Rien à signaler": 4}
        TON = {"Écart soutenu": "pos", "Écart isolé — prudence": "neu",
               "Fragile — dépend de la méthode": "neg",
               "Trop peu de books": "outline", "Rien à signaler": "outline"}

        def nom_book(b):
            return {"_max_marche": "⌀ meilleur du marché",
                    "_moyenne_marche": "⌀ moyenne marché"}.get(b, b)

        def ton_ecart(v):
            # Seuil de ±1 point, comme la maquette (gapClass).
            return "pos" if v >= 1 else ("neg" if v <= -1 else "neu")

        rp = res.assign(_o=res.verdict.map(ORDRE).fillna(9)).sort_values(
            ["_o", "kickoff"]).reset_index(drop=True)
        theme.tableau(pd.DataFrame({
            "Constat": [theme.badge(v, TON.get(v, "outline")) for v in rp.verdict],
            "Match": rp.home_team + " – " + rp.away_team,
            "Issue visée": rp.issue_prix.map(lib),
            "Cote": rp.cote_prix.map("{:.2f}".format),
            "Chez": rp.book_prix.map(nom_book),
            "Écart %": [theme.badge(f"{v:+.2f}", ton_ecart(v)) for v in rp.ecart_prix],
            "min %": rp.ev_min.map("{:+.2f}".format),
            "max %": rp.ev_max.map("{:+.2f}".format),
            "Books au prix": rp.soutien_prix,
        }), html=["Constat", "Écart %"],
            aligne_droite=["Cote", "Écart %", "min %", "max %", "Books au prix"],
            classes={"Chez": "od-muted"})

        st.markdown("""
**min % / max %** encadrent l'écart selon la méthode de dévig retenue (Shin, power, odds ratio,
proportionnelle). Quand le signe change entre les deux, le chiffre mesure le choix de méthode et
non le marché — c'est systématiquement le cas sur les issues à faible probabilité, où
`research/RESULTS.md` (R3) a mesuré 16,6 % de divergence relative entre méthodes.
""")

    st.divider()
    # Titre et sélecteur sur une même ligne, comme la maquette.
    t1, t2 = st.columns([1, 1], vertical_alignment="center")
    t1.subheader("Détail d'un match")
    libelles = (res.kickoff.str[11:16] + " · " + res.home_team + " – " + res.away_team
                + " (" + res.league.astype(str) + ")")
    choix = t2.selectbox("Match", libelles.tolist(), label_visibility="collapsed")
    ligne = res.loc[libelles == choix].iloc[0]
    fk = ligne.fixture_key

    nom_prono = {"1": ligne.home_team, "N": "Match nul",
                 "2": ligne.away_team}[ligne.issue_probable]
    if a_confiance:
        st.markdown(f"### {NIV_ICONE.get(ligne.confiance, '')} Pronostic : **{nom_prono}** "
                    f"· confiance {ligne.confiance.lower()}")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Probabilité de marché", f"{100 * ligne.p_probable:.1f} %",
                  lib[ligne.issue_probable], delta_color="off")
        d2.metric("Réussite historique", f"{100 * ligne.reussite_hist:.1f} %",
                  f"± {100 * ligne.ic95_hist:.1f} pts", delta_color="off")
        d3.metric("Échoue quand même", f"{100 * ligne.echoue_hist:.1f} %",
                  "du temps", delta_color="off")
        d4.metric("Échantillon", f"{ligne.n_hist:,}", "matchs historiques",
                  delta_color="off")
        st.caption("La réussite historique est mesurée sur les matchs de l'historique dont la "
                   "probabilité annoncée tombait dans la même tranche. Elle n'est pas propre à "
                   "ce match : elle dit ce que vaut, en moyenne, un pronostic à ce niveau.")
    else:
        st.markdown(f"### Pronostic : **{nom_prono}** "
                    f"({100 * ligne.p_probable:.1f} %)")

    buts_ui.bloc_buts(ligne, r.get("totaux"))

    paris_ui.formulaire_pari(ligne, det, methode, source=r.get("fournisseur"),
                             totaux=r.get("totaux"))

    with st.expander("Dispersion des prix sur ce match"):
        e1, e2, e3 = st.columns(3)
        e1.metric("Issue visée par le prix", lib[ligne.issue_prix],
                  f"{ligne.ecart_prix:+.2f} %", delta_color="off")
        e2.metric("Meilleure cote", f"{ligne.cote_prix:.2f}",
                  nom_book(ligne.book_prix), delta_color="off")
        e3.metric("Selon la méthode", f"{ligne.ev_min:+.1f} → {ligne.ev_max:+.1f} %",
                  "stable" if ligne.ev_robuste else "change de signe",
                  delta_color="normal" if ligne.ev_robuste else "inverse")
        if str(ligne.book_prix).startswith("_"):
            st.caption("⌀ = agrégat de marché, pas un bookmaker. Voir le tableau livre par livre.")
        if not ligne.ev_robuste:
            st.error("L'écart change de signe selon la méthode de dévig : il mesure le choix "
                     "de méthode, pas le marché. Typique des issues à faible probabilité.")
        elif ligne.verdict == "Écart isolé — prudence":
            st.warning(f"Prix {ligne.prime_prix:+.1f} % au-dessus du deuxième, affiché par "
                       f"{int(ligne.soutien_prix)} bookmaker(s) seulement — presque toujours "
                       "une cote périmée ou erronée.")
        elif ligne.verdict == "Écart soutenu":
            st.success(f"Écart soutenu par {int(ligne.soutien_prix)} bookmakers et stable sur "
                       "les quatre méthodes de dévig.")
    d = det[det.fixture_key == fk].copy()
    d["type"] = np.where(d.bookmaker.isin(AGREGATS), "agrégat",
                np.where(d.bookmaker.isin(AUTRE_INSTANT), "autre instant", "book"))
    d = d.sort_values(["type", "bookmaker"])

    couleurs_books = theme.palette_books(d.bookmaker)

    c1, c2 = st.columns([1.3, 1])
    with c1:
        theme.tableau(
            pd.DataFrame({
                "Bookmaker": [theme.pastille(b, couleurs_books) + " " + str(b)
                              for b in d.bookmaker],
                "Type": d.type,
                "Cote 1": d.cote_1.map("{:.2f}".format),
                "Cote N": d.cote_N.map("{:.2f}".format),
                "Cote 2": d.cote_2.map("{:.2f}".format),
                "P(1)": (100 * d.p_1).map("{:.1f}".format),
                "P(N)": (100 * d.p_N).map("{:.1f}".format),
                "P(2)": (100 * d.p_2).map("{:.1f}".format),
                "Marge %": d.marge.map("{:.2f}".format),
            }), html=["Bookmaker"],
            aligne_droite=["Cote 1", "Cote N", "Cote 2", "P(1)", "P(N)", "P(2)",
                           "Marge %"],
            classes={"Type": "od-muted"})
        st.caption("« autre instant » = même bookmaker relevé plus tôt. Exclu du consensus "
                   "et du meilleur prix : ce n'est pas un concurrent, et cette cote n'est "
                   "plus disponible.")
    with c2:
        books = d[d.type == "book"]
        longd = books.melt(
            id_vars="bookmaker", value_vars=["p_1", "p_N", "p_2"],
            var_name="issue", value_name="p")
        longd["issue"] = longd.issue.map({"p_1": "1", "p_N": "N", "p_2": "2"})
        noms = books.bookmaker.tolist()
        ch = alt.Chart(longd).mark_circle(
            size=110, opacity=.88, stroke=theme.BG, strokeWidth=1).encode(
            x=alt.X("p:Q", title="Probabilité (marge retirée)", axis=alt.Axis(format="%")),
            y=alt.Y("issue:N", title=None, sort=["1", "N", "2"]),
            # Une couleur fixe par bookmaker, comme la légende de la maquette.
            color=alt.Color("bookmaker:N", title="Bookmaker", legend=None,
                            scale=alt.Scale(domain=noms,
                                            range=[couleurs_books[str(b)] for b in noms])),
            tooltip=["bookmaker", "issue", alt.Tooltip("p:Q", format=".1%")],
        ).properties(height=220)
        st.altair_chart(ch, use_container_width=True)
        theme.legende_books(noms, couleurs_books)
        st.caption("Dispersion entre bookmakers. Points resserrés = marché d'accord.")


# ==========================================================================
elif page == "Mes paris":
    paris_ui.page()


# ==========================================================================
elif page == "Dévig d'un livre":
    st.title("Retirer la marge d'un livre de cotes")
    st.caption("`1 / cote` n'est pas une probabilité : la somme dépasse 1. "
               "La façon dont on redistribue cet excédent change complètement "
               "le résultat sur les outsiders.")

    c1, c2 = st.columns([1, 2])
    with c1:
        n = st.number_input("Nombre d'issues", 2, 12, 3)
        defauts = [1.80, 3.60, 4.80] + [5.0] * 10
        libelles_def = ["Domicile", "Nul", "Extérieur"] + [f"Issue {i}" for i in range(4, 13)]
        cotes, libelles = [], []
        for i in range(int(n)):
            a, b = st.columns([2, 1])
            libelles.append(a.text_input(f"Issue {i+1}", libelles_def[i], key=f"l{i}",
                                         label_visibility="collapsed" if i else "visible"))
            cotes.append(b.number_input(f"Cote {i+1}", 1.01, 1000.0, float(defauts[i]),
                                        step=0.01, key=f"c{i}",
                                        label_visibility="collapsed" if i else "visible"))

    r = analyser_livre(cotes, libelles)
    t = r["probabilites"]

    with c2:
        aff = pd.DataFrame({
            "Issue": t.index, "Cote": t["cote"],
            "Brute 1/c": 100 * t["implicite_brute"],
            "Shin": 100 * t["shin"], "Power": 100 * t["power"],
            "Odds ratio": 100 * t["odds_ratio"], "Proportionnelle": 100 * t["proportional"],
            "Cote juste (Shin)": r["cote_juste_shin"],
        })
        st.dataframe(
            aff.style.format({c: "{:.2f} %" for c in
                              ["Brute 1/c", "Shin", "Power", "Odds ratio", "Proportionnelle"]}
                             | {"Cote": "{:.2f}", "Cote juste (Shin)": "{:.3f}"})
               .background_gradient(cmap=theme.GRADIENT_BLEU, subset=["Shin"]),
            use_container_width=True, hide_index=True)
        st.caption("Le tableau défile horizontalement si la fenêtre est étroite.")

    st.divider()
    k1, k2, k3 = st.columns(3)
    k1.metric("Overround", f"{r['overround']:.4f}",
              help="Somme des probabilités implicites brutes. > 1 = le livre porte une marge.")
    k2.metric("Marge", f"{r['marge_pct']:+.2f} %")
    k3.metric("z (Shin)", f"{r['z_shin']:.4f}",
              help="Part du volume que le modèle de Shin attribue à des parieurs informés.")

    st.subheader("Ce que la normalisation proportionnelle vous ferait croire")
    biais = pd.DataFrame({
        "Issue": t.index,
        "Écart (points)": r["biais_proportionnel_pts"].to_numpy(),
        "Écart relatif (%)": r["biais_proportionnel_rel"].to_numpy(),
    })
    g1, g2 = st.columns([1, 1])
    with g1:
        st.dataframe(biais.style.format({"Écart (points)": "{:+.3f}",
                                         "Écart relatif (%)": "{:+.2f}"}),
                     use_container_width=True, hide_index=True)
    with g2:
        ch = alt.Chart(biais).mark_bar().encode(
            x=alt.X("Écart relatif (%):Q", title="Erreur relative de la proportionnelle (%)"),
            y=alt.Y("Issue:N", sort=None),
            color=alt.condition(alt.datum["Écart relatif (%)"] > 0,
                                alt.value(theme.ROUGE), alt.value(theme.BLEU)),
            tooltip=["Issue", "Écart (points)", "Écart relatif (%)"],
        ).properties(height=40 * len(biais) + 40)
        st.altair_chart(ch, use_container_width=True)

    pire = int(np.argmax(np.abs(r["biais_proportionnel_rel"].to_numpy())))
    st.info(
        f"**Erreur maximale sur « {t.index[pire]} » : "
        f"{r['biais_proportionnel_rel'].iloc[pire]:+.1f} % en relatif.** "
        "Mesuré sur 128 734 matchs réels, ce biais atteint +16,6 % sous 5 % de probabilité "
        "et −1,3 % au-dessus de 70 %. Un moteur d'edge bâti sur la proportionnelle signalerait "
        "des opportunités systématiques et fictives sur les outsiders."
    )


# ==========================================================================
elif page == "Calibration du marché":
    st.title("Le marché est-il bien calibré ?")
    st.caption("Quand le marché annonce 70 %, l'événement arrive-t-il vraiment 70 % du temps ?")

    f1, f2 = st.columns(2)
    codes = ["(tous)"] + sorted(clo.league_code.unique())
    code = f1.selectbox("Championnat", codes)
    methode = f2.selectbox("Méthode de dévig", ["shin", "power", "odds_ratio", "proportional"])
    f3, f4 = st.columns(2)
    an_min, an_max = int(clo.date.dt.year.min()), int(clo.date.dt.year.max())
    annees = f3.slider("Période", an_min, an_max, (an_min, an_max))
    n_bins = f4.slider("Nombre de bins", 5, 25, 12)

    d = clo if code == "(tous)" else clo[clo.league_code == code]
    d = d[(d.date.dt.year >= annees[0]) & (d.date.dt.year <= annees[1])]

    if len(d) < 200:
        st.warning(f"Seulement {len(d)} matchs sur ce filtre. Résultat non interprétable.")
        st.stop()

    y = cible(d)
    p = probabilites_marche(d, "psc", methode)
    courbe = courbe_calibration(p, y, n_bins)
    brier = float(np.mean(np.sum((p - y) ** 2, axis=1)))
    ll = float(-np.mean(np.sum(y * np.log(np.clip(p, 1e-15, 1)), axis=1)))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Matchs", f"{len(d):,}")
    m2.metric("Brier", f"{brier:.5f}")
    m3.metric("Log loss", f"{ll:.5f}")
    m4.metric("ECE", f"{ece(courbe):.5f}", help="Expected calibration error. Plus bas = mieux.")

    if True:
        base = alt.Chart(courbe.assign(annonce=100 * courbe.annonce,
                                       observe=100 * courbe.observe))
        diag = alt.Chart(pd.DataFrame({"x": [0, 100]})).mark_line(
            strokeDash=[6, 4], color="#52525b").encode(x="x:Q", y="x:Q")
        pts = base.mark_circle(size=140, color=theme.BLEU).encode(
            x=alt.X("annonce:Q", title="Probabilité annoncée (%)", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("observe:Q", title="Fréquence observée (%)", scale=alt.Scale(domain=[0, 100])),
            size=alt.Size("n:Q", legend=None, scale=alt.Scale(range=[60, 500])),
            tooltip=[alt.Tooltip("annonce:Q", format=".1f", title="annoncé %"),
                     alt.Tooltip("observe:Q", format=".1f", title="observé %"),
                     alt.Tooltip("n:Q", title="n")])
        ligne = base.mark_line(color=theme.BLEU, opacity=.5).encode(x="annonce:Q", y="observe:Q")
        st.altair_chart((diag + ligne + pts).properties(height=440), use_container_width=True)
        st.caption("Les points sur la diagonale = marché parfaitement calibré. "
                   "La taille du point reflète l'effectif du bin.")

    with st.expander("Détail par bin", expanded=True):
        aff = courbe.assign(annonce=100 * courbe.annonce, observe=100 * courbe.observe)[
            ["annonce", "observe", "n", "ecart_pts"]]
        aff.columns = ["annoncé %", "observé %", "n", "écart pts"]
        st.dataframe(aff.style.format({"annoncé %": "{:.1f}", "observé %": "{:.1f}",
                                       "écart pts": "{:+.2f}"})
                        .background_gradient(cmap=theme.GRADIENT_DIVERGENT,
                                        subset=["écart pts"], vmin=-5, vmax=5),
                     use_container_width=True, hide_index=True)

    if code == "(tous)":
        st.subheader("Comparaison des méthodes de dévig")
        st.caption("Mesuré, pas supposé. L'écart agrégé est minime — "
                   "mais il décide d'où l'on croirait avoir de l'edge.")
        st.dataframe(comparer_methodes(df).style.format(
            {"brier": "{:.6f}", "log_loss": "{:.6f}", "ece": "{:.5f}"}),
            use_container_width=True, hide_index=True)


# ==========================================================================
elif page == "Cartographie":
    st.title("Cartographie des championnats")

    t1, t2 = st.tabs(["Marge du bookmaker", "Information tardive"])

    with t1:
        st.caption("Marge Pinnacle moyenne à la clôture. Proxy d'efficience : "
                   "une marge faible signale un marché sur lequel le book est confiant.")
        m = carte_marges(df)
        ch = alt.Chart(m).mark_bar().encode(
            x=alt.X("marge:Q", title="Marge moyenne (%)"),
            y=alt.Y("league_code:N", sort="x", title=None),
            color=alt.Color("marge:Q", scale=alt.Scale(range=theme.ECHELLE_SEQ_CHAUDE), legend=None),
            tooltip=["country", "league", alt.Tooltip("marge:Q", format=".2f"),
                     alt.Tooltip("n:Q", title="matchs")],
        ).properties(height=22 * len(m) + 30)
        st.altair_chart(ch, use_container_width=True)
        st.dataframe(m.assign(depuis=m.depuis.dt.year, jusqua=m.jusqua.dt.year)
                      [["league_code", "country", "league", "n", "depuis", "jusqua", "marge"]]
                      .style.format({"marge": "{:.2f} %"}),
                     use_container_width=True, hide_index=True)
        st.warning("**Attention à l'interprétation.** Une marge élevée ne signale pas un marché "
                   "exploitable. La corrélation mesurée entre marge et retard d'un modèle "
                   "Dixon-Coles vaut +0,057 — nulle. Une marge élevée traduit l'incertitude du "
                   "bookmaker, laquelle coïncide avec des données plus pauvres pour le modèle.")

    with t2:
        st.caption("Brier(cote précoce) − Brier(clôture) : de combien le prix se bonifie "
                   "entre le relevé de milieu de semaine et le coup d'envoi.")
        t = carte_information_tardive(df)
        if len(t) == 0:
            st.info("Aucune cote précoce disponible.")
        else:
            ch = alt.Chart(t).mark_bar().encode(
                x=alt.X("information_tardive:Q", title="Information tardive (Δ Brier)"),
                y=alt.Y("league_code:N", sort="-x", title=None),
                color=alt.Color("information_tardive:Q",
                                scale=alt.Scale(range=theme.ECHELLE_SEQ_VIOLETTE), legend=None),
                tooltip=["country", "league",
                         alt.Tooltip("information_tardive:Q", format=".5f"),
                         alt.Tooltip("n:Q", title="matchs")],
            ).properties(height=22 * len(t) + 30)
            st.altair_chart(ch, use_container_width=True)
            st.dataframe(t[["league_code", "country", "league", "n", "brier_precoce",
                            "brier_cloture", "information_tardive"]].style.format(
                {"brier_precoce": "{:.5f}", "brier_cloture": "{:.5f}",
                 "information_tardive": "{:.5f}"}),
                use_container_width=True, hide_index=True)
            st.info("**Lecture.** Élevé = beaucoup d'information arrive tard, miser tôt est "
                    "risqué. Faible = le prix précoce est déjà quasi définitif, miser tôt "
                    "n'apporte rien. Le total mesuré ne dépasse jamais 0,006 de Brier — "
                    "six fois moins que le retard d'un modèle Dixon-Coles sur ce même prix.")


# ==========================================================================
elif page == "Explorateur de matchs":
    st.title("Explorateur de matchs")
    st.caption("Probabilités de marché dévigées par Shin, avec le résultat réel.")

    f1, f2, f3 = st.columns(3)
    code = f1.selectbox("Championnat", sorted(clo.league_code.unique()),
                        index=sorted(clo.league_code.unique()).index("E0")
                        if "E0" in set(clo.league_code) else 0)
    d = clo[clo.league_code == code]
    saisons = sorted(d.season.astype(str).unique(), reverse=True)
    saison = f2.selectbox("Saison", saisons)
    d = d[d.season.astype(str) == saison]
    equipes = ["(toutes)"] + sorted(set(d.home_team) | set(d.away_team))
    eq = f3.selectbox("Équipe", equipes)
    if eq != "(toutes)":
        d = d[(d.home_team == eq) | (d.away_team == eq)]

    if len(d) == 0:
        st.info("Aucun match.")
        st.stop()

    p = probabilites_marche(d, "psc", "shin")
    vue = pd.DataFrame({
        "Date": d.date.dt.date.to_numpy(),
        "Domicile": d.home_team.to_numpy(),
        "Extérieur": d.away_team.to_numpy(),
        "Score": [f"{h}–{a}" for h, a in zip(d.home_goals, d.away_goals)],
        "Rés.": d.result.to_numpy(),
        "P(1) %": 100 * p[:, 0], "P(N) %": 100 * p[:, 1], "P(2) %": 100 * p[:, 2],
        "Cote 1": d.psc_h.to_numpy(), "Cote N": d.psc_d.to_numpy(), "Cote 2": d.psc_a.to_numpy(),
    })
    st.dataframe(
        vue.style.format({c: "{:.1f}" for c in ["P(1) %", "P(N) %", "P(2) %"]}
                         | {c: "{:.2f}" for c in ["Cote 1", "Cote N", "Cote 2"]})
           .background_gradient(cmap=theme.GRADIENT_BLEU,
                               subset=["P(1) %", "P(N) %", "P(2) %"]),
        use_container_width=True, hide_index=True, height=560)

    y = cible(d)
    st.caption(f"{len(d)} matchs · Brier du marché sur cette sélection : "
               f"{float(np.mean(np.sum((p - y) ** 2, axis=1))):.5f}")


# ==========================================================================
elif page == "Collecte en cours":
    import sqlite3
    from odds.data.collect import BASE_DONNEES, resume

    st.title("Collecte de cotes")
    st.caption("Historique constitué par nous, horodaté par nous. Pinnacle n'étant plus "
               "publié après le 2026-01-14, c'est la seule source de mesure en avant.")

    if not Path(BASE_DONNEES).exists():
        st.info("Aucune collecte encore enregistrée.\n\n"
                "Lancez :  `uv run odds collect`")
        st.stop()

    r = resume()
    if r["lignes"] == 0:
        st.info("Base créée mais vide. Lancez :  `uv run odds collect`")
        st.stop()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Observations", f"{r['lignes']:,}")
    m2.metric("Matchs suivis", f"{r['matchs']:,}")
    m3.metric("Passes", f"{r['runs']:,}")
    duree = pd.Timestamp(r["jusqua"]) - pd.Timestamp(r["depuis"])
    m4.metric("Profondeur", f"{duree.days} j" if duree.days else
              f"{int(duree.total_seconds() // 3600)} h")
    st.caption(f"{r['depuis']} → {r['jusqua']} (UTC)")

    runs = r["derniers_runs"].copy()
    derniere = runs.iloc[0] if len(runs) else None
    if derniere is not None and pd.notna(derniere.erreur):
        st.error(f"**La dernière passe a échoué** : {derniere.erreur}\n\n"
                 "Voir `logs/collect.err`.")
    elif runs.erreur.notna().any():
        n_ko = int(runs.erreur.notna().sum())
        st.success(f"Dernière passe au vert. ({n_ko} passe(s) en échec plus tôt dans "
                   "l'historique — conservées telles quelles.)")
    else:
        st.success("Toutes les passes récentes au vert.")

    if _c:
        from odds.data.collect import conso_credits
        from odds.data.oddsapi import projection

        st.subheader("Crédits The Odds API")
        conso = conso_credits()
        actifs = conso[conso.credits > 0].tail(7) if len(conso) else conso
        par_jour = float(actifs.credits.mean()) if len(actifs) else 0.0
        p = projection(_c["restants"], par_jour)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Restants", f"{_c['restants']:,}", f"sur {_c['total']:,}",
                  delta_color="off")
        k2.metric("Rythme", f"{par_jour:.1f} /jour",
                  help="Moyenne sur les 7 derniers jours où des crédits ont été consommés.")
        k3.metric("Jours avant réinit.", p["jours_restants_mois"])
        k4.metric("Besoin d'ici là", f"{p['besoin_fin_de_mois']:.0f}",
                  "✅ suffisant" if p["suffisant"] else "⚠️ insuffisant",
                  delta_color="normal" if p["suffisant"] else "inverse")

        st.progress(min(1.0, _c["part_utilisee"]),
                    text=f"{100 * _c['part_utilisee']:.1f} % du quota mensuel consommé")

        if not p["suffisant"] and par_jour > 0:
            st.error(f"Au rythme actuel, épuisement estimé le **{p['epuisement']}**, "
                     f"avant la réinitialisation. Réduisez `ODDS_API_SPORTS` ou "
                     f"`ODDS_API_BUDGET_JOUR`.")

        if len(conso) > 1:
            ch = alt.Chart(conso).mark_bar().encode(
                x=alt.X("jour:N", title=None),
                y=alt.Y("credits:Q", title="Crédits consommés"),
                tooltip=["jour", "credits", "passes"],
            ).properties(height=180)
            st.altair_chart(ch, use_container_width=True)

        ecart = _c["utilises"] - int(conso.credits.sum() if len(conso) else 0)
        if ecart > 0:
            st.caption(f"ℹ️ Le compteur de l'API indique {_c['utilises']:,} crédits utilisés, "
                       f"contre {int(conso.credits.sum()):,} enregistrés par nos passes "
                       f"({ecart:,} d'écart). L'écart correspond aux appels faits hors "
                       "collecte — exploration manuelle, ou anciens lancements de tests "
                       "avant la mise en place du garde-fou.")

    st.subheader("Fraîcheur des flux amont")
    fx = r.get("flux", pd.DataFrame())
    if len(fx):
        vfx = pd.DataFrame({
            "Flux": fx.flux,
            "Publié le": fx.last_modified,
            "Âge (h)": fx.age_heures,
            "Matchs": fx.n_matchs,
            "Couvre du": fx.date_min,
            "au": fx.date_max,
            "Statut": np.where(fx.perime, "⚠️ en retard", "✅ à jour"),
        })
        st.dataframe(vfx.style.format({"Âge (h)": "{:.1f}"}),
                     use_container_width=True, hide_index=True)
        st.caption("football-data publie ses fixtures environ deux fois par semaine "
                   "(milieu de semaine, puis avant le week-end). Entre deux publications, "
                   "aucune nouvelle date n'apparaît — ce n'est pas une panne du collecteur.")
    else:
        st.caption("Pas encore d'état de flux enregistré.")

    st.subheader("Couverture par bookmaker")
    b = r["bookmakers"].copy()
    b["rôle"] = np.where(b.bookmaker == "betfair_exchange", "benchmark",
                np.where(b.bookmaker.str.startswith("_"), "agrégat", "book"))
    st.dataframe(b, use_container_width=True, hide_index=True)
    st.caption("**betfair_exchange** est le benchmark retenu en avant : "
               "prix réellement négociable, seul substitut sérieux à Pinnacle.")

    st.subheader("Dernières passes")
    runs["statut"] = np.where(runs.erreur.notna(), "⚠️ erreur", "✅")
    st.dataframe(runs[["run_id", "matchs", "lignes_vues", "lignes_ecrites", "statut", "erreur"]],
                 use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Mouvement des cotes")
    con = sqlite3.connect(BASE_DONNEES)
    matchs = pd.read_sql(
        "SELECT fixture_key, league, kickoff, home_team, away_team, "
        "COUNT(*) n, COUNT(DISTINCT observed_at) points "
        "FROM odds_snapshot GROUP BY fixture_key "
        "ORDER BY points DESC, kickoff DESC LIMIT 200", con)

    if matchs.points.max() < 2:
        st.info("Une seule observation par match pour l'instant — il faut au moins deux "
                "passes espacées pour tracer un mouvement. L'agent collecte toutes les heures.")
        con.close()
        st.stop()

    matchs["libelle"] = (matchs.kickoff.str[:16] + " · " + matchs.home_team
                         + " – " + matchs.away_team + f"  ({matchs.points} pts)")
    choix = st.selectbox("Match", matchs.libelle.tolist())
    fk = matchs.loc[matchs.libelle == choix, "fixture_key"].iloc[0]
    serie = pd.read_sql(
        "SELECT observed_at, bookmaker, market, selection, odds FROM odds_snapshot "
        "WHERE fixture_key = ? AND market = '1X2' ORDER BY observed_at", con, params=(fk,))
    con.close()

    serie["observed_at"] = pd.to_datetime(serie.observed_at)
    ch = alt.Chart(serie).mark_line(point=True).encode(
        x=alt.X("observed_at:T", title="Observé à (UTC)"),
        y=alt.Y("odds:Q", title="Cote", scale=alt.Scale(zero=False)),
        color=alt.Color("selection:N", title="Issue"),
        strokeDash=alt.StrokeDash("bookmaker:N", title="Bookmaker"),
        tooltip=["observed_at:T", "bookmaker", "selection",
                 alt.Tooltip("odds:Q", format=".2f")],
    ).properties(height=380)
    st.altair_chart(ch, use_container_width=True)
    st.caption("Seuls les CHANGEMENTS sont enregistrés : une cote stable ne "
               "produit pas de nouveau point.")
