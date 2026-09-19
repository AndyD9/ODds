"""Liste d'invités et utilisateur du carnet — decisions/0009.

La connexion elle-même est celle de Streamlit (``st.login``) ; ce qui nous
appartient, et qui est testé ici, c'est la règle d'entrée et le fait que
chacun ne voit que ses paris.
"""

import pytest

from odds import config, paper
from odds.app import acces


def test_la_liste_vide_ne_laisse_entrer_personne():
    assert not acces.autorise("a@b.c", frozenset())
    assert not acces.autorise(None, frozenset({"a@b.c"}))
    assert not acces.autorise("", frozenset({"a@b.c"}))


def test_l_adresse_est_comparee_sans_casse_ni_espaces(monkeypatch):
    monkeypatch.setenv("ODDS_INVITES", "Andy@Example.com , ami@example.com")
    config.recharger()
    assert acces.invites() == {"andy@example.com", "ami@example.com"}
    assert acces.autorise("  ANDY@example.com ")
    assert not acces.autorise("inconnu@example.com")


def test_sans_auth_configuree_on_reste_en_mode_local():
    assert acces.ouvrir() is None
    assert paper.utilisateur_courant() == paper.UTILISATEUR_LOCAL


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
    paper.definir_utilisateur("andy@example.com")
    try:
        id_andy = _pari(carnet)
        paper.definir_utilisateur("ami@example.com")
        id_ami = _pari(carnet, issue="2")

        assert list(paper.paris(carnet).id) == [id_ami]
        with pytest.raises(KeyError):
            paper.annuler(id_andy, chemin=carnet)     # pas le sien
        paper.supprimer(id_andy, chemin=carnet)       # silencieux, et sans effet

        paper.definir_utilisateur("andy@example.com")
        d = paper.paris(carnet)
        assert list(d.id) == [id_andy]
        assert d.resultat.isna().all()
    finally:
        paper.definir_utilisateur(None)


def test_le_score_regle_les_paris_de_tout_le_monde(carnet):
    """Un score est un fait : qui le saisit règle le match pour tous."""
    paper.definir_utilisateur("andy@example.com")
    try:
        _pari(carnet, issue="1")
        paper.definir_utilisateur("ami@example.com")
        _pari(carnet, issue="2")
        assert paper.regler_match("m1", 2, 0, chemin=carnet) == 2
        assert list(paper.paris(carnet).resultat) == ["perdu"]
        paper.definir_utilisateur("andy@example.com")
        assert list(paper.paris(carnet).resultat) == ["gagne"]
    finally:
        paper.definir_utilisateur(None)


def test_chaque_invite_a_sa_bankroll_le_proprietaire_garde_l_historique(carnet, monkeypatch):
    monkeypatch.setenv("ODDS_PROPRIETAIRE", "andy@example.com")
    config.recharger()
    try:
        # Sans contexte posé, l'utilisateur courant est le propriétaire.
        assert paper.utilisateur_courant() == "andy@example.com"
        paper.definir_bankroll_initiale(500.0, chemin=carnet)
        paper.definir_utilisateur("ami@example.com")
        assert paper.bankroll_initiale(carnet) == paper.BANKROLL_DEFAUT
        paper.definir_bankroll_initiale(200.0, chemin=carnet)
        paper.definir_utilisateur("andy@example.com")
        assert paper.bankroll_initiale(carnet) == 500.0
    finally:
        paper.definir_utilisateur(None)
        config.recharger()


def test_le_proprietaire_adopte_les_paris_inscrits_avant_les_comptes(carnet, monkeypatch):
    id_local = _pari(carnet)                      # utilisateur « local »
    assert list(paper.paris(carnet).id) == [id_local]
    monkeypatch.setenv("ODDS_PROPRIETAIRE", "andy@example.com")
    config.recharger()
    try:
        paper.definir_utilisateur("andy@example.com")
        assert list(paper.paris(carnet).id) == [id_local]
        paper.definir_utilisateur("ami@example.com")
        assert len(paper.paris(carnet)) == 0
    finally:
        paper.definir_utilisateur(None)
        config.recharger()
