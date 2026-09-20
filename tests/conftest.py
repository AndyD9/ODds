"""Garde-fous appliqués à TOUS les tests.

Motif : `collecter()` déclenche la passe The Odds API dès que ODDS_API_KEY
est configurée — et elle l'est, via .env. Sans ce fichier, lancer la suite
consomme de vrais crédits payants, silencieusement. C'est arrivé.

Trois verrous, tous automatiques :

1. la configuration est neutralisée (aucune clé visible depuis un test) —
   ni .env, ni variables d'environnement, ni secrets Streamlit ;
2. tout appel réseau du client The Odds API lève immédiatement ;
3. tout appel réseau vers la copie distante de l'état (decisions/0009) lève
   immédiatement : un test qui la configure par mégarde ne doit pas écrire
   dans un vrai seau.

Portée **session**, et c'est important : le test de fumée construit son
tableau de bord dans une fixture de module, que pytest instancie AVANT toute
fixture de fonction. Un verrou de portée fonction arriverait après le premier
rendu — et un `.streamlit/secrets.toml` laissé sur le poste après un essai
d'hébergement ferait passer la page d'accueil pour une porte fermée.

Un test qui a réellement besoin d'un de ces comportements doit le
réactiver explicitement, ce qui le rend visible à la relecture.
"""

import pytest

CLES_NEUTRALISEES = ("ODDS_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY",
                     "SUPABASE_BUCKET", "ODDS_INVITES", "ODDS_PROPRIETAIRE", "ODDS_URL")


@pytest.fixture(autouse=True, scope="session")
def aucun_appel_api_payant(tmp_path_factory):
    from odds import config, stockage
    from odds.data import oddsapi

    mp = pytest.MonkeyPatch()

    # 1) .env pointé vers un fichier inexistant, variables d'environnement
    #    effacées, secrets Streamlit absents : plus aucune clé n'est visible.
    #    Les secrets sont neutralisés dans ``config``, hors du dossier de
    #    l'application : le harnais AppTest réimporte ``odds.app.*`` à chaque
    #    exécution, un attribut remplacé là serait perdu.
    mp.setattr(config, "FICHIER_ENV", tmp_path_factory.mktemp("env") / ".env")
    for cle in CLES_NEUTRALISEES:
        mp.delenv(cle, raising=False)
    mp.setattr(config, "_secrets_streamlit", lambda: None)
    config.recharger()

    # 2) ceinture et bretelles : la couche réseau elle-même est bloquée.
    def interdit(*a, **k):
        raise AssertionError(
            "Un test a tenté un appel réseau vers The Odds API. "
            "Les tests ne doivent jamais consommer de crédits payants.")

    mp.setattr(oddsapi, "_get", interdit)

    # 3) même verrou sur la copie distante de l'état.
    def interdit_stockage(*a, **k):
        raise AssertionError("Un test a tenté un appel réseau vers Supabase Storage.")

    mp.setattr(stockage, "_requete", interdit_stockage)

    yield
    mp.undo()
    config.recharger()


@pytest.fixture(autouse=True)
def configuration_relue():
    """Le cache de configuration ne survit pas à un test : ce qu'un test pose
    dans l'environnement ne déteint pas sur le suivant."""
    from odds import config
    config.recharger()
    yield
    config.recharger()
