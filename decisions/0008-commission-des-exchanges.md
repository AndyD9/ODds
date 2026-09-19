# 0008 — Les cotes d'exchange sont comparées nettes de commission

**Statut :** acceptée · **Date :** 2026-09-19 · **Code :** `src/odds/market/commission.py`,
`src/odds/analysis/consensus.py`, `src/odds/paper.py`, `src/odds/app/`

## Contexte

Un bookmaker prend sa marge **dans le prix**. Une bourse d'échange n'en prend presque pas — c'est
pourquoi ses cotes sont si souvent les plus hautes — et se paie **après coup, sur le gain** :

```text
cote nette = 1 + (cote − 1) × (1 − commission)
```

L'outil comparait les deux telles quelles. La conséquence était mécanique, et mesurée sur les
144 matchs de la collecte : **14 des 21 « écarts soutenus » portaient sur Betfair Exchange**, pour
un écart moyen de +1,5 %. Or à 5 % de commission, un écart de +1,8 % à la cote 2,38 vaut −1,1 % :
la totalité de l'avantage annoncé était déjà prélevée par la bourse.

Ce n'est pas une imprécision d'affichage, c'est la fabrication d'un avantage fictif — exactement
ce que le projet a construit tout son dispositif pour ne pas faire. R3 avait écarté les écarts qui
ne mesurent que le choix de la méthode de dévig ; la normalisation proportionnelle avait été
écartée parce qu'elle « signalerait des opportunités systématiques et entièrement fictives sur les
outsiders ». Comparer une bourse à un bookmaker sur la cote brute produit le même genre d'artefact,
et l'interface le poussait en tête de page sous le titre « à prendre aujourd'hui ».

## Décision

Un seul module, `market/commission.py`, sait quels livres sont des bourses et à quel taux. Le taux
par défaut est celui de la bourse (Betfair 5 %, Smarkets et Betdaq 2 %, Matchbook 1,5 %) ;
`COMMISSION_EXCHANGE` dans `.env` le remplace par celui du compte, car il dépend du compte autant
que de la bourse.

La ligne de partage est **le prix comme information contre le prix comme paiement** :

- **l'information reste brute.** La probabilité dévigée d'une bourse est la meilleure estimation
  disponible ; le consensus continue de la lire telle quelle. La commission n'apprend rien sur le
  résultat du match ;
- **tout ce qui se paie passe au net.** Le choix du meilleur prix, l'écart au consensus, la prime
  au deuxième prix, le soutien à 1 %, les bornes sur les quatre méthodes, Kelly, la mise proposée,
  la répartition d'une couverture, le profit du carnet et le CLV.

Le carnet garde **les deux** : `cote` est le prix affiché sur le ticket, `commission` le taux figé
au moment du pari (schéma v4). Le taux d'un compte change ; un pari déjà pris, non.

L'interface affiche aussi les deux — « à 6,00 chez Matchbook · 5,92 net » — parce qu'un utilisateur
qui ne retrouve pas chez son livre la cote que l'écran lui montre cesse à juste titre de croire
l'écran.

**Le CLV compare le net pris à la clôture brute.** La clôture est une référence de prix, pas un
pari qu'on aurait placé ; la question est « ce que j'ai encaissé bat-il le prix final du marché ? ».

## Options écartées

- **Exclure les bourses du price shopping.** Simple, et faux : une bourse offre réellement le
  meilleur prix une fois sur cinq, commission comprise. L'écarter reviendrait à renoncer à des
  prix qui paient, pour éviter d'avoir à faire une soustraction.
- **Stocker la cote nette dans le carnet et rien d'autre.** Le carnet porterait alors un prix que
  l'utilisateur n'a jamais vu affiché nulle part, et qu'aucun ticket ne confirme. Le rapprochement
  avec la réalité — le seul contrôle dont dispose un carnet papier — deviendrait impossible.
- **Appliquer la commission à la probabilité dévigée de la bourse.** Tentant, puisque la cote
  nette d'une bourse ressemble à une cote de bookmaker margée. C'est un contresens : la commission
  ne déforme pas l'estimation du marché, elle prélève sur le gain. Le faire dégraderait la
  meilleure source de probabilité dont on dispose.
- **Un taux unique en dur.** Betfair et Matchbook diffèrent d'un facteur trois, et le taux réel
  dépend du volume du compte. Une constante aurait été fausse pour tout le monde, et invisible.
- **Ne rien changer et le dire dans une note.** C'était l'état de fait. Une note ne se lit pas au
  moment où une carte verte propose une cote en tête de page.

## Conséquences

- **Le nombre de signaux est divisé par deux.** Sur les mêmes 144 matchs : 21 « écarts soutenus »
  avant, **10 après**. Sur la journée du 2026-09-19 : 6 avant, 4 après. Betfair Exchange, qui
  portait deux tiers des signaux, n'en porte plus aucun — et là où il reste le mieux-payant, son
  écart moyen est de **−1,24 %**. Ce n'est pas une perte d'information : ces signaux-là n'en
  étaient pas.
- **Le profit affiché des paris déjà inscrits baisse.** La migration v4 renseigne rétroactivement
  la commission d'après le nom du livre. Un pari pris sur une bourse a toujours payé sa
  commission ; le carnet ne l'écrivait pas et annonçait un gain qu'on n'aurait pas encaissé.
  C'est une correction, pas une perte.
- **Le taux par défaut n'est pas le vôtre.** 5 % est le tarif de base de Betfair ; un compte à
  2 % voit ses écarts sous-estimés. `odds config` affiche le taux effectivement appliqué, et
  `COMMISSION_EXCHANGE` le corrige en une ligne.
- **Un nom de livre inconnu n'a pas de commission.** Une jambe de couverture dont le bookmaker est
  saisi à la main sous un nom fantaisiste sera comptée brute. Le nom saisi est normalisé (casse et
  espaces), mais il n'y a pas d'appariement approximatif : mieux vaut une commission manquée qu'une
  commission inventée sur un bookmaker classique.
- **Ce qui ferait rouvrir cette décision :** une bourse dont le tarif dépend du marché ou du
  résultat net de la journée — Betfair l'a fait — ne se décrit plus par un taux unique par livre ;
  il faudrait alors un taux par pari, saisi au moment de le prendre.
