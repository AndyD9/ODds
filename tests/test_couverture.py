"""Couverture — dutching, Kelly simultané, carnet groupé.

Ce que ces tests protègent : les endroits où une couverture mentirait sans
bruit — une répartition qui ne rend pas la même somme, une espérance qui
ne serait pas la somme des jambes, un Kelly simultané qui s'écarterait de
l'optimum, un plafond appliqué à la jambe au lieu du match.
"""

import numpy as np
import pytest
from scipy.optimize import minimize

from odds import paper
from odds.market import couverture as cv
from odds.market.devig import devig
from odds.models.football import buts

# Monaco – Lens, l'exemple de la discussion.
COTES = {"1": 1.90, "N": 3.76, "2": 2.90}
P_LIVRE = dict(zip(("1", "N", "2"), devig([1.90, 3.76, 2.90])))


# ---------------------------------------------------------------------------
# Partitions
# ---------------------------------------------------------------------------

def test_chaque_partition_recouvre_chaque_score_exactement_une_fois():
    x, y = np.meshgrid(np.arange(8), np.arange(8), indexing="ij")
    for nom, codes in cv.PARTITIONS.items():
        somme = sum(buts.marche(c).predicat(x, y).astype(int) for c in codes)
        assert (somme == 1).all(), nom


def test_tout_code_du_catalogue_appartient_a_une_partition():
    for code in buts.MARCHES:
        assert code in cv.PARTITIONS[cv.partition_de(code)]
    with pytest.raises(ValueError):
        cv.partition_de("X")


# ---------------------------------------------------------------------------
# Retour égal
# ---------------------------------------------------------------------------

def test_repartir_rend_la_meme_somme_sur_chaque_issue():
    m = cv.repartir(COTES, 100.0)
    assert m["1"] == pytest.approx(46.29, abs=0.01)
    assert m["N"] == pytest.approx(23.39, abs=0.01)
    assert m["2"] == pytest.approx(30.32, abs=0.01)
    retours = {c: m[c] * COTES[c] for c in COTES}
    assert all(r == pytest.approx(87.94, abs=0.01) for r in retours.values())


def test_couvrir_tout_perd_exactement_la_marge():
    c = cv.couvrir(("1", "N", "2"), COTES, P_LIVRE, 100.0)
    assert c.complete
    # Retour égal : le profit ne dépend plus de l'issue, et vaut 1/Σ − 1.
    for code in c.partition:
        assert c.profit(code) == pytest.approx(100 * (1 / c.booksum - 1))
    assert c.pire == pytest.approx(-12.06, abs=0.01)
    assert c.esperance == pytest.approx(c.pire)


def test_deux_issues_sur_trois_est_une_double_chance():
    c = cv.couvrir(("1", "N"), COTES, P_LIVRE, 100.0)
    assert c.mises["1"] == pytest.approx(66.43, abs=0.01)
    assert c.mises["N"] == pytest.approx(33.57, abs=0.01)
    assert c.profit("1") == pytest.approx(c.profit("N"))
    assert c.meilleur == pytest.approx(26.22, abs=0.01)
    assert c.pire == pytest.approx(-100.0)
    assert c.cote_synthetique == pytest.approx(1.262, abs=0.001)
    assert c.p_couverte == pytest.approx(P_LIVRE["1"] + P_LIVRE["N"])


def test_l_esperance_est_la_somme_des_esperances_des_jambes():
    p = {"1": 0.55, "N": 0.25, "2": 0.20}
    c = cv.couvrir(("1", "N"), COTES, p, 40.0)
    par_jambe = sum(c.mises[k] * (p[k] * COTES[k] - 1.0) for k in c.codes)
    assert c.esperance == pytest.approx(par_jambe)


def test_toutes_les_couvertures_enumere_chaque_sous_ensemble():
    toutes = cv.toutes_les_couvertures(COTES, P_LIVRE, 100.0)
    assert len(toutes) == 2 ** 3 - 1
    # Triées par espérance décroissante ; au livre dévigé, toutes négatives.
    ev = [c.esperance for c in toutes]
    assert ev == sorted(ev, reverse=True)
    assert all(e < 0 for e in ev)


def test_couvrir_refuse_une_issue_hors_partition_et_des_probas_brutes():
    with pytest.raises(ValueError):
        cv.couvrir(("1", "total_over_2.5"), {**COTES, "total_over_2.5": 1.9},
                   P_LIVRE, 10.0)
    brutes = {k: 1 / v for k, v in COTES.items()}      # somme > 1
    with pytest.raises(ValueError):
        cv.couvrir(("1",), COTES, brutes, 10.0)


# ---------------------------------------------------------------------------
# Rembourser
# ---------------------------------------------------------------------------

def test_rembourser_le_nul():
    c = cv.rembourser("1", ("N",), COTES, P_LIVRE, 10.0)
    assert c.mises["N"] == pytest.approx(3.62, abs=0.01)
    assert c.profit("1") == pytest.approx(5.38, abs=0.01)
    assert c.profit("N") == pytest.approx(0.0, abs=1e-9)
    assert c.profit("2") == pytest.approx(-13.62, abs=0.01)


def test_rembourser_impossible_quand_les_secondaires_coutent_trop():
    with pytest.raises(ValueError):
        cv.rembourser("1", ("N", "2"), {"1": 1.9, "N": 1.5, "2": 1.5}, P_LIVRE, 10.0)


# ---------------------------------------------------------------------------
# Kelly simultané
# ---------------------------------------------------------------------------

def _optimum_numerique(p, c):
    """Maximise Σ p_i log(1 − Σf + f_i c_i) sous f ≥ 0, Σf < 1."""
    codes = list(p)
    P = np.array([p[k] for k in codes])
    C = np.array([c[k] for k in codes])

    def objectif(f):
        f = np.asarray(f)
        richesse = 1.0 - f.sum() + f * C
        if (richesse <= 0).any():
            return 1e6
        return -float(np.sum(P * np.log(richesse)))

    r = minimize(objectif, np.full(len(codes), 0.02), method="L-BFGS-B",
                 bounds=[(0.0, 0.6)] * len(codes),
                 options={"ftol": 1e-15, "gtol": 1e-12, "maxiter": 10_000})
    return dict(zip(codes, r.x))


def test_kelly_simultane_une_seule_issue_redonne_kelly():
    p = {"1": 0.50, "N": 0.30, "2": 0.20}         # seul le nul a de la valeur
    f = cv.kelly_simultane(p, COTES)
    assert f["N"] == pytest.approx(paper.kelly(0.30, 3.76))
    assert f["1"] == 0.0 and f["2"] == 0.0


def test_kelly_simultane_ne_couvre_rien_au_prix_du_livre():
    f = cv.kelly_simultane(P_LIVRE, COTES)
    assert all(v == 0.0 for v in f.values())
    assert paper.proposer_couverture(1000.0, P_LIVRE, COTES)["plafond"] == "kelly"


def test_kelly_simultane_couvre_une_jambe_sans_valeur_quand_la_position_est_grosse():
    # Monaco a de la valeur (0,58 × 1,90 = 1,10) ; le nul n'en a pas seul
    # (0,24 × 3,76 = 0,90). Kelly le couvre quand même : de la variance
    # rachetée, pas de la valeur. C'est LE cas où « couvrir » se justifie.
    p = {"1": 0.58, "N": 0.24, "2": 0.18}
    f = cv.kelly_simultane(p, COTES)
    assert f["1"] > 0 and f["N"] > 0 and f["2"] == 0.0
    assert p["N"] * COTES["N"] < 1.0
    num = _optimum_numerique(p, COTES)
    for k in f:
        assert f[k] == pytest.approx(num[k], abs=2e-4), k


@pytest.mark.parametrize("graine", range(6))
def test_kelly_simultane_egale_l_optimum_numerique(graine):
    rng = np.random.default_rng(graine)
    p = rng.dirichlet([2, 1.5, 2])
    # Cotes autour du prix juste, avec un peu de bruit : de la valeur ici ou là.
    c = 1.0 / p * rng.uniform(0.9, 1.15, size=3)
    P = dict(zip(("1", "N", "2"), p))
    C = dict(zip(("1", "N", "2"), c))
    if sum(1 / v for v in c) < 1.0:
        pytest.skip("sur-arbitrage : Kelly non borné, hors du domaine testé")
    f = cv.kelly_simultane(P, C)
    num = _optimum_numerique(P, C)
    for k in f:
        assert f[k] == pytest.approx(num[k], abs=5e-4), (k, P, C)
    assert sum(f.values()) < 1.0


def test_couverture_kelly_en_euros():
    p = {"1": 0.58, "N": 0.24, "2": 0.18}
    c = cv.couverture_kelly(p, COTES, bankroll=1000.0, fraction=0.1)
    f = cv.kelly_simultane(p, COTES)
    assert c.mises["1"] == pytest.approx(1000 * 0.1 * f["1"])
    assert cv.couverture_kelly(P_LIVRE, COTES, 1000.0) is None


# ---------------------------------------------------------------------------
# Moteur de mise
# ---------------------------------------------------------------------------

def test_proposer_couverture_plafonne_la_somme_des_jambes_pas_chacune():
    p = {"1": 0.58, "N": 0.24, "2": 0.18}
    r = paper.proposer_couverture(bankroll=1000.0, probas=p, cotes=COTES)
    assert set(r["mises"]) == {"1", "N"}
    assert r["total"] == pytest.approx(10.0, abs=0.01)     # 1 % du match
    assert r["plafond"] == "match"
    # Les proportions de Kelly sont conservées sous le plafond.
    f = r["fractions"]
    assert r["mises"]["1"] / r["mises"]["N"] == pytest.approx(f["1"] / f["N"], rel=1e-2)


def test_proposer_couverture_sur_une_issue_egale_proposer_mise():
    p = {"1": 0.50, "N": 0.30, "2": 0.20}
    r = paper.proposer_couverture(bankroll=1000.0, probas=p, cotes=COTES)
    seul = paper.proposer_mise(bankroll=1000.0, p=0.30, cote=3.76)
    assert set(r["mises"]) == {"N"}
    assert r["mises"]["N"] == pytest.approx(seul["mise"])
    assert r["plafond"] is None


def test_proposer_couverture_respecte_l_exposition():
    p = {"1": 0.58, "N": 0.24, "2": 0.18}
    r = paper.proposer_couverture(bankroll=1000.0, probas=p, cotes=COTES,
                                  exposition=48.0)
    assert r["total"] == pytest.approx(2.0, abs=0.01)
    assert r["plafond"] == "exposition"


def test_proposer_couverture_applique_la_confiance():
    p = {"1": 0.58, "N": 0.24, "2": 0.18}
    plein = paper.proposer_couverture(1000.0, p, COTES, n_books=12)
    derive = paper.proposer_couverture(1000.0, p, COTES, n_books=12, p_cotee=False)
    assert derive["total_theorique"] == pytest.approx(
        plein["total_theorique"] * paper.CONFIANCE_PENALITE_DERIVEE)


# ---------------------------------------------------------------------------
# Carnet
# ---------------------------------------------------------------------------

@pytest.fixture
def carnet(tmp_path):
    return tmp_path / "paper.db"


def test_enregistrer_couverture_lie_les_jambes_et_se_regle_d_un_score(carnet):
    p = {"1": 0.58, "N": 0.24, "2": 0.18}
    c = cv.couvrir(("1", "N"), COTES, p, 10.0)
    groupe = paper.enregistrer_couverture(
        "oa:ml", "2026-09-20 19:00", "Monaco", "Lens", c,
        bookmakers={"1": "bet365", "N": "bwin"}, chemin=carnet)
    d = paper.paris(carnet)
    assert len(d) == 2
    assert set(d.groupe) == {groupe}
    assert d.mise.sum() == pytest.approx(10.0)

    # Match nul : la jambe « nul » gagne, la jambe « Monaco » perd, et le net
    # du groupe est celui que la couverture annonçait.
    assert paper.regler_match("oa:ml", 1, 1, chemin=carnet) == 2
    d = paper.paris(carnet)
    assert d.profit.sum() == pytest.approx(c.profit("N"))
    cs = paper.couvertures(d)
    assert len(cs) == 1
    assert cs.profit.iloc[0] == pytest.approx(c.profit("N"))
    assert cs.statut.iloc[0] == "réglée"
    assert cs.pire.iloc[0] == pytest.approx(-10.0)     # Lens : tout perdu
    assert cs.n_jambes.iloc[0] == 2


def test_un_pari_isole_n_a_pas_de_groupe(carnet):
    paper.enregistrer("oa:x", "2026-09-20 19:00", "A", "B", "1", 2.0, 0.55, 5.0,
                      chemin=carnet)
    d = paper.paris(carnet)
    assert d.groupe.isna().all()
    assert len(paper.couvertures(d)) == 0


def test_couverture_complete_a_un_pire_cas_borne(carnet):
    c = cv.couvrir(("1", "N", "2"), COTES, P_LIVRE, 100.0)
    paper.enregistrer_couverture("oa:c", "2026-09-20 19:00", "Monaco", "Lens", c,
                                 chemin=carnet)
    cs = paper.couvertures(paper.paris(carnet))
    assert cs.pire.iloc[0] == pytest.approx(-12.06, abs=0.01)
    assert cs.statut.iloc[0] == "en attente"


def test_un_carnet_v2_recoit_la_colonne_groupe(carnet):
    import sqlite3
    con = sqlite3.connect(carnet)
    con.executescript("""
        CREATE TABLE pari (id INTEGER PRIMARY KEY AUTOINCREMENT, place_a TEXT,
            fixture_key TEXT, source TEXT, league TEXT, kickoff TEXT,
            home_team TEXT, away_team TEXT, issue TEXT, marche TEXT, cote REAL,
            bookmaker TEXT, p_modele REAL, methode TEXT, mise REAL,
            mise_proposee REAL, bankroll_avant REAL, kelly REAL, f_effectif REAL,
            plafond TEXT, cote_cloture REAL, book_cloture TEXT, resultat TEXT,
            buts_dom INTEGER, buts_ext INTEGER, regle_a TEXT, note TEXT);
        CREATE TABLE reglage (cle TEXT PRIMARY KEY, valeur TEXT);
        INSERT INTO reglage VALUES ('schema_version', '2');
        INSERT INTO pari (place_a, fixture_key, kickoff, home_team, away_team,
            issue, marche, cote, p_modele, mise, resultat)
        VALUES ('2026-09-18 10:00:00', 'fk', '2026-09-18 18:00', 'A', 'B',
                '1', '1X2', 2.0, 0.55, 10.0, 'gagne');
    """)
    con.commit(); con.close()
    d = paper.paris(carnet)
    assert "groupe" in d.columns and d.groupe.isna().all()
    assert d.statut.iloc[0] == "gagné"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_couvrir(capsys):
    from odds.cli import main
    assert main(["couvrir", "1.90", "3.76", "2.90"]) == 0
    sortie = capsys.readouterr().out
    assert "12.06" in sortie                      # la perte garantie de la couverture complète
    assert "aucune issue ne bat sa réserve" in sortie
    assert main(["couvrir", "1.90", "3.76", "2.90", "--probas", "0.58", "0.24", "0.18",
                 "--libelles", "Monaco", "Nul", "Lens"]) == 0
    sortie = capsys.readouterr().out
    assert "Monaco" in sortie and "espérance négative seule" in sortie
    assert main(["couvrir", "1.90"]) == 1
