"""Test de fumée du tableau de bord.

Il ne dit pas que la page est belle : il dit qu'elle ne lève pas. C'est le
filet que `src/odds/app/` n'avait pas — 3 800 lignes dont aucune n'était
exercée, alors qu'elles appellent `analysis/` à chaque écran. Un renommage
dans le noyau cassait une page jusqu'à ce qu'on l'ouvre à la main.

Trois choses vérifiées, dans cet ordre de coût :

1. chaque page du tableau de bord s'exécute de bout en bout sans exception
   et produit quelque chose (`AppTest`, le harnais officiel de Streamlit) ;
2. les fragments HTML de `theme.py` sont bien formés et **échappent** ce
   qu'on leur donne — ils sont rendus avec ``unsafe_allow_html=True`` ;
3. la zone fragile de `theme.css` reste bornée (décision 0007).

Les pages lisent la base d'historique réelle. Sans elle — dépôt fraîchement
cloné, avant la première collecte — les tests de la partie 1 sont ignorés :
un tableau de bord sans données affiche une erreur propre, ce n'est pas une
régression.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd
import pytest

from odds.app import libelles, theme

RACINE = Path(__file__).resolve().parents[1]
DASHBOARD = RACINE / "src" / "odds" / "app" / "dashboard.py"
FEUILLE = RACINE / "src" / "odds" / "app" / "theme.css"

PAGES_OUTIL = ["Matchs par date", "Mes paris", "Collecte en cours"]
PAGES_RECHERCHE = ["Dévig d'un livre", "Calibration du marché", "Cartographie",
                   "Explorateur de matchs"]


# --- 1. les pages s'exécutent ----------------------------------------------

@pytest.fixture(scope="module")
def app():
    """Tableau de bord chargé une fois, réutilisé par toutes les pages."""
    from odds.chemins import BDD_COLLECTE

    if not BDD_COLLECTE.exists() or BDD_COLLECTE.stat().st_size == 0:
        pytest.skip(f"pas d'historique collecté ({BDD_COLLECTE}) : "
                    "le tableau de bord n'a rien à afficher")

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(DASHBOARD), default_timeout=120)
    at.run()
    if at.exception:
        pytest.fail("le tableau de bord lève au chargement : "
                    + " | ".join(at.exception.values))
    return at


def _verifier(at, page: str) -> None:
    assert not at.exception, (f"la page « {page} » lève : "
                              + " | ".join(at.exception.values))
    # `st.error` est réservé à ce qui est SURVENU et demande un geste : flux
    # en retard, passe échouée, crédits épuisés, drawdown de réexamen. Une
    # limite mesurée et permanente — dérivation qui surestime, écart qui
    # dépend de la méthode, couverture qui perd par construction — passe par
    # `theme.reserve`, et n'est donc pas une erreur. C'est cette frontière
    # qui rend l'assertion ci-dessous utilisable : sans elle, le test se
    # déclenchait sur une phrase pédagogique et il aurait fallu le désarmer.
    assert not at.error, (f"la page « {page} » affiche une erreur : "
                          + " | ".join(e.value for e in at.error))
    # Un st.stop() précoce laisserait une page vide, sans lever : on exige
    # que la page ait effectivement écrit quelque chose.
    rendu = len(at.markdown) + len(at.dataframe) + len(at.caption)
    assert rendu > 0, f"la page « {page} » n'a rien rendu"


def test_le_tableau_de_bord_se_charge(app):
    _verifier(app, "Matchs par date")
    assert app.sidebar.radio, "la navigation a disparu de la barre latérale"


@pytest.mark.parametrize("page", PAGES_OUTIL)
def test_page_outil(app, page):
    app.sidebar.radio[0].set_value(page).run()
    _verifier(app, page)


@pytest.mark.parametrize("page", PAGES_RECHERCHE)
def test_page_recherche(app, page):
    app.sidebar.radio[1].set_value(page).run()
    _verifier(app, page)


# --- 2. les fragments de theme.py ------------------------------------------

def test_libelles():
    assert libelles.championnat("soccer_epl") == "Premier League"
    assert libelles.championnat("soccer_inconnu_xyz") == "Inconnu Xyz"
    assert libelles.championnat("déjà lisible") == "déjà lisible"
    assert libelles.bookmaker("betfair_ex_eu") == "Betfair Exchange"
    assert libelles.date_longue(dt.date(2026, 9, 18)) == "Vendredi 18 septembre 2026"


@pytest.fixture
def html_rendu(monkeypatch):
    """Capture ce que `theme` envoie à `st.markdown(unsafe_allow_html=True)`."""
    sortie = []
    monkeypatch.setattr(theme.st, "markdown",
                        lambda corps, **k: sortie.append(corps))
    return sortie


def test_la_reserve_echappe_et_rend_le_gras(html_rendu):
    """`reserve` est rendue sans échappement par Streamlit : elle échappe."""
    theme.reserve("Écart de **2,4 points** chez <script>x</script>", "attention")
    html = html_rendu[0]
    assert "od-reserve-attention" in html
    assert "<strong>2,4 points</strong>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_un_niveau_de_reserve_inconnu_leve():
    """Une faute de frappe rendrait le filet de couleur muet, sans le dire."""
    with pytest.raises(ValueError):
        theme.reserve("…", "urgent")


def test_le_tableau_dessine_echappe_les_cellules(html_rendu):
    """Le tableau est rendu sans échappement par Streamlit : c'est `tableau`
    qui échappe. Un nom d'équipe exotique ne doit pas pouvoir écrire de
    balise dans la page."""
    df = pd.DataFrame({"Équipe": ['<script>x</script>'], "Cote": [1.85]})
    theme.tableau(df, aligne_droite=("Cote",))
    html = html_rendu[0]
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_les_colonnes_html_passent_telles_quelles(html_rendu):
    """`html=` est la porte de sortie assumée : les fragments que theme.py
    produit lui-même (badges, barres) y transitent sans être échappés."""
    df = pd.DataFrame({"Accord": [theme.badge("oui", "pos")]})
    theme.tableau(df, html=("Accord",))
    assert "od-badge-pos" in html_rendu[0]


def test_le_badge_echappe_son_texte():
    assert "<script>" not in theme.badge("<script>x</script>")


def test_la_barre_1n2_somme_a_cent():
    barre = theme.barre_1n2(0.5, 0.3, 0.2)
    largeurs = [float(x) for x in re.findall(r"width:([\d.]+)%", barre)]
    assert largeurs == [50.0, 30.0, 20.0]


def test_le_tableau_dessine_rend_toutes_les_lignes(html_rendu):
    df = pd.DataFrame({"Match": ["A – B", "C – D"], "Cote": [1.85, 3.2]})
    theme.tableau(df, aligne_droite=("Cote",))
    html = html_rendu[0]
    assert html.count("<tr>") == 3         # en-tête + deux lignes
    assert "A – B" in html and "1.85" in html


# --- 3. le compteur de dette (décision 0007) -------------------------------

INTERNES = re.compile(r'data-testid|data-baseweb|stMarkdown|\bemotion\b')
PLAFOND = 150


def test_la_zone_fragile_reste_bornee():
    """Compteur de la décision 0007 : tant que l'habillage des widgets tient
    en une centaine de lignes, rester sur Streamlit est le bon calcul. Passé
    150, la décision est à rouvrir — pas à contourner en relevant le seuil."""
    lignes = [n for n, ligne in enumerate(FEUILLE.read_text().splitlines(), 1)
              if INTERNES.search(ligne) and not ligne.lstrip().startswith(("*", "/*"))]
    assert len(lignes) <= PLAFOND, (
        f"{len(lignes)} lignes de theme.css visent des internes Streamlit "
        f"(plafond {PLAFOND}). Voir decisions/0007-rester-sur-streamlit.md : "
        "c'est le signal d'une migration, pas d'un seuil à relever.")
