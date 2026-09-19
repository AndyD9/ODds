"""Libellés humains pour les identifiants techniques affichés à l'écran.

Les clés de The Odds API (``soccer_epl``, ``betfair_ex_eu``) sont des
identifiants d'intégration : elles n'ont rien à faire dans une carte ou un
tableau lus par une personne. Ce module les traduit, et se replie sur une
mise en forme raisonnable pour ce qu'il ne connaît pas — le code brut reste
disponible pour les infobulles et les onglets techniques.

Aucune logique d'analyse ici : uniquement de la présentation.
"""

from __future__ import annotations

import datetime as dt
import re

# --- championnats ----------------------------------------------------------
# Clés « sport » de The Odds API. Les codes football-data (E0, SP1…) et les
# noms en clair de l'historique passent tels quels : ils sont déjà lisibles.
CHAMPIONNATS = {
    "soccer_epl": "Premier League",
    "soccer_efl_champ": "Championship",
    "soccer_england_league1": "League One",
    "soccer_england_league2": "League Two",
    "soccer_france_ligue_one": "Ligue 1",
    "soccer_france_ligue_two": "Ligue 2",
    "soccer_spain_la_liga": "La Liga",
    "soccer_spain_segunda_division": "Segunda",
    "soccer_italy_serie_a": "Serie A",
    "soccer_italy_serie_b": "Serie B",
    "soccer_germany_bundesliga": "Bundesliga",
    "soccer_germany_bundesliga2": "2. Bundesliga",
    "soccer_netherlands_eredivisie": "Eredivisie",
    "soccer_portugal_primeira_liga": "Primeira Liga",
    "soccer_belgium_first_div": "Pro League",
    "soccer_turkey_super_league": "Süper Lig",
    "soccer_greece_super_league": "Super League (Grèce)",
    "soccer_switzerland_superleague": "Super League (Suisse)",
    "soccer_austria_bundesliga": "Bundesliga (Autriche)",
    "soccer_denmark_superliga": "Superliga",
    "soccer_sweden_allsvenskan": "Allsvenskan",
    "soccer_norway_eliteserien": "Eliteserien",
    "soccer_poland_ekstraklasa": "Ekstraklasa",
    "soccer_spl": "Premiership",
    "soccer_usa_mls": "MLS",
    "soccer_mexico_ligamx": "Liga MX",
    "soccer_brazil_campeonato": "Série A (Brésil)",
    "soccer_argentina_primera_division": "Liga Profesional",
    "soccer_japan_j_league": "J1 League",
    "soccer_china_superleague": "Super League (Chine)",
    "soccer_uefa_champs_league": "Ligue des champions",
    "soccer_uefa_europa_league": "Ligue Europa",
    "soccer_uefa_europa_conference_league": "Ligue Conférence",
}

# --- bookmakers ------------------------------------------------------------
# Clés The Odds API et football-data. Un suffixe de pays (_fr, _de, _nl, _se,
# _it, _eu, _uk, _us) désigne la même enseigne : on le retire.
BOOKMAKERS = {
    "betfair_ex": "Betfair Exchange",
    "betfair_exchange": "Betfair Exchange",
    "betfair_sportsbook": "Betfair",
    "betfair": "Betfair",
    "bet365": "bet365",
    "pinnacle": "Pinnacle",
    "matchbook": "Matchbook",
    "onexbet": "1xBet",
    "sport888": "888sport",
    "williamhill": "William Hill",
    "betvictor": "BetVictor",
    "paddypower": "Paddy Power",
    "skybet": "Sky Bet",
    "bwin": "bwin",
    "unibet": "Unibet",
    "betclic": "Betclic",
    "winamax": "Winamax",
    "pmu": "PMU",
    "betsson": "Betsson",
    "nordicbet": "NordicBet",
    "leovegas": "LeoVegas",
    "marathonbet": "Marathonbet",
    "tipico": "Tipico",
    "codere": "Codere",
    "coolbet": "Coolbet",
    "everygame": "Everygame",
    "gtbets": "GTbets",
    "suprabets": "Suprabets",
    "betonlineag": "BetOnline",
    "betonline": "BetOnline",
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "caesars": "Caesars",
    "ladbrokes": "Ladbrokes",
    "coral": "Coral",
    "boylesports": "BoyleSports",
    "livescorebet": "LiveScore Bet",
    "grosvenor": "Grosvenor",
}

# Agrégats de marché : ce ne sont pas des bookmakers, et on ne peut pas y
# miser. Le signe ⌀ le rappelle.
AGREGATS_LIBELLES = {
    "_max_marche": "⌀ meilleur du marché",
    "_moyenne_marche": "⌀ moyenne marché",
}

_SUFFIXE_PAYS = re.compile(r"_(fr|de|nl|se|it|eu|uk|us|es|pt|be|dk|no|fi|au|ca)$")


def championnat(code) -> str:
    """« soccer_epl » → « Premier League » ; tout autre libellé passe tel quel."""
    c = str(code)
    if c in CHAMPIONNATS:
        return CHAMPIONNATS[c]
    if c.startswith("soccer_"):
        return c[len("soccer_"):].replace("_", " ").title()
    return c


def bookmaker(code) -> str:
    """« betfair_ex_eu » → « Betfair Exchange », « unibet_nl » → « Unibet »."""
    c = str(code)
    if c in AGREGATS_LIBELLES:
        return AGREGATS_LIBELLES[c]
    if c in BOOKMAKERS:
        return BOOKMAKERS[c]
    racine = _SUFFIXE_PAYS.sub("", c)
    if racine in BOOKMAKERS:
        return BOOKMAKERS[racine]
    return racine.replace("_", " ").title()


JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS_FR = [None, "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]


def date_longue(d: dt.date) -> str:
    """« vendredi 18 septembre 2026 », majuscule initiale."""
    texte = f"{JOURS_FR[d.weekday()]} {d.day} {MOIS_FR[d.month]} {d.year}"
    return texte[0].upper() + texte[1:]
