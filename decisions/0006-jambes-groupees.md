# 0006 — Les jambes d'une couverture sont des paris ordinaires reliés par un groupe

**Statut :** acceptée · **Date :** 2026-09-18 · **Code :** `src/odds/paper.py`,
`src/odds/market/couverture.py`

## Contexte

Une couverture est plusieurs mises sur des issues exclusives d'un même marché, prises ensemble.
Le carnet ne connaissait que le pari isolé : une ligne, une issue, un verdict. Il faut pouvoir
inscrire une couverture, la régler, lui calculer un CLV, et la juger sur son **net** — car elle
perd une jambe par construction et le taux de réussite par jambe ne la décrit pas.

## Décision

Chaque jambe est une ligne `pari` ordinaire, avec sa cote, son bookmaker, sa probabilité, sa
`mise_proposee` et son CLV. Une colonne `groupe` (TEXT, NULL pour un pari isolé) relie les jambes
d'une même couverture. `enregistrer_couverture` écrit toutes les jambes dans **une transaction**
et renvoie l'identifiant du groupe ; `couvertures()` agrège par groupe : mise, net, statut, pire
cas accepté. Le schéma passe en version 3 par le mécanisme de migration existant.

## Options écartées

- **Une table `couverture` avec ses jambes en lignes filles.** Plus « propre » relationnellement.
  Écartée : le règlement par score (`regler_match`), la capture du CLV et le bilan lisent la table
  `pari` et fonctionneraient sans changement sur les jambes — les dupliquer dans une seconde
  table obligerait à réécrire trois chemins qui marchent pour un lien qu'une colonne suffit à
  porter.
- **Une seule ligne par couverture, avec la répartition en JSON.** Un seul enregistrement, un
  seul verdict. Écartée : une jambe a sa propre cote de clôture, son propre bookmaker et son
  propre CLV ; les fondre dans une ligne perdrait précisément ce que le CLV mesure.
- **Ne rien relier et laisser l'utilisateur regrouper à l'œil.** C'est ce que le carnet
  permettait déjà, et c'est ce qui fait chuter le taux de réussite à chaque couverture sans que
  rien ait été mal joué.

## Conséquences

- Le plafond de 1 % par match (prereg 0001 §4) s'applique à la **somme** des jambes, réduites
  dans la même proportion quand il mord (`proposer_couverture`). Il ne compte pas, en revanche,
  les paris isolés déjà inscrits sur le même match — pas plus que `proposer_mise` ne le faisait.
  C'est une limite connue, à lever ensemble pour les deux chemins ou pour aucun.
- Le bilan par jambe (`bilan`) reste juste : profits et mises s'additionnent. La page « Mes
  paris » gagne une vue « Couvertures » qui montre le net par groupe, et marque les jambes d'un
  badge dans l'historique.
- `kelly` sur une jambe porte la fraction de Kelly **simultané**, pas celle du pari seul. Les
  deux coïncident quand la couverture n'a qu'une jambe.
