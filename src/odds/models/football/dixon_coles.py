"""Dixon-Coles avec time decay et shrinkage.

Modèle :
    lambda = exp(attaque_dom + defense_ext + avantage_domicile)
    mu     = exp(attaque_ext + defense_dom)
    P(x,y) = tau(x, y, lambda, mu, rho) * Poisson(x; lambda) * Poisson(y; mu)

avec la correction de Dixon-Coles (1997) sur les scores faibles :
    tau(0,0) = 1 - lambda*mu*rho     tau(0,1) = 1 + lambda*rho
    tau(1,0) = 1 + mu*rho            tau(1,1) = 1 - rho
    tau      = 1 partout ailleurs

Trois éléments comptent davantage que la correction tau elle-même (PLAN §14.1) :

1. **Time decay** : poids exp(-xi * jours_ecoules). Paramétré par demi-vie.
2. **Shrinkage** (ridge sur attaque/défense) : tire les équipes à faible
   échantillon vers la moyenne du groupe. Indispensable pour les promus, qui
   arrivent sans historique. Résout aussi la dégénérescence du modèle
   (attaque + c, défense - c laisse lambda inchangé) en sélectionnant la
   solution de norme minimale.
3. **Regroupement par pyramide** : les divisions d'un même pays sont ajustées
   ensemble, sinon un promu n'a aucun historique exploitable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

# Divisions reliées par promotion/relégation : ajustées ensemble.
POOLS = {
    "E0": "ENG", "E1": "ENG", "E2": "ENG", "E3": "ENG",
    "SC0": "SCO", "SC1": "SCO",
    "D1": "GER", "D2": "GER",
    "I1": "ITA", "I2": "ITA",
    "SP1": "ESP", "SP2": "ESP",
    "F1": "FRA", "F2": "FRA",
}


def pool_of(league_code: str) -> str:
    return POOLS.get(league_code, league_code)


@dataclass
class DCParams:
    teams: list[str]
    attack: np.ndarray
    defence: np.ndarray
    home_adv: float
    rho: float
    n_matchs: int
    as_of: object

    @property
    def index(self) -> dict[str, int]:
        return {t: i for i, t in enumerate(self.teams)}

    def to_vector(self) -> np.ndarray:
        return np.concatenate([self.attack, self.defence, [self.home_adv, self.rho]])


def _tau_and_grad(x, y, lam, mu, rho):
    """log(tau) et ses dérivées partielles. Vectorisé."""
    tau = np.ones_like(lam)
    dl = np.zeros_like(lam)   # d log tau / d lambda
    dm = np.zeros_like(lam)   # d log tau / d mu
    dr = np.zeros_like(lam)   # d log tau / d rho

    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)

    tau[m00] = 1.0 - lam[m00] * mu[m00] * rho
    tau[m01] = 1.0 + lam[m01] * rho
    tau[m10] = 1.0 + mu[m10] * rho
    tau[m11] = 1.0 - rho
    tau = np.clip(tau, 1e-10, None)

    dl[m00] = -mu[m00] * rho / tau[m00]
    dm[m00] = -lam[m00] * rho / tau[m00]
    dr[m00] = -lam[m00] * mu[m00] / tau[m00]

    dl[m01] = rho / tau[m01]
    dr[m01] = lam[m01] / tau[m01]

    dm[m10] = rho / tau[m10]
    dr[m10] = mu[m10] / tau[m10]

    dr[m11] = -1.0 / tau[m11]

    return np.log(tau), dl, dm, dr


def fit_dixon_coles(
    home_idx: np.ndarray,
    away_idx: np.ndarray,
    home_goals: np.ndarray,
    away_goals: np.ndarray,
    weights: np.ndarray,
    n_teams: int,
    ridge: float = 1.0,
    x0: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Maximum de vraisemblance pondéré, avec gradient analytique."""
    x = home_goals.astype(float)
    y = away_goals.astype(float)
    w = weights.astype(float)

    def objectif(theta):
        a = theta[:n_teams]
        b = theta[n_teams : 2 * n_teams]
        gamma, rho = theta[-2], theta[-1]

        lam = np.exp(a[home_idx] + b[away_idx] + gamma)
        mu = np.exp(a[away_idx] + b[home_idx])
        lam = np.clip(lam, 1e-8, 30.0)
        mu = np.clip(mu, 1e-8, 30.0)

        logtau, dl, dm, dr = _tau_and_grad(x, y, lam, mu, rho)
        ll = w * (x * np.log(lam) - lam + y * np.log(mu) - mu + logtau)

        # pénalité ridge (shrinkage vers la moyenne du groupe)
        penalite = ridge * (np.sum(a**2) + np.sum(b**2))
        cout = -ll.sum() + penalite

        g_lam = w * ((x - lam) + lam * dl)   # -> attaque_dom, defense_ext, gamma
        g_mu = w * ((y - mu) + mu * dm)      # -> attaque_ext, defense_dom

        grad_a = np.bincount(home_idx, g_lam, n_teams) + np.bincount(away_idx, g_mu, n_teams)
        grad_b = np.bincount(away_idx, g_lam, n_teams) + np.bincount(home_idx, g_mu, n_teams)
        grad_gamma = g_lam.sum()
        grad_rho = (w * dr).sum()

        grad = -np.concatenate([grad_a, grad_b, [grad_gamma, grad_rho]])
        grad[:n_teams] += 2.0 * ridge * a
        grad[n_teams : 2 * n_teams] += 2.0 * ridge * b
        return cout, grad

    if x0 is None:
        x0 = np.zeros(2 * n_teams + 2)
        x0[-2] = 0.25    # avantage domicile
        x0[-1] = -0.05   # rho
    bornes = [(-3.0, 3.0)] * (2 * n_teams) + [(-1.0, 1.5), (-0.2, 0.2)]

    res = minimize(objectif, x0, jac=True, method="L-BFGS-B", bounds=bornes,
                   options={"maxiter": 400, "ftol": 1e-10})
    theta = res.x
    return theta[:n_teams], theta[n_teams : 2 * n_teams], float(theta[-2]), float(theta[-1])


def score_matrix(lam: float, mu: float, rho: float, max_goals: int = 12) -> np.ndarray:
    k = np.arange(max_goals + 1)
    m = np.outer(poisson.pmf(k, lam), poisson.pmf(k, mu))
    m[0, 0] *= 1.0 - lam * mu * rho
    m[0, 1] *= 1.0 + lam * rho
    m[1, 0] *= 1.0 + mu * rho
    m[1, 1] *= 1.0 - rho
    m = np.clip(m, 0.0, None)
    return m / m.sum()


def predict_1x2(params: DCParams, home: str, away: str, max_goals: int = 12) -> np.ndarray:
    """(P(dom), P(nul), P(ext)). Équipe inconnue -> rating moyen (= 0 après shrinkage)."""
    idx = params.index
    i, j = idx.get(home), idx.get(away)
    a_i = params.attack[i] if i is not None else 0.0
    b_i = params.defence[i] if i is not None else 0.0
    a_j = params.attack[j] if j is not None else 0.0
    b_j = params.defence[j] if j is not None else 0.0

    lam = float(np.exp(a_i + b_j + params.home_adv))
    mu = float(np.exp(a_j + b_i))
    m = score_matrix(lam, mu, params.rho, max_goals)
    return np.array([np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()])
