"""Tests des modules transverses : vocabulaire de la collecte, chemins, temps.

Ce qu'ils protègent : les invariants sur lesquels plusieurs modules
s'appuient sans les vérifier eux-mêmes — la traduction unique entre codes de
pari et lignes collectées, l'ordre lexicographique des horodatages, et le
rapatriement des bases d'état depuis leur ancien emplacement.
"""

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from odds import chemins, temps
from odds.market.vocabulaire import (MARCHE_1X2, MARCHE_TOTAUX, code_collecte,
                                     selection_collectee, selection_totaux)
from odds.models.football import buts


# --- vocabulaire -----------------------------------------------------------

def test_aller_retour_sur_tous_les_marches_collectables():
    for code in buts.MARCHES:
        paire = selection_collectee(code)
        if paire is None:
            # Non collecté : totaux par équipe et BTTS, et rien d'autre.
            assert buts.marche(code).famille in ("total_dom", "total_ext", "btts"), code
            continue
        assert code_collecte(*paire) == code, code


def test_le_vocabulaire_est_celui_de_the_odds_api():
    assert selection_collectee("1") == (MARCHE_1X2, "home")
    assert selection_collectee("total_over_2.5") == (MARCHE_TOTAUX, "over_2.5")
    assert selection_totaux(3.5, "under") == "under_3.5"
    assert code_collecte("totals", "over_1.5") == "total_over_1.5"
    assert code_collecte("h2h_lay", "home") is None
    assert code_collecte("totals", "n_importe_quoi") is None


# --- temps -----------------------------------------------------------------

def test_l_ordre_lexicographique_est_l_ordre_chronologique():
    """Les requêtes de clôture comparent des chaînes de formats différents.
    Cela ne tient que par le préfixe commun : on le vérifie explicitement."""
    kickoff = temps.minute("2026-09-18 18:30")
    avant = temps.seconde("2026-09-18 18:29:59")
    apres = temps.seconde("2026-09-18 18:30:00")
    assert avant <= kickoff < apres
    assert temps.jour("2026-09-18 23:59") == "2026-09-18"


def test_un_horodatage_avec_fuseau_est_ramene_en_utc():
    import pandas as pd
    assert temps.minute(pd.Timestamp("2026-09-18 20:30", tz="Europe/Paris")) == "2026-09-18 18:30"
    s = pd.Series(["2026-09-18T18:30:00Z"])
    assert temps.serie_en_minutes(s).iloc[0] == "2026-09-18 18:30"


# --- chemins ---------------------------------------------------------------

def test_rapatrier_deplace_une_base_de_l_ancien_emplacement(tmp_path, monkeypatch):
    etat, recherche = tmp_path / "data", tmp_path / "research" / "data"
    recherche.mkdir(parents=True)
    (recherche / "paper.db").write_bytes(b"carnet")
    monkeypatch.setattr(chemins, "ETAT", etat)
    monkeypatch.setattr(chemins, "RECHERCHE", recherche)

    cible = chemins.rapatrier(etat / "paper.db")
    assert cible.read_bytes() == b"carnet"
    assert not (recherche / "paper.db").exists()
    # Idempotent, et sans effet hors du dossier d'état.
    assert chemins.rapatrier(cible) == cible
    ailleurs = tmp_path / "x.db"
    assert chemins.rapatrier(ailleurs) == ailleurs and not ailleurs.exists()


# --- fiabilité datée -------------------------------------------------------

def _ecrire_table(chemin, meta):
    import pandas as pd
    t = pa.Table.from_pandas(pd.DataFrame({"code": ["btts_oui"], "contraint": [False],
                                           "borne_inf": [0.4], "borne_sup": [0.6],
                                           "n": [1000], "reussite": [0.5],
                                           "ic95": [0.03], "p_moyenne": [0.5]}),
                             preserve_index=False)
    pq.write_table(t.replace_schema_metadata(meta), chemin)


def test_une_table_calculee_pour_un_autre_rho_est_refusee(tmp_path, monkeypatch):
    from odds.analysis import fiabilite
    chemin = tmp_path / "f.parquet"
    monkeypatch.setattr(chemins, "FIABILITE_BUTS", chemin)

    bonne = fiabilite.metadonnees_fiabilite()
    _ecrire_table(chemin, {**bonne, fiabilite.CLE_RHO: b"-0.05"})
    t = fiabilite.fiabilite_buts()
    assert len(t) == 0 and "rho" in t.attrs["motif"] and "-0.05" in t.attrs["motif"]
    assert fiabilite.tranche_fiabilite_buts("btts_oui", 0.5) is None

    # Réécrite au même chemin : le cache, indexé sur la date du fichier, suit.
    import os, time
    _ecrire_table(chemin, bonne)
    os.utime(chemin, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
    t = fiabilite.fiabilite_buts()
    assert len(t) == 1
    assert fiabilite.tranche_fiabilite_buts("btts_oui", 0.5).n == 1000


def test_la_signature_du_catalogue_change_avec_ses_codes(monkeypatch):
    avant = buts.signature_catalogue()
    monkeypatch.setitem(buts.MARCHES, "faux_marche", buts.MARCHES["btts_oui"])
    assert buts.signature_catalogue() != avant
