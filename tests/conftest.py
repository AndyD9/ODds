"""Garde-fous appliqués à TOUS les tests.

Motif : `collecter()` déclenche la passe The Odds API dès que ODDS_API_KEY
est configurée — et elle l'est, via .env. Sans ce fichier, lancer la suite
consomme de vrais crédits payants, silencieusement. C'est arrivé.

Deux verrous, tous deux automatiques :

1. la configuration est neutralisée (aucune clé visible depuis un test) ;
2. tout appel réseau du client The Odds API lève immédiatement.

Un test qui a réellement besoin d'un de ces comportements doit le
réactiver explicitement, ce qui le rend visible à la relecture.
"""

import pytest


@pytest.fixture(autouse=True)
def aucun_appel_api_payant(tmp_path_factory, monkeypatch):
    from odds import config
    from odds.data import oddsapi

    # 1) .env pointé vers un fichier inexistant + variable d'environnement
    #    effacée : plus aucune clé n'est visible.
    monkeypatch.setattr(config, "FICHIER_ENV",
                        tmp_path_factory.mktemp("env") / ".env")
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    # Hébergement (decisions/0009) : ni copie distante ni comptes pendant
    # les tests — le carnet reste local, l'utilisateur reste « local ».
    for cle in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_BUCKET",
                "ODDS_INVITES", "ODDS_PROPRIETAIRE"):
        monkeypatch.delenv(cle, raising=False)
    config.recharger()

    # 2) ceinture et bretelles : la couche réseau elle-même est bloquée.
    def interdit(*a, **k):
        raise AssertionError(
            "Un test a tenté un appel réseau vers The Odds API. "
            "Les tests ne doivent jamais consommer de crédits payants.")

    monkeypatch.setattr(oddsapi, "_get", interdit)

    # 3) même verrou sur la copie distante de l'état : un test qui la
    #    configure par mégarde ne doit pas écrire dans un vrai seau.
    from odds import stockage

    def interdit_stockage(*a, **k):
        raise AssertionError("Un test a tenté un appel réseau vers Supabase Storage.")

    monkeypatch.setattr(stockage, "_requete", interdit_stockage)

    yield
    config.recharger()
