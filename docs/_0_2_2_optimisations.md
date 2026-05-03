# Analyse 0.2.2 - optimisations performances doctrine summary

## 1) Objectif

Ce document formalise les optimisations de performance pour les vues doctrine summary de `aa-fitting-mastery`, avec un focus sur les scénarios « grosse alliance » (beaucoup de joueurs, beaucoup d’alts, plusieurs doctrines/fittings).

Objectifs principaux :

- réduire le temps de chargement perçu des pages summary ;
- réduire le nombre de requêtes SQL et le coût CPU total ;
- introduire du cache sur les données peu volatiles ;
- conserver un comportement fonctionnel strictement identique.

---

## 2) Périmètre analysé

Flux principaux :

- `mastery/views/summary.py`
  - `summary_list_view`
  - `summary_doctrine_detail_view`
  - `summary_fitting_detail_view`
- `mastery/views/summary_helpers.py`
  - `_build_member_groups_for_summary`
  - `_build_fitting_user_rows`
  - `_build_doctrine_summary`
  - `_build_fitting_kpis`
  - `_build_doctrine_kpis`
- `mastery/services/pilots/pilot_progress_service.py`
  - `build_for_character`
  - `_load_character_skill_map`
  - `_load_skillset_skills`
  - `_load_skill_dogma_cached`

---

## 3) Hotspots identifiés

## 3.1 Coût dominant : calcul progress par couple character x fitting

Le coût principal est la multiplication des appels à `build_for_character(character, skillset)` dans les boucles summary.

- Complexité effective: `O(nombre_characters_in_scope * nombre_fittings_configurés)`.
- Chaque appel calcule les missing rows, SP manquants, estimations temps, buckets.
- Le cache intra-requête (`progress_cache` et `progress_context`) existe, mais ne couvre pas les requêtes HTTP suivantes.

Impact : très sensible sur les grosses alliances (latence multi-secondes).

## 3.2 N+1 potentiel côté skills personnage

Dans `pilot_progress_service._load_character_skill_map`, les skills d’un personnage sont chargés par personnage.

- Même avec cache_context, le premier passage pour chaque personnage déclenche une requête.
- Sur gros volumes, cela peut représenter des centaines/milliers de requêtes selon la cardinalité.

Impact : fort sur DB + sérialisation ORM.

## 3.3 Filtrage Python évitable sur fitting maps approuvées

`_approved_fitting_maps()` charge toutes les maps puis filtre en Python.

- `select_related(...).all()` + `if _is_approved_fitting_map(obj)`
- Le filtre `status=APPROVED` peut être appliqué directement en SQL.

Impact : modéré à fort selon volumétrie historique de maps.

## 3.4 Recalcul KPI fitting inutile dans doctrine detail

`_build_doctrine_summary()` calcule déjà `fit["kpis"]`, puis `summary_doctrine_detail_view` recalcule ces KPI.

Impact : CPU doublé sur cette partie, sans valeur fonctionnelle.

## 3.5 Requêtes et opérations redondantes mineures

- `eligible_users.exists()` avant le queryset final in-scope: requête supplémentaire évitable.
- Doubles prefetch sur doctrines/fittings possibles selon chemins.
- Plusieurs passes Python successives sur les mêmes structures (`user_rows`) pour agrégats.

Impact : faible individuellement, utile en cumul.

---

## 4) Optimisations recommandées

## 4.1 Quick wins (faible risque, gains immédiats)

1. Filtrer `_approved_fitting_maps()` en SQL:
   - `FittingSkillsetMap.objects.filter(status=APPROVED)...`
   - Option complémentaire: restreindre aux fittings réellement accessibles/affichés.

2. Supprimer le double calcul KPI fitting dans `summary_doctrine_detail_view`.

3. Retirer les `exists()` et autres checks intermédiaires qui forcent des requêtes anticipées.

4. Réduire les passes Python redondantes dans `_build_fitting_user_rows` / KPI (single-pass lorsque possible).

Gains attendus: ~10-25% selon dataset.

## 4.2 Optimisations structurelles (gros gains)

1. **Préchargement batch des skills personnages**
   - Charger en une fois les skills des personnages in-scope de la requête.
   - Alimenter `cache_context["character_skills"]` avant les boucles de progression.

2. **Préparation par skillset**
   - Pré-calculer par `skillset_id` les structures stables utilisées par `build_for_character`.
   - Réutiliser dans tous les calculs du même rendu.

3. **Pipeline orienté “compute once, reuse many”**
   - Calculer une fois les objets intermédiaires pour doctrine/fitting puis éviter les recompositions.

Gains attendus: ~30-60% sur les gros volumes si N+1 fortement réduit.

---

## 5) Stratégie cache recommandée

Hypothèse métier confirmée: les données personnages changent relativement peu souvent.

## 5.1 Cache applicatif de progression (priorité haute)

Cache du résultat de progression par couple personnage/skillset:

- clé: `mastery:summary:progress:v1:{character_id}:{skillset_id}`
- valeur: payload `build_for_character(..., include_export_lines=False)`
- TTL: 5 à 15 minutes
- invalidation: TTL + purge ciblée si sync skills ou regen skillset

Effet: évite de recalculer entièrement les mêmes progressions à chaque ouverture de page.

## 5.2 Cache des groupes in-scope (priorité moyenne)

Cache de la population filtrée summary group:

- clé: `mastery:summary:groups:v1:{group_id}:{activity_days}:{include_inactive}`
- valeur: projection légère (`user_id`, `character_ids`, `main_character_id`, `last_seen`)
- TTL: 5 à 10 minutes

Effet: réduit le coût des filtres audience/activité récurrents.

## 5.3 Principes de sécurité cache

- éviter un cache HTML complet au début (stale plus difficile à maîtriser) ;
- cacher des briques métier atomiques ;
- versionner les clés (`v1`) pour migrations de format sans casse.

---

## 6) Plan d’implémentation par phases

### État global actuel des phases

- **P0** : implémentée côté code pour les vues summary, baseline de référence encore à relever/archiver sur dataset réel.
- **P1** : implémentée.
- **P2** : implémentée pour le batching `character_skills` intra-requête et son instrumentation debug.
- **P3** : implémentée (cache partagé inter-requêtes progression personnage/skillset + invalidation sur régénération).

## Phase P0 - Mesure (obligatoire)

- instrumenter temps total vue, temps calcul progress, nombre de requêtes SQL ;
- capturer baseline sur:
  - `summary_list_view`
  - `summary_doctrine_detail_view`
  - `summary_fitting_detail_view`

Livrable: baseline de référence (avant optimisation).

État d'avancement (implémenté côté code) :

- instrumentation admin-only sur les trois vues summary via snapshots session + page debug dédiée ;
- métriques P0 actuellement capturées :
  - `view_total_ms`
  - `sql_query_count`
  - `progress_calls`
  - `progress_cache_hits`
  - `progress_cache_misses`
  - `progress_cache_entries`
  - `member_groups`
  - `active_characters_total`
- compteurs métier spécifiques selon la vue :
  - `visible_doctrines` sur `summary_list_view`
  - `configured_fittings` / `fittings_total` sur `summary_doctrine_detail_view`
  - `user_rows` / `flyable_now_users` sur `summary_fitting_detail_view`

Reste à faire pour clôturer opérationnellement P0 :

- relever une baseline stable sur dataset représentatif ;
- comparer ces snapshots avant/après futures optimisations ;
- idéalement archiver ces valeurs dans un document de benchmark ou ticket de suivi.

## Phase P1 - Quick wins

- SQL filter pour fitting maps approuvées ;
- suppression recalcul KPI doctrine detail ;
- suppression requêtes auxiliaires évitables.

État d'avancement (implémenté) :

- `_approved_fitting_maps()` filtre désormais directement `status=APPROVED` en SQL (plus de filtre Python post-`all()`).
- `_build_member_groups_for_summary()` n'utilise plus le `exists()` anticipé sur les utilisateurs éligibles.
- En mode `include_inactive=True`, la résolution des main characters d'activité est désormais ignorée (requête SQL évitée, résultat inchangé).

Validation: comparer latence + requêtes vs baseline.

## Phase P2 - Batching

- préchargement massif des skills personnages in-scope ;
- alimentation `cache_context` en amont.

Validation: chute significative du nombre de requêtes SQL et du temps DB.

État d'avancement (implémenté) :

- `_prime_summary_character_skills_cache_context()` précharge les `CharacterSkill` de tous les personnages in-scope en une seule passe ORM ;
- `PilotProgressService._load_character_skill_map()` consomme ensuite `cache_context["character_skills"]` avant tout fallback DB ;
- instrumentation P2 exposée dans la page debug admin :
  - `prime_calls`
  - `prime_character_ids_total`
  - `prime_already_cached`
  - `prime_uncached`
  - `prime_rows_loaded`
  - `cache_hits`
  - `cache_misses`
  - `db_loads`
  - `skills_loaded`

Remarque de périmètre :

- cette phase est considérée comme réalisée pour le batching `character_skills` ;
- les sous-idées listées en §4.2.2 (« préparation par skillset ») et §4.2.3 (« compute once, reuse many ») restent des optimisations structurelles complémentaires, mais hors du livrable P2 initial ciblé ici.

## Phase P3 - Cache partagé

- cache progression personnage/skillset ;
- cache member groups in-scope ;
- invalidation minimale viable + monitoring hit rate.

Validation: gains stables inter-requêtes (pas uniquement intra-requête).

État d'avancement (implémenté) :

- Nouveau module `mastery/services/summary_cache.py` :
  - `get_skillset_cache_version(skillset_id, version_context)` — lit le compteur de génération du skillset depuis le cache Django, avec mémoire locale intra-requête via `version_context` ;
  - `invalidate_progress_cache_for_skillset(skillset_id)` — incrémente le compteur de génération, invalidant effectivement toutes les entrées de progression associées ;
  - `build_progress_cache_key(character_id, skillset_id, version)` — construit la clé `mastery:progress:v1:{char}:{ss}:{version}` ;
  - `get_cached_progress(character_id, skillset_id, version_context)` — lecture depuis le cache Django avec gestion des erreurs ;
  - `set_cached_progress(cache_key, progress)` — écriture avec TTL configurable (`MASTERY_SUMMARY_PROGRESS_CACHE_TTL`, défaut 600 s).
- Intégration dans `mastery/views/summary_helpers.py` :
  - `_summary_p3_progress_cache_metrics()` — bucket d'instrumentation `p3_metrics.shared_progress_cache` (`cache_hits`, `cache_misses`, `cache_writes`, `stale_fallbacks`) ;
  - `_progress_for_character()` modifié : cherche d'abord dans le cache intra-requête (P0), puis dans le cache Django (P3), puis calcule et écrit dans les deux caches.
- Invalidation dans `mastery/services/doctrine/doctrine_skill_service.py` :
  - `generate_for_fitting()` appelle `summary_cache.invalidate_progress_cache_for_skillset(fitting_map.skillset_id)` après chaque régénération de plan.
- Nouveau setting `MASTERY_SUMMARY_PROGRESS_CACHE_TTL` (défaut: 600 s, min: 0 pour désactiver).
- Template debug `summary_p2_metrics_debug.html` enrichi d'une section **Phase P3** affichant hits, misses, writes, stale fallbacks et hit ratio calculé.
- 3 nouveaux tests P3 ajoutés dans `mastery/tests/test_views.py` : cache hit, cache miss + write, hit P3 puis intra-requête.

Note sur le cache member-groups :

- la projection légère des `member_groups` serait possible mais nécessiterait de resérialiser/recharger des objets ORM (Character/User) à partir d'IDs — gain modéré pour coût de complexité élevé ;
- reporté : la réduction du coût dominant (progress par character × fitting) couvre l'essentiel du gain visé par P3.

---

## 7) Métriques de succès

Métriques cibles (à adapter après baseline):

- latence p50/p95 de `summary_list_view`;
- latence p50/p95 de `summary_doctrine_detail_view`;
- nombre moyen de requêtes SQL par page;
- temps cumulé DB vs temps CPU Python;
- cache hit ratio (P3).

Cible pragmatique:

- p50 divisé par ~2 sur gros volumes ;
- réduction SQL de 40%+ sur pages summary.

---

## 8) Risques et garde-fous

Risques:

- cache périmé (stale data) ;
- invalidation incomplète ;
- augmentation mémoire côté worker.

Garde-fous:

- TTL courts au départ ;
- versionnage des clés ;
- feature flags pour activer par étape ;
- rollback simple (désactivation cache).

---

## 9) Optimisations additionnelles (Alpha / Omega)

Les changements récents (flags `required_requires_omega`, `recommended_requires_omega`, `max_alpha_level`, badge clone grade, conversion "Make Skill Plan Alpha Compatible") ouvrent des optimisations ciblées supplémentaires.

### 9.1 Pré-calcul réutilisable des métadonnées clone-grade

Constat:

- le statut Alpha/Omega est recalculé à chaque preview/génération à partir des caps clone-grade ;
- ces caps sont globalement stables entre deux imports SDE.

Optimisation proposée:

- construire un cache partagé des caps Alpha par `skill_type_id` (ou par lot de skill ids) ;
- versionner la clé de cache avec la version SDE active (`sde_version_id` / hash d’import) ;
- injecter ce cache en amont de `preview_fitting` et des parcours summary.

Effet attendu:

- baisse des lectures DB SDE répétées ;
- stabilité de latence sur les parcours multipliant les fitting previews.

### 9.2 KPI "compatibilité Alpha" calculés en single-pass

Constat:

- les cartes de plan calculent déjà des compteurs Omega ;
- les mêmes flags servent aussi aux badges ligne à ligne.

Optimisation proposée:

- produire, dans un seul passage sur `active_rows`, un payload agrégé incluant:
  - `required_plan_alpha_compatible`,
  - `recommended_plan_alpha_compatible`,
  - `can_make_recommended_plan_alpha_compatible`,
  - nombre de skills ajustables pour la conversion Alpha ;
- réutiliser ce payload tel quel côté template et endpoints d’action.

Effet attendu:

- moins de dérives entre UI et backend ;
- suppression des recalculs annexes lors de l’affichage de l’éditeur.

### 9.3 Prévisualisation de conversion Alpha sans recalcul complet

Constat:

- l’action de conversion Alpha fait un `preview_fitting` complet avant d’appliquer les clamps.

Optimisation proposée:

- introduire une forme de "plan delta" léger:
  - extraire uniquement les lignes actives avec `recommended_level > max_alpha_level` ;
  - mémoriser ce delta (ids + niveau cible) en cache court côté requête/session ;
  - réutiliser ce delta lors du POST si le fingerprint du plan n’a pas changé.

Effet attendu:

- réduction CPU sur les clics répétés/rafraîchissements éditeur ;
- action POST plus déterministe.

### 9.4 Invalidation ciblée du cache Alpha/Omega

Déclencheurs à considérer:

- import SDE (nouvelle version clone-grade) ;
- modification du fitting (skills, blacklist, manuel, override rec) ;
- synchronisation doctrine/fitting.

Principe:

- invalidation granulaire par scope (skillset/fitting/doctrine), pas flush global ;
- fallback TTL court pour sécurité si invalidation manquée.

### 9.5 Instrumentation dédiée Alpha/Omega

Ajouter des métriques dédiées pour objectiver les gains:

- ratio de plans `required` Alpha-compatibles ;
- ratio de plans `recommended` convertibles ;
- nombre moyen de skills clampés par conversion ;
- temps moyen du endpoint de conversion Alpha ;
- hit ratio du cache clone-grade.

---

## 10) Recommandation finale

Ordre recommandé pour maximiser le ratio gain/risque:

1. P0 baseline métriques
2. P1 quick wins
3. P2 batching DB/ORM
4. P3 cache partagé

Cette séquence permet des gains rapides sans compromettre la stabilité, puis des gains structurels majeurs adaptés aux grandes alliances.

---

## 11) Étendre la page debug avec de nouvelles métriques par phase

La page debug admin (`Summary Debug Metrics`) a vocation à agréger les métriques utiles **par phase d’optimisation** quand elles deviennent pertinentes.

### 11.1 Contrat de données actuel

Les snapshots sont stockés en session avec une structure de ce type :

```python
{
    "captured_at": "2026-05-02T09:15:00+00:00",
    "source": "summary_list",
    "metrics": {
        "p0_metrics": {
            "summary_view": {
                "view_total_ms": 84.2,
                "sql_query_count": 17,
                "progress_calls": 96,
            }
        },
        "p2_metrics": {
            "character_skills": {
                "prime_calls": 1,
                "cache_hits": 95,
            }
        },
    },
}
```

Convention à respecter :

- une phase = une clé racine nommée `pX_metrics` ;
- à l’intérieur, regrouper les compteurs par sous-domaine stable (`summary_view`, `character_skills`, etc.) ;
- n’y mettre que des valeurs sérialisables en session (bool/int/float/str/dicts/listes simples).

### 11.2 Où injecter de nouvelles métriques

1. **Métriques de vue / orchestration**
   - fichier : `mastery/views/summary.py`
   - usage : compléter `progress_context["pX_metrics"]["summary_view"]` juste avant le stockage du snapshot.

2. **Métriques de helpers summary**
   - fichier : `mastery/views/summary_helpers.py`
   - usage : incrémenter un bucket dans `cache_context` pendant les boucles ou le préchargement.

3. **Métriques de service métier**
   - fichier : `mastery/services/pilots/pilot_progress_service.py`
   - usage : alimenter le bucket de phase via `cache_context` quand un fallback DB, un hit cache ou un calcul lourd se produit.

### 11.3 Procédure recommandée pour une nouvelle phase

Exemple pour une future **P3** de cache partagé :

1. créer une clé `p3_metrics` ;
2. y ajouter un sous-bucket clair, par ex. `shared_progress_cache` ;
3. y exposer des compteurs simples et actionnables, par ex. :
   - `cache_hits`
   - `cache_misses`
   - `cache_writes`
   - `cache_invalidations`
   - `stale_fallbacks`
4. ajouter une section conditionnelle dédiée dans le template `mastery/templates/mastery/summary_p2_metrics_debug.html` ;
5. ajouter des tests de snapshot + rendu dans `mastery/tests/test_views.py`.

### 11.4 Règles pratiques

- privilégier des compteurs et durées agrégées, pas des payloads volumineux ;
- éviter tout objet ORM dans les snapshots ;
- ne pas exposer de secrets/settings sensibles ;
- conserver une cardinalité basse pour que la page debug reste lisible ;
- si une métrique sert à valider une phase, documenter explicitement son interprétation dans ce fichier.

