"""Métriques de calibration. Brier et log loss multiclasses."""

from __future__ import annotations

import numpy as np


def brier(p: np.ndarray, y: np.ndarray) -> float:
    """Brier multiclasse : moyenne sur les matchs de somme_k (p_k - y_k)^2.

    Borne : 0 (parfait) à 2 (pire). Un modèle uniforme à 3 issues vaut 2/3.
    """
    return float(np.mean(np.sum((p - y) ** 2, axis=1)))


def log_loss(p: np.ndarray, y: np.ndarray, eps: float = 1e-15) -> float:
    return float(-np.mean(np.sum(y * np.log(np.clip(p, eps, 1.0)), axis=1)))


def brier_par_match(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.sum((p - y) ** 2, axis=1)


def log_loss_par_match(p: np.ndarray, y: np.ndarray, eps: float = 1e-15) -> np.ndarray:
    return -np.sum(y * np.log(np.clip(p, eps, 1.0)), axis=1)


def bootstrap_blocs(
    valeurs_a: np.ndarray,
    valeurs_b: np.ndarray,
    blocs: np.ndarray,
    n_iter: int = 2000,
    seed: int = 20260918,
) -> tuple[float, float, float]:
    """IC 95 % de la différence moyenne (a - b), par bootstrap de BLOCS.

    Les matchs d'une même journée/saison ne sont pas indépendants. Un
    bootstrap i.i.d. sous-estimerait donc l'intervalle. On rééchantillonne
    des blocs entiers.

    Renvoie (différence observée, borne basse, borne haute).
    """
    diff = valeurs_a - valeurs_b
    observe = float(diff.mean())

    codes, inverse = np.unique(blocs, return_inverse=True)
    ordre = np.argsort(inverse, kind="stable")
    debuts = np.searchsorted(inverse[ordre], np.arange(len(codes)))
    fins = np.append(debuts[1:], len(ordre))
    par_bloc = [ordre[d:f] for d, f in zip(debuts, fins)]

    rng = np.random.default_rng(seed)
    tirages = np.empty(n_iter)
    n_blocs = len(par_bloc)
    for i in range(n_iter):
        choix = rng.integers(0, n_blocs, n_blocs)
        idx = np.concatenate([par_bloc[c] for c in choix])
        tirages[i] = diff[idx].mean()
    return observe, float(np.percentile(tirages, 2.5)), float(np.percentile(tirages, 97.5))
