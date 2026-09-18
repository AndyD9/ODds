# Pré-enregistrement 0004 — Couvrir plusieurs issues d'un même marché

**Date d'enregistrement :** 2026-09-18
**Statut :** actif
**Enregistré avant :** toute couverture inscrite au carnet papier.

Le carnet portait des paris isolés : une issue, une cote, une mise. Il s'ouvre aux
**couvertures** — plusieurs mises sur des issues exclusives d'un même marché, prises ensemble et
jugées ensemble. Ce document fixe ce qu'est une couverture, comment elle est répartie et bornée,
et ce qu'on refusera d'en conclure, **avant** que la première ne soit enregistrée.

---

## 1. Ce qui ne change pas

- **Papier uniquement** (prereg 0001 §5). Aucun passage d'ordre.
- **Aucune affirmation sur le ROI** sous 20 000 paris réglés (prereg 0001 §2). Une couverture de
  trois jambes compte pour trois paris réglés dans ce décompte, et pour une position dans le
  bilan net.
- **Les probabilités viennent du prix** (prereg 0003 §3) : 1X2 dévigé par Shin, ou matrice de
  score implicite pour les marchés de buts. Jamais d'un modèle ajusté sur l'historique.

## 2. Ce qu'est une couverture

Des mises sur un sous-ensemble d'une **partition** : des issues exclusives qui recouvrent tous les
scores. Les partitions sont celles du catalogue (`market/couverture.py`, `PARTITIONS`) : le 1X2,
chaque ligne over/under du total, chaque ligne par équipe, BTTS. Un test vérifie que chaque
partition recouvre chaque score exactement une fois.

On ne couvre **pas** entre partitions. « Monaco » et « moins de 3 buts » ne s'excluent pas ; leur
combinaison n'a pas de retour garanti et n'est pas une couverture au sens de ce document.

## 3. Répartition — figée

Deux répartitions existent dans le code. Une seule est proposée par le moteur.

**Kelly simultané** (Smoczynski & Tomkins, 2010), la seule que le moteur signe. Issues classées
par `p × cote` décroissant, retenues tant qu'elles battent la réserve
`R(S) = (1 − Σ_S p) / (1 − Σ_S 1/cote)` ; fraction `p − R / cote` sur chaque issue retenue. Pour
une issue seule, la fraction est exactement `(p × cote − 1) / (cote − 1)` : la formule de
prereg 0001 §4. Ce n'est pas une nouvelle règle de mise, c'est la même sur plusieurs issues.

**Retour égal** (dutching), au choix de l'utilisateur : `mise_i ∝ 1 / cote_i`. Elle est affichée
pour être comprise, avec son espérance en face, et enregistrable — l'écart à la proposition du
moteur est alors conservé jambe par jambe (`mise_proposee`), comme pour tout pari.

## 4. Bornes — les mêmes, sur la somme

    f_effectif = f_base × confiance(...)             (prereg 0001 §4, 0003 §5)
    mises_i    = bankroll × fraction_i × f_effectif
    Σ mises_i  ≤ 1 % de bankroll                     plafond par MATCH, pas par jambe
    Σ mises_i  ≤ exposition restante                 5 % simultané

Le plafond par match porte sur la **somme des jambes**. Trois jambes à 1 % chacune seraient 3 %
sur un seul coup d'envoi ; le plafond de §4 dit « par match » et c'est ainsi qu'il est lu. Quand
le plafond mord, toutes les jambes sont réduites dans la même proportion : la forme de Kelly est
conservée, seule l'échelle change.

Les signaux de `confiance()` sont ceux du marché couvert : `n_hist` de la tranche de l'issue la
plus probable pour le 1X2, de la table des buts pour les autres ; `p_cotee` faux dès que la
matrice est dérivée du 1X2 seul.

## 5. Ce que le moteur refuse

- **Une couverture sans issue qui batte sa réserve.** Le moteur ne propose rien, comme
  `proposer_mise` ne propose rien sous le prix juste.
- **Une couverture complète à perte garantie.** `Σ 1/cote ≥ 1` sur toute la partition garantit
  une perte de `1 − 1/Σ`. Elle reste affichée et enregistrable pour l'exercice, jamais proposée.
- **Corriger une espérance par la répartition.** Le module porte l'invariant en tête de
  docstring : l'espérance d'une couverture est la somme des espérances de ses jambes. Aucune
  ligne de code ne le contourne, et un test le vérifie.

## 6. Ce que Kelly couvre qui n'a pas de valeur — et pourquoi c'est correct

Kelly simultané peut retenir une issue dont `p × cote < 1`. Exemple enregistré ici : Monaco à
1,90 avec p = 0,58 (valeur), nul à 3,76 avec p = 0,24 (`0,24 × 3,76 = 0,90`, pas de valeur).
Kelly mise 12,4 % sur Monaco **et 0,95 % sur le nul**. Le nul n'a pas d'espérance positive ; il
réduit la variance d'une position devenue grosse, et la croissance logarithmique le paie. C'est
la seule forme de « couverture » que ce projet reconnaît comme justifiée, et elle est bornée par
la formule, pas par un jugement. L'interface le dit en clair : *ce n'est pas de la valeur, c'est
une assurance*.

## 7. Carnet

Les jambes d'une couverture partagent un `groupe` (`decisions/0006`). Chaque jambe garde sa cote,
son bookmaker, sa probabilité, son CLV : elle se règle et se mesure comme un pari isolé. La vue
« Couvertures » du carnet juge le **net par groupe** — une couverture perd une jambe par
construction, et le taux de réussite par jambe ne la décrit pas.

## 8. Ce que ce suivi ne pourra pas dire

- **Si couvrir vaut mieux que ne pas couvrir.** Comparer les deux demanderait de jouer les deux
  sur les mêmes matchs ; on ne joue qu'une position. Le carnet mesure ce qui a été fait.
- **Un ROI**, avant 20 000 paris réglés, tous marchés confondus.
- **Un CLV sur les jambes non collectées** (totaux par équipe, BTTS), pour la raison de
  prereg 0003 §7.

## 9. Critère d'arrêt

Si, sur 100 couvertures réglées ou plus, le net cumulé des jambes que Kelly a retenues **sans
valeur** (`p × cote < 1`) est inférieur à ce qu'aurait coûté leur simple absence — c'est-à-dire
si l'assurance a coûté plus que la variance qu'elle a retirée, mesurée par la croissance
logarithmique de la bankroll avec et sans ces jambes —, la couverture de jambes sans valeur est
refermée et le moteur ne propose plus que les issues à `p × cote > 1`. Seuil fixé ici, avant la
première couverture.

---

## Journal des modifications

| Date | Modification | Raison |
|---|---|---|
| 2026-09-18 | Création | — |
