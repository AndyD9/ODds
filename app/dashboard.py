"""Tableau de bord — analyse des probabilités de marché.

Périmètre assumé : cet outil ne produit AUCUN signal de pari. Il a été établi
(research/RESULTS.md) qu'un modèle de comptage sur données publiques ne bat ni
la clôture ni le prix précoce. Ce qui reste utile et vérifié : retirer
correctement la marge, mesurer la calibration, cartographier les marchés.
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

from odds.analysis import (AGREGATS, AUTRE_INSTANT, analyser_livre, avec_cloture,
                           carte_information_tardive, carte_marges, charger, cible,
                           comparer_methodes, courbe_calibration, dates_disponibles,
                           ece, matchs_a_la_date, probabilites_marche)

st.set_page_config(page_title="Analyse des probabilités de marché",
                   page_icon="📊", layout="wide")

COULEURS = {"shin": "#2563eb", "power": "#059669",
            "odds_ratio": "#d97706", "proportional": "#dc2626"}


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
page = st.sidebar.radio("Page", ["Matchs par date", "Dévig d'un livre",
                                 "Calibration du marché", "Cartographie",
                                 "Explorateur de matchs", "Collecte en cours"])
st.sidebar.caption(
    f"{len(df):,} matchs · {len(clo):,} avec clôture Pinnacle\n\n"
    f"{clo.date.min().date()} → {clo.date.max().date()}"
)
st.sidebar.warning("Cet outil ne produit **aucun signal de pari**. "
                   "Voir `research/RESULTS.md`.")


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

    # --- les deux lectures, explicitement séparées -------------------------
    st.subheader("Quelle issue ?")
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**① Ce que le marché juge le plus probable**")
        st.caption("Lecture factuelle des probabilités, marge retirée. "
                   "**Ce n'est pas une recommandation de pari** : au prix juste, miser sur le "
                   "favori a une espérance nulle. Le marché a déjà tout intégré — c'est "
                   "précisément ce qu'a établi `research/RESULTS.md`.")
    with g2:
        st.markdown("**② Où le meilleur prix s'écarte le plus du consensus**")
        st.caption("Price shopping : `(probabilité consensus × meilleure cote) − 1`. "
                   "Observation sur la **dispersion des prix**, pas une prédiction. "
                   "Biaisé à la hausse — le maximum sur N bookmakers retient "
                   "disproportionnellement la cote périmée ou erronée, et l'effet est "
                   "maximal sur les gros outsiders.")

    n_desaccord = int((~res.accord).sum())
    if n_desaccord:
        st.warning(f"**Les deux lectures divergent sur {n_desaccord} match(s) sur {len(res)}.** "
                   "Quand elles divergent, c'est presque toujours parce qu'un bookmaker affiche "
                   "un prix isolé sur un outsider — le cas où l'indicateur ② est le moins fiable.")

    st.subheader("Matchs du jour")
    lib = {"1": "Domicile", "N": "Nul", "2": "Extérieur"}

    def nom_book(b):
        """Un agrégat n'est pas un endroit où miser : le dire explicitement."""
        return {"_max_marche": "⌀ meilleur du marché",
                "_moyenne_marche": "⌀ moyenne marché"}.get(b, b)
    vue = pd.DataFrame({
        "Heure": res.kickoff.str[11:16],
        "Champ.": res.league.astype(str),
        "Domicile": res.home_team, "Extérieur": res.away_team,
        "P(1) %": 100 * res.p_1, "P(N) %": 100 * res.p_N, "P(2) %": 100 * res.p_2,
        "① Marché": res.issue_probable.map(lib),
        "① Prob. %": 100 * res.p_probable,
        "② Prix": res.issue_prix.map(lib),
        "② Cote": res.cote_prix,
        "② Chez": res.book_prix.map(nom_book),
        "② Écart %": res.ecart_prix,
        "Accord": np.where(res.accord, "✓", "✗"),
        "Books": res.n_books, "Marge %": res.marge, "Dispersion": res.dispersion,
    })
    if historique and "score" in res.columns:
        vue.insert(4, "Score", res.score.to_numpy())
        vue.insert(5, "Rés.", res.resultat.map(
            {"H": "Domicile", "D": "Nul", "A": "Extérieur"}).to_numpy())

    st.dataframe(
        vue.style.format({**{c: "{:.1f}" for c in ["P(1) %", "P(N) %", "P(2) %", "① Prob. %"]},
                          **{c: "{:.2f}" for c in ["② Cote", "Marge %", "Dispersion"]},
                          "② Écart %": "{:+.2f}"})
           .background_gradient(cmap="Blues", subset=["P(1) %", "P(N) %", "P(2) %"])
           .background_gradient(cmap="RdYlGn", subset=["② Écart %"], vmin=-5, vmax=5),
        use_container_width=True, hide_index=True, height=min(560, 44 + 36 * len(vue)))

    st.caption("**① Marché** = issue la plus probable selon les cotes dévigées. "
               "**② Prix** = issue dont le meilleur prix disponible s'écarte le plus du "
               "consensus, avec le bookmaker qui l'affiche. Les deux répondent à des "
               "questions différentes et ne sont pas interchangeables.")

    st.divider()
    st.subheader("Détail d'un match")
    libelles = (res.kickoff.str[11:16] + " · " + res.home_team + " – " + res.away_team
                + " (" + res.league.astype(str) + ")")
    choix = st.selectbox("Match", libelles.tolist())
    ligne = res.loc[libelles == choix].iloc[0]
    fk = ligne.fixture_key

    d1, d2, d3 = st.columns(3)
    d1.metric("① Marché juge le plus probable", lib[ligne.issue_probable],
              f"{100 * ligne.p_probable:.1f} %", delta_color="off")
    d2.metric("② Meilleur écart de prix", lib[ligne.issue_prix],
              f"{ligne.ecart_prix:+.2f} %", delta_color="normal")
    d3.metric("② Meilleure cote", f"{ligne.cote_prix:.2f}",
              nom_book(ligne.book_prix), delta_color="off")
    if str(ligne.book_prix).startswith("_"):
        st.caption("⌀ = agrégat de marché, pas un bookmaker : cette cote indique le meilleur "
                   "prix constaté, sans dire chez qui. Voir le tableau livre par livre.")
    if not ligne.accord:
        st.warning("Les deux lectures divergent sur ce match. ② porte sur une issue que le "
                   "marché juge moins probable : vérifiez dans le tableau ci-dessous si "
                   "un seul bookmaker est à l'origine de l'écart.")
    d = det[det.fixture_key == fk].copy()
    d["type"] = np.where(d.bookmaker.isin(AGREGATS), "agrégat",
                np.where(d.bookmaker.isin(AUTRE_INSTANT), "autre instant", "book"))
    d = d.sort_values(["type", "bookmaker"])

    c1, c2 = st.columns([3, 2])
    with c1:
        st.dataframe(
            pd.DataFrame({
                "Bookmaker": d.bookmaker, "Type": d.type,
                "Cote 1": d.cote_1, "Cote N": d.cote_N, "Cote 2": d.cote_2,
                "P(1) %": 100 * d.p_1, "P(N) %": 100 * d.p_N, "P(2) %": 100 * d.p_2,
                "Marge %": d.marge,
            }).style.format({**{c: "{:.2f}" for c in ["Cote 1", "Cote N", "Cote 2", "Marge %"]},
                             **{c: "{:.1f}" for c in ["P(1) %", "P(N) %", "P(2) %"]}}),
            use_container_width=True, hide_index=True)
        st.caption("« autre instant » = même bookmaker relevé plus tôt. Exclu du consensus "
                   "et du meilleur prix : ce n'est pas un concurrent, et cette cote n'est "
                   "plus disponible.")
    with c2:
        longd = d[d.type == "book"].melt(
            id_vars="bookmaker", value_vars=["p_1", "p_N", "p_2"],
            var_name="issue", value_name="p")
        longd["issue"] = longd.issue.map({"p_1": "1", "p_N": "N", "p_2": "2"})
        ch = alt.Chart(longd).mark_circle(size=110, opacity=.85).encode(
            x=alt.X("p:Q", title="Probabilité (marge retirée)", axis=alt.Axis(format="%")),
            y=alt.Y("issue:N", title=None, sort=["1", "N", "2"]),
            color=alt.Color("bookmaker:N", title="Bookmaker"),
            tooltip=["bookmaker", "issue", alt.Tooltip("p:Q", format=".1%")],
        ).properties(height=220)
        st.altair_chart(ch, use_container_width=True)
        st.caption("Dispersion entre bookmakers. Points resserrés = marché d'accord.")


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
               .background_gradient(cmap="Blues", subset=["Shin"]),
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
                                alt.value("#dc2626"), alt.value("#2563eb")),
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
            strokeDash=[6, 4], color="#94a3b8").encode(x="x:Q", y="x:Q")
        pts = base.mark_circle(size=140, color="#2563eb").encode(
            x=alt.X("annonce:Q", title="Probabilité annoncée (%)", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("observe:Q", title="Fréquence observée (%)", scale=alt.Scale(domain=[0, 100])),
            size=alt.Size("n:Q", legend=None, scale=alt.Scale(range=[60, 500])),
            tooltip=[alt.Tooltip("annonce:Q", format=".1f", title="annoncé %"),
                     alt.Tooltip("observe:Q", format=".1f", title="observé %"),
                     alt.Tooltip("n:Q", title="n")])
        ligne = base.mark_line(color="#2563eb", opacity=.5).encode(x="annonce:Q", y="observe:Q")
        st.altair_chart((diag + ligne + pts).properties(height=440), use_container_width=True)
        st.caption("Les points sur la diagonale = marché parfaitement calibré. "
                   "La taille du point reflète l'effectif du bin.")

    with st.expander("Détail par bin", expanded=True):
        aff = courbe.assign(annonce=100 * courbe.annonce, observe=100 * courbe.observe)[
            ["annonce", "observe", "n", "ecart_pts"]]
        aff.columns = ["annoncé %", "observé %", "n", "écart pts"]
        st.dataframe(aff.style.format({"annoncé %": "{:.1f}", "observé %": "{:.1f}",
                                       "écart pts": "{:+.2f}"})
                        .background_gradient(cmap="RdBu", subset=["écart pts"], vmin=-5, vmax=5),
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
            color=alt.Color("marge:Q", scale=alt.Scale(scheme="yelloworangered"), legend=None),
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
                                scale=alt.Scale(scheme="purples"), legend=None),
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
           .background_gradient(cmap="Blues", subset=["P(1) %", "P(N) %", "P(2) %"]),
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
