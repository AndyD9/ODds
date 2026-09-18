"""Découpage temporel train / validation / test.

Figé le 2026-09-18, AVANT tout résultat (prereg 0001).

Le jeu de TEST n'est touché qu'une fois par version de modèle. Toute
exploration, tout réglage d'hyperparamètre, toute calibration se font sur la
validation. Cette contrainte est la seule chose qui rend le chiffre final
interprétable.
"""

from __future__ import annotations

import pandas as pd

# Bornes calées sur la couverture réelle du benchmark Pinnacle, qui s'arrête
# au 2026-01-14 sur football-data.co.uk (cf. prereg 0001, journal 2026-09-18).
# Choisies pour que le TEST dépasse le seuil de 20 000 du prereg tout en
# gardant le maximum de données d'entraînement.
#   train      : < 2022-01-01                    105 617 matchs
#   validation : [2022-01-01, 2024-01-01)         23 117 matchs
#   test       : >= 2024-01-01                    21 892 matchs
TRAIN_FIN = pd.Timestamp("2022-01-01")
VALID_FIN = pd.Timestamp("2024-01-01")


def assign_split(df: pd.DataFrame, col: str = "date") -> pd.Series:
    d = pd.to_datetime(df[col])
    return pd.Series(
        pd.cut(
            d,
            bins=[pd.Timestamp.min, TRAIN_FIN, VALID_FIN, pd.Timestamp.max],
            labels=["train", "validation", "test"],
            right=False,
        ),
        index=df.index,
    ).astype("string")


def train_valid(df: pd.DataFrame) -> pd.DataFrame:
    """Tout sauf le test. À utiliser pour toute exploration."""
    return df[assign_split(df) != "test"]
