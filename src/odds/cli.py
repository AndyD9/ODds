"""Interface en ligne de commande.

    uv run odds devig 1.80 3.60 4.80
    uv run odds couvrir 1.90 3.76 2.90
    uv run odds ingest
    uv run odds carte
    uv run odds calibration --championnat E0
    uv run odds app
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from odds import chemins

RACINE = chemins.RACINE


def _fmt(df: pd.DataFrame, **kw) -> str:
    return df.to_string(index=False, float_format=lambda v: f"{v:.4f}", **kw)


def cmd_devig(args) -> int:
    from odds.analysis import analyser_livre

    cotes = args.cotes
    if len(cotes) < 2:
        print("Il faut au moins 2 cotes.", file=sys.stderr)
        return 1
    if any(c <= 1.0 for c in cotes):
        print("Toute cote doit être > 1.0", file=sys.stderr)
        return 1

    r = analyser_livre(cotes, args.libelles)
    t = r["probabilites"]

    print(f"\nLivre : {len(cotes)} issues   overround {r['overround']:.4f}"
          f"   marge {r['marge_pct']:+.2f} %   z (Shin) {r['z_shin']:.4f}\n")

    aff = pd.DataFrame({
        "issue": t.index,
        "cote": t["cote"],
        "brute 1/c": 100 * t["implicite_brute"],
        "Shin": 100 * t["shin"],
        "power": 100 * t["power"],
        "odds ratio": 100 * t["odds_ratio"],
        "proportion.": 100 * t["proportional"],
        "cote juste": r["cote_juste_shin"],
    })
    print(_fmt(aff))

    print("\nBiais de la normalisation proportionnelle, par rapport à Shin :")
    b = pd.DataFrame({
        "issue": t.index,
        "écart (pts)": r["biais_proportionnel_pts"].to_numpy(),
        "écart (%)": r["biais_proportionnel_rel"].to_numpy(),
    })
    print(_fmt(b))
    pire = int(np.argmax(np.abs(r["biais_proportionnel_rel"].to_numpy())))
    print(f"\n  La proportionnelle se trompe le plus sur « {t.index[pire]} » : "
          f"{r['biais_proportionnel_rel'].iloc[pire]:+.1f} % en relatif.")
    print("  Un moteur d'edge bâti dessus signalerait des opportunités fictives sur cette issue.")
    print("\n  Rappel : ces probabilités sont celles du MARCHÉ, corrigées de la marge.")
    print("  Ce ne sont pas des prédictions et elles ne constituent pas un signal.\n")
    return 0


def cmd_couvrir(args) -> int:
    """``odds couvrir 1.90 3.76 2.90`` — toutes les couvertures d'un marché."""
    from odds.market import couverture as cv
    from odds.market.devig import devig

    cotes = args.cotes
    if len(cotes) < 2:
        print("Il faut au moins 2 cotes : les issues exclusives d'un même marché.",
              file=sys.stderr)
        return 1
    if any(c <= 1.0 for c in cotes):
        print("Toute cote doit être > 1.0", file=sys.stderr)
        return 1
    libelles = args.libelles or (
        ["Domicile", "Nul", "Extérieur"] if len(cotes) == 3
        else [f"Issue {i + 1}" for i in range(len(cotes))])
    if len(libelles) != len(cotes):
        print("Autant de libellés que de cotes.", file=sys.stderr)
        return 1

    # Sans probabilités fournies, celles du livre lui-même, dévigées : toute
    # couverture a alors une espérance négative, et c'est exactement ce que
    # la sortie doit montrer — répartir ne crée rien.
    if args.probas:
        if len(args.probas) != len(cotes) or abs(sum(args.probas) - 1.0) > 0.02:
            print("Les probabilités doivent être aussi nombreuses que les cotes "
                  "et sommer à 1.", file=sys.stderr)
            return 1
        probas, origine = list(args.probas), "fournies"
    else:
        probas, origine = list(devig(cotes, "shin")), "livre dévigé (Shin)"

    partition = tuple(libelles)
    P = dict(zip(partition, probas))
    C = dict(zip(partition, cotes))
    booksum = sum(1.0 / c for c in cotes)

    print(f"\nMarché : {len(cotes)} issues   Σ 1/cote = {booksum:.4f}   "
          f"probabilités : {origine}")
    for lib, p_, c in zip(partition, probas, cotes):
        print(f"  {lib:<14} cote {c:>6.2f}   p {100 * p_:5.1f} %   "
              f"p × cote {p_ * c:.3f}")

    if booksum < 1.0:
        print(f"\n  Σ 1/cote < 1 : couvrir TOUT garantit {100 * (1 / booksum - 1):+.2f} % "
              "de la mise, quelle que soit l'issue (sur-arbitrage — vérifiez que "
              "les prix sont encore affichés).")
    else:
        print(f"\n  Couvrir TOUT garantit une perte de {100 * (1 - 1 / booksum):.2f} % "
              "de la mise : c'est la marge, payée d'avance.")

    mise = float(args.mise)
    print(f"\nToutes les couvertures à retour égal, pour {mise:.2f} :")
    lignes = []
    for cvr in cv.toutes_les_couvertures(C, P, mise, partition):
        lignes.append({
            "issues couvertes": " + ".join(cvr.codes),
            "répartition": " / ".join(f"{cvr.mises[c]:.2f}" for c in cvr.codes),
            "si couvert": cvr.meilleur if cvr.retour_egal else float("nan"),
            "sinon": -cvr.total if not cvr.complete else cvr.pire,
            "P(couvert) %": 100 * cvr.p_couverte,
            "espérance": cvr.esperance,
            "cote synth.": cvr.cote_synthetique,
        })
    t = pd.DataFrame(lignes)
    print(t.to_string(index=False, float_format=lambda v: f"{v:+.2f}"
                      if abs(v) < 1e6 else "—"))

    f = cv.kelly_simultane(P, C, partition)
    retenues = {k: v for k, v in f.items() if v > 0}
    print("\nKelly simultané (fractions de bankroll, avant f_base et plafonds) :")
    if not retenues:
        print("  aucune issue ne bat sa réserve : à ces probabilités, ne rien miser.")
    else:
        for k, v in retenues.items():
            print(f"  {k:<14} {100 * v:5.2f} %   (p × cote {P[k] * C[k]:.3f})")
        print(f"  total          {100 * sum(retenues.values()):5.2f} %")
        sans_valeur = [k for k in retenues if P[k] * C[k] < 1.0]
        if sans_valeur:
            print(f"  NB : {', '.join(sans_valeur)} a une espérance négative seule ; "
                  "Kelly la couvre quand même, parce que la position sur les "
                  "autres issues est grosse — ce n'est pas de la valeur, c'est "
                  "de la variance rachetée.")
    print("\nRappel : aucune répartition ne crée d'espérance. La somme des espérances "
          "des jambes est celle de la couverture.")
    return 0


def cmd_ingest(args) -> int:
    from odds.data.footballdata import load_all
    df = load_all(verbose=not args.silencieux)
    out = chemins.PARQUET
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"\n{len(df):,} matchs -> {out}")
    print(f"période : {df.date.min().date()} -> {df.date.max().date()}")
    print(f"sources : {df.odds_source.value_counts(dropna=False).to_dict()}")
    return 0


def cmd_carte(args) -> int:
    from odds.analysis import carte_marges, carte_information_tardive, charger
    df = charger()

    m = carte_marges(df)
    print("\n=== MARGE PINNACLE PAR CHAMPIONNAT (proxy d'efficience) ===\n")
    print(_fmt(m.assign(depuis=m.depuis.dt.year, jusqua=m.jusqua.dt.year)
                [["league_code", "country", "league", "n", "depuis", "jusqua", "marge"]]))

    t = carte_information_tardive(df)
    if len(t):
        print("\n\n=== INFORMATION TARDIVE (Brier précoce - Brier clôture) ===")
        print("    élevé = beaucoup d'information arrive tard, miser tôt est risqué")
        print("    faible = le prix précoce est déjà quasi définitif\n")
        print(_fmt(t[["league_code", "country", "n", "brier_precoce",
                      "brier_cloture", "information_tardive"]]))
    print()
    return 0


def cmd_calibration(args) -> int:
    from odds.analysis import (avec_cloture, charger, cible, comparer_methodes,
                              courbe_calibration, ece, probabilites_marche)
    df = charger()
    d = avec_cloture(df)
    if args.championnat:
        d = d[d.league_code.str.upper() == args.championnat.upper()]
        if len(d) == 0:
            print(f"Aucun match pour « {args.championnat} ».", file=sys.stderr)
            return 1
    if args.depuis:
        d = d[d.date >= pd.Timestamp(args.depuis)]

    y = cible(d)
    p = probabilites_marche(d, "psc", args.methode)
    c = courbe_calibration(p, y, args.bins)

    titre = args.championnat.upper() if args.championnat else "tous championnats"
    print(f"\n=== CALIBRATION DU MARCHÉ — {titre} — dévig {args.methode} ===")
    print(f"n = {len(d):,} matchs   ECE = {ece(c):.5f}\n")
    aff = c.assign(annonce=100 * c.annonce, observe=100 * c.observe)
    aff.columns = ["bin", "annoncé %", "observé %", "n", "écart pts"]
    print(_fmt(aff))
    print("\n  Un marché bien calibré a « observé » proche de « annoncé » dans chaque ligne.\n")

    if not args.championnat:
        print("=== COMPARAISON DES MÉTHODES DE DÉVIG ===\n")
        print(_fmt(comparer_methodes(df).assign(
            brier=lambda x: x.brier, log_loss=lambda x: x.log_loss)))
        print()
    return 0


def cmd_collect(args) -> int:
    from odds.data.collect import collecter, resume
    if args.resume:
        r = resume()
        if r["lignes"] == 0:
            print("Aucune collecte enregistrée. Lancez :  uv run odds collect")
            return 0
        print(f"\nHistorique de cotes propre")
        print(f"  {r['lignes']:,} observations · {r['matchs']:,} matchs · {r['runs']} passes")
        print(f"  {r['depuis']} -> {r['jusqua']} (UTC)\n")
        print("Par bookmaker :")
        print(_fmt(r["bookmakers"]))
        print("\nDernières passes :")
        print(_fmt(r["derniers_runs"]))
        print()
        return 0

    print(f"Collecte — {pd.Timestamp.now("UTC"):%Y-%m-%d %H:%M:%S} UTC")
    # Hébergé (decisions/0009) : la base de collecte vit dans le seau. On la
    # tire avant la passe — l'ordonnanceur a besoin des dernières passes — et
    # on la repousse après, même si la passe a eu des erreurs : ce qui a été
    # écrit l'a été. Sans configuration, les deux appels sont inertes.
    from odds import chemins, stockage
    if stockage.actif() and stockage.rafraichir(chemins.BDD_COLLECTE):
        print("  base de collecte ramenée du seau")
    try:
        r = collecter()
    finally:
        if stockage.publier(chemins.BDD_COLLECTE):
            print("  base de collecte poussée dans le seau")
    print(f"\n  run {r['run_id']} · {r['matchs']} matchs · "
          f"{r['vues']} cotes vues · {r['ecrites']} écrites")
    if r.get("credits"):
        print(f"  crédits The Odds API : {r['credits']} consommés · "
              f"{r.get('credits_restants')} restants ce mois-ci")
    if r["erreurs"]:
        print("  erreurs :", "; ".join(r["erreurs"]))
        return 1
    return 0


def cmd_etat(args) -> int:
    """Copie distante de l'état — mise en service et dépannage (decisions/0009)."""
    from odds import stockage
    if not stockage.actif():
        print("Copie distante non configurée : SUPABASE_URL et SUPABASE_SERVICE_KEY "
              "manquent (voir .streamlit/secrets.toml.example).")
        return 1
    if args.sens == "pousser":
        noms = stockage.pousser_tout()
        print("Poussé :", ", ".join(noms) if noms else "rien (aucun fichier local)")
    else:
        noms = stockage.demarrer()
        print("Ramené :", ", ".join(noms) if noms else "rien (tout est à jour)")
    return 0


def cmd_config(args) -> int:
    from odds import config

    if args.init:
        if config.FICHIER_ENV.exists():
            print(f"{config.FICHIER_ENV} existe déjà — rien n'a été modifié.")
            print("Éditez-le directement, ou supprimez-le d'abord.")
            return 1
        config.FICHIER_ENV.write_text(
            config.FICHIER_EXEMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Créé : {config.FICHIER_ENV}")
        print("\nRenseignez ODDS_API_KEY dedans, puis vérifiez avec :  uv run odds config")
        print("\nNe collez jamais la clé dans un message ou une capture d'écran.")
        return 0

    etat = config.resume()
    existe = config.FICHIER_ENV.exists()
    print(f"\nFichier : {config.FICHIER_ENV}  {'✅ présent' if existe else '❌ absent'}")
    if not existe:
        print("\nPour le créer :  uv run odds config --init\n")

    print()
    print(_fmt(pd.DataFrame([
        {"Réglage": e["réglage"], "Valeur": e["valeur"],
         "Origine": e["origine"], "Statut": "✅" if e["ok"] else "❌ manquant"}
        for e in etat])))

    from odds.market import commission
    impose = commission._surcharge()
    if impose is None:
        taux = ", ".join(f"{b} {100 * t:g} %" for b, t in
                         sorted(set((b.split("_ex")[0], t)
                                    for b, t in commission.TAUX_DEFAUT.items())))
        print(f"\nCommission des bourses d'échange : taux par défaut ({taux}).")
    else:
        print(f"\nCommission des bourses d'échange : {100 * impose:g} % sur toutes.")
    print("Les cotes d'exchange sont comparées NETTES de cette commission.")

    if config.est_configure("ODDS_API_KEY"):
        cout = config.cout_par_passe()
        par_jour = int(config.get("ODDS_API_BUDGET_JOUR") or 14)
        print(f"\nCoût d'une passe : {cout} crédits "
              f"({len(config.get_liste('ODDS_API_SPORTS'))} championnats "
              f"x {len(config.get_liste('ODDS_API_MARKETS'))} marchés "
              f"x {len(config.get_liste('ODDS_API_REGIONS'))} régions)")
        if cout > 0:
            print(f"Budget {par_jour} crédits/jour -> {par_jour // cout} passe(s) par jour "
                  f"maximum, soit ~{30 * par_jour} crédits/mois.")
            if 30 * par_jour > 500:
                print("⚠️  Au-delà des 500 crédits/mois de l'offre gratuite.")
    else:
        print("\n❌ ODDS_API_KEY n'est pas renseignée. Clé gratuite (500 crédits/mois) :")
        print("   https://the-odds-api.com/#get-access")
    print()
    return 0


def cmd_credits(args) -> int:
    from odds import config
    from odds.data.collect import conso_credits
    from odds.data.oddsapi import credits, projection

    if not config.est_configure("ODDS_API_KEY"):
        print("ODDS_API_KEY non configurée.  uv run odds config --init")
        return 1

    c = credits()
    barre_n = 32
    plein = int(barre_n * c["part_utilisee"])
    barre = "█" * plein + "░" * (barre_n - plein)

    print(f"\nCrédits The Odds API")
    print(f"  [{barre}]  {100 * c['part_utilisee']:.1f} %")
    print(f"  {c['restants']:,} restants sur {c['total']:,}  "
          f"({c['utilises']:,} utilisés ce mois-ci)")
    print("  (compteur lu via /sports, qui ne coûte aucun crédit)")

    d = conso_credits()
    recents = d[d.credits > 0].tail(7)
    par_jour = float(recents.credits.mean()) if len(recents) else 0.0

    if len(d):
        print("\nConsommation par jour :")
        print(_fmt(d.tail(10).rename(
            columns={"jour": "Jour", "credits": "Crédits", "passes": "Passes"})))

    p = projection(c["restants"], par_jour)
    print(f"\nRythme sur les 7 derniers jours actifs : {par_jour:.1f} crédits/jour")
    print(f"Jours restants avant réinitialisation   : {p['jours_restants_mois']}")
    if par_jour > 0:
        print(f"Besoin d'ici la fin du mois             : {p['besoin_fin_de_mois']:.0f} crédits")
        if p["suffisant"]:
            marge = c["restants"] - p["besoin_fin_de_mois"]
            print(f"✅ Suffisant, avec {marge:.0f} crédits de marge.")
        else:
            print(f"⚠️  Insuffisant : épuisement estimé le {p['epuisement']}.")
            print("   Réduisez ODDS_API_SPORTS ou ODDS_API_BUDGET_JOUR.")
    print()
    return 0


def cmd_app(args) -> int:
    app = chemins.RACINE / "src" / "odds" / "app" / "dashboard.py"
    print(f"Lancement du tableau de bord : {app}")
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app),
                            "--server.port", str(args.port), "--server.headless", "true"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="odds",
        description="Outil d'analyse des probabilités de marché. "
                    "Ne produit aucun signal de pari (voir research/RESULTS.md).",
    )
    sub = p.add_subparsers(dest="commande", required=True)

    d = sub.add_parser("devig", help="retirer la marge d'un livre de cotes")
    d.add_argument("cotes", type=float, nargs="+", help="cotes décimales, ex : 1.80 3.60 4.80")
    d.add_argument("--libelles", nargs="+", default=None, help="noms des issues")
    d.set_defaults(func=cmd_devig)

    cvp = sub.add_parser("couvrir", help="répartir une mise sur plusieurs issues d'un marché")
    cvp.add_argument("cotes", type=float, nargs="+",
                     help="cotes des issues exclusives, ex : 1.90 3.76 2.90")
    cvp.add_argument("--probas", type=float, nargs="+", default=None,
                     help="vos probabilités, sommant à 1 (défaut : le livre dévigé)")
    cvp.add_argument("--libelles", nargs="+", default=None, help="noms des issues")
    cvp.add_argument("--mise", type=float, default=100.0, help="mise totale à répartir")
    cvp.set_defaults(func=cmd_couvrir)

    i = sub.add_parser("ingest", help="télécharger et normaliser les données")
    i.add_argument("--silencieux", action="store_true")
    i.set_defaults(func=cmd_ingest)

    c = sub.add_parser("carte", help="marges et information tardive par championnat")
    c.set_defaults(func=cmd_carte)

    k = sub.add_parser("calibration", help="calibration réelle du marché")
    k.add_argument("--championnat", default=None, help="code, ex : E0, NOR, CHN")
    k.add_argument("--depuis", default=None, help="date ISO, ex : 2020-01-01")
    k.add_argument("--methode", default="shin", choices=["shin", "power", "odds_ratio", "proportional"])
    k.add_argument("--bins", type=int, default=12)
    k.set_defaults(func=cmd_calibration)

    co = sub.add_parser("collect", help="collecter les cotes des matchs à venir")
    co.add_argument("--resume", action="store_true", help="afficher l'état de l'historique")
    co.set_defaults(func=cmd_collect)

    cf = sub.add_parser("config", help="état de la configuration locale (.env)")
    cf.add_argument("--init", action="store_true",
                    help="créer .env à partir de .env.example")
    cf.set_defaults(func=cmd_config)

    cr = sub.add_parser("credits", help="crédits The Odds API restants et projection")
    cr.set_defaults(func=cmd_credits)

    et = sub.add_parser("etat", help="copie distante de l'état (carnet, collecte, parquets)")
    et.add_argument("sens", choices=["pousser", "tirer"],
                    help="pousser le local vers le seau, ou ramener le seau en local")
    et.set_defaults(func=cmd_etat)

    a = sub.add_parser("app", help="lancer le tableau de bord")
    a.add_argument("--port", type=int, default=8501)
    a.set_defaults(func=cmd_app)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
