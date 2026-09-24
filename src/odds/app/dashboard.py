"""Tableau de bord — probabilités de marché et marchés de buts.

Périmètre (prereg 0003 §1) : outil personnel à usage éducatif, suivi de paris
en **papier** uniquement. Ce qu'il montre est encadré par deux mesures : ni
Dixon-Coles ni aucune dérivation ne bat le prix de marché, sur le 1X2
(RESULTS R8) comme sur les buts (R9). Le prix reste la meilleure information
disponible ; l'outil sert à le lire correctement, pas à prétendre le battre.
"""

from __future__ import annotations

import sys
from html import escape
from pathlib import Path

# Hébergé sans installation du paquet (decisions/0009) : ``src`` doit être
# sur le chemin pour que ``odds`` s'importe. Sans effet quand il l'est déjà.
_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from odds import chemins, paper, stockage
from odds.app import acces, buts_ui, couverture_ui, paris_ui, theme
from odds.app.libelles import bookmaker, championnat, date_longue
from odds.analysis.fiabilite import tranche_fiabilite
from odds.analysis import (AGREGATS, AUTRE_INSTANT, N_BOOKS_MINI, SEUIL_COTE_SURE,
                           SEUIL_EV_MINI, SEUIL_P_SUR, SEUIL_PRIME_ISOLEE,
                           SOUTIEN_MINI, VERDICT_VALEUR, _niveau,
                           analyser_livre, avec_cloture, carte_information_tardive,
                           carte_marges, charger, cible, comparer_methodes,
                           courbe_calibration, dates_disponibles, ece,
                           fiabilite_historique, matchs_a_la_date, paris_surs,
                           probabilites_marche)

st.set_page_config(page_title="Analyse des probabilités de marché",
                   page_icon="📊", layout="wide")
theme.appliquer()

# Qui entre (decisions/0009). En local : personne n'est demandé, rien ne
# change. Hébergé : connexion, liste d'invités, et l'adresse devient
# l'utilisateur du carnet pour toute cette exécution.
utilisateur = acces.ouvrir()


@st.cache_resource(show_spinner="Récupération de l'état…")
def _etat_au_demarrage(actif: bool) -> list[str]:
    """Une fois par processus : ramène l'état depuis le seau, s'il y en a un.

    ``actif`` fait partie de la clé de cache : si les secrets arrivent après
    le premier rendu, le rapatriement se fait au rendu suivant au lieu de
    rester mémorisé comme « rien à faire ».
    """
    return stockage.demarrer() if actif else []


@st.cache_data(ttl=300, show_spinner=False)
def _collecte_a_jour() -> bool:
    """Au plus toutes les cinq minutes : la base de collecte a-t-elle bougé ?

    Le collecteur écrit ailleurs ; quand son empreinte change, on ramène le
    fichier. Aucun cache de l'application ne dépend de cette base — les
    matchs du jour sont relus à chaque exécution — donc rien à vider.
    """
    return stockage.rafraichir(chemins.BDD_COLLECTE)


_etat_au_demarrage(stockage.actif())
_collecte_a_jour()

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
    # Hébergée, l'application n'a pas de disque durable : ses données viennent
    # du seau. Si ce fichier manque, c'est presque toujours que les secrets
    # Supabase ne sont pas lus — le dire vaut mieux qu'un chemin introuvable.
    if stockage.actif():
        st.error(f"{e}\n\nLa copie distante est configurée mais ne contient pas ce fichier. "
                 "Depuis le poste : `uv run odds etat pousser`.")
    else:
        from odds import config
        st.error("Aucune configuration Supabase n'est lue : `SUPABASE_URL` et "
                 "`SUPABASE_SERVICE_KEY` manquent dans les secrets de l'application "
                 "(Community Cloud → Manage app → Settings → Secrets). Sans eux, l'application "
                 f"hébergée n'a pas de données.\n\nDiagnostic : {config.diagnostic_secrets()}"
                 f"\n\nDétail : {e}")
    st.stop()

clo = avec_cloture(df)

st.sidebar.title("Probabilités de marché")
acces.barre_laterale(utilisateur)

# Navigation en deux groupes : l'outil (ce qu'on ouvre chaque jour) et la
# recherche (ce qu'on consulte pour comprendre). Deux radios, une seule
# sélection : choisir dans l'un vide l'autre.
PAGES_OUTIL = ["Matchs par date", "Mes paris", "Collecte en cours"]
PAGES_RECHERCHE = ["Dévig d'un livre", "Calibration du marché", "Cartographie",
                   "Explorateur de matchs"]


def _naviguer(groupe: str) -> None:
    autre = "nav_recherche" if groupe == "nav_outil" else "nav_outil"
    if st.session_state.get(groupe) is not None:
        st.session_state[autre] = None


if "nav_outil" not in st.session_state:
    st.session_state["nav_outil"] = "Matchs par date"
    st.session_state["nav_recherche"] = None
st.sidebar.radio("Outil", PAGES_OUTIL, key="nav_outil",
                 on_change=_naviguer, args=("nav_outil",))
st.sidebar.radio("Recherche", PAGES_RECHERCHE, key="nav_recherche",
                 on_change=_naviguer, args=("nav_recherche",))
page = (st.session_state.get("nav_outil") or st.session_state.get("nav_recherche")
        or "Matchs par date")

# Les pages qui ont des réglages experts les posent ici, repliés, sous la
# navigation et avant les crédits.
reglages_sidebar = st.sidebar.container()


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
    st.sidebar.caption(f"Compteur de crédits indisponible : {_e}")

if _c:
    st.sidebar.divider()
    st.sidebar.caption(f"**Crédits The Odds API** · {_c['restants']:,} restants "
                       f"sur {_c['total']:,} ce mois-ci")
    st.sidebar.progress(min(1.0, _c["part_utilisee"]))

# Pied de barre : le cadrage, vrai sans être crié.
st.sidebar.divider()
st.sidebar.caption(
    f"{len(df):,} matchs · {len(clo):,} avec clôture Pinnacle · "
    f"{clo.date.min().date()} → {clo.date.max().date()}")
st.sidebar.caption(
    "Outil personnel, paris en papier uniquement. Aucun modèle ici ne bat le "
    "prix de marché, ni sur le 1X2 (R8) ni sur les buts (R9) : l'outil sert à "
    "lire le prix, pas à le battre.")


# ==========================================================================
if page == "Matchs par date":
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

    # Réglage expert hors du chemin principal : le verdict « écart soutenu »
    # exige le même signe sous les quatre méthodes, ce choix ne le change
    # donc pas. Il vit dans la barre latérale, replié, défaut Shin.
    with reglages_sidebar, st.expander("Réglages avancés"):
        methode = st.selectbox(
            "Méthode de dévig", ["shin", "power", "odds_ratio", "proportional"],
            help="Le verdict « écart soutenu » exige le même signe sous les quatre "
                 "méthodes : ce choix déplace les chiffres, pas la décision.")
        # prereg 0006 : les deux seuils de « sûr et payant ». Réglables parce
        # qu'ils se contraignent l'un l'autre — la cote juste d'un favori à p
        # vaut 1/p — et que le bon compromis se lit sur la page, pas dans le
        # code. Le défaut du premier est la borne du niveau « Élevée » de la
        # table de confiance ; le déplacer change le niveau affiché.
        # En points de pourcentage : un curseur de 0,55 à 0,92 s'affiche
        # « 1 % » sous tous les formats entiers de Streamlit.
        p_min_sur = st.slider(
            "« Sûr » : probabilité minimale (%)", 55, 92, int(100 * SEUIL_P_SUR), 1,
            help="Le défaut est le seuil de la confiance « élevée ». La table de "
                 "fiabilité mesure ce que vaut ce niveau : à 70 % annoncés, "
                 "l'issue s'est produite 74,5 % du temps sur 5 028 matchs ; "
                 "à 80 %, 83,6 % sur 2 174.") / 100.0
        cote_min_sure = st.slider(
            "« Payant » : cote nette minimale", 1.05, 2.00, SEUIL_COTE_SURE, 0.01,
            help="Le gain en dessous duquel le pari ne vous intéresse pas. La cote "
                 "juste d'un favori à 70 % vaut 1,43, à 80 % 1,25 : tant que ce "
                 "plancher reste sous la cote juste, c'est l'écart au consensus "
                 "qui décide, pas lui.")

    # En-tête : la date en clair est le titre ; le sélecteur et le filtre de
    # championnats sont à sa droite. Le filtre est rempli plus bas, une fois
    # les matchs du jour connus.
    e1, e2, e3 = st.columns([2.4, 1, 1.6], vertical_alignment="bottom")
    jour = e2.date_input(
        "Date", value=defaut, min_value=pd.Timestamp(dispo["historique"][0]).date(),
        max_value=max_selectionnable,
        help=("Cotes collectées disponibles pour : " + ", ".join(collecte_jours[-6:]))
        if collecte_jours else None)
    e1.title(date_longue(jour) + (" · aujourd'hui" if jour == aujourdhui else ""))

    # --- fraîcheur du flux amont ------------------------------------------
    # Une journée vide vient presque toujours de la source, pas de nous :
    # football-data ne publie ses fixtures que deux fois par semaine environ.
    try:
        from odds.data.collect import etat_flux
        fx = etat_flux()
    except Exception:
        fx = pd.DataFrame()

    # La fraîcheur va dans la ligne de statut ; seul un flux en retard mérite
    # un bandeau. La publication par à-coups est expliquée là où elle se
    # voit : sur une journée vide.
    # Streamlit Cloud relance ce script au push sans réimporter `odds` : un
    # `etat_flux` d'avant la trêve peut encore tourner. Sans ses colonnes, on
    # retombe sur le jugement par l'âge seul au lieu de planter.
    if len(fx) and "treve" not in fx:
        fx = fx.assign(treve=False, prochain_annonce=pd.NaT)
    flux_txt = ""
    if len(fx):
        pub = fx.last_modified_dt.max()
        couv_max = fx.date_max.max()
        age = float(fx.age_heures.max())
        flux_txt = f"flux publié il y a {age:.0f} h, couvre jusqu'au {couv_max}"
        if fx.treve.any():
            flux_txt += (" · trêve : aucun match annoncé avant le "
                         f"{date_longue(fx.prochain_annonce.iloc[0].date()).lower()}")
        if fx.perime.any():
            # Hébergée, la collecte tourne sur GitHub Actions : le journal
            # local n'y reçoit plus rien.
            ou = ("les passes « Collecte des cotes » dans l'onglet Actions du dépôt"
                  if stockage.actif() else "`logs/collect.err`")
            st.error(f"**Le flux amont semble en retard** : publié le "
                     f"{pub:%a %d %b %H:%M UTC}, il y a {age:.0f} h. "
                     f"Vérifiez {ou}.")

    with st.spinner("Calcul…"):
        r = matchs_a_la_date(jour, methode)

    if r.vide:
        st.info(f"**Aucun match au {jour}.**")
        if (jour >= aujourdhui and len(fx) and fx.treve.any()
                and jour < fx.prochain_annonce.iloc[0].date()):
            st.markdown(
                "**Trêve** : aucun des championnats suivis par The Odds API n'annonce "
                "de match avant le "
                f"{date_longue(fx.prochain_annonce.iloc[0].date()).lower()}. "
                "football-data n'a donc rien de nouveau à publier : ce n'est pas une panne.")
        elif jour >= aujourdhui and len(fx):
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

    res_tout, det = r.resume, r.detail
    historique = r.source == "historique"

    # --- filtre championnat, dans l'en-tête --------------------------------
    ligues = sorted(res_tout.league.astype(str).unique())
    choisies = e3.multiselect(
        f"Championnats ({len(ligues)})", ligues, default=ligues, format_func=championnat,
        help="Vide = tous les championnats.")
    res = res_tout[res_tout.league.astype(str).isin(choisies)] if choisies else res_tout
    res = res.reset_index(drop=True)

    if len(res) == 0:
        st.warning("Aucun championnat sélectionné.")
        st.stop()

    # --- une ligne de statut à la place de cinq bandeaux --------------------
    # Source, volume, fraîcheur et les médianes qui décrivent la journée. Un
    # bandeau coloré n'apparaît que si quelque chose est anormal.
    if historique:
        statut = (f"Historique · cotes de clôture Pinnacle, résultat connu · "
                  f"{len(res)} matchs sur {len(res_tout)} ce jour-là")
    else:
        fournisseur = r.fournisseur or "football-data"
        nom = {"odds-api": "The Odds API", "football-data": "football-data.co.uk"}.get(
            fournisseur, fournisseur)
        statut = (f"{nom} · {len(res)} matchs sur {len(res_tout)} collectés · "
                  f"jusqu'à {int(res_tout.n_books.max())} bookmakers · "
                  f"marge médiane {res.marge.median():.2f} % · "
                  f"dispersion médiane {res.dispersion.median():.2f} pt")
        if fournisseur == "football-data":
            statut += (" · fixtures publiées deux fois par semaine, journée "
                       "peut-être incomplète")
    if flux_txt:
        statut += " · " + flux_txt
    st.caption(statut)

    lib = {"1": "Domicile", "N": "Nul", "2": "Extérieur"}

    nom_book = bookmaker

    def nom_issue(r, code: str) -> str:
        return {"1": r.home_team, "N": "Match nul", "2": r.away_team}[code]

    # Libellé unique par match : c'est la clé du sélecteur « Détail d'un
    # match », et ce que le bouton d'une carte y dépose.
    libelles = (res.kickoff.str[11:16] + " · " + res.home_team + " – " + res.away_team
                + " (" + res.league.astype(str).map(championnat) + ")")

    def _choisir(libelle: str, origine: dict | None = None) -> None:
        st.session_state["match_choisi"] = libelle
        # D'où vient ce pari : prereg 0006 §5 demande que les paris pris au
        # titre de « sûr et payant » soient suivis à part, sans quoi leur CLV
        # se noierait dans celui des écarts de prix. Le formulaire n'inscrit
        # la marque que si l'issue finalement choisie est bien celle de la
        # carte : l'utilisateur reste libre d'en prendre une autre.
        st.session_state["origine_pari"] = origine

    def statut_issue(r) -> tuple[str, str, bool]:
        """Dit en clair si l'issue visée par le prix est le favori du marché.

        Une cote au-dessus du consensus tombe souvent sur un outsider : sans
        cette ligne, « Elche CF · +3,3 % » se lit comme un pronostic de
        victoire, ce qu'il n'est pas. Renvoie l'étiquette courte, le détail
        chiffré et ``True`` si l'issue est le favori du marché.
        """
        p = 100 * r.p_prix
        if r.issue_prix == r.issue_probable:
            return "Favori du marché", f"{p:.0f} % pour le marché", True
        return ("Outsider",
                f"{p:.0f} % pour le marché · favori : "
                f"{nom_issue(r, r.issue_probable)} {100 * r.p_probable:.0f} %", False)

    # --- la décision d'abord ------------------------------------------------
    # La page répond à « qu'est-ce que je parie aujourd'hui ? » : la réponse
    # vient en tête, une carte par écart soutenu. Le tableau et le détail
    # suivent, comme preuve. Les écarts fragiles ou isolés sont nommés et
    # écartés en une ligne atténuée : un +9 % rouge ne doit pas voler le
    # regard au +3 % vert qui, lui, tient.
    if not historique:
        # Règle d'affichage choisie par l'utilisateur (2026-09-18) : parmi
        # les écarts soutenus — donc à espérance positive et robuste — le
        # plus probable d'abord, même si son espérance est la plus faible.
        # L'espérance filtre, la probabilité ordonne.
        prises = (res[res.verdict == VERDICT_VALEUR]
                  .sort_values(["p_prix", "ecart_prix"], ascending=[False, False]))
        bruit = res[(res.verdict != VERDICT_VALEUR) & np.isfinite(res.ecart_prix)
                    & (res.ecart_prix > 0)
                    & res.verdict.isin(["Écart isolé — prudence",
                                        "Fragile — dépend de la méthode"])]
        n_p = len(prises)

        def proposition(proba: float, cote_nette: float, robuste: bool,
                        n_books: int) -> dict | None:
            """Proposition du moteur de prereg §4 pour une issue et son prix.

            C'est ici que la probabilité entre en jeu : à espérance égale,
            Kelly mise moins sur l'issue improbable, et la confiance mesurée
            sur la tranche de probabilité module encore la mise.
            """
            try:
                b = paper.bankroll()
                tr = tranche_fiabilite(float(proba), methode)
                return paper.proposer_mise(
                    bankroll=b["courante"], p=float(proba), cote=float(cote_nette),
                    exposition=b["exposition"], n_hist=int(tr.n),
                    n_books=int(n_books), ev_robuste=bool(robuste), p_cotee=True)
            except Exception:
                return None

        def mise_proposee(p) -> dict | None:
            """Proposition pour l'issue visée par le prix."""
            return proposition(p.p_prix, p.cote_nette_prix, p.ev_robuste, p.n_books)

        # --- sûr et payant (prereg 0006) --------------------------------
        # Ce que l'utilisateur vient chercher d'abord : un favori net, payé
        # au-dessus du consensus. Les deux seuils se contraignent — la cote
        # juste d'un favori à p est 1/p — et la page le dit quand elle ne
        # trouve rien, au lieu de laisser croire à une panne.
        surs = paris_surs(res, p_min_sur, cote_min_sure)
        # Ce que le seuil coûte, dit en paris et pas en points : « 1 sur 4
        # perd » se lit, « 25,5 % d'échec » se survole. Mesuré sur la
        # tranche qui COMMENCE au seuil — les bornes sont ouvertes à gauche,
        # lire p_min tel quel tomberait dans la tranche du dessous — et
        # jamais estimé ; sans historique on ne dit rien.
        try:
            tr_seuil = tranche_fiabilite(float(p_min_sur) + 1e-9, methode)
            echoue = 1.0 - float(tr_seuil.reussite)
            n_seuil = f"{int(tr_seuil.n):,}".replace(",", " ")
            perd = (f" Au seuil, 1 pari sur {round(1 / echoue)} perd "
                    f"(mesuré : {100 * echoue:.1f} % d'échec sur {n_seuil} matchs "
                    f"entre {100 * float(tr_seuil.borne_inf):.0f} et "
                    f"{100 * float(tr_seuil.borne_sup):.0f} %)."
                    if 0 < echoue < 1 and int(tr_seuil.n) else "")
        except Exception:
            perd = ""
        theme.eyebrow(
            f"Sûr et payant · confiance {_niveau(p_min_sur).lower()} "
            f"(probabilité ≥ {100 * p_min_sur:.0f} %) et cote nette ≥ {cote_min_sure:.2f}"
            + (f" · {len(surs)} match{'s' if len(surs) > 1 else ''}" if len(surs)
               else " · rien aujourd'hui"),
            "info" if len(surs) else "",
            sous_titre="Le favori du marché, quand un livre le paie au-dessus du "
                       "consensus des autres. Trié du plus sûr au moins sûr." + perd)
        if len(surs):
            for debut in range(0, len(surs), 3):
                cols = st.columns(3)
                for col, (i, p) in zip(cols, surs.iloc[debut:debut + 3].iterrows()):
                    try:
                        tr = tranche_fiabilite(float(p.p_sure), methode)
                        mesure = (f"mesuré : {100 * float(tr.reussite):.1f} % de "
                                  f"réussite sur {int(tr.n):,} matchs".replace(",", " ")
                                  if tr is not None and int(tr.n) else "")
                    except Exception:
                        # Historique absent (installation neuve) : on ne
                        # remplace pas la mesure par une estimation.
                        mesure = ""

                    prop = proposition(p.p_sure, p.cote_sure_nette,
                                       p.ev_robuste_sur, p.n_books)
                    note = (f"mise proposée {prop['mise']:.2f} € · " if prop else "")
                    note += (f"cote juste {1 / p.p_sure:.2f} · "
                             f"{int(p.soutien_sur)} books au prix · "
                             f"{p.verdict_sur.lower()} "
                             f"({p.ev_min_sur:+.1f} → {p.ev_max_sur:+.1f} % "
                             "selon la méthode)")
                    with col:
                        st.markdown(theme.carte_sure(
                            championnat(p.league), p.kickoff[11:16],
                            f"{p.home_team} – {p.away_team}",
                            nom_issue(p, p.issue_sure), p.cote_sure,
                            nom_book(p.book_sur), p.p_sure, note, mesure=mesure,
                            ev=p.ecart_sur, nette=p.cote_sure_nette),
                            unsafe_allow_html=True)
                        st.button("Préparer le pari", key=f"sur_{p.fixture_key}",
                                  on_click=_choisir,
                                  args=(libelles[i],
                                        {"fixture_key": p.fixture_key,
                                         "issue": p.issue_sure,
                                         "regle": "0006",
                                         "seuils": (p_min_sur, cote_min_sure)}),
                                  width="stretch")
        else:
            # Pourquoi c'est vide : l'arithmétique d'abord, le contournement
            # ensuite. Une page vide sans motif se lit comme une panne.
            juste = 1.0 / p_min_sur
            detente = max(0.55, p_min_sur - 0.05)
            n_detente = len(paris_surs(res, detente, cote_min_sure))
            if cote_min_sure >= juste - 1e-9:
                # Le plancher de cote est au-dessus de la cote juste : la
                # règle demande qu'un livre paie mieux que le prix juste.
                texte = (
                    f"Aucun favori à {100 * p_min_sur:.0f} % ou plus n'est payé "
                    f"{cote_min_sure:.2f} au-dessus du consensus aujourd'hui. "
                    f"**Ce n'est pas une panne, c'est de l'arithmétique** : la cote "
                    f"juste d'un favori à {100 * p_min_sur:.0f} % vaut "
                    f"{juste:.2f}. Exiger en plus {cote_min_sure:.2f} revient à "
                    "demander qu'un livre paie ce favori **à son prix juste ou "
                    "mieux** — et un livre vit de ne pas le faire.")
            else:
                # Le plancher est sous la cote juste : il ne gêne pas. Ce
                # qui manque, c'est un livre réel au-dessus du consensus.
                texte = (
                    f"Aucun favori à {100 * p_min_sur:.0f} % ou plus n'est payé "
                    "au-dessus du consensus des autres livres aujourd'hui, chez un "
                    f"bookmaker réel. La cote juste à {100 * p_min_sur:.0f} % vaut "
                    f"{juste:.2f} : le plancher de {cote_min_sure:.2f} n'écarte rien, "
                    "c'est l'écart positif qui manque — **le cas ordinaire**, un "
                    "livre vit de payer le favori sous son prix.")
            if n_detente:
                texte += (f" À {100 * detente:.0f} %, il y en a {n_detente} : "
                          "le curseur est dans les réglages avancés.")
            theme.reserve(texte)

        if n_p:
            n_out = int((prises.issue_prix != prises.issue_probable).sum())
            cadrage = ("Une carte est une cote plus haute que le consensus des autres "
                       "bookmakers, pas un pronostic de victoire : ")
            if n_out == n_p:
                cadrage += ("l'issue retenue n'est le favori sur aucun de ces matchs, "
                            "elle perdra le plus souvent, et c'est attendu.")
            elif n_out:
                cadrage += (f"sur {n_out} de ces {n_p} cartes, l'issue retenue n'est pas "
                            "le favori du marché.")
            else:
                cadrage += "ici, elle coïncide avec le favori du marché."
            theme.eyebrow(f"Meilleur écart, quelle que soit l'issue · {n_p} écart"
                          f"{'s' if n_p > 1 else ''} "
                          f"soutenu{'s' if n_p > 1 else ''}"
                          + (" · du plus probable au moins probable" if n_p > 1 else ""),
                          "pos", sous_titre=cadrage)
            for debut in range(0, n_p, 3):
                cols = st.columns(3)
                for col, (i, p) in zip(cols, prises.iloc[debut:debut + 3].iterrows()):
                    prop = mise_proposee(p)
                    mise = (f"mise proposée {prop['mise']:.2f} € (Kelly × confiance "
                            f"{prop['confiance']:.2f}) · " if prop else "")
                    comm = (f"commission {100 * p.commission_prix:g} % déduite · "
                            if p.commission_prix else "")
                    note = (f"{mise}{comm}cote juste {1 / p.p_prix:.2f} · "
                            f"{int(p.soutien_prix)} books au prix · stable sur les 4 "
                            f"méthodes ({p.ev_min:+.1f} → {p.ev_max:+.1f} %)")
                    statut, detail_statut, favori = statut_issue(p)
                    with col:
                        st.markdown(theme.carte_prise(
                            championnat(p.league), p.kickoff[11:16],
                            f"{p.home_team} – {p.away_team}", nom_issue(p, p.issue_prix),
                            p.cote_prix, nom_book(p.book_prix), p.ecart_prix, note,
                            statut=statut, statut_detail=detail_statut, favori=favori,
                            nette=float(p.cote_nette_prix)),
                            unsafe_allow_html=True)
                        st.button("Préparer le pari", key=f"prep_{p.fixture_key}",
                                  on_click=_choisir, args=(libelles[i],),
                                  width="stretch")
        else:
            theme.eyebrow("Meilleur écart, quelle que soit l'issue · rien")
            st.info(
                "**Aucune cote à valeur soutenue aujourd'hui.** Aucun prix ne bat le "
                f"consensus des autres livres d'au moins {SEUIL_EV_MINI:.0f} % de façon "
                "stable et soutenue. Miser sur le favori ne crée pas de valeur : au "
                "prix juste, l'espérance est nulle.")
        if len(bruit):
            morceaux = []
            for _, e in bruit.sort_values("ecart_prix", ascending=False).iterrows():
                motif = ("l'écart change de signe selon la méthode de dévig"
                         if e.verdict.startswith("Fragile")
                         else f"prix isolé, {int(e.soutien_prix)} book(s) seulement")
                morceaux.append(
                    f"<b>{escape(e.home_team)} – {escape(e.away_team)}</b>, "
                    f"{escape(nom_issue(e, e.issue_prix))} à {e.cote_prix:.2f} "
                    f"(<s>{e.ecart_prix:+.1f} %</s>) : {motif}")
            st.markdown('<div class="od-ecarte">Écarté · ' + " · ".join(morceaux)
                        + "</div>", unsafe_allow_html=True)

    # Ordre de lecture des verdicts : la valeur soutenue d'abord, quel que
    # soit son niveau. Un +9 % fragile trié au-dessus d'un +3 % soutenu
    # ferait exactement ce que le verdict existe pour empêcher.
    ORDRE_VERDICT = {"Écart soutenu": 0, "Écart isolé — prudence": 1,
                     "Fragile — dépend de la méthode": 2, "Trop peu de books": 3,
                     "Rien à signaler": 4}

    # Motif court d'un écart qui n'est pas une valeur.
    MOTIF_BRUIT = {"Fragile — dépend de la méthode": "fragile",
                   "Écart isolé — prudence": "isolé",
                   "Trop peu de books": "trop peu de books"}

    def cellule_valeur(r) -> str:
        """Cellule « Valeur » : la couleur est réservée à l'écart soutenu.

        Un écart fragile ou isolé est écrit en gris et barré : il reste
        lisible (on sait pourquoi il n'est pas retenu) sans voler le regard.
        """
        if not np.isfinite(r.ecart_prix):
            return '<span class="od-muted2">—</span>'
        net = f" ({r.cote_nette_prix:.2f} net)" if r.commission_prix else ""
        detail = escape(f"{nom_issue(r, r.issue_prix)} à {r.cote_prix:.2f}{net} · "
                        f"{nom_book(r.book_prix)}")
        if r.verdict == VERDICT_VALEUR:
            return (theme.badge(f"{r.ecart_prix:+.1f} %", "pos")
                    + f' <span class="od-muted" style="font-size:var(--fs-xs);">{detail}</span>')
        motif = MOTIF_BRUIT.get(r.verdict, "sous le seuil")
        chiffre = f"{r.ecart_prix:+.1f} %"
        if r.verdict in MOTIF_BRUIT:
            chiffre = f"<s>{chiffre}</s>"
        return (f'<span class="od-muted2 od-num">{chiffre}</span> '
                f'<span class="od-muted2" style="font-size:var(--fs-xs);">{motif} · {detail}</span>')

    # --- tous les matchs du jour : la preuve, après la décision ---------------
    # La pédagogie (ce que « valeur » veut dire, d'où vient la confiance) est
    # dans les volets repliés sous le tableau, pas au-dessus.
    st.divider()
    a_confiance = "confiance" in res.columns

    def deux_lignes(haut: str, bas: str) -> str:
        """Cellule à deux niveaux : l'essentiel, puis le contexte en petit."""
        return (f"<div>{escape(haut)}</div>"
                f'<div class="od-muted2" style="font-size:var(--fs-xs);">{escape(bas)}</div>')

    if a_confiance:
        tri = st.radio(
            "Trier par", ["Valeur", "Probabilité", "Heure"], horizontal=True,
            key="tri_matchs",
            help="« Valeur » : le match dont une cote bat le plus le consensus des "
                 "autres livres en tête — c'est ce qui départage deux paris, et ce "
                 "n'est pas l'issue la plus probable. « Probabilité » : le pronostic "
                 "du marché le plus sûr en tête.")
        if tri == "Valeur":
            # Même ordre que les cartes : verdict d'abord, puis, à verdict
            # égal, la probabilité de l'issue visée par le prix.
            res = (res.assign(_o=res.verdict.map(ORDRE_VERDICT).fillna(9))
                      .sort_values(["_o", "p_prix", "ecart_prix"],
                                   ascending=[True, False, False], na_position="last")
                      .drop(columns="_o").reset_index(drop=True))
        elif tri == "Probabilité":
            res = res.sort_values("p_probable", ascending=False).reset_index(drop=True)
        else:
            res = res.sort_values("kickoff").reset_index(drop=True)

        # Sept colonnes : ce qui départage deux paris, rien d'autre. Les
        # statistiques historiques du niveau de probabilité (réussite, ± pts,
        # échec, n) vivent dans le détail du match, onglet « Historique ».
        prono = pd.DataFrame({
            "Heure": res.kickoff.str[11:16],
            "Match": [deux_lignes(f"{h} – {a}", championnat(l)) for h, a, l
                      in zip(res.home_team, res.away_team, res.league)],
            "1 · N · 2": [theme.barre_1n2(a, b, c) for a, b, c
                          in zip(res.p_1, res.p_N, res.p_2)],
            "Pronostic du marché": [deux_lignes(nom_issue(r, r.issue_probable),
                                                f"{100 * r.p_probable:.1f} % · confiance "
                                                f"{r.confiance.lower()}")
                                    for _, r in res.iterrows()],
            "Cote vs consensus": [cellule_valeur(r) for _, r in res.iterrows()],
            "Books": res.n_books,
        })
        prono.insert(0, "Pari", paris_ui.marque_paris(res.fixture_key))
        colonnes_html = ["Pari", "Match", "1 · N · 2", "Pronostic du marché",
                         "Cote vs consensus"]
        if historique and "score" in res.columns:
            juste = (res.resultat.map({"H": "1", "D": "N", "A": "2"})
                     == res.issue_probable)
            # Position relative : le tableau gagne et perd des colonnes selon
            # le contexte, des index en dur se décalent en silence.
            ou = prono.columns.get_loc("Books")
            prono.insert(ou, "Score", res.score.to_numpy())
            prono.insert(ou + 1, "Résultat", res.resultat.map(
                {"H": "Domicile", "D": "Nul", "A": "Extérieur"}).to_numpy())
            prono.insert(ou + 2, "Vu juste",
                         [theme.icone_oui_non(bool(j)) for j in juste])
            colonnes_html.append("Vu juste")

        with st.container(border=True):
            theme.titre_section(f"Les {len(res)} matchs du jour")
            theme.tableau(prono, html=colonnes_html, aligne_droite=["Books"],
                          classes={"Heure": "od-mono"})

        # Le pari à valeur est déjà en tête de page ; ici, une seule ligne
        # atténuée pour rappeler que le plus probable n'est pas le plus rentable.
        meilleur = res.loc[res.p_probable.idxmax()]
        nom = {"1": meilleur.home_team, "N": "le match nul",
               "2": meilleur.away_team}[meilleur.issue_probable]
        st.caption(
            f"Le pronostic le plus sûr du jour, **{nom}** ({meilleur.home_team} – "
            f"{meilleur.away_team}), est donné à {100 * meilleur.p_probable:.1f} % ; ce "
            f"niveau se vérifie {100 * meilleur.reussite_hist:.1f} % du temps "
            f"(n = {meilleur.n_hist:,}). Le plus sûr n'est pas le plus rentable : au prix "
            "juste, l'espérance est nulle.")
        if historique:
            st.caption("Valeur non mesurable sur une date historique : une seule cote "
                       "(clôture Pinnacle), donc pas de consensus d'autres livres à battre.")

        with st.expander("Ce que « valeur » veut dire ici — et ce qu'elle ne dit pas"):
            st.markdown(f"""
La **valeur** d'un pari est son espérance par euro misé : `p × cote − 1`. Elle est positive
quand le prix pris dépasse la cote juste `1 / p`. C'est elle qui départage deux paris — un
favori à 80 % coté 1,20 vaut **−4 %**, un outsider à 24 % coté 4,40 vaut **+5,6 %**. La
probabilité dit ce qui est probable ; la valeur dit ce qui vaut d'être pris. Kelly n'en est
qu'une mise à l'échelle : même signe, même seuil.

Ici, `p` est le **consensus dévigé des autres bookmakers**, recalculé sans le livre qui affiche
le prix (sinon il tirerait la médiane vers lui et masquerait son propre écart). La valeur mesure
donc que **ce prix bat les autres opérateurs** — pas qu'il bat la vérité. Aucun modèle de ce
projet ne bat le marché (R8, R9) ; ce qui reste, et qui est réel, c'est de prendre le meilleur
prix quand il existe.

Trois filtres séparent une valeur d'une cote périmée, et seuls les trois réunis donnent le
badge vert **« Écart soutenu »** :

| filtre | seuil | pourquoi |
|---|---|---|
| écart au consensus | ≥ {SEUIL_EV_MINI:.0f} % | en deçà, le bruit domine |
| soutien | ≥ {SOUTIEN_MINI} livres à 1 % du meilleur prix, et pas plus de {SEUIL_PRIME_ISOLEE:.0f} % au-dessus du deuxième | un prix isolé est presque toujours périmé ou erroné |
| robustesse | même signe sous Shin, power, odds ratio et proportionnelle | sous 5 % de probabilité, les méthodes divergent de 16,6 % (R3) |

Un consensus de moins de {N_BOOKS_MINI} livres ne permet aucun verdict.
""")

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
            st.altair_chart((diag + ch).properties(height=300), width="stretch")
            st.dataframe(
                tbl.assign(p_moyenne=100 * tbl.p_moyenne, reussite=100 * tbl.reussite,
                           ic95=100 * tbl.ic95)[["bin", "n", "p_moyenne", "reussite", "ic95"]]
                   .rename(columns={"bin": "Tranche", "p_moyenne": "Annoncé %",
                                    "reussite": "Observé %", "ic95": "± pts"})
                   .style.format({"Annoncé %": "{:.1f}", "Observé %": "{:.1f}",
                                  "± pts": "{:.1f}", "n": "{:,}"}),
                width="stretch", hide_index=True)
    else:
        st.warning("Historique indisponible : le score de confiance ne peut pas être calculé. "
                   "Lancez `uv run odds ingest`.")

    # --- dispersion des prix (section secondaire) --------------------------
    st.divider()
    with st.expander("Dispersion des prix entre bookmakers (analyse secondaire)"):
        st.caption("Où le meilleur prix disponible s'écarte-t-il du consensus des autres "
                   "bookmakers ? C'est une observation sur le **désaccord entre opérateurs**, "
                   "sans rapport avec la probabilité qu'une issue se produise.")

        TON = {"Écart soutenu": "pos", "Écart isolé — prudence": "neu",
               "Fragile — dépend de la méthode": "neg",
               "Trop peu de books": "outline", "Rien à signaler": "outline"}

        def ton_ecart(v):
            # Seuil de ±1 point, comme la maquette (gapClass).
            return "pos" if v >= 1 else ("neg" if v <= -1 else "neu")

        rp = res.assign(_o=res.verdict.map(ORDRE_VERDICT).fillna(9)).sort_values(
            ["_o", "kickoff"]).reset_index(drop=True)
        theme.tableau(pd.DataFrame({
            "Constat": [theme.badge(v, TON.get(v, "outline")) for v in rp.verdict],
            "Match": rp.home_team + " – " + rp.away_team,
            "Issue visée": rp.issue_prix.map(lib),
            "Cote": rp.cote_prix.map("{:.2f}".format),
            "Chez": [nom_book(b) + (f" · {n:.2f} net" if c else "")
                     for b, n, c in zip(rp.book_prix, rp.cote_nette_prix,
                                        rp.commission_prix)],
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
    # `res` a pu être retrié depuis le calcul des libellés : on les recalcule
    # dans l'ordre courant. Le choix vit dans la session pour qu'un bouton
    # « Préparer le pari » puisse l'imposer ; par défaut, le pari à la plus
    # forte valeur, sinon le premier de la liste.
    libelles = (res.kickoff.str[11:16] + " · " + res.home_team + " – " + res.away_team
                + " (" + res.league.astype(str).map(championnat) + ")")
    options = libelles.tolist()
    if st.session_state.get("match_choisi") not in options:
        # Par défaut, la première carte : l'écart soutenu le plus probable.
        soutenus = res[(res.verdict == VERDICT_VALEUR) & np.isfinite(res.p_prix)]
        defaut_match = (options[int(soutenus.p_prix.idxmax())]
                        if not historique and len(soutenus) else options[0])
        st.session_state["match_choisi"] = defaut_match
    choix = t2.selectbox("Match", options, key="match_choisi",
                         label_visibility="collapsed")
    ligne = res.loc[libelles == choix].iloc[0]
    fk = ligne.fixture_key

    # En-tête du détail : le match, une ligne de contexte, et la décision si
    # l'écart est soutenu. Le reste est réparti en onglets, « Parier » ouvert
    # par défaut : c'est l'action, les autres sont des preuves.
    nom_prono = nom_issue(ligne, ligne.issue_probable)
    st.markdown(f"### {ligne.home_team} – {ligne.away_team}")
    contexte = (f"{championnat(ligne.league)} · {ligne.kickoff[11:16]} · "
                f"{int(ligne.n_books)} bookmakers"
                f" · pronostic du marché : **{nom_prono}** ({100 * ligne.p_probable:.1f} %")
    contexte += (f", confiance {ligne.confiance.lower()})" if a_confiance else ")")
    st.caption(contexte)
    if ligne.verdict == VERDICT_VALEUR:
        statut, detail_statut, favori = statut_issue(ligne)
        net = (f" ({ligne.cote_nette_prix:.2f} net de commission)"
               if ligne.commission_prix else "")
        st.success(f"**Cote à valeur soutenue** : {nom_issue(ligne, ligne.issue_prix)} à "
                   f"{ligne.cote_prix:.2f} chez {nom_book(ligne.book_prix)}{net}, "
                   f"{ligne.ecart_prix:+.1f} % d'espérance par euro misé, "
                   f"{int(ligne.soutien_prix)} livres au prix, signe stable sur les "
                   f"quatre méthodes. {statut.lower().capitalize()} : {detail_statut}"
                   + ("." if favori else
                      " — ce pari perdra le plus souvent, l'espérance vient du prix."))

    o_parier, o_buts, o_couvrir, o_books, o_hist = st.tabs([
        "Parier", "Marchés de buts", "Couvrir plusieurs issues",
        f"{int(ligne.n_books)} bookmakers", "Historique du niveau"])

    with o_parier:
        paris_ui.formulaire_pari(ligne, det, methode, source=r.fournisseur,
                                 totaux=r.totaux)

    with o_buts:
        buts_ui.bloc_buts(ligne, r.totaux)

    with o_couvrir:
        couverture_ui.bloc_couverture(ligne, det, methode, source=r.fournisseur,
                                      totaux=r.totaux)

    with o_hist:
        if a_confiance:
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Favori du marché", f"{100 * ligne.p_probable:.1f} %",
                      nom_prono, delta_color="off")
            d2.metric("Réussite historique", f"{100 * ligne.reussite_hist:.1f} %",
                      f"± {100 * ligne.ic95_hist:.1f} pts", delta_color="off")
            d3.metric("Échoue quand même", f"{100 * ligne.echoue_hist:.1f} %",
                      "du temps", delta_color="off")
            d4.metric("Échantillon", f"{ligne.n_hist:,}", "matchs historiques",
                      delta_color="off")
            st.caption("La réussite historique est mesurée sur les matchs de l'historique "
                       "dont la probabilité annoncée tombait dans la même tranche. Elle "
                       "n'est pas propre à ce match : elle dit ce que vaut, en moyenne, un "
                       "pronostic à ce niveau. La valeur, elle, est propre à ce match et à "
                       "ce prix.")
        else:
            st.caption("Historique indisponible : lancez `uv run odds ingest`.")

    with o_books:
        e1, e2, e3 = st.columns(3)
        e1.metric("Issue visée par le prix", lib[ligne.issue_prix],
                  f"{ligne.ecart_prix:+.2f} %", delta_color="off")
        e2.metric("Meilleure cote", f"{ligne.cote_prix:.2f}",
                  nom_book(ligne.book_prix)
                  + (f" · {ligne.cote_nette_prix:.2f} net" if ligne.commission_prix
                     else ""), delta_color="off")
        e3.metric("Selon la méthode", f"{ligne.ev_min:+.1f} → {ligne.ev_max:+.1f} %",
                  "stable" if ligne.ev_robuste else "change de signe",
                  delta_color="normal" if ligne.ev_robuste else "inverse")
        if str(ligne.book_prix).startswith("_"):
            st.caption("⌀ = agrégat de marché, pas un bookmaker. Voir le tableau livre par livre.")
        if not ligne.ev_robuste:
            theme.reserve("L'écart change de signe selon la méthode de dévig : il mesure "
                          "le choix de méthode, pas le marché. Typique des issues à faible "
                          "probabilité.", "grave")
        elif ligne.verdict == "Écart isolé — prudence":
            theme.reserve(f"Prix {ligne.prime_prix:+.1f} % au-dessus du deuxième, affiché "
                          f"par {int(ligne.soutien_prix)} bookmaker(s) seulement — presque "
                          "toujours une cote périmée ou erronée.", "attention")
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
                    # Colonne rendue en HTML : le nom vient de l'API et doit
                    # être échappé comme toute autre chaîne externe.
                    "Bookmaker": [theme.pastille(b, couleurs_books) + " " + escape(str(b))
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
            st.caption("« autre instant » = même bookmaker relevé plus tôt. Exclu du "
                       "consensus et du meilleur prix : ce n'est pas un concurrent, et "
                       "cette cote n'est plus disponible.")
        with c2:
            books = d[d.type == "book"]
            longd = books.melt(
                id_vars="bookmaker", value_vars=["p_1", "p_N", "p_2"],
                var_name="issue", value_name="p")
            longd["issue"] = longd.issue.map({"p_1": "1", "p_N": "N", "p_2": "2"})
            noms = books.bookmaker.tolist()
            ch = alt.Chart(longd).mark_circle(
                size=110, opacity=.88, stroke=theme.BG, strokeWidth=1).encode(
                x=alt.X("p:Q", title="Probabilité (marge retirée)",
                        axis=alt.Axis(format="%")),
                y=alt.Y("issue:N", title=None, sort=["1", "N", "2"]),
                # Une couleur fixe par bookmaker, comme la légende de la maquette.
                color=alt.Color("bookmaker:N", title="Bookmaker", legend=None,
                                scale=alt.Scale(domain=noms,
                                                range=[couleurs_books[str(b)]
                                                       for b in noms])),
                tooltip=["bookmaker", "issue", alt.Tooltip("p:Q", format=".1%")],
            ).properties(height=220)
            st.altair_chart(ch, width="stretch")
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
            width="stretch", hide_index=True)
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
                     width="stretch", hide_index=True)
    with g2:
        ch = alt.Chart(biais).mark_bar().encode(
            x=alt.X("Écart relatif (%):Q", title="Erreur relative de la proportionnelle (%)"),
            y=alt.Y("Issue:N", sort=None),
            color=alt.condition(alt.datum["Écart relatif (%)"] > 0,
                                alt.value(theme.ROUGE), alt.value(theme.BLEU)),
            tooltip=["Issue", "Écart (points)", "Écart relatif (%)"],
        ).properties(height=40 * len(biais) + 40)
        st.altair_chart(ch, width="stretch")

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
        theme.reserve(f"Seulement {len(d)} matchs sur ce filtre. Résultat non "
                      "interprétable.", "attention")
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
        st.altair_chart((diag + ligne + pts).properties(height=440), width="stretch")
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
                     width="stretch", hide_index=True)

    if code == "(tous)":
        st.subheader("Comparaison des méthodes de dévig")
        st.caption("Mesuré, pas supposé. L'écart agrégé est minime — "
                   "mais il décide d'où l'on croirait avoir de l'edge.")
        st.dataframe(comparer_methodes(df).style.format(
            {"brier": "{:.6f}", "log_loss": "{:.6f}", "ece": "{:.5f}"}),
            width="stretch", hide_index=True)


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
        st.altair_chart(ch, width="stretch")
        st.dataframe(m.assign(depuis=m.depuis.dt.year, jusqua=m.jusqua.dt.year)
                      [["league_code", "country", "league", "n", "depuis", "jusqua", "marge"]]
                      .style.format({"marge": "{:.2f} %"}),
                     width="stretch", hide_index=True)
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
            st.altair_chart(ch, width="stretch")
            st.dataframe(t[["league_code", "country", "league", "n", "brier_precoce",
                            "brier_cloture", "information_tardive"]].style.format(
                {"brier_precoce": "{:.5f}", "brier_cloture": "{:.5f}",
                 "information_tardive": "{:.5f}"}),
                width="stretch", hide_index=True)
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
        width="stretch", hide_index=True, height=560)

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
            st.altair_chart(ch, width="stretch")

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
                     width="stretch", hide_index=True)
        st.caption("football-data publie ses fixtures environ deux fois par semaine "
                   "(milieu de semaine, puis avant le week-end). Entre deux publications, "
                   "aucune nouvelle date n'apparaît — ce n'est pas une panne du collecteur.")
    else:
        st.caption("Pas encore d'état de flux enregistré.")

    st.subheader("Couverture par bookmaker")
    b = r["bookmakers"].copy()
    b["rôle"] = np.where(b.bookmaker == "betfair_exchange", "benchmark",
                np.where(b.bookmaker.str.startswith("_"), "agrégat", "book"))
    st.dataframe(b, width="stretch", hide_index=True)
    st.caption("**betfair_exchange** est le benchmark retenu en avant : "
               "prix réellement négociable, seul substitut sérieux à Pinnacle.")

    st.subheader("Dernières passes")
    runs["statut"] = np.where(runs.erreur.notna(), "⚠️ erreur", "✅")
    st.dataframe(runs[["run_id", "matchs", "lignes_vues", "lignes_ecrites", "statut", "erreur"]],
                 width="stretch", hide_index=True)

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
    st.altair_chart(ch, width="stretch")
    st.caption("Seuls les CHANGEMENTS sont enregistrés : une cote stable ne "
               "produit pas de nouveau point.")
