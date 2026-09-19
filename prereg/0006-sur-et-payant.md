# Pré-enregistrement 0006 — « Sûr et payant » : un favori net, payé au-dessus du consensus

**Date d'enregistrement :** 2026-09-19
**Statut :** actif
**Enregistré avant :** tout pari inscrit au carnet au titre de cette règle.

**Numérotation :** le 0005 reste réservé aux hypothèses forme / blessures / compositions
esquissées dans `docs/futur/forme-blessures-compositions.md` (H8, H9, H10), écrites avant
celle-ci et non encore enregistrées.

---

## 1. La demande, et ce qu'elle implique

Demande de l'utilisateur, le 2026-09-19 : au-delà de la plus-value, « les outsiders ne sont pas
des paris qui passent forcément ; il faut quand même un taux de safe supérieur à 80 %, et gagner
avec des cotes à **1,25 minimum**, car en dessous ça n'a plus d'intérêt ».

Les deux seuils n'en font qu'un, et il faut le dire avant de construire :

    cote juste d'un favori à 80 %  =  1 / 0,80  =  1,25

Exiger `p ≥ 0,80` **et** `cote ≥ 1,25`, c'est exiger `p × cote ≥ 1`, c'est-à-dire une espérance
positive ou nulle sur un gros favori — donc qu'un bookmaker paie ce favori **à son prix juste ou
mieux**. Ce n'est pas impossible ; c'est rare, et c'est rare pour une raison structurelle : un
livre vit de la marge qu'il prend sur le prix.

Mesuré sur les 144 matchs collectés, **avant** d'écrire la règle (comptage de faisabilité, pas
résultat de rentabilité) :

| seuil de probabilité | cote juste | candidats (cote nette ≥ 1,25 et écart > 0) | réussite mesurée de la tranche |
|---|---|---|---|
| 85 % | 1,176 | **0** | 89,2 % (n = 1 085) |
| 80 % | 1,250 | **0** | 83,6 % (n = 2 174) |
| 78 % | 1,282 | **0** | 79,1 % (n = 3 173) |
| 75 % | 1,333 | 3 | 79,1 % (n = 3 173) |
| 72 % | 1,389 | 4 | 74,5 % (n = 5 028) |
| 70 % | 1,429 | 4 | 74,5 % (n = 5 028) |
| 60 % | 1,667 | 9 | 62,5 % (n = 10 505) |

Les 7 favoris à 80 % et plus de ces 144 matchs étaient offerts à **1,10 de cote nette médiane**,
pour un écart médian de **−1,17 %**. Aucun n'approchait 1,25.

Le point le plus proche de la demande qui existe réellement dans les données est donc
**p ≥ 75 %, cote nette ≥ 1,25**, dont la tranche est mesurée à **79,1 % de réussite** — un point
sous les 80 % demandés, et ce point manquant est le prix du 1,25.

## 2. La règle — figée

Une cote est « sûre et payante » si les quatre conditions tiennent ensemble :

1. l'issue est **le favori du marché** (`issue == issue_probable`). La table de fiabilité mesure
   la fréquence de l'issue **la plus probable** ; l'appliquer à une autre serait un emprunt
   abusif, comme l'interdit déjà `tranche_fiabilite_buts` pour les marchés de buts ;
2. sa probabilité de consensus dévigé atteint `p_min` (défaut **0,70**, la borne basse du
   niveau de confiance « Élevée » de `fiabilite.NIVEAUX` — le chiffre déjà affiché à côté de
   chaque pronostic ; 0,80 à l'enregistrement, voir le journal) ;
3. la meilleure cote **nette de commission** (decisions/0008) atteint `cote_min` (défaut
   **1,25**), chez un **bookmaker réel** — un agrégat de marché dit qu'un prix existe sans dire
   chez qui, on ne peut pas y miser ;
4. cette cote bat le consensus des **autres** livres, recalculé sans celui qui l'affiche
   (`ecart > 0`).

`p_min` et `cote_min` sont **réglables dans l'interface**, et c'est délibéré : ils se contraignent
l'un l'autre par `cote_juste = 1/p`, et le compromis se lit sur la page. `cote_min` est la valeur
demandée ; `p_min` a été abaissé le jour même de 0,80 à 0,70, par décision de l'utilisateur et au
vu du tableau de §1 (journal). Les déplacer reste une décision de l'utilisateur, affichée dans le
titre du bloc avec le niveau de confiance correspondant et le taux d'échec mesuré à ce niveau
(« 1 pari sur 4 perd »), jamais un choix silencieux du code.

À 0,70, la cote juste vaut 1,43 : le plancher de 1,25 **ne lie plus**, et c'est la condition 4 —
un livre réel au-dessus du consensus des autres — qui fait le tri. Le plancher garde son sens de
« gain en dessous duquel le pari n'intéresse pas », et redevient contraignant si l'utilisateur
remonte `p_min` au-dessus de 0,80.

## 3. Ce que la règle ne fait pas

- **Elle ne remplace pas le verdict.** Un favori bien payé mais soutenu par un seul livre passe la
  règle et sort « écart isolé » ; s'il change de signe selon la méthode de dévig, il sort
  « fragile » (R3). Le verdict est affiché sur la carte, sans rien filtrer : la règle dit ce qui
  est sûr et payant, le verdict dit ce que le prix vaut. Les confondre reviendrait à ajouter un
  deuxième canal de recommandation qui échapperait aux garde-fous du premier.
- **Elle ne remplace pas la mise.** Kelly × confiance (prereg 0001 §4) reste le seul moteur de
  mise, et les plafonds s'appliquent inchangés. Une probabilité élevée fait mécaniquement une
  mise plus grosse ; c'est déjà dans la formule, il n'y a rien à ajouter.
- **Elle ne change pas la règle de sélection existante.** Le bloc « meilleur écart, quelle que
  soit l'issue » reste affiché en dessous, avec sa règle du 2026-09-18 (parmi les écarts
  soutenus, le plus probable d'abord). Les deux répondent à deux questions différentes et sont
  présentées comme telles.
- **Elle ne promet pas de gagner.** Un taux de réussite de 79 % n'est pas un profit : à 1,31, il
  faut 76,3 % pour être à l'équilibre. La marge entre les deux est l'écart affiché, et elle est
  de l'ordre de 2 % — bien à l'intérieur du bruit sur quelques dizaines de paris (prereg 0001 §2 :
  aucune affirmation sur le ROI sous 20 000 paris réglés).

## 4. Ce qu'on refusera d'en conclure

- Qu'une suite de paris « sûrs » gagnants valide la règle. À 79 % de réussite, dix paris gagnants
  d'affilée arrivent une fois sur dix ; c'est la variance du niveau de probabilité, pas une
  preuve.
- Qu'un pari « sûr » perdu invalide quoi que ce soit. Un favori à 80 % perd **un match sur
  cinq**, et le tableau de bord affiche ce taux d'échec à côté de chaque pronostic depuis
  l'origine.
- Que le seuil de 1,25 rende un pari rentable. Il rend le **gain** intéressant si le pari passe ;
  la rentabilité se joue entre `p` et `1/cote`, pas sur la valeur absolue de la cote.
- Que descendre `p_min` jusqu'à ce que des candidats apparaissent soit un réglage neutre. Chaque
  point de probabilité abandonné se paie en fréquence d'échec, et la table de §1 le chiffre.

## 5. Critère de révision

Cette règle est un **filtre d'affichage**, pas une hypothèse testable : elle ne prédit rien. Ce
qui sera mesuré, comme pour tout pari du carnet, est le **CLV** (prereg 0001 §5) des paris pris à
ce titre, suivi séparément grâce à la colonne `note` du carnet.

Elle sera rouverte si, et seulement si :

- le CLV moyen des paris « sûrs et payants » est négatif sur au moins 50 paris réglés — le prix
  aurait alors systématiquement bougé contre nous, ce qui indiquerait qu'on prend des cotes
  périmées plutôt que des prix généreux ;
- ou la règle ne produit aucun candidat sur trois mois de collecte continue à ses valeurs par
  défaut, auquel cas c'est la demande qu'il faut reformuler, pas le seuil qu'il faut baisser en
  silence.

## Journal

| date | modification | raison |
|---|---|---|
| 2026-09-19 | création | demande de l'utilisateur ; seuils 0,80 / 1,25 fixés par lui, faisabilité mesurée avant écriture |
| 2026-09-19 | `p_min` par défaut : 0,80 → **0,70**, défini comme la borne du niveau « Élevée » | demande de l'utilisateur, le jour même : « se baser sur la confiance, choisir les confiances élevées en priorité ». Ce n'est pas un réglage neutre, et §4 le dit : le tableau de §1 chiffre ce qu'il coûte — réussite mesurée **74,5 %** (n = 5 028) au lieu de 83,6 %, soit un pari perdu sur quatre au lieu d'un sur cinq — et ce qu'il rapporte : la règle à 0,80 était structurellement vide (0 candidat sur 144 matchs, mesuré **avant** l'écriture, pas après une série perdante), à 0,70 elle en avait 4. La condition d'écart positif est inchangée : aucun candidat n'est retenu sous sa cote juste. Le critère de révision de §5 reste, aux nouvelles valeurs par défaut. |
