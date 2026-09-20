"""Porte d'entrée de l'application hébergée — qui entre, et sous quel nom.

L'accès se fait par **lien personnel** (decisions/0009) : chaque invité reçoit
une adresse de la forme ``https://…/?cle=<clé>``, où la clé est une chaîne
aléatoire longue qui n'existe que dans les secrets de l'application, en face
de son nom. La clé est le sésame ; le nom devient l'utilisateur du carnet.

Deux modes, décidés par la présence d'invités :

- **local** (aucun invité configuré) : rien ne change, l'utilisateur est celui
  de ``paper.utilisateur_courant()`` — le propriétaire configuré, sinon
  « local ». C'est le mode de ``uv run odds app`` et des tests ;
- **hébergé** : la clé est lue dans l'adresse, sinon dans un cookie posé à la
  première visite, sinon dans la session. Sans clé valide, la page est une
  porte fermée et rien d'autre ne s'exécute.

Ce que cela vaut, dit sans détour : un lien est un jeton au porteur. Qui a le
lien entre au nom de l'invité — comme une clé de maison. C'est acceptable
pour un carnet **papier** ouvert à des gens qu'on connaît ; révoquer
quelqu'un, c'est retirer sa ligne des secrets. Les clés se comparent en
temps constant et font 32 caractères aléatoires : les deviner n'est pas
une attaque réaliste.
"""

from __future__ import annotations

import hmac
import secrets as secrets_

import streamlit as st

from odds import config, paper

PARAMETRE = "cle"
COOKIE = "odds_cle"
UN_AN = 365 * 24 * 3600


def nouvelle_cle() -> str:
    """32 caractères sûrs pour une adresse — ``odds inviter``."""
    return secrets_.token_urlsafe(24)


def _invites_secrets() -> dict[str, str]:
    """Section ``[invites]`` des secrets Streamlit : nom = "clé". Vide sans secrets."""
    section = config.section_secrets("invites")
    return {str(cle): str(nom).strip().lower() for nom, cle in section.items() if cle}


def _invites_env() -> dict[str, str]:
    """``ODDS_INVITES="nom:clé,nom:clé"`` — pour un .env ou la CLI."""
    out = {}
    for paire in config.get_liste("ODDS_INVITES"):
        nom, sep, cle = paire.partition(":")
        if sep and cle.strip() and nom.strip():
            out[cle.strip()] = nom.strip().lower()
    return out


def invites() -> dict[str, str]:
    """Clé → nom d'utilisateur. Vide = mode local."""
    return {**_invites_env(), **_invites_secrets()}


def identifier(cle: str | None, liste: dict[str, str] | None = None) -> str | None:
    """Le nom que désigne cette clé, ou None. Comparaison en temps constant."""
    if not cle:
        return None
    liste = invites() if liste is None else liste
    cle = cle.strip()
    for attendue, nom in liste.items():
        if hmac.compare_digest(attendue.encode(), cle.encode()):
            return nom
    return None


def _cookies() -> dict:
    try:
        return dict(st.context.cookies)
    except Exception:
        return {}


def _cle_presentee() -> str | None:
    """Dans l'adresse d'abord — c'est le lien qu'on a reçu — puis cookie, puis session."""
    try:
        depuis_url = st.query_params.get(PARAMETRE)
    except Exception:
        depuis_url = None
    return depuis_url or _cookies().get(COOKIE) or st.session_state.get("acces_cle")


def _poser_cookie(cle: str, duree: int = UN_AN) -> None:
    """Retient la clé dans le navigateur, pour revenir sans le lien.

    Streamlit ne sait pas écrire un cookie ; un fragment HTML le fait pour
    lui, depuis la même origine. Si le navigateur refuse, rien n'est perdu :
    le lien reste le moyen d'entrer.
    """
    st.components.v1.html(
        f"<script>document.cookie = '{COOKIE}={cle}; path=/; max-age={duree}; "
        "SameSite=Lax; Secure';</script>", height=0)


def _page_refusee() -> None:
    st.title("Accès sur invitation")
    st.write("Cette application s'ouvre avec un **lien personnel**. Le vôtre est absent "
             "de l'adresse, ou n'est plus valide. Demandez-en un au propriétaire, puis "
             "ouvrez-le tel quel : le navigateur le retiendra.")
    st.caption("Outil personnel, paris en papier uniquement.")


def ouvrir() -> str | None:
    """À appeler en tête de page. Renvoie le nom connecté, ou None en local.

    Arrête le script — ``st.stop()`` — tant que la clé n'est pas valide :
    rien de ce qui suit ne s'exécute.
    """
    liste = invites()
    if not liste:
        return None
    if st.session_state.pop("acces_oublier", False):
        # « Oublier ce navigateur » : le cookie de la requête en cours porte
        # encore la clé, on ne la lit donc pas, et on l'efface côté client.
        _poser_cookie("", duree=0)
        try:
            st.query_params.clear()
        except Exception:
            pass
        cle = None
    else:
        cle = _cle_presentee()
    nom = identifier(cle, liste)
    if nom is None:
        _page_refusee()
        st.stop()
    st.session_state["acces_cle"] = cle
    if _cookies().get(COOKIE) != cle:
        _poser_cookie(cle)
    paper.definir_utilisateur(nom)
    return nom


def _oublier() -> None:
    """Rappel de bouton : on ne dessine rien ici, ``ouvrir`` fera le ménage."""
    st.session_state.pop("acces_cle", None)
    st.session_state["acces_oublier"] = True


def barre_laterale(nom: str | None) -> None:
    """Qui est connecté, et le moyen d'oublier ce navigateur. Rien en mode local."""
    if not nom:
        return
    st.sidebar.caption(f"Connecté : {nom}")
    st.sidebar.button("Oublier ce navigateur", on_click=_oublier, key="acces_sortie",
                      help="Efface la clé de ce navigateur. Le lien personnel reste valable.")
