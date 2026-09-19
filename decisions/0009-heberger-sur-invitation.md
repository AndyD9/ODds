# 0009 — Héberger l'application, sur invitation, sans quitter Streamlit

**Statut :** proposée · **Date :** 2026-09-19 · **Code :** `src/odds/stockage.py`,
`src/odds/app/acces.py`, `src/odds/paper.py` (schéma v5), `.github/workflows/collecte.yml`

## Contexte

La décision 0007 gardait Streamlit **parce que** l'outil n'avait qu'un utilisateur, en local, et
listait ce qui la ferait rouvrir : « consulter ou inscrire un pari depuis un téléphone ; un
deuxième utilisateur ». Le 2026-09-19, l'utilisateur demande les deux à la fois : déployer
l'application, et n'en ouvrir l'accès qu'à des personnes qu'il choisit. Il pensait à Vercel et à
Supabase, dispose d'un hébergement web mutualisé chez OVH, et veut une solution gratuite.

Trois contraintes cadrent le choix :

1. **Streamlit a besoin d'un processus qui tourne**, avec un websocket. Vercel exécute des
   fonctions courtes ; un hébergement mutualisé sert du PHP et des fichiers. Aucun des deux ne
   peut faire tourner l'application telle qu'elle est. Le candidat désigné par 0007 pour ce cas
   était FastAPI + HTMX — une à deux semaines de réécriture, sans valeur analytique.
2. **Le disque d'un hébergeur gratuit ne survit pas à un redémarrage.** Or `data/` est l'état
   irremplaçable (decisions/0004) : le carnet et la base de collecte doivent vivre ailleurs.
3. **Le collecteur tourne toutes les heures**, aujourd'hui par `launchd` sur le poste de
   l'utilisateur. Hébergé, il doit tourner quelque part qui ne s'endort pas.

## Décision

On reste sur Streamlit, hébergé sur **Streamlit Community Cloud** (gratuit, une application
privée, s'endort après douze heures sans visite). L'état vit dans un **seau Supabase Storage**
privé, copié fichier entier. L'accès passe par **`st.login`** (OpenID Connect, Google) et une
**liste d'invités** dans les secrets. La collecte passe sur un **cron GitHub Actions**.

### L'état : SQLite reste le format, le seau est la copie de référence

On ne réécrit pas les 59 requêtes pour Postgres. `stockage.py` copie les fichiers de
`chemins.ETAT` — et les deux parquets dérivés, longs à régénérer — dans le seau :

- au réveil d'une instance, `demarrer()` ramène ce qui a changé (empreinte ETag, fichier par
  fichier, écriture atomique) ;
- après **chaque** écriture au carnet, `paper._valider` commite puis `publier` ; un carnet de
  32 Ko part en quelques dizaines de millisecondes ;
- le collecteur tire la base de collecte avant sa passe et la repousse après ; l'application la
  rafraîchit au plus toutes les cinq minutes quand l'empreinte distante change.

Ce qui rend l'approche tenable, et qui est la **condition** de cette décision : **un seul
écrivain par fichier**. L'application écrit le carnet et lui seul ; le collecteur écrit la base
de collecte et elle seule. Community Cloud exécute une instance ; une seconde ferait perdre des
écritures, et c'est écrit plus bas comme premier motif de révision.

Ce qu'on perd, en le sachant : une écriture faite dans la fraction de seconde qui précède un
arrêt brutal de l'instance n'est pas copiée. Pour un carnet **papier**, c'est un pari à
réinscrire, pas une perte d'argent.

### L'accès : la connexion est celle de Streamlit, la règle est la nôtre

Community Cloud sait rendre une application privée et inviter des adresses, mais depuis
Streamlit 1.42 **il ne transmet plus l'adresse connectée à l'application** — on ne saurait pas
qui inscrit un pari. On utilise donc `st.login` avec un client OAuth Google, et l'application
elle-même tient la liste : `ODDS_INVITES` dans les secrets. L'application Community Cloud reste
publique au sens de l'hébergeur ; sa première page est une porte fermée. Y ajouter quelqu'un est
un réglage, pas un déploiement.

### Le carnet : une colonne, pas une base par personne

Schéma v5 : chaque pari porte `utilisateur` (l'adresse). `paris()`, `annuler`, `derregler`,
`supprimer` et la bankroll ne voient que l'utilisateur courant, posé par `acces.ouvrir()` à
chaque exécution de page via une variable de contexte. **Le règlement d'un match et la capture
des clôtures portent sur tous les paris du match** : un score est un fait, qui le saisit le
saisit pour tout le monde — c'est voulu, et c'est une raison de n'inviter que des gens de
confiance. Les paris inscrits avant les comptes portent « local » ; le propriétaire
(`ODDS_PROPRIETAIRE`) les adopte dès qu'il est configuré, en local comme hébergé, et garde la
bankroll historique. Un invité part de la bankroll par défaut.

### La collecte : GitHub Actions, à h+7

Un workflow planifié chaque heure exécute `odds collect` avec les secrets du dépôt. L'ordonnanceur
de `collect.py` (decisions/0002) décide toujours seul si la passe vaut un appel payant : un
déclenchement à vide ne coûte rien. Coût GitHub : un peu plus d'une minute par heure, dans les
2 000 minutes mensuelles d'un dépôt privé gratuit.

## Options écartées

- **Réécrire en FastAPI + HTMX pour Vercel.** C'est ce que 0007 désignait. Écartée pour la même
  raison qu'elle y était différée : une à deux semaines pour reproduire l'existant, alors que la
  question ouverte reste la sélection par EV. Cette décision *est* une réouverture de 0007, et
  elle conclut que le déclencheur (« un deuxième utilisateur ») est satisfait à moindre coût.
- **Supabase Postgres à la place de SQLite.** L'option « propre » : écritures concurrentes, plus de
  copie de fichiers, RLS possible. Écartée aujourd'hui parce qu'elle impose de traduire 59 sites
  d'appel et deux dialectes (les tests resteraient sur SQLite), pour 5 Mo de données et une
  instance unique. C'est la **destination désignée** si les conditions de révision se réalisent.
- **Turso / libSQL.** SQLite servi en réseau, presque sans changement de code. Écartée : un
  fournisseur de plus, pour un problème que le seau règle déjà.
- **L'hébergement mutualisé OVH.** Ne peut pas exécuter l'application. Il pourrait servir une
  page de redirection vers l'URL Community Cloud, rien de plus.
- **L'allowlist de Community Cloud seule, sans `st.login`.** Elle ferme la porte mais ne dit pas
  qui est entré : impossible d'attribuer un pari.

## Conséquences

- Trois modes coexistent, et le code les distingue par la configuration seulement : **local**
  (rien de configuré, comportement inchangé, celui des tests), **hébergé** (`[auth]` +
  `ODDS_INVITES` + Supabase), **collecteur** (Supabase seul). `tests/conftest.py` neutralise la
  configuration d'hébergement comme il neutralise déjà la clé API.
- La mise en service demande des gestes manuels de l'utilisateur, listés dans le README : un
  dépôt GitHub (le projet n'a pas encore de dépôt distant), un projet Supabase avec un seau
  privé `etat`, un client OAuth Google, les secrets Community Cloud et GitHub, puis
  `odds etat pousser` une fois pour amorcer le seau depuis le disque local.
- Les scripts qui écrivent dans `data/` **hors** de `paper` et `collect` — s'il en apparaît —
  doivent appeler `stockage.publier`, sinon leur écriture ne survit pas au prochain réveil.
- L'application s'endort après douze heures sans visite ; le premier réveil prend une trentaine
  de secondes, dont le rapatriement de l'état.
- **Ce qui ferait rouvrir cette décision**, écrit maintenant : une deuxième instance de
  l'application (Community Cloud ou ailleurs) ; une écriture perdue constatée au carnet ; plus
  d'une vingtaine d'invités ; ou un besoin d'écrire l'état depuis un troisième endroit. Un seul
  suffit, et la destination est alors Supabase Postgres, pas un autre mécanisme de copie.
