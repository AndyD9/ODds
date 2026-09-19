"""Copie distante de l'état — decisions/0009.

Le réseau est remplacé par un seau en mémoire : ce qui est testé, c'est le
contrat — inerte sans configuration, ne télécharge que ce qui a changé,
ne remplace jamais un fichier local par une absence distante, écrit de
façon atomique.
"""

import json

import pytest

from odds import config, stockage


class Seau:
    """Un faux Supabase Storage : objets + réponses HTTP minimales."""

    def __init__(self):
        self.objets: dict[str, bytes] = {}
        self.appels: list[tuple[str, str]] = []

    def requete(self, methode, url, **kw):
        self.appels.append((methode, url))
        chemin = url.split("/storage/v1/", 1)[1]
        if chemin.startswith("object/list/"):
            return _Rep(json=[{"name": n, "metadata": {"eTag": f'"{hash(b)}"'}}
                              for n, b in self.objets.items()])
        if chemin.startswith("object/authenticated/"):
            nom = chemin.split("/", 3)[3]
            if nom not in self.objets:
                raise AssertionError("404")
            return _Rep(content=self.objets[nom])
        if chemin.startswith("object/") and methode == "POST":
            nom = chemin.split("/", 2)[2]
            assert kw["headers"].get("x-upsert") == "true"
            self.objets[nom] = kw["data"]
            return _Rep(json={"Key": nom})
        raise AssertionError(f"appel inattendu : {methode} {url}")


class _Rep:
    def __init__(self, json=None, content=b""):
        self._json, self.content = json, content

    def json(self):
        return self._json


@pytest.fixture
def seau(tmp_path, monkeypatch):
    s = Seau()
    monkeypatch.setattr(stockage, "_requete", s.requete)
    monkeypatch.setattr(stockage, "EMPREINTES", tmp_path / "empreintes.json")
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "cle")
    config.recharger()
    yield s
    config.recharger()


def test_sans_configuration_tout_est_inerte(tmp_path, monkeypatch):
    f = tmp_path / "paper.db"
    f.write_bytes(b"x")
    assert not stockage.actif()
    assert stockage.publier(f) is False
    assert stockage.rafraichir(f) is False
    assert stockage.demarrer() == []


def test_publier_puis_rafraichir_ne_retelecharge_pas_sans_changement(tmp_path, seau):
    f = tmp_path / "paper.db"
    f.write_bytes(b"v1")
    assert stockage.publier(f) is True
    assert seau.objets["paper.db"] == b"v1"
    # L'empreinte a été relue après la copie : rien à ramener.
    assert stockage.rafraichir(f) is False
    assert not any(u.endswith("object/authenticated/etat/paper.db") for _, u in seau.appels)


def test_rafraichir_ramene_une_version_distante_plus_recente(tmp_path, seau):
    f = tmp_path / "odds_history.db"
    f.write_bytes(b"ancien")
    seau.objets["odds_history.db"] = b"nouveau"       # écrit par le collecteur
    assert stockage.rafraichir(f) is True
    assert f.read_bytes() == b"nouveau"
    assert not f.with_name("odds_history.db.part").exists(), "écriture atomique"
    assert stockage.rafraichir(f) is False, "déjà à jour"


def test_une_absence_distante_ne_remplace_jamais_le_local(tmp_path, seau):
    f = tmp_path / "paper.db"
    f.write_bytes(b"le carnet d'origine")
    assert stockage.rafraichir(f) is False
    assert f.read_bytes() == b"le carnet d'origine"


def test_publier_un_fichier_absent_ne_fait_rien(tmp_path, seau):
    assert stockage.publier(tmp_path / "inexistant.db") is False
    assert seau.objets == {}


def test_demarrer_ramene_les_fichiers_connus(tmp_path, seau, monkeypatch):
    fichiers = {"paper.db": tmp_path / "paper.db",
                "odds_history.db": tmp_path / "odds_history.db"}
    monkeypatch.setattr(stockage, "FICHIERS", fichiers)
    seau.objets["paper.db"] = b"carnet"
    assert stockage.demarrer() == ["paper.db"]
    assert fichiers["paper.db"].read_bytes() == b"carnet"
    assert not fichiers["odds_history.db"].exists()
    empreintes = json.loads(stockage.EMPREINTES.read_text())
    assert set(empreintes) == {"paper.db"}
