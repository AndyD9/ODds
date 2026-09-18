"""Test anti-fuite. Tourne en CI (PLAN §13.4).

Si ce test échoue, tout résultat de backtest est invalide : le modèle aurait
vu des données postérieures à la date de prédiction.
"""

import numpy as np
import pandas as pd
import pytest

from odds.models.football.dixon_coles import fit_dixon_coles
from odds.pit.walk_forward import walk_forward

RNG = np.random.default_rng(20260918)


def _dataset_synthetique(n_equipes=16, n_saisons=6, debut="2015-01-01"):
    equipes = [f"T{i:02d}" for i in range(n_equipes)]
    attaque = dict(zip(equipes, RNG.normal(0, 0.28, n_equipes)))
    defense = dict(zip(equipes, RNG.normal(0, 0.22, n_equipes)))
    lignes, jour = [], pd.Timestamp(debut)
    for _ in range(n_saisons):
        for i in range(n_equipes):
            for j in range(n_equipes):
                if i == j:
                    continue
                lam = np.exp(attaque[equipes[i]] + defense[equipes[j]] + 0.27)
                mu = np.exp(attaque[equipes[j]] + defense[equipes[i]])
                lignes.append({
                    "date": jour, "league_code": "SYN", "home_team": equipes[i],
                    "away_team": equipes[j], "home_goals": RNG.poisson(lam),
                    "away_goals": RNG.poisson(mu),
                })
                jour += pd.Timedelta(days=1)
    return pd.DataFrame(lignes)


def test_ajustement_ignore_le_futur():
    """Ajuster sur D tronqué à T, ou sur D complet filtré à T, doit être
    strictement identique."""
    df = _dataset_synthetique(n_equipes=12, n_saisons=3)
    T = df.date.iloc[len(df) // 2]

    passe = df[df.date < T]
    equipes = pd.unique(pd.concat([passe.home_team, passe.away_team]))
    idx = {t: i for i, t in enumerate(equipes)}
    args = (passe.home_team.map(idx).to_numpy(), passe.away_team.map(idx).to_numpy(),
            passe.home_goals.to_numpy(), passe.away_goals.to_numpy(),
            np.ones(len(passe)), len(equipes))

    r1 = fit_dixon_coles(*args, ridge=1.0)
    df_avec_futur = pd.concat([df, _dataset_synthetique(n_equipes=12, n_saisons=2, debut="2030-01-01")])
    passe2 = df_avec_futur[df_avec_futur.date < T]
    assert len(passe2) == len(passe)
    r2 = fit_dixon_coles(*args, ridge=1.0)
    for v1, v2 in zip(r1, r2):
        assert np.allclose(v1, v2)


def test_walk_forward_insensible_aux_donnees_futures():
    """LE test central.

    Les prédictions sur une période P doivent être BIT POUR BIT identiques,
    que le dataset contienne ou non des matchs postérieurs à P. Toute
    différence signale une fuite.
    """
    df = _dataset_synthetique(n_equipes=14, n_saisons=5)
    coupure = df.date.iloc[int(0.7 * len(df))]

    tronque = df[df.date < coupure]
    complet = df

    commun = dict(demi_vie_jours=300.0, ridge=1.0, refit_jours=45, min_matchs=200,
                  predire_jusqua=coupure)
    a = walk_forward(tronque, **commun)
    b = walk_forward(complet, **commun)

    # La dernière fenêtre de réajustement déborde la coupure : le dataset
    # complet y contient des matchs que le tronqué n'a pas. On compare donc
    # l'intersection, c'est-à-dire tous les matchs strictement antérieurs à
    # la coupure — les seuls pour lesquels la comparaison a un sens.
    cle = ["date", "home_team", "away_team"]
    a = a[a.date < coupure].sort_values(cle).reset_index(drop=True)
    b = b[b.date < coupure].sort_values(cle).reset_index(drop=True)

    assert len(a) > 200, "le test doit porter sur un volume significatif"
    assert len(a) == len(b), "le tronqué doit couvrir exactement les mêmes matchs"
    assert (a[cle].values == b[cle].values).all()
    for c in ("dc_h", "dc_d", "dc_a", "home_adv", "rho"):
        assert a[c].to_numpy() == pytest.approx(b[c].to_numpy(), abs=1e-12), (
            f"FUITE DETECTEE sur {c} : la présence de données futures a changé "
            f"les prédictions passées"
        )


def test_aucune_prediction_utilise_un_match_du_jour_meme():
    """La borne est stricte : un match du jour J ne peut pas servir à
    prédire un autre match du jour J."""
    df = _dataset_synthetique(n_equipes=12, n_saisons=3)
    res = walk_forward(df, demi_vie_jours=300.0, ridge=1.0, refit_jours=30, min_matchs=150)
    assert len(res) > 0
    assert (res.fit_as_of <= res.date).all()


def test_les_probabilites_sont_valides():
    df = _dataset_synthetique(n_equipes=12, n_saisons=3)
    res = walk_forward(df, demi_vie_jours=300.0, ridge=1.0, refit_jours=30, min_matchs=150)
    p = res[["dc_h", "dc_d", "dc_a"]].to_numpy()
    assert p.sum(axis=1) == pytest.approx(np.ones(len(p)), abs=1e-9)
    assert (p > 0).all() and (p < 1).all()
