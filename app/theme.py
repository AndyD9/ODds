"""Habillage du tableau de bord, repris de la maquette « Main ».

Trois couches, dans cet ordre de préférence :

1. ``.streamlit/config.toml`` — tout ce que le thème natif sait exprimer
   (couleurs, rayons, typographie, palettes de graphiques).
2. ``app/theme.css`` — la géométrie que le thème ne dit pas : tuiles,
   alertes bordées, puces, tableaux dessinés.
3. ce module — les quelques fragments que Streamlit n'a pas du tout :
   le tableau HTML de la maquette, ses pastilles, sa barre 1 · N · 2, et
   un thème Altair assorti.

Aucune logique d'analyse ici : uniquement de la présentation.
"""

from __future__ import annotations

import zlib
from html import escape
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from matplotlib.colors import LinearSegmentedColormap

FEUILLE = Path(__file__).with_name("theme.css")

# --- jetons de la maquette --------------------------------------------------
BG = "#09090b"
CARTE = "#18181b"
CARTE_2 = "#101013"
BORDURE = "#27272a"
BORDURE_2 = "#1f1f23"
TEXTE = "#fafafa"
ATTENUE = "#a1a1aa"
ATTENUE_2 = "#71717a"
CORPS = "#d4d4d8"

BLEU = "#60a5fa"
BLEU_CLAIR = "#93c5fd"
EMERAUDE = "#6ee7b7"
EMERAUDE_VIF = "#34d399"
AMBRE = "#fcd34d"
ROUGE = "#fca5a5"

# Couleurs de bookmaker de la maquette (BOOK_COLORS), agrégats en gris.
COULEURS_BOOK = {
    "bet365": "#60a5fa",
    "betfair_exchange": "#34d399",
    "betfair_sportsbook": "#f472b6",
    "betvictor": "#f87171",
    "bwin": "#a78bfa",
    "paddypower": "#fbbf24",
    "skybet": "#38bdf8",
}
COULEUR_AGREGAT = "#52525b"
PALETTE = ["#60a5fa", "#34d399", "#f472b6", "#f87171", "#a78bfa", "#fbbf24",
           "#38bdf8", "#fb923c", "#4ade80", "#c4b5fd", "#f9a8d4", "#facc15",
           "#22d3ee", "#a3e635", "#e879f9", "#fda4af", "#818cf8", "#2dd4bf"]

# Les quatre méthodes de dévig, dans la teinte de la maquette.
COULEURS_METHODE = {"shin": BLEU, "power": EMERAUDE_VIF,
                    "odds_ratio": "#fbbf24", "proportional": "#f87171"}

# Rampes continues pour Vega-Lite — les schémas intégrés (« blues »,
# « purples », « yelloworangered ») partent du blanc et écrasent le fond.
ECHELLE_SEQ = ["#101828", "#1a3557", "#27568b", "#3d7cc0", "#6ea9e6", "#93c5fd"]
ECHELLE_SEQ_CHAUDE = ["#1c1710", "#3a2a12", "#5e4415", "#8a6318", "#c08a1d",
                      "#fcd34d"]
ECHELLE_SEQ_VIOLETTE = ["#16121f", "#241b38", "#352752", "#4a356f", "#6b4fa0",
                        "#a78bfa"]

# Dégradés pour les tableaux natifs : les cartes matplotlib claires
# (« RdYlGn », « Blues ») brûlent sur un fond #09090b.
GRADIENT_BLEU = LinearSegmentedColormap.from_list(
    "od_bleu", ["#101828", "#1a3557", "#27568b", "#3d7cc0", "#93c5fd"])
GRADIENT_DIVERGENT = LinearSegmentedColormap.from_list(
    "od_divergent", ["#fca5a5", "#95575b", "#46484f", "#3f7d75", "#6ee7b7"])


def couleur_book(nom: str) -> str:
    """Teinte d'un bookmaker pris isolément ; gris pour les agrégats.

    Les sept livres nommés dans la maquette gardent leur couleur. Les autres
    reçoivent une teinte tirée d'une empreinte du nom — stable d'un rerun à
    l'autre, donc la légende ne change pas de couleur sous les yeux de
    l'utilisateur. Deux livres peuvent tomber sur la même : quand on dispose
    de la liste complète, ``palette_books`` évite ces collisions.
    """
    nom = str(nom)
    if nom.startswith("_"):
        return COULEUR_AGREGAT
    if nom in COULEURS_BOOK:
        return COULEURS_BOOK[nom]
    return PALETTE[zlib.crc32(nom.encode("utf-8")) % len(PALETTE)]


def palette_books(noms) -> dict[str, str]:
    """Une couleur par bookmaker, distinctes tant qu'il y en a assez.

    Nous relevons une vingtaine de livres par match, là où la maquette en
    montrait sept. Attribuer les teintes dans l'ordre de la liste — plutôt
    que par empreinte — garantit que deux lignes voisines se distinguent.
    """
    libres = [c for c in PALETTE if c not in COULEURS_BOOK.values()]
    attrib, i = {}, 0
    for nom in dict.fromkeys(str(n) for n in noms):
        if nom.startswith("_"):
            attrib[nom] = COULEUR_AGREGAT
        elif nom in COULEURS_BOOK:
            attrib[nom] = COULEURS_BOOK[nom]
        else:
            attrib[nom] = libres[i % len(libres)]
            i += 1
    return attrib


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def appliquer() -> None:
    """Injecte la feuille de style. À appeler une fois, au tout début."""
    st.markdown(f"<style>{FEUILLE.read_text(encoding='utf-8')}</style>",
                unsafe_allow_html=True)
    alt.theme.enable("od_sombre")


@alt.theme.register("od_sombre", enable=False)
def _theme_altair() -> alt.theme.ThemeConfig:
    """Thème Vega-Lite assorti : fond transparent, grille discrète."""
    axe = {
        "labelColor": ATTENUE,
        "labelFontSize": 11,
        "titleColor": ATTENUE_2,
        "titleFontSize": 11,
        "titleFontWeight": "normal",
        "domainColor": BORDURE,
        "tickColor": BORDURE,
        "gridColor": BORDURE_2,
        "gridDash": [2, 3],
    }
    return {
        "config": {
            "background": "transparent",
            "font": "-apple-system, BlinkMacSystemFont, Segoe UI, Inter, "
                    "Helvetica, Arial, sans-serif",
            "view": {"stroke": "transparent", "continuousHeight": 260},
            "axis": axe,
            "axisY": {**axe, "domainColor": "transparent"},
            "legend": {
                "labelColor": CORPS,
                "labelFontSize": 12,
                "titleColor": ATTENUE_2,
                "titleFontSize": 11,
                "titleFontWeight": "normal",
                "symbolType": "circle",
            },
            "title": {"color": TEXTE, "fontSize": 13, "fontWeight": 600,
                      "anchor": "start", "offset": 12},
            "range": {"category": PALETTE},
            "bar": {"color": BLEU},
            "point": {"color": BLEU},
            "circle": {"color": BLEU},
            "line": {"color": BLEU},
        }
    }


# ---------------------------------------------------------------------------
# Fragments dessinés
# ---------------------------------------------------------------------------

def titre_section(texte: str) -> None:
    """Intertitre .section-title : 13px, semi-gras, gris clair."""
    st.markdown(f'<div class="od-titre-section">{escape(texte)}</div>',
                unsafe_allow_html=True)


def etat_vide(texte: str) -> None:
    """Encadré pointillé .empty-state."""
    st.markdown(f'<div class="od-vide">{escape(texte)}</div>',
                unsafe_allow_html=True)


def badge(texte: str, ton: str = "outline") -> str:
    """Pastille .badge — renvoie du HTML, à insérer dans un tableau."""
    return f'<span class="od-badge od-badge-{ton}">{escape(str(texte))}</span>'


def barre_1n2(p1: float, pn: float, p2: float) -> str:
    """Barre empilée 1 · N · 2, en pourcentages, surmontée des valeurs."""
    a, b, c = 100 * p1, 100 * pn, 100 * p2
    return (
        '<div class="od-mono" style="display:flex;gap:6px;margin-bottom:5px;'
        'font-size:12.5px;">'
        f'<span style="color:{BLEU_CLAIR};">{a:.1f}</span>'
        '<span class="od-muted2">·</span>'
        f'<span class="od-muted">{b:.1f}</span>'
        '<span class="od-muted2">·</span>'
        f'<span class="od-muted2">{c:.1f}</span></div>'
        f'<div class="od-bar" title="1: {a:.1f}% · N: {b:.1f}% · 2: {c:.1f}%">'
        f'<div class="od-bar-1" style="width:{a:.1f}%;"></div>'
        f'<div class="od-bar-N" style="width:{b:.1f}%;"></div>'
        f'<div class="od-bar-2" style="width:{c:.1f}%;"></div></div>'
    )


# Les deux glyphes « accord / désaccord » de la maquette.
_COCHE = ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
          'stroke="currentColor" stroke-width="2.3" stroke-linecap="round" '
          'stroke-linejoin="round"><polyline points="5 13 9.5 17.5 19 6.5">'
          "</polyline></svg>")
_CROIX = ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
          'stroke="currentColor" stroke-width="2.3" stroke-linecap="round" '
          'stroke-linejoin="round"><line x1="6" y1="6" x2="18" y2="18">'
          '</line><line x1="18" y1="6" x2="6" y2="18"></line></svg>')

TONS_CONFIANCE = {"Très élevée": "pos", "Élevée": "info", "Modérée": "neu",
                  "Faible": "neu", "Très faible": "neg"}


def icone_oui_non(ok: bool) -> str:
    """Coche émeraude ou croix rouge, comme la colonne « Accord »."""
    couleur, glyphe = ((EMERAUDE, _COCHE) if ok else (ROUGE, _CROIX))
    return (f'<span style="display:inline-flex;color:{couleur};">{glyphe}'
            "</span>")


def pastille(nom: str, couleurs: dict | None = None) -> str:
    """Point coloré précédant un nom de bookmaker."""
    c = (couleurs or {}).get(str(nom)) or couleur_book(nom)
    return f'<span class="od-dot" style="background:{c};"></span>'


def legende_books(noms, couleurs: dict | None = None) -> None:
    """Légende à points, comme sous le nuage de la maquette."""
    items = "".join(f'<span>{pastille(n, couleurs)}{escape(str(n))}</span>'
                    for n in noms)
    st.markdown(f'<div class="od-legende">{items}</div>',
                unsafe_allow_html=True)


def tableau(df: pd.DataFrame, aligne_droite=(), html=(),
            classes: dict | None = None) -> None:
    """Rend un DataFrame avec le tableau de la maquette.

    ``aligne_droite`` : colonnes numériques (alignées à droite, chiffres
    tabulaires). ``html`` : colonnes dont le contenu est déjà du HTML et ne
    doit pas être échappé. ``classes`` : classe CSS supplémentaire par
    colonne.
    """
    classes = classes or {}
    aligne_droite, html = set(aligne_droite), set(html)

    def cellule(col, val):
        cls = ["od-num"] if col in aligne_droite else []
        if col in classes:
            cls.append(classes[col])
        attr = f' class="{" ".join(cls)}"' if cls else ""
        contenu = str(val) if col in html else escape("" if pd.isna(val)
                                                      else str(val))
        return f"<td{attr}>{contenu}</td>"

    def entete(col):
        attr = ' class="od-num"' if col in aligne_droite else ""
        return f"<th{attr}>{escape(str(col))}</th>"

    entetes = "".join(entete(c) for c in df.columns)
    lignes = "".join(
        "<tr>" + "".join(cellule(c, r[c]) for c in df.columns) + "</tr>"
        for _, r in df.iterrows())

    st.markdown(
        f'<div class="od-table-wrap"><table class="od-table">'
        f"<thead><tr>{entetes}</tr></thead><tbody>{lignes}</tbody>"
        "</table></div>",
        unsafe_allow_html=True)
