# Pré-enregistrement 0003 — Ouverture du carnet aux marchés de buts

**Date d'enregistrement :** 2026-09-18
**Statut :** actif
**Enregistré avant :** tout pari papier sur un marché autre que le 1X2.

Le carnet papier ne portait que le 1X2. Il s'ouvre aux marchés de buts — total du match, total
par équipe, les deux équipes marquent. Ce document fixe ce qui est ouvert, comment la
probabilité est produite et comment la mise est bornée, **avant** qu'un seul de ces paris ne
soit enregistré. Le faire après reviendrait à choisir les règles en connaissant les résultats.

---

## 1. Ce qui change de cadre

Le périmètre « aucun signal de pari » (RESULTS R8) est levé : l'outil est un outil personnel à
usage éducatif, et il peut donc afficher des probabilités qui ne sont pas de simples lectures de
prix. Ce qui ne change pas :

- **l'exploitation reste en papier** (prereg 0001 §5), sans passage d'ordre ;
- **aucune affirmation sur le ROI** sous 20 000 paris réglés (prereg 0001 §2) ;
- le **CLV** reste le seul critère lisible à court terme (prereg 0001 §5).

## 2. Marchés ouverts

| famille | codes | coté par une source accessible ? |
|---|---|---|
| Résultat | `1`, `N`, `2` | oui, ~24 bookmakers |
| Total du match | `total_over/under_{0.5 … 5.5}` | **ligne 2,5 seulement** |
| Total par équipe | `dom_/ext_over/under_{0.5 … 3.5}` | non |
| Les deux marquent | `btts_oui`, `btts_non` | non |

## 3. Source de la probabilité — figée

Matrice de score ajustée pour reproduire les prix de marché dévigués (Shin), et **jamais**
Dixon-Coles. Ce n'est pas une préférence : RESULTS R9 mesure que DC perd contre la matrice
implicite sur tous les marchés de buts, dans toutes les strates, y compris sur les petits
championnats et sur les marchés que personne ne cote.

- une cote over/under existe → elle contraint la matrice, `rho` est ajusté sur ce match ;
- sinon → le 1X2 seul contraint la matrice, `rho = −0,09` (calibré train+validation, vérifié sur
  le jeu de test, R9c).

## 4. Bornes d'usage — mesurées, pas choisies

R9d établit que la dérivation surestime les buts des matchs déséquilibrés, d'autant plus que le
favori est fort. La table `buts.BIAIS_DERIVE` fige les valeurs mesurées et l'interface affiche le
biais correspondant à chaque match. **Aucune correction n'est appliquée** : un rattrapage ajusté
sur la donnée qui a révélé le biais serait du surajustement.

## 5. Staking — `confiance` v2

Un quatrième facteur est ajouté à la fonction de prereg 0001 §4, et versionné ici avant tout
résultat :

    confiance = f(n) × f(data_quality) × f(incertitude) × f(source)

    f(source) = 1,0   probabilité lue sur un prix (1X2, ou matrice contrainte
                      par une cote de totaux)
              = 0,5   probabilité dérivée du 1X2 seul

Justification : R9b mesure un ECE de 0,0073 dans le premier cas contre 0,0366 dans le second. La
dégradation est mesurée ; le coefficient 0,5, lui, est une **convention** — celle déjà retenue
pour un écart non robuste à la méthode de dévig, faute d'une façon défendable d'en dériver une
autre. Il est figé ici et ne sera pas ajusté en fonction des résultats obtenus.

Par ailleurs, `n_hist` n'est **pas** transmis pour un pari de buts : la table de fiabilité
historique est mesurée sur l'issue la plus probable du 1X2, et l'appliquer à un autre marché
serait un emprunt abusif. Un signal absent vaut 1 — on ne pénalise pas ce qu'on n'a pas mesuré.

## 6. Règlement

Par le **score**, saisi à la main, une fois par match. Chaque marché décide lui-même s'il est
gagné, par le prédicat qui a servi à le coter (`odds.models.football.buts`). Un marché ne peut
donc pas être coté selon une règle et réglé selon une autre.

La saisie reste manuelle : les noms d'équipe diffèrent entre The Odds API et football-data,
`analysis.py` refuse déjà de les rapprocher, et un règlement automatique approximatif inscrirait
des gains faux dans un historique destiné à trancher une question.

## 7. Ce que ce suivi ne pourra pas dire

- **Pas de CLV sur les totaux par équipe ni sur BTTS.** Aucune source accessible ne les cote,
  donc aucune cote de clôture à comparer. Le CLV manquera précisément là où la probabilité est
  dérivée plutôt que lue. C'est la limite la plus gênante de cette extension et elle est
  structurelle, pas provisoire.
- **Pas de ROI interprétable** avant 20 000 paris réglés, tous marchés confondus (prereg 0001 §2).
- Le suivi par marché sera **encore plus lent à devenir lisible** que le suivi global, puisqu'il
  divise le même échantillon.

## 8. Critère d'arrêt

Si, sur les marchés de buts dérivés, le CLV mesuré sur le total du match (le seul mesurable)
s'avère négatif sur 200 paris ou plus, l'ouverture est refermée sur les marchés dérivés. Seuil
fixé ici, avant le premier pari.
