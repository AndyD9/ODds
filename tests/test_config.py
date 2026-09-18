"""Tests de la configuration locale.

Le point critique est le masquage : rien de ce module ne doit pouvoir faire
apparaître une clé en clair dans une sortie, un log ou une capture d'écran.
"""

import pytest

from odds import config


@pytest.fixture
def env(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    monkeypatch.setattr(config, "FICHIER_ENV", f)
    config.recharger()
    yield f
    config.recharger()


def test_parser_formats_courants():
    p = config._parser(
        "# commentaire\n"
        "A=1\n"
        "  B = deux  \n"
        'C="entre guillemets"\n'
        "D='apostrophes'\n"
        "\n"
        "ligne sans egal\n"
        "E=avec=des=egals\n"
    )
    assert p == {"A": "1", "B": "deux", "C": "entre guillemets",
                 "D": "apostrophes", "E": "avec=des=egals"}


def test_environnement_prime_sur_fichier(env, monkeypatch):
    env.write_text("ODDS_API_REGIONS=uk\n")
    config.recharger()
    assert config.get("ODDS_API_REGIONS") == "uk"
    monkeypatch.setenv("ODDS_API_REGIONS", "us")
    assert config.get("ODDS_API_REGIONS") == "us"


def test_valeur_par_defaut_si_absent(env):
    env.write_text("")
    config.recharger()
    assert config.get("ODDS_API_REGIONS") == "eu"
    assert config.get("ODDS_API_KEY") is None
    assert config.est_configure("ODDS_API_KEY") is False


def test_cle_jamais_en_clair_dans_le_resume(env, monkeypatch):
    secret = "sk_live_0123456789abcdef"
    env.write_text(f"ODDS_API_KEY={secret}\n")
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    config.recharger()

    assert config.get("ODDS_API_KEY") == secret, "la valeur reste lisible par le code"

    texte = str(config.resume())
    assert secret not in texte, "LA CLE FUITE dans resume()"
    assert secret[4:-4] not in texte, "le corps de la clé fuite"
    ligne = [e for e in config.resume() if e["réglage"] == "ODDS_API_KEY"][0]
    assert ligne["valeur"].startswith("sk_l") and ligne["valeur"].endswith("cdef")
    assert "*" in ligne["valeur"]


def test_masquage_cle_courte():
    assert config._masquer("abc") == "***"
    assert config._masquer("12345678") == "********"
    assert config._masquer("123456789") == "1234*6789"


def test_cle_absente_nest_pas_masquee_en_etoiles(env):
    env.write_text("ODDS_API_KEY=\n")
    config.recharger()
    ligne = [e for e in config.resume() if e["réglage"] == "ODDS_API_KEY"][0]
    assert ligne["valeur"] == "(non renseigné)"
    assert ligne["ok"] is False


def test_get_liste(env):
    env.write_text("ODDS_API_SPORTS=a, b ,c,,\n")
    config.recharger()
    assert config.get_liste("ODDS_API_SPORTS") == ["a", "b", "c"]


def test_cout_par_passe(env):
    env.write_text("ODDS_API_SPORTS=a,b,c\nODDS_API_MARKETS=h2h,totals\nODDS_API_REGIONS=eu\n")
    config.recharger()
    assert config.cout_par_passe() == 6           # 3 x 2 x 1
    env.write_text("ODDS_API_SPORTS=a,b,c\nODDS_API_MARKETS=h2h,totals\nODDS_API_REGIONS=eu,uk\n")
    config.recharger()
    assert config.cout_par_passe() == 12          # 3 x 2 x 2


def test_exemple_ne_contient_aucune_valeur_de_cle():
    """.env.example est versionné : il ne doit jamais porter de secret."""
    txt = config.FICHIER_EXEMPLE.read_text(encoding="utf-8")
    for ligne in txt.splitlines():
        if ligne.startswith("ODDS_API_KEY"):
            assert ligne.strip() == "ODDS_API_KEY=", "valeur non vide dans .env.example"


def test_env_est_ignore_par_git():
    ignore = (config.RACINE / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in [l.strip() for l in ignore], ".env DOIT être dans .gitignore"
