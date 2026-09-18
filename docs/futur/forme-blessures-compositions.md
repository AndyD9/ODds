# Forme, blessures, compositions — par où les prendre sans se mentir

**Date :** 2026-09-18 · **Statut :** réflexion, rien de construit · **Précède :** un pré-enregistrement 0005

La question posée : « gérer la forme de l'équipe, les blessures, les XI de départ ». Ce document dit
ce que le projet a **déjà mesuré** sur ce sujet, ce que ça interdit d'espérer, et ce qui reste
faisable — dans l'ordre où ça coûte le moins.

---

## 1. Ce qu'on sait déjà, et qui borne tout le reste

Trois mesures de `research/RESULTS.md` parlent directement de cette question, même si aucune ne
la nommait :

| mesure | ce qu'elle dit de la forme et des absences |
|---|---|
| **R5** — Dixon-Coles perd 0,0151 de Brier contre la clôture, 0 championnat sur 23 | un modèle qui ne sait *rien* des absences perd nettement contre un prix qui les connaît |
| **R7** — le prix précoce (milieu de semaine) est déjà hors d'atteinte ; l'information tardive vaut au plus 0,006 de Brier | **c'est le plafond** de tout ce que forme, blessures et compositions apportent *ensemble* entre le mercredi et le coup d'envoi. Pas seulement pour nous : pour le marché lui-même |
| **R9** — la matrice calée sur le prix bat DC sur tous les marchés de buts | même là où personne ne cote, le prix reste la meilleure source |

Conséquence, écrite avant de construire quoi que ce soit : **un ajustement de probabilité fondé
sur la forme ou les absences ne battra pas la clôture.** Le marché intègre les compositions en
quelques minutes après leur publication, et il intègre la forme depuis longtemps — c'est
précisément ce que le prix précoce contient déjà. Une hypothèse qui dirait le contraire est
testable, et le pronostic subjectif de ce document est qu'elle sera rejetée.

Ce qui ne veut pas dire qu'il n'y a rien à faire. Il y a trois choses, de nature différente.

## 2. Trois usages, du moins cher au plus cher

### 2a. Le mouvement du prix comme *mesure* des absences — gratuit, données déjà là

La collecte horaire relève le prix de ~24 bookmakers depuis 36 h avant chaque match. Quand une
composition tombe sans un titulaire, **c'est le prix qui bouge**, et on le voit dans
`odds_history.db` sans connaître le nom du joueur. Le mouvement de cote dans les dernières heures
est la trace la plus fiable et la moins coûteuse de l'information tardive — c'est d'ailleurs ce que
R7 mesure sur l'historique.

Ce que ça permet, qui est mesurable et qui n'exige aucune source nouvelle :

- **par match** : afficher le mouvement du consensus depuis la première observation, et
  surtout dans les 2 dernières heures. Un match dont le prix a bougé de 3 points à H−1 est un
  match où quelque chose s'est passé ; le carnet peut le savoir avant de proposer une mise ;
- **par pari** : le CLV mesure déjà si l'on a pris un prix meilleur que la clôture. On peut
  décomposer : combien du CLV vient du *price shopping* (meilleur book au même instant), combien du
  *timing* (le prix a bougé après la prise). C'est la seule façon de savoir si miser tôt ou tard
  nous coûte ou nous rapporte — et donc si les compositions sont un risque pour nos positions ;
- **par championnat** : la carte « information tardive » existe déjà sur l'historique Pinnacle.
  La refaire sur notre collecte, en avant, dira où les compositions déplacent le plus les prix.

**Hypothèse à pré-enregistrer (H9)** : « le mouvement du consensus dans les 2 h précédant le coup
d'envoi est corrélé au CLV des paris pris avant ce mouvement ». Gratuit, mesurable dès quelques
centaines de paris papier, et il répond à la vraie question — *nos positions souffrent-elles des
compositions ?* — sans jamais avoir besoin d'une composition.

### 2b. La forme comme *variable de test* — gratuit, parquet existant

Le parquet porte 159 671 matchs avec scores et dates. La forme se calcule dessus sans rien
télécharger : points sur 5 matchs, buts marqués et encaissés glissants, jours de repos,
domicile/extérieur consécutifs. Le harnais point-in-time (`pit/walk_forward.py`) et le test
anti-fuite garantissent que rien du futur ne s'y glisse.

La question honnête n'est pas « la forme prédit-elle le résultat ? » — elle le prédit, faiblement,
et le marché le sait. La question est : **« une fois le prix connu, la forme apporte-t-elle encore
quelque chose ? »** Test : régression du résultat sur (probabilité de marché dévigée, variables de
forme), sur la validation, Brier contre le marché seul.

**Hypothèse à pré-enregistrer (H8)** : « ajouter la forme récente à la probabilité de marché
dévigée améliore le Brier sur la validation, IC 95 % excluant 0 ». Pronostic subjectif : rejetée,
ou un gain sous 0,001 de Brier — de l'ordre de ce que R7 laisse comme plafond. Le test coûte une
journée et une centaine de lignes, et il ferme la question au lieu de la laisser revenir.

Ce qu'on ne fera **pas** : brancher la forme dans la matrice implicite ou dans le moteur de mise
avant ce verdict. La matrice reproduit le prix ; y ajouter un terme reviendrait à dire qu'on sait
mieux que lui, ce que R5 et R9 interdisent d'affirmer sans mesure.

### 2c. Les absences et les XI comme *données* — coûteux, à ne construire qu'après 2a et 2b

Aucune source du projet ne porte les effectifs. Il faudrait une source nouvelle, avec les
contraintes que ce projet s'impose :

| source | ce qu'elle donne | limites |
|---|---|---|
| API-Football (api-sports.io) | blessures, suspensions, XI ~1 h avant, notes | 100 requêtes/jour gratuites — de l'ordre d'un championnat suivi |
| football-data.org | calendrier, scores, quelques compositions | compositions rares au palier gratuit |
| Transfermarkt, Sofascore, FotMob | absences et XI complets | pas d'API publique ; le scraping viole leurs conditions et casse sans préavis |

Et les mêmes exigences que pour les cotes : **horodatage de disponibilité** (`observed_at` à nous,
pas la date du match), stockage au format long (`match, équipe, joueur, statut, instant`), noms
d'équipe alignés sur la source de cotes — le point où les deux sources de collecte refusent déjà
de se rapprocher, et qui serait le premier problème pratique.

Ce que ça permettrait de mesurer, et seulement après des mois de collecte :

- **H10 (descriptive)** : « la part des minutes jouées la saison passée absente du XI explique le
  mouvement de prix à H−1 ». Elle ne prédit rien qu'on puisse jouer — quand le XI sort, le prix a
  bougé — mais elle dirait *combien* le marché paie un titulaire, ce qui est une connaissance ;
- un affichage de veille dans le détail d'un match : absences connues, et **si le prix a déjà
  réagi**. C'est informatif, pas prédictif, et la carte doit le dire comme les autres.

Le seul cas où les absences deviendraient un avantage serait de les connaître **avant** le
marché. Avec des sources publiques, ça n'arrive pas. Le dire ici évite de le découvrir après six
mois de collecte.

## 3. Ordre proposé, et critère d'arrêt

1. **H9** — mouvement de prix et CLV. Sur notre collecte, sans source nouvelle. Une semaine.
2. **H8** — la forme après le prix. Sur le parquet, avec le harnais PIT. Une journée de calcul.
3. **2c** seulement si H8 ou H9 laissent une porte ouverte, et en commençant par un championnat
   pour tenir dans le palier gratuit.

Critère d'arrêt, fixé maintenant : si H8 est rejetée **et** que H9 montre que nos paris précoces
ne perdent pas de CLV au moment des compositions, alors forme et absences ne changent rien à ce
que le carnet fait, et la question est **fermée** — la collecte d'effectifs n'est pas construite.

Tout ce qui précède est à recopier dans un `prereg/0005` avant la première ligne de code, avec les
seuils d'échantillon de prereg 0001 §2 et le pronostic subjectif de l'auteur.
