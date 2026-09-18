"""Harnais de backtest point-in-time.

Règle absolue (PLAN §4.3, §13.1) : au moment de prédire un match joué à la
date t, le modèle ne voit QUE des matchs de date strictement antérieure à t.

Elo et Dixon-Coles sont des modèles à état. Un ajustement global suivi d'un
"backtest" fait porter aux notes d'équipe de l'information future — la fuite
la plus courante et la plus flatteuse du domaine. D'où le réajustement
glissant implémenté ici, et le test `tests/test_no_lookahead.py` qui vérifie
que la propriété tient réellement.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from odds.models.football.dixon_coles import DCParams, fit_dixon_coles, pool_of, predict_1x2


def demi_vie_vers_xi(demi_vie_jours: float) -> float:
    return float(np.log(2.0) / demi_vie_jours)


def walk_forward(
    df: pd.DataFrame,
    demi_vie_jours: float = 365.0,
    ridge: float = 1.0,
    refit_jours: int = 30,
    min_matchs: int = 300,
    horizon_demi_vies: float = 5.0,
    predire_depuis: pd.Timestamp | None = None,
    predire_jusqua: pd.Timestamp | None = None,
    verbose: bool = False,
) -> pd.DataFrame:
    """Réajustement glissant par pyramide, prédiction des matchs à venir.

    ``horizon_demi_vies`` tronque l'historique : au-delà de 5 demi-vies, le
    poids est < 3 %, la contribution est négligeable et le coût de calcul ne
    l'est pas.
    """
    xi = demi_vie_vers_xi(demi_vie_jours)
    fenetre = int(horizon_demi_vies * demi_vie_jours)
    df = df.copy()
    df["pool"] = df.league_code.map(pool_of)

    sorties = []
    for pool, g in df.groupby("pool", sort=True):
        g = g.sort_values("date").reset_index(drop=True)
        dates = g.date.to_numpy()

        debut = predire_depuis or g.date.iloc[0]
        fin = predire_jusqua or (g.date.iloc[-1] + pd.Timedelta(days=1))
        bornes = pd.date_range(debut, fin, freq=f"{refit_jours}D")
        if len(bornes) == 0:
            continue

        warm: dict[str, np.ndarray] = {}
        gamma_prec, rho_prec = 0.25, -0.05

        for t0 in bornes:
            t1 = t0 + pd.Timedelta(days=refit_jours)
            # --- HISTORIQUE : strictement antérieur à t0 -------------------
            passe = g[(dates < t0.to_datetime64()) & (dates >= (t0 - pd.Timedelta(days=fenetre)).to_datetime64())]
            futur = g[(dates >= t0.to_datetime64()) & (dates < t1.to_datetime64())]
            if len(futur) == 0 or len(passe) < min_matchs:
                continue

            equipes = pd.unique(pd.concat([passe.home_team, passe.away_team]))
            idx = {t: i for i, t in enumerate(equipes)}
            n = len(equipes)

            poids = np.exp(-xi * (t0 - passe.date).dt.days.to_numpy())
            x0 = np.zeros(2 * n + 2)
            for t, i in idx.items():
                if t in warm:
                    x0[i], x0[n + i] = warm[t]
            x0[-2], x0[-1] = gamma_prec, rho_prec

            a, b, gamma, rho = fit_dixon_coles(
                passe.home_team.map(idx).to_numpy(),
                passe.away_team.map(idx).to_numpy(),
                passe.home_goals.to_numpy(),
                passe.away_goals.to_numpy(),
                poids, n, ridge=ridge, x0=x0,
            )
            warm = {t: (a[i], b[i]) for t, i in idx.items()}
            gamma_prec, rho_prec = gamma, rho

            params = DCParams(list(equipes), a, b, gamma, rho, len(passe), t0)
            probas = np.vstack([predict_1x2(params, h, aw)
                                for h, aw in zip(futur.home_team, futur.away_team)])
            out = futur.copy()
            out[["dc_h", "dc_d", "dc_a"]] = probas
            out["fit_as_of"] = t0
            out["fit_n"] = len(passe)
            out["fit_n_equipes"] = n
            out["home_adv"] = gamma
            out["rho"] = rho
            out["equipe_inconnue"] = (~futur.home_team.isin(idx)) | (~futur.away_team.isin(idx))
            sorties.append(out)

        if verbose:
            print(f"  {pool:5s} ok", flush=True)

    if not sorties:
        return pd.DataFrame()
    return pd.concat(sorties, ignore_index=True).sort_values("date").reset_index(drop=True)
