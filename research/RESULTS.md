# Résultats — Étape 1

Journal des résultats mesurés. Chaque entrée précise le jeu de données utilisé.
**Le jeu de test (>= 2024-01-01) n'a pas encore été touché.**

---

## R1 — Dataset constitué (2026-09-18)

| | |
|---|---|
| Source | football-data.co.uk (option A, PLAN §7.2) |
| Total | **159 671 matchs** |
| Dont Pinnacle closing | **150 626 matchs**, 2012-03-02 → 2026-01-14 |
| Championnats | 19 principaux + 16 « extra » (Danemark, Norvège, Suède, Finlande, Autriche, Suisse, Pologne, Roumanie, Irlande, Chine, Japon, Mexique, USA, Brésil, Argentine, Russie) |
| Découpage | train 105 617 / validation 23 117 / test 21 892 |

**Constat critique :** Pinnacle closing s'arrête au **2026-01-14** sur la source gratuite. La
colonne est vide à partir de février 2026 et absente des fichiers 2026-27. Seule `AvgCH`
subsiste. L'étape 1 est intégralement réalisable, mais **aucune mesure en avant ne pourra
utiliser Pinnacle depuis cette source**. La collecte propre (option A) devient urgente.

---

## R2 — Efficience de marché par championnat (train + validation)

Marge Pinnacle moyenne, proxy d'efficience. Premier élément de la cartographie de PLAN §2.

```text
Big 5 européens         2,35 - 2,41 %   ← marchés les plus efficients
Irlande, Danemark       2,52 - 2,55 %
Argentine, Japon        2,56 - 2,70 %
Scandinavie, Pologne    2,90 - 3,03 %
Belgique, Roumanie      3,18 - 3,66 %
Grèce                   3,75 %
Chine                   4,22 %          ← marge la plus élevée
```

Le classement suit la théorie. **Mais la hiérarchie n'est pas « grands vs petits »** : l'Irlande
et le Danemark ont des marges comparables au Big 5, tandis que la Grèce et la Belgique — des
championnats principaux — sont au-dessus de plusieurs « petits ». L'hypothèse H2 ne peut donc pas
se contenter d'opposer main et extra ; elle devra raisonner par championnat.

---

## R3 — H3 : comparaison des méthodes de dévig — **CONFIRMÉE**

n = 128 734 (train + validation), 1X2, Pinnacle closing. Marge moyenne 2,88 %.

### Calibration agrégée

| méthode | Brier | log loss |
|---|---|---|
| power | 0,598434 | 1,000659 |
| **shin** | **0,598457** | **1,000703** |
| odds_ratio | 0,598462 | 1,000721 |
| proportional | 0,598552 | 1,000891 |
| *(base rate)* | 0,648690 | 1,072648 |
| *(uniforme)* | 0,666667 | 1,098612 |

Bootstrap par blocs championnat-saison, 1000 tirages :

```text
Brier     shin - proportional = -0,0000951  IC95 [-0,000133, -0,000059]  SHIN MEILLEUR
Brier     shin - power        = +0,0000233  IC95 [+0,000007, +0,000041]  power meilleur
Brier     shin - odds_ratio   = -0,0000046  IC95 [-0,000011, +0,000002]  non concluant
```

**H3 est confirmée** : Shin calibre mieux que la proportionnelle, IC excluant 0.

**Résultat exploratoire non pré-enregistré :** la power method bat Shin, également de façon
significative. Conformément à la discipline du prereg, ce résultat ne peut pas justifier à lui
seul un changement de méthode par défaut. Il motive un nouveau pré-enregistrement.

### Le résultat qui compte vraiment

L'écart agrégé est minuscule (0,016 % relatif sur le Brier). La décomposition par plage de
probabilité montre pourquoi c'est trompeur :

| plage de proba | n sélections | proportionnelle | Shin | écart | **écart relatif** |
|---|---|---|---|---|---|
| 0 – 5 % | 1 289 | 3,9 % | 3,3 % | +0,65 pt | **+16,6 %** |
| 5 – 10 % | 7 069 | 7,9 % | 7,3 % | +0,59 pt | +7,4 % |
| 10 – 20 % | 43 205 | 15,9 % | 15,5 % | +0,39 pt | +2,5 % |
| 20 – 35 % | 204 442 | 27,6 % | 27,5 % | +0,12 pt | +0,4 % |
| 35 – 50 % | 77 808 | 41,9 % | 42,1 % | −0,18 pt | −0,4 % |
| 50 – 70 % | 43 211 | 58,0 % | 58,5 % | −0,54 pt | −0,9 % |
| 70 – 100 % | 9 178 | 77,0 % | 78,0 % | −1,02 pt | −1,3 % |

Le favourite-longshot bias est mesuré sur 128 734 matchs réels, et il est exactement dans le sens
annoncé : la proportionnelle **surestime les outsiders de 16,6 % en relatif** sous 5 %, et
**sous-estime les favoris de 1,3 %** au-dessus de 70 %.

**Conclusion opérationnelle.** Le choix de la méthode de dévig ne change quasiment rien à la
calibration agrégée, mais change massivement **où l'on croit avoir de l'edge**. Avec la
proportionnelle, un moteur d'edge aurait signalé des opportunités systématiques sur les outsiders
— purement artefactuelles. C'est la justification empirique de PLAN §9.

---

## R4 — Benchmark établi

La barre que le modèle devra franchir (train + validation, Pinnacle closing dévigé Shin) :

```text
Brier     = 0,598457
log loss  = 1,000703
```

Pour référence, le taux de base vaut 0,648690. **Le marché apporte donc 0,0502 de Brier au-dessus
du taux de base.** Dixon-Coles devra faire mieux que 0,598457 pour que H1 soit acceptée.

---

## Prochaine étape

Dixon-Coles avec time decay et reconstruction point-in-time, contre ce benchmark. C'est le test
de H1, qui décide de la suite du projet (prereg 0001 §7).

---

## R5 — H1 : **REJETÉE**. Dixon-Coles ne bat pas la clôture. (2026-09-18)

Configuration gelée sur validation (demi-vie 365 j, ridge 1.0, refit 30 j, dévig Shin), jeu de
test touché **une seule fois**, conformément au prereg.

### Résultat principal — n = 21 892 matchs, 2024-01-01 → 2026-01-14

| | Brier | log loss |
|---|---|---|
| **Marché (Pinnacle closing + Shin)** | **0,597374** | **0,999152** |
| Dixon-Coles | 0,612458 | 1,021675 |
| Mélange (poids gelés sur validation) | 0,597412 | 0,999133 |
| Taux de base | 0,650607 | 1,075265 |

```text
Brier    DC - marché = +0,015084   IC95 [+0,012930, +0,017358]
log loss DC - marché = +0,022524   IC95 [+0,019345, +0,025997]
```

**H1 est rejetée.** Le marché est strictement meilleur, avec un intervalle de confiance très
éloigné de zéro. L'écart vaut 2,5 % du log loss — soit **160 fois** l'écart entre méthodes de
dévig mesuré en R3. Aucun raffinement de réglage ne franchit un tel fossé.

### Le modèle n'apporte pas d'information orthogonale

Mélange log-linéaire `p ∝ marché^w1 · DC^w2`, poids ajustés sur validation puis **gelés** :

```text
w1 = +1,1258   (marché)
w2 = -0,0826   (DC — poids NÉGATIF)

hors échantillon : Brier mélange - marché = +0,000038  IC95 [-0,000193, +0,000265]
                   -> non concluant
```

Le poids optimal sur Dixon-Coles est négatif et le mélange ne bat pas le marché seul hors
échantillon. Le modèle n'apporte donc rien, ni seul ni en combinaison. C'est la vérification
décisive : un modèle moins bon peut rester utile s'il porte de l'information orthogonale. Ce
n'est pas le cas ici.

### H2 : **rejetée** — aucun championnat n'échappe à la règle

**0 championnat sur 23** (n ≥ 500) où Dixon-Coles bat le marché. L'écart va de +0,0055
(League One) à +0,0346 (Turquie).

Corrélation entre la marge du bookmaker et l'écart au marché : **+0,057**, c'est-à-dire nulle.
La marge élevée d'un championnat ne signale donc **pas** un marché exploitable. Sur validation,
la Chine — plus forte marge mesurée (4,22 %) — affichait le pire écart de tous (+0,0586).

C'est la tension centrale de PLAN §2, tranchée dans le sens défavorable : une marge élevée ne
traduit pas l'inefficience du marché mais l'incertitude du bookmaker, laquelle coïncide avec des
données plus pauvres pour le modèle. L'avantage informationnel du marché y est **plus grand**,
pas plus petit.

### Vérification de saine implémentation

Le log loss de Dixon-Coles (1,0217) contre celui de la clôture (0,9992) reproduit ce que rapporte
la littérature — les modèles de comptage sur données publiques y sont systématiquement 1 à 3 %
derrière la ligne de clôture. Le résultat n'est pas un défaut d'implémentation : c'est la réponse.

Contrôles indépendants : récupération de paramètres sur données simulées (γ vrai 0,280 → estimé
0,278 ; corrélation attaque 0,964, défense 0,950), optimum de réglage à l'intérieur de la grille
et sur un plateau large (demi-vie 240–730 j, ridge 0,3–3,0), et test anti-fuite au vert.

---

## R6 — Déclenchement du critère d'arrêt

Prereg 0001 §7 et PLAN §0.4 prévoyaient ce cas :

```text
Si H1 est rejetée :
  → ne pas construire l'infrastructure
  → soit pivot vers une source de données propriétaire
  → soit redéfinition en outil personnel d'analyse et de calibration
```

**Le critère est déclenché.** Aucune ligne de Docker, Postgres, FastAPI, worker d'ingestion ou
frontend ne doit être écrite sur la base de ce résultat.

### Ce que l'étape 1 a produit et qui reste valable

- 159 671 matchs normalisés, dont 150 626 avec clôture Pinnacle ;
- module de dévig validé (4 méthodes, 135 tests), et la démonstration empirique que le choix de
  méthode décide d'où l'on croit avoir de l'edge (R3) ;
- harnais point-in-time avec test anti-fuite bit-pour-bit ;
- Dixon-Coles avec time decay, shrinkage et regroupement par pyramide ;
- la mesure du benchmark, et la cartographie des marges par championnat.

Coût : une session. Le plan initial prévoyait d'atteindre ce point après six mois
d'infrastructure.

### La seule piste que ce résultat NE ferme PAS

Battre la **clôture** est le test le plus dur qui soit : elle intègre toute l'information arrivée
jusqu'au coup d'envoi. Mais on ne parie jamais à la clôture — on parie à un prix antérieur.

La question ouverte est donc différente : **Dixon-Coles bat-il la cote d'OUVERTURE ?** Si oui,
parier tôt sur les désaccords avec l'ouverture produirait un CLV positif, même avec un modèle
inférieur à la clôture.

Les fichiers principaux de football-data contiennent `PSH`/`PSD`/`PSA` — Pinnacle à l'ouverture —
qui ne sont pas encore chargés dans le schéma. Le test est donc réalisable sans nouvelle donnée.

**Cette hypothèse est exploratoire et doit être pré-enregistrée avant d'être testée.** Elle n'est
pas couverte par le prereg 0001, et le jeu de test a déjà servi pour H1.

---

## R7 — H5 : **REJETÉE**. La cote précoce est déjà hors d'atteinte. (2026-09-18)

Prereg 0002. Configuration Dixon-Coles gelée, aucun paramètre réajusté.

### H6 (contrôle) — confirmée

n = 77 609 (train + validation, 19 championnats principaux).

```text
Brier    cote précoce 0,599773   clôture 0,597663   écart +0,002110
log loss cote précoce 1,002664   clôture 0,999428   écart +0,003236

IC95 [+0,001720, +0,002528]  ->  la clôture est bien meilleure
```

La prémisse tient : le prix se bonifie entre le relevé précoce et la clôture. **Mais de très
peu — 0,32 % de log loss.** Mon pronostic pré-enregistré annonçait 1 à 1,5 %. Il était trop
optimiste d'un facteur 3 à 5.

### H5 — rejetée

n = 14 121 (validation).

| | Brier | log loss |
|---|---|---|
| Clôture | 0,589926 | 0,988499 |
| Cote précoce | 0,592624 | 0,992680 |
| Dixon-Coles | 0,605098 | 1,011226 |

```text
Brier    DC - précoce = +0,012474   IC95 [+0,010377, +0,014659]
log loss DC - précoce = +0,018546   IC95 [+0,015587, +0,021595]
```

### Le chiffre qui ferme la question

```text
information tardive totale (précoce -> clôture)  =  0,00211 de Brier
retard de Dixon-Coles sur la cote précoce        =  0,01247 de Brier

                       rapport  =  5,9x
```

Autrement dit : **même en misant au tout premier prix affiché, et même en captant l'intégralité
de l'information qui arrive ensuite jusqu'au coup d'envoi, le modèle resterait à six fois cet
écart de la parité.** Le budget total d'information tardive ne couvre pas un sixième du retard.

Ce n'est plus une question de finesse de modèle ni de choix de championnat. Le prix précoce de
Pinnacle intègre déjà pratiquement tout ce qu'un modèle sur données publiques peut savoir.

### Carte de l'information tardive — le sous-produit

Brier précoce − Brier clôture, par championnat (train + validation) :

```text
Grèce                +0,00593   ← le plus d'information tardive
Écosse D2            +0,00492
Italie B, Turquie    +0,00286
...
Angleterre D2        +0,00118
Portugal             +0,00083
Bundesliga           +0,00074   ← prix précoce quasi déjà final
```

Aucun championnat n'atteint la moitié du retard de Dixon-Coles. Le maximum mesuré (Grèce,
+0,0059) reste inférieur de moitié à l'écart DC/précoce (+0,0125). **Il n'existe donc pas de
championnat où la stratégie « miser tôt » puisse fonctionner avec ce modèle.**

Lecture indépendante du projet : la Bundesliga et le Portugal ont un prix précoce quasi définitif
— y miser tôt n'apporte rien. La Grèce et la D2 écossaise portent le plus d'information tardive,
donc le plus de risque à miser tôt sans cette information.

---

## R8 — Conclusion de l'étape 1

Trois hypothèses testées, trois rejets convergents :

| | Hypothèse | Verdict |
|---|---|---|
| H1 | DC bat la clôture | **REJETÉE** — +0,0151 de Brier, 0/23 championnats |
| H2 | L'écart est meilleur sur les petits championnats | **REJETÉE** — corrélation marge/écart = +0,057 |
| H3 | Shin calibre mieux que la proportionnelle | CONFIRMÉE |
| H5 | DC bat la cote précoce | **REJETÉE** — +0,0125, soit 5,9× l'information tardive totale |
| H6 | La clôture bat la cote précoce (contrôle) | CONFIRMÉE — mais de 0,32 % seulement |

Et une vérification décisive : le modèle n'apporte **aucune information orthogonale** — poids de
mélange négatif, gain hors échantillon non concluant.

**La question du projet est close.** Un modèle de comptage sur données publiques ne bat ni la
clôture, ni le prix précoce, dans aucun des 23 championnats testés, ni seul ni en combinaison.

Le critère d'arrêt de prereg 0002 §7 s'applique : atterrissage en outil personnel d'analyse et de
calibration. Le pivot vers des données propriétaires reste la seule voie ouverte vers un signal,
et il exige un chiffrage avant tout engagement.

**Coût total : une session.** Le plan initial situait ce point après six mois d'infrastructure.
