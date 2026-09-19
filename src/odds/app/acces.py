"""Porte d'entrée de l'application hébergée — qui entre, et sous quel nom.

Deux modes, décidés par la présence d'une section ``[auth]`` dans les
secrets Streamlit (decisions/0009) :

- **local** (pas de ``[auth]``) : rien ne change, l'utilisateur est celui de
  ``paper.utilisateur_courant()`` — le propriétaire configuré, sinon
  « local ». C'est le mode de ``uv run odds app`` et des tests ;
- **hébergé** : ``st.login`` (OpenID Connect, Google) identifie la personne,
  puis on n'ouvre qu'aux adresses de ``ODDS_INVITES``. Une adresse connue
  devient l'utilisateur du carnet : chacun voit et écrit ses paris, et
  seulement les siens.

La liste d'invités est la seule règle d'accès. Elle vit dans les secrets,
pas dans le code : y ajouter quelqu'un est un réglage, pas un déploiement.
"""

from __future__ import annotations

import streamlit as st

from odds import config, paper


def invites() -> frozenset[str]:
    """Adresses autorisées, en minuscules. Vide = personne n'entre."""
    return frozenset(a.lower() for a in config.get_liste("ODDS_INVITES"))


def autorise(email: str | None, liste: frozenset[str] | None = None) -> bool:
    """Une adresse entre si, et seulement si, elle est sur la liste."""
    if not email:
        return False
    liste = invites() if liste is None else liste
    return email.strip().lower() in liste


def _auth_configuree() -> bool:
    try:
        return "auth" in st.secrets
    except Exception:          # pas de fichier de secrets : mode local
        return False


def _connecte() -> bool:
    try:
        return bool(st.user.is_logged_in)
    except Exception:
        return False


def _page_de_connexion() -> None:
    st.title("Probabilités de marché")
    st.write("Outil personnel, sur invitation. Paris en papier uniquement.")
    st.button("Se connecter avec Google", on_click=st.login, type="primary")


def _page_refusee(email: str) -> None:
    st.title("Accès réservé")
    st.write(f"L'adresse **{email}** n'est pas sur la liste des invités. "
             "Demandez au propriétaire de l'ajouter, puis reconnectez-vous.")
    st.button("Se déconnecter", on_click=st.logout)


def ouvrir() -> str | None:
    """À appeler en tête de page. Renvoie l'adresse connectée, ou None en local.

    Arrête le script — ``st.stop()`` — tant que la personne n'est pas à la
    fois connectée et invitée : rien de ce qui suit ne s'exécute.
    """
    if not _auth_configuree():
        return None
    if not _connecte():
        _page_de_connexion()
        st.stop()
    email = (getattr(st.user, "email", None) or "").strip().lower()
    if not autorise(email):
        _page_refusee(email or "(sans adresse)")
        st.stop()
    paper.definir_utilisateur(email)
    return email


def barre_laterale(email: str | None) -> None:
    """Qui est connecté, et la porte de sortie. Rien en mode local."""
    if not email:
        return
    st.sidebar.caption(f"Connecté : {email}")
    st.sidebar.button("Se déconnecter", on_click=st.logout, key="acces_sortie")
