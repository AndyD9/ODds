"""Tests du score de confiance.

Le score n'est pas une estimation : il est adossé à la fréquence réellement
observée dans l'historique. Ces tests vérifient que le lien entre une
probabilité affichée et sa tranche historique ne se décale pas.
"""

import numpy as np
import pandas as pd
import pytest

import odds.analysis as ana


@pytest.fixture
def table(monkeypatch):
    """Table de fiabilité synthétique, aux valeurs connues."""
    t = pd.DataFrame({
        "bin": ["(0.0, 0.4]", "(0.4, 0.45]", "(0.7, 0.75]", "(0.9, 1.01]"],
        "n": [31613, 30749, 5028, 317],
        "p_moyenne": [0.375, 0.424, 0.723, 0.919],
        "reussite": [0.368, 0.428, 0.745, 0.934],
        "ic95": [0.005, 0.006, 0.012, 0.027],
        "borne_inf": [0.0, 0.40, 0.70, 0.90],
        "borne_sup": [0.40, 0.45, 0.75, 1.01],
    })
    monkeypatch.setattr(ana, "fiabilite_historique", lambda methode="shin": t)
    return t


@pytest.mark.parametrize("p,attendu", [
    (0.95, "Très élevée"), (0.85, "Très élevée"),
    (0.84, "Élevée"), (0.70, "Élevée"),
    (0.69, "Modérée"), (0.60, "Modérée"),
    (0.59, "Faible"), (0.50, "Faible"),
    (0.49, "Très faible"), (0.34, "Très faible"),
])
def test_niveaux(p, attendu):
    assert ana._niveau(p) == attendu


def test_association_a_la_bonne_tranche(table):
    res = pd.DataFrame({"p_probable": [0.936, 0.72, 0.42, 0.35]})
    out = ana.annoter_confiance(res)
    assert out.reussite_hist.tolist() == [0.934, 0.745, 0.428, 0.368]
    assert out.n_hist.tolist() == [317, 5028, 30749, 31613]


def test_bornes_de_tranche_exclusives_a_gauche(table):
    """0.40 appartient à (0.0, 0.40], pas à (0.40, 0.45]."""
    out = ana.annoter_confiance(pd.DataFrame({"p_probable": [0.40, 0.4001]}))
    assert out.reussite_hist.tolist() == [0.368, 0.428]


def test_echec_est_le_complement(table):
    out = ana.annoter_confiance(pd.DataFrame({"p_probable": [0.936, 0.42]}))
    assert (out.reussite_hist + out.echoue_hist).tolist() == pytest.approx([1.0, 1.0])


def test_confiance_tres_elevee_echoue_quand_meme(table):
    """Garde-fou pédagogique : même le niveau le plus sûr échoue.

    Si ce test cassait parce que echoue_hist vaut 0, l'interface
    afficherait une certitude qui n'existe pas.
    """
    out = ana.annoter_confiance(pd.DataFrame({"p_probable": [0.936]}))
    assert out.confiance.iloc[0] == "Très élevée"
    assert out.echoue_hist.iloc[0] > 0.05, "un pronostic à 93 % échoue ~7 % du temps"


def test_dataframe_vide(table):
    assert len(ana.annoter_confiance(pd.DataFrame({"p_probable": []}))) == 0


def test_colonnes_dorigine_conservees(table):
    res = pd.DataFrame({"p_probable": [0.72], "home_team": ["A"], "away_team": ["B"]})
    out = ana.annoter_confiance(res)
    assert out.home_team.iloc[0] == "A" and out.away_team.iloc[0] == "B"
    assert {"confiance", "reussite_hist", "n_hist", "ic95_hist",
            "echoue_hist"} <= set(out.columns)


def test_table_reelle_est_monotone_et_calibree():
    """Sur les vraies données : la réussite doit croître avec la probabilité
    annoncée, et rester proche d'elle."""
    t = ana.fiabilite_historique()
    assert len(t) >= 8
    assert t.reussite.is_monotonic_increasing, "réussite non monotone"
    ecart = (t.reussite - t.p_moyenne).abs()
    assert ecart.max() < 0.05, f"écart de calibration trop grand : {ecart.max():.3f}"
    assert t.n.sum() > 100_000
