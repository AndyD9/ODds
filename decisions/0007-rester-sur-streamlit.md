# 0007 — Rester sur Streamlit, et borner ce qu'il coûte

**Statut :** proposée · **Date :** 2026-09-18 · **Code :** `src/odds/app/`

## Contexte

Le tableau de bord pèse 3 847 lignes, dont 916 de CSS. Sur ces 916, **108 visent des sélecteurs
internes de Streamlit** (`[data-testid="stSidebar"]`, `stMetricValue`, `stAlertContainer`…), et
`theme.py` dessine à la main, en HTML brut, le tableau de la maquette et ses pastilles parce que
`st.dataframe` ne sait pas les exprimer. C'est le symptôme habituel : on ne se sert plus de
Streamlit pour ce qu'il fait bien (poser des widgets sans écrire de front), on lutte contre lui
pour obtenir une mise en page précise. La refonte « la décision d'abord » a encore épaissi cette
couche.

Trois faits cadrent la question, et aucun n'est du côté du confort de mise en page :

1. **Un seul utilisateur, en local.** Pas d'authentification, pas de déploiement, pas de
   concurrence : deux SQLite sur le disque et `uv run odds app`. Les raisons habituelles de
   quitter Streamlit (sessions, droits, montée en charge) ne s'appliquent pas.
2. **Le noyau est déjà hors de l'interface.** `analysis/` sert la CLI et le tableau de bord ; les
   modules `app/` lisent, mettent en forme, et écrivent au carnet. Une migration ne toucherait
   pas au modèle — mais ne ferait pas non plus avancer d'un jour la prochaine étape, le prereg
   0005 (H8/H9/H10).
3. **Aucun test ne touche `app/`.** Une réécriture de 3 800 lignes se ferait sans filet, et sa
   seule preuve de non-régression serait l'œil.

## Décision

On reste sur Streamlit. On traite la dette de mise en page comme une dette **bornée**, pas comme
un motif de migration : on fige la version, on isole les sélecteurs internes dans un seul fichier
identifié comme fragile, et on note à l'avance ce qui ferait changer d'avis.

Concrètement :

- **Épingler** `streamlit~=1.64.0` au lieu de `>=1.64.0` — au patch, pas à la mineure :
  `~=1.64` autoriserait 1.65, qui est précisément la mise à jour qui renomme un
  `data-testid`. Cent lignes de CSS reposent sur des
  attributs que Streamlit ne documente pas et change sans préavis ; un plancher ouvert transforme
  une mise à jour de routine en interface cassée un matin de collecte.
- **Regrouper** les règles visant `data-testid` en une seule section en tête de `theme.css`,
  sous un commentaire qui dit qu'elle est liée à la version épinglée. Le reste du fichier — les
  tuiles, le tableau dessiné, les pastilles, la barre 1 · N · 2 — ne dépend que de notre propre
  balisage et survivrait tel quel à un changement de socle.
- **Un test de fumée**, `tests/test_app_fumee.py`, qui exécute les sept pages du tableau de bord
  avec `AppTest` (le harnais officiel de Streamlit, sans navigateur) et vérifie qu'aucune ne lève
  ni ne reste vide, puis exerce les fragments HTML de `theme.py` — dont l'échappement des
  cellules, qui est rendu avec `unsafe_allow_html=True`. Il ne prouve pas que la page est belle ;
  il prouve qu'elle ne casse pas après un renommage dans `analysis/`. Sans historique collecté,
  la première partie s'ignore au lieu d'échouer.

## Options écartées

- **FastAPI + HTMX (ou un front Vite/React) à la place.** On gagnerait la maîtrise complète du
  rendu, un vrai comportement mobile, et des pages qui ne se réexécutent pas en entier à chaque
  clic. Écartée **pour l'instant** : le coût est d'une à deux semaines de travail solo pour
  reproduire ce qui existe, à valeur analytique nulle, alors que la question ouverte du projet
  n'est pas l'affichage mais la sélection par EV et sa validation. Le devis est honnête, pas
  prohibitif — ce qui manque, c'est un bénéfice qui le justifie aujourd'hui.
- **Un composant Streamlit sur mesure (React) pour le tableau de décision.** Techniquement le
  bon geste si le tableau dessiné devenait interactif (tri, sélection de jambes dans la grille).
  Écartée aujourd'hui : il introduit une chaîne de build npm dans un dépôt qui n'en a pas, pour
  un tableau qui reste en lecture. À reprendre si l'interaction arrive.
- **Dash, Reflex, NiceGUI, Panel.** Migrer d'un framework Python tout-en-un vers un autre
  framework Python tout-en-un : on rachèterait les mêmes contraintes sous d'autres noms, et on
  paierait quand même la réécriture. Écartée sans hésitation.
- **Sortir des pages HTML statiques depuis la CLI.** Séduisant : la lecture est l'essentiel de
  l'usage, et un fichier statique se consulte de n'importe où. Écartée : le carnet **écrit** —
  inscrire un pari, ajuster une mise, régler un match. Il faudrait de toute façon un serveur pour
  la moitié qui compte, et on se retrouverait avec deux interfaces à tenir.

## Conséquences

- La mise en page reste contrainte par ce que Streamlit expose. Toute maquette qui demande une
  géométrie que le CSS ne peut pas plier se paiera en HTML brut dans `theme.py`, comme le tableau
  actuel. C'est acceptable tant que ces fragments restent en lecture seule : dès qu'un élément
  dessiné à la main doit devenir cliquable, la décision est à rouvrir.
- Chaque interaction réexécute le script. Les trois `@st.cache_data` tiennent aujourd'hui ; si un
  clic dépasse la seconde une fois la fiabilité par tranche élargie, c'est un signal à mesurer,
  pas à contourner par un cache de plus.
- **Ce qui ferait rouvrir cette décision**, écrit maintenant pour ne pas en discuter à chaud :
  consulter ou inscrire un pari depuis un téléphone ; un deuxième utilisateur ; un tableau
  dessiné qui doit devenir interactif ; ou une mise à jour de Streamlit qui casse la section CSS
  épinglée deux fois de suite. Un seul de ces points suffit, et le candidat désigné est alors
  FastAPI + HTMX, pas un autre framework Python.
- La dette reste visible, et **mesurée** : `test_la_zone_fragile_reste_bornee` compte les lignes
  de `theme.css` visant un interne (108 aujourd'hui) et échoue au-delà de 150. Le jour où il
  casse, la réponse n'est pas de relever le seuil : c'est que le rapport coût/bénéfice de la
  migration a basculé.
- Restait une dette voisine, hors de cette décision : `use_container_width`, appelé 26 fois et
  annoncé supprimé depuis le 31 décembre 2025. **Soldée le 2026-09-19** — remplacée par
  `width="stretch"` partout, pendant que la version est épinglée et que rien ne presse. C'était
  exactement le genre de travail que l'épinglage rend planifiable au lieu de subi ; la sortie des
  tests ne porte plus un seul avertissement de suppression.
