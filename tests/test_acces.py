"""Liens personnels et utilisateur du carnet — decisions/0009.

La clé est le sésame, le nom devient l'utilisateur. Ce qui est testé : la
lecture des invités, la comparaison des clés, le mode local quand il n'y a
personne, et le fait que chacun ne voit que ses paris.
"""

import pytest

from odds import config, paper
from odds.app import acces


def test_sans_invite_on_reste_en_mode_local():
    assert acces.invites() == {}
    assert acces.ouvrir() is None
    assert paper.utilisateur_courant() == paper.UTILISATEUR_LOCAL


def test_les_invites_se_lisent_depuis_l_environnement(monkeypatch):
    monkeypatch.setenv("ODDS_INVITES", "Andy:k1 , paul:k2, malforme, :k3")
    config.recharger()
    assert acces.invites() == {"k1": "andy", "k2": "paul"}


def test_identifier_ne_reconnait_que_la_cle_exacte():
    liste = {"abcdefghijklmnopqrstuvwxyz012345": "andy"}
    assert acces.identifier("abcdefghijklmnopqrstuvwxyz012345", liste) == "andy"
    assert acces.identifier(" abcdefghijklmnopqrstuvwxyz012345 ", liste) == "andy"
    assert acces.identifier("abcdefghijklmnopqrstuvwxyz01234", liste) is None
    assert acces.identifier("", liste) is None
    assert acces.identifier(None, liste) is None


def test_une_cle_neuve_est_longue_et_sure_pour_une_adresse():
    a, b = acces.nouvelle_cle(), acces.nouvelle_cle()
    assert a != b
    assert len(a) >= 32
    assert all(c.isalnum() or c in "-_" for c in a)


@pytest.fixture
def carnet(tmp_path):
    return tmp_path / "paper.db"


def _pari(carnet, **kw):
    base = dict(fixture_key="m1", kickoff="2026-10-01 20:00", home_team="A",
                away_team="B", issue="1", cote=2.0, p_modele=0.55, mise=5.0,
                chemin=carnet)
    base.update(kw)
    return paper.enregistrer(**base)


def test_chacun_ne_voit_et_ne_touche_que_ses_paris(carnet):
    paper.definir_utilisateur("andy")
    try:
        id_andy = _pari(carnet)
        paper.definir_utilisateur("paul")
        id_paul = _pari(carnet, issue="2")

        assert list(paper.paris(carnet).id) == [id_paul]
        with pytest.raises(KeyError):
            paper.annuler(id_andy, chemin=carnet)     # pas le sien
        paper.supprimer(id_andy, chemin=carnet)       # silencieux, et sans effet

        paper.definir_utilisateur("andy")
        d = paper.paris(carnet)
        assert list(d.id) == [id_andy]
        assert d.resultat.isna().all()
    finally:
        paper.definir_utilisateur(None)


def test_le_score_regle_les_paris_de_tout_le_monde(carnet):
    """Un score est un fait : qui le saisit règle le match pour tous."""
    paper.definir_utilisateur("andy")
    try:
        _pari(carnet, issue="1")
        paper.definir_utilisateur("paul")
        _pari(carnet, issue="2")
        assert paper.regler_match("m1", 2, 0, chemin=carnet) == 2
        assert list(paper.paris(carnet).resultat) == ["perdu"]
        paper.definir_utilisateur("andy")
        assert list(paper.paris(carnet).resultat) == ["gagne"]
    finally:
        paper.definir_utilisateur(None)


def test_chaque_invite_a_sa_bankroll_le_proprietaire_garde_l_historique(carnet, monkeypatch):
    monkeypatch.setenv("ODDS_PROPRIETAIRE", "andy")
    config.recharger()
    try:
        # Sans contexte posé, l'utilisateur courant est le propriétaire.
        assert paper.utilisateur_courant() == "andy"
        paper.definir_bankroll_initiale(500.0, chemin=carnet)
        paper.definir_utilisateur("paul")
        assert paper.bankroll_initiale(carnet) == paper.BANKROLL_DEFAUT
        paper.definir_bankroll_initiale(200.0, chemin=carnet)
        paper.definir_utilisateur("andy")
        assert paper.bankroll_initiale(carnet) == 500.0
    finally:
        paper.definir_utilisateur(None)
        config.recharger()


def test_le_proprietaire_adopte_les_paris_inscrits_avant_les_comptes(carnet, monkeypatch):
    id_local = _pari(carnet)                      # utilisateur « local »
    assert list(paper.paris(carnet).id) == [id_local]
    monkeypatch.setenv("ODDS_PROPRIETAIRE", "andy")
    config.recharger()
    try:
        paper.definir_utilisateur("andy")
        assert list(paper.paris(carnet).id) == [id_local]
        paper.definir_utilisateur("paul")
        assert len(paper.paris(carnet)) == 0
    finally:
        paper.definir_utilisateur(None)
        config.recharger()
