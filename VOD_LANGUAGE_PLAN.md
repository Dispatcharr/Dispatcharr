# Dispatcharr — VOD Category Language & Quality Metadata (backend-only)

**Author:** northernpowerhouse · **Reviewer:** SergeantPanda · **Date:** 2026-09-13
**Base:** fork of `Dispatcharr/Dispatcharr` @ `origin/dev` (includes #1511)
**Scope:** backend only. UI for assigning language/quality to categories lands in a follow-up, after review.

---

## 1. Goal

Make a best effort to guarantee the VOD stream a client plays is in the language the client asked
for, without depending on providers naming things consistently or exposing language metadata.

The lever is the **category**: an operator **manually** assigns a language (and optionally a default
quality) to a VOD category per M3U account. Every VOD item ingested under that category inherits
that language. Titles are then grouped by language, and within a language group **quality decides
priority**.

**Language is never inferred from the title.** There is no language regex anywhere in this plan.
The only two sources are the operator's manual category assignment and, where a provider happens to
expose it, the provider's own per-stream language field. Quality is the only thing that uses title
matching, and only as the first step of its own precedence chain.

### Resolution precedence (single rule, used everywhere)

```
language(relation) = provider-supplied language   # only if the provider actually gave one
                  or category language            # operator-assigned, M3UVODCategoryRelation
                  or None                         # "unknown" — behaves exactly as today

quality(relation)  = title match on the item name # existing detection, unchanged
                  or category default quality     # operator-assigned
                  or None                         # sorts last
```

For the overwhelming majority of titles the language comes from the category, so a title appears
**once per category-language**. Multiple language variants *inside one category* only happen when
the provider itself supplied language metadata on individual streams — that metadata wins for that
stream and splits it out.

---

## 2. What exists today (verified via deepwiki against `Dispatcharr/Dispatcharr`)

| Piece | Location | Today's behaviour |
|---|---|---|
| `M3UVODCategoryRelation` | `apps/vod/models.py` | `m3u_account`, `category`, `enabled`, **`custom_properties` (JSONField, already present)**, timestamps. `unique_together(m3u_account, category)` |
| `M3UVODCategoryRelationSerializer` | `apps/vod/serializers.py` | exposes `category`, `m3u_account`, `enabled` — **does not expose `custom_properties`** |
| Write path | `M3UAccountViewSet.update_group_settings` → `PATCH /api/m3u/accounts/{pk}/group-settings/` | already bulk-writes `custom_properties` for category relations via `ensure_custom_properties_dict()` — same code path as live-stream `ChannelGroupM3UAccount` |
| Movie/Series dedup (ingest) | `apps/vod/tasks.py` `process_movie_batch` / `process_series_batch` | key = `tmdb_{id}` → `imdb_{id}` → `name_{name}_{year}` |
| Relation identity (ingest) | same | `M3UMovieRelation` looked up by `(m3u_account, stream_id)`; `M3USeriesRelation` by `(m3u_account, external_series_id)`. Existing rows are **updated in place**, so **relation PKs are stable across refreshes** |
| Stale cleanup | `cleanup_orphaned_vod_content` | deletes relations whose `last_seen` is older than the cutoff, then orphaned `Movie`/`Series` |
| Quality detection | `M3UMovieRelationSerializer.get_quality_info` / episode equivalent | relation `custom_properties['quality'|'resolution']` → `video` width/height → substring match on name (`4K`/`2160p`, `1080p`/`FHD`, `720p`/`HD`, `480p`) → bitrate. Returns `quality_info`; **not persisted** |
| Movie output | `apps/output/views.py` `xc_get_vod_streams` → `_xc_fetch_priority_distinct_relations` | Postgres `DISTINCT ON (movie_id)`, ordered `movie_id, -m3u_account__priority, id`. **`stream_id = Movie.id`** |
| Series output | `xc_get_series` | `DISTINCT ON (series_id)`, same ordering. **`series_id = the winning M3USeriesRelation.id`** |
| Playback | `stream_xc_movie` / `xc_get_vod_info` → `_select_vod_stream` → `_get_content_and_relation` | `stream_id` → `Movie.id` → candidates ordered `-priority, id`; first with profile capacity wins |
| Caching | — | no caching layer on VOD category/stream output |

**No migration is needed.** `custom_properties` already exists on `M3UVODCategoryRelation` and the
bulk write path already persists it. This mirrors how live-stream groups carry extra settings on
`ChannelGroupM3UAccount.custom_properties`.

### 2.1 Why you see no duplicate series today — and why that is consistent with this plan

Both things are true at once:

* The **relation table** really is one row per (title, category, provider). `M3USeriesRelation` is
  keyed on `(m3u_account, external_series_id)`, so a series carried by two providers has two rows.
* The **output** collapses them. `xc_get_series` passes `distinct_field='series_id'` to
  `_xc_fetch_priority_distinct_relations`, which does `DISTINCT ON (series_id)` after ordering by
  `-m3u_account__priority, id`. Two providers ⇒ two relation rows ⇒ **one** output row, carrying the
  `series_id` of the higher-priority provider's relation. Upstream test
  `test_series_picks_highest_priority_relation` asserts exactly this.

So "99% of my VODs appear in two providers, and I see no duplicates" is the expected result: the
duplicates exist in the database and are deduped at output. This feature does not create duplicates —
it changes the **dedup key** from `series_id` to `(series_id, language)`. With no languages assigned
everything falls into one group and the output is unchanged. With two providers in two different
language categories, the group splits and you get the two entries you want.

---

## 3. Storage schema

### 3.1 `M3UVODCategoryRelation.custom_properties`

```jsonc
{
  "language": "es",       // ISO 639-1, lowercase, 2 letters. Absent/null = unassigned.
  "quality":  "1080p"     // one of 4K | 1080p | 720p | 480p | SD. Absent/null = no default.
}
```

Both keys optional. Unknown/extra keys preserved untouched (merge, never replace the dict).

### 3.2 `M3UMovieRelation` / `M3UEpisodeRelation`.`custom_properties`

Ingestion writes **one** additional top-level key, and only when the provider actually supplied
language metadata:

```jsonc
{ "basic_data": { ... }, "language": "es" }
```

Top-level (not nested inside `basic_data`) so it can be pulled out of Postgres with a
`KeyTextTransform` annotation instead of transferring the whole JSON blob per row.

**That is the entire persistent footprint.** No third store, no registry, no ID table — see §5.

---

## 4. New module: `apps/vod/language.py`

Small, dependency-free, no DB access except the one cached lookup.

```python
QUALITY_ORDER = ("4K", "1080p", "720p", "480p", "SD")   # index = rank, lower is better
SUFFIX_RE     = re.compile(r"[\[(][A-Za-z]{2}[\])]\s*$")

get_category_metadata()            # -> {(m3u_account_id, category_id): {"language":..., "quality":...}}
                                   #    single query over M3UVODCategoryRelation, cached
vod_language_enabled()             # -> bool, True iff any category relation has a language set
resolve_language(rel_lang, cat_meta)
resolve_quality(name, cat_meta)    # title match first, then category default
quality_rank(quality)              # -> int, unknown sorts last
apply_language_suffix(name, lang)  # -> "Inception [ES]"; no-op if lang is None or SUFFIX_RE matches
```

### 4.1 `get_category_metadata()` caching

`M3UVODCategoryRelation` is a small table (hundreds of rows). One `.values()` query fetches
`m3u_account_id`, `category_id`, `custom_properties`, built into a dict. Cached in Django's cache
(Redis) under `vod:category_meta:v1` with a long TTL, **invalidated explicitly** at the end of
`update_group_settings`. Resolution is always live against current config — nothing is baked into
ingested rows, so changing a category's language takes effect immediately with no re-ingest and no
mass row rewrite.

`vod_language_enabled()` is derived from the same cached dict — zero extra queries.

### 4.2 Quality matching

Lift the name-matching branch of the existing `get_quality_info` into `resolve_quality()` as a
single precompiled pattern, and have the serializers call it so there is exactly one
implementation. Behaviour is unchanged for the serializers; the only addition is the category
default as a final fallback *before* returning `None`.

Computed at output time, not persisted: it is a precompiled regex over a name already present in
the row, and keeping it live means a category's default quality can change without a re-ingest.
(If profiling ever says otherwise, precompute into `relation.custom_properties["quality_tag"]` at
ingest and read it via `KeyTextTransform` — future optimisation, not done now.)

### 4.3 Title suffix

`apply_language_suffix` appends `" [ES]"` (uppercased ISO 639-1) to **every** title that resolves to
a known language, regardless of whether that title has one language group or several — this is a
change from the earlier draft, which only suffixed contested titles. It is skipped when:

* the language is unknown (nothing to append), or
* the title already ends in a bracketed/parenthesised 2-letter token (`SUFFIX_RE`), so provider
  titles that already carry `(EN)` or `[ES]` are left alone rather than double-tagged.

---

## 5. ID scheme — the winning relation's ID (your suggestion; adopted)

**`stream_id` for a movie becomes the ID of an `M3UMovieRelation`, not `Movie.id`.**

This is your proposal and it is better than the synthetic-encoding scheme in the previous draft.
It works because #1511 guarantees a relation exists for every (title, category, provider)
combination, and language is a property of the category — so **the relation is already the
per-language handle**. It also makes movies behave exactly like series, which have used relation IDs
as their output ID all along.

What it buys us over the encoded/registry scheme:

* no `CoreSettings` language registry, no append race between workers
* no stride constant, no 32-bit `movie_id * 64` ceiling
* no encode/decode arithmetic and no dead branch when a slot is missing
* movies and series finally use the same kind of identifier

### 5.1 Which relation in the group gets to be the ID

The group `(movie, language)` may contain several relations (multiple providers, multiple qualities).
Whichever one we nominate, its ID becomes the client-visible `stream_id`. Two candidates:

| Nominee | Behaviour |
|---|---|
| **Winner** (highest quality, then priority) | matches what series does today, but the ID *moves* whenever quality/priority ranking changes — e.g. adding a higher-priority provider silently repoints every affected title |
| **Anchor = `min(id)` in the group** *(chosen)* | ID is fixed by whichever relation was ingested first and is immune to priority and quality changes; only moves if that exact relation is pruned by `cleanup_orphaned_vod_content` |

**Decided (§11.0c): anchor** for movies. Relation PKs are stable across refreshes (updated in place,
keyed on `(m3u_account, stream_id)`), so the anchor is durable in normal operation. Selection of
*which stream actually plays* is completely independent of the anchor — see §6.7.

**Series stay on their current winner-ID behaviour in v1**, to keep the diff and the regression
surface small; only their dedup key changes. The resulting movies-anchor / series-winner split is a
**deliberate, decided asymmetry**, not an oversight: nominate for stability where the ID is just a
name, nominate for quality where the ID is a handle. Rationale and rejected alternative in §11.0(c).

### 5.2 Namespace and the one-time churn

With the feature **off**, `stream_id` remains `Movie.id` and output is byte-identical to today.
With it **on**, every movie emits a relation ID — including unknown-language titles — so that the
namespace is uniformly "relation IDs" and never a mix. Consequences:

* Enabling the feature is a **one-time client re-scan** — *accepted, see §11.0(a)*. Unavoidable in
  any scheme that gives a title more than one identity, and it happens once rather than
  continuously.
* `Movie.id` and `M3UMovieRelation.id` are separate sequences and can collide numerically, so a
  client that scanned before the switch could send an ID that resolves in the wrong namespace.
  Guard: resolve as a relation ID first and, **only on miss**, fall back to `Movie.id` (one extra
  query, only on the failure path). Log the fallback at debug so operators can see stale clients.

---

## 6. Changes by file

### 6.1 `apps/vod/language.py` — new
As §4.

### 6.2 `apps/vod/serializers.py`
* `M3UVODCategoryRelationSerializer`: add `custom_properties = serializers.JSONField(required=False)`,
  matching `ChannelGroupM3UAccountSerializer`. Validate on write: `language` is a 2-letter alpha code
  (lowercased) or null; `quality` is in `QUALITY_ORDER` or null. Reject anything else with a 400
  rather than silently storing junk.
* `get_quality_info` (movie + episode): delegate the name branch to `resolve_quality()`; append the
  category default as the last fallback.

### 6.3 `apps/m3u/views.py` — `M3UAccountViewSet.update_group_settings`
* The existing `ensure_custom_properties_dict()` write path already persists the new keys — change it
  to **merge** incoming `custom_properties` into the existing dict rather than replace, so a caller
  that sends only `language` can't wipe an unrelated key.
* Invalidate `vod:category_meta:v1` at the end of the action.
* Nothing else: no registry, no ID allocation, no side effects on ingestion.

This endpoint already accepts a **list** of `category_settings` in one PATCH, so the planned UI
(select a batch of categories, assign language and/or quality to all of them) is a single call
against the API exactly as it stands. No batch-specific backend work is required.

### 6.4 `apps/vod/tasks.py` — ingestion
* In `process_movie_batch` / `process_series_batch` / episode processing, when building the relation's
  `custom_properties`, check the provider payload for a language field (`language`, `audio_language`,
  `lang`, and the language entry inside `detailed_info.audio` where present). If found and it
  normalises to a 2-letter code, set top-level `custom_properties["language"]`.
* That dict is **already** written per relation on every refresh — this adds a dict lookup and an
  assignment. No extra queries, no extra writes, no extra passes.
* Nothing else changes. Category `enabled` filtering, dedup keys, and the bulk create/update flow all
  stay as-is. **Category language deliberately does not touch ingestion** — it is applied at read
  time so the operator can change it without re-ingesting.

### 6.5 `apps/output/views.py` — movies
```
if not vod_language_enabled():
    <existing code path, completely untouched>
```
Otherwise, replace the single `DISTINCT ON (movie_id)` fetch with two narrow queries:

1. **Selection pass** — `.values("id", "movie_id", "category_id", "m3u_account__priority",
   "movie__name")` plus `rel_lang=KeyTextTransform("language", "custom_properties")`, filtered exactly
   as today (active accounts, category filter, adult filter), ordered by `movie_id, id`. Group in
   Python by `(movie_id, resolved_language)`. Per group record `anchor_id = min(id)`.
2. **Hydration pass** — the *existing* wide fetch (`XC_MOVIE_VALUE_FIELDS`,
   `_xc_annotate_relation_artwork`) restricted to `id__in=<anchor ids>`.

Emit as today, with two differences: `stream_id = anchor_id`, and
`name = apply_language_suffix(name, language)` per §4.3.

Payload cost: pass 1 transfers ~6 scalar columns per relation instead of one wide row per movie;
pass 2 transfers the same wide rows as today, one per emitted entry. No JSON blobs cross the wire.

### 6.6 `apps/output/views.py` — series
Same feature gate. Dedup key in `_xc_fetch_priority_distinct_relations` becomes
`(series_id, language)`; ranking within a group becomes `(quality_rank, -priority, id)`.
`series_id` stays the winning `M3USeriesRelation.id` (§5.1). Titles get the same suffix treatment.
`xc_get_series_info` needs no change — the relation already pins the provider, hence the language,
hence the episodes.

### 6.7 `apps/proxy/vod_proxy/views.py` — playback
* `_get_content_and_relation`: resolve the incoming `stream_id` as an `M3UMovieRelation.id` first,
  falling back to `Movie.id` on miss (§5.2). From the resolved relation take its `movie` and its
  resolved language.
* `_select_vod_stream`: build the candidate set from **all** relations for that movie in that
  language group — *not* just the anchor — and order by `(quality_rank, -m3u_account__priority, id)`.
  The anchor is an identifier, never a playback constraint; the best-quality stream in the group
  plays. Unknown language ⇒ unchanged ordering.
* If the language group yields no playable relation, **fall back to the full candidate set** rather
  than failing — a wrong-language stream still beats a dead link. Log at debug.

### 6.8 `apps/output/views.py` — `xc_get_vod_categories`
Unchanged. Categories stay real `VODCategory` rows; language lives on the items, and in practice a
language-tagged category already *is* the language boundary.

---

## 7. Regression guards

Acceptance criteria for review:

1. **Zero-config is a no-op.** With no category languages assigned, `vod_language_enabled()` is False
   and every touched path takes the original branch. Output bytes identical, query count identical,
   `stream_id` values identical.
2. **No migration.** `git diff` contains no file under any `migrations/`.
3. **Query budget.** The language path adds one cached query (`get_category_metadata`) and converts
   one wide query into one narrow + one wide. No per-row queries, no N+1, no JSON blobs selected.
4. **Ingestion cost.** One dict lookup per relation. No new queries, writes, or passes.
5. **`custom_properties` is merged, never replaced**, on both category relations and item relations.
6. **Unknown stays unknown.** Unassigned categories with no provider metadata behave as today —
   single entry, provider-priority ordered, no suffix.
7. **Playback never hard-fails** because of language filtering (§6.7 fallback).
8. **The anchor never constrains playback** — a title whose anchor is a 720p relation still plays the
   1080p relation in the same language group.

---

## 8. Tests

* `resolve_language` / `resolve_quality` precedence tables, including provider-overrides-category.
* `apply_language_suffix`: appends for known languages; no-op for unknown; no double-tag on titles
  already ending `(EN)` / `[es]`; applied even when the title has only one language group.
* Anchor selection is `min(id)` and is stable when account priority changes or a higher-quality
  relation is added.
* Relation-ID-first resolution with `Movie.id` fallback, including the deliberate collision case
  (a `Movie.id` that also exists as an `M3UMovieRelation.id`).
* `update_group_settings` persists `language`/`quality`, preserves unrelated keys, accepts a batch of
  categories in one PATCH, and rejects a bad language code and a bad quality value.
* `xc_get_vod_streams`: two providers, same movie, different category languages ⇒ two entries with
  distinct stream IDs and suffixed names; same language ⇒ one entry, and **higher quality wins even
  when the lower-quality provider has higher account priority**.
* `xc_get_vod_streams` with no languages configured ⇒ output equal to the pre-change fixture
  (snapshot test — the regression canary).
* `xc_get_series` dedup by `(series, language)`; `series_id` remains a real relation ID; the existing
  `test_series_picks_highest_priority_relation` still passes unmodified.
* `stream_xc_movie` with an anchor ID plays the best-quality relation in that language group; with
  none available, falls back rather than 404s.

---

## 9. Fork & branch setup

`/home/joe/projects/dev/dispatcharr` already has both remotes:
`origin` = `Dispatcharr/Dispatcharr`, `fork` = `northernpowerhouse/Dispatcharr`.

```bash
git fetch origin
git switch -c feature/vod-category-language-quality origin/dev
# ... work ...
git push -u fork feature/vod-category-language-quality
```

Current checkout is `fix/vod-duplicate-batch-relations-1511` (6b81a884); the new branch comes off
`origin/dev`, not off that. **#1511 is already merged to `dev`**, which this design depends on: "a
relation for every category/stream a movie or series appears under in a batch" is what guarantees a
title carried in both an English and a Spanish category has a relation under *each* — the input this
feature groups over, and the reason relation IDs work as per-language handles (§5).

---

## 10. Deferred / follow-up

* **UI** — a category picker supporting multi-select, with language and/or quality applied to the
  selection in one PATCH to the existing group-settings endpoint (§6.3).
* Optional core setting for a global default language for unassigned categories (explicitly *not* in
  v1 — unassigned means unknown).
* Ingest-time quality precompute, only if profiling justifies it.
* Language-aware failover across language groups is out of scope; VOD has no failover today and this
  change does not introduce one beyond the §6.7 safety fallback.

---

## 11. Decisions and open items

### 11.0 Decided — not open for re-litigation

**(a) The one-time client re-scan on first enabling is accepted.** *(northernpowerhouse, 2026-09-13.)*
Movie `stream_id` moves from `Movie.id` to an `M3UMovieRelation.id` the first time a category is
given a language. Clients must re-scan once. This is inherent to giving a title more than one
identity and has no avoidable alternative under any ID scheme, so it is not a trade-off to revisit —
it only needs to be in the changelog and the eventual UI copy, loudly enough that operators expect
it before they flip the switch.

Implications now locked in:

* The stale-client guard in §5.2 (resolve as relation ID first, fall back to `Movie.id` on miss,
  log at debug) is **required**, not optional — it is what stops a client that scanned before the
  switch from silently resolving into the wrong ID namespace.
* Zero-config remains a strict no-op (§7.1). The re-scan is the cost of *enabling* the feature, never
  of upgrading to it. An operator who never assigns a language never re-scans.
* The changelog entry must state plainly: assigning a language to a VOD category for the first time
  changes movie stream IDs and requires a client library refresh.

**(b) Suffix format.** 2-letter ISO 639-1, uppercased, square brackets (`"Inception [ES]"`), appended
to every title with a resolved language, skipped when the title already ends in a bracketed or
parenthesised 2-letter token. *(northernpowerhouse, 2026-09-13.)*

**(c) Nomination rule stays deliberately different per content type.** *(northernpowerhouse,
2026-09-13.)* Movies nominate the **anchor** (`min(id)` in the language group); series keep the
**winner** (quality, then priority). Note the ID *type* is already aligned by this change — both are
`M3U*Relation` IDs — so this is only about which relation in a group is nominated.

*Root cause of the original asymmetry.* It follows from the XC protocol, not from sloppiness. A
movie `stream_id` is a leaf: the client plays it directly and `stream_xc_movie` picks the provider
at play time, so provider choice is deferred and the ID never needed to name one — hence `Movie.id`.
A `series_id` is an interior node that must expand into an episode list, and `M3UEpisodeRelation` is
FK'd to `M3USeriesRelation` (added in 0.19.0 for CASCADE deletion and per-provider scoping of
stale-episode cleanup), so episodes are only enumerable *through* a provider relation. Provider
choice cannot be deferred past the listing, so it is baked into the handle. Episodes then use the
provider's own external `stream_id` — a third convention.

*Why the difference is correct rather than tolerated.* For movies the anchor is purely an
identifier: playback re-ranks the whole language group independently of it, so nominating a stable
relation costs nothing. For series the relation ID **is** the episode source, so the winner is the
only semantically correct nominee. The rule is therefore: **nominate for stability where the ID is
just a name, nominate for quality where the ID is a handle.**

*Rejected alternative:* series adopt the anchor too, gated on the same flag. Looks more consistent
but buys stability at the wrong layer — `xc_get_series_info` would need a new
anchor → group → winner → enumerate step to avoid serving the anchor provider's episode list, and
episode IDs would still move when the winner changed. Consistency at the top, churn one level down.

*Implications now locked in:*

* §6.6 stands as written: for series, only the dedup key changes, to `(series_id, language)`.
  `_xc_fetch_priority_distinct_relations` keeps its existing `-m3u_account__priority, id` ordering
  with `quality_rank` prepended. No anchor logic on the series path, no change to
  `xc_get_series_info`.
* The existing upstream test `test_series_picks_highest_priority_relation` must keep passing
  **unmodified** — it is the guard that this decision was honoured.
* Add a short comment at each nomination site naming the rule above, so the asymmetry reads as
  intentional to the next person in this code rather than as a bug to be "fixed".

### 11.1 Open for SergeantPanda

Nothing blocking. Every design question raised during planning has been decided by the author and
recorded in §11.0. What is wanted from review is a deliberate yes/no on those three, in particular:

1. **§11.0(a)** — the one-time client re-scan when a category is first given a language, and the
   changelog wording that must accompany it.
2. **§11.0(c)** — the deliberate movies-anchor / series-winner asymmetry, which is the one decision
   a reviewer is most likely to read as an oversight rather than a choice.
3. **§11.0(b)** — the user-visible title suffix format.

If all three hold, implementation proceeds against §6 with §7 as the acceptance criteria.

---

## 12. Implementation status (2026-09-13)

Implemented in full against §6, on `feature/vod-category-language-quality` (branched off
`origin/dev`, which includes #1511). Everything below is a deviation from, or an addition beyond,
the literal text of §6 — anything not mentioned here was built exactly as written. `git diff` still
contains no file under any `migrations/` directory (§7.2 holds).

### 12.1 `apps/vod/language.py` (§4)

Built as specified, plus:

* **`match_quality_from_name(name)` split out as its own function**, separate from
  `resolve_quality(name, cat_meta)`. §4 only listed `resolve_quality`; splitting the bare
  name-matching regex out was necessary so `M3UMovieRelationSerializer.get_quality_info` (§6.2) could
  reuse *just* the title-matching step without also pulling in the category-default fallback at that
  point in its precedence chain — `get_quality_info` has its own additional detection steps (video
  resolution, bitrate) interleaved between "title match" and "category default" that `resolve_quality`
  alone can't express.
* **3-letter → 2-letter language code mapping** (`_ISO_639_2_TO_1`). §6.4 says to check
  `detailed_info.audio` for a language, but real provider audio metadata almost always reports ISO
  639-2/B codes (`"eng"`, `"spa"`) rather than the 2-letter codes categories are assigned in. Without
  a mapping table, that source would essentially never produce a usable value. Added a static table
  covering ~35 common languages; anything not in it is treated as no provider language (falls through
  to the category, same as if the field were absent) rather than guessed.
* **`resolve_movie_relation(raw_id, extra_filters, select_related)`** — not in §4's function list.
  Needed once it became clear (see §12.4 below) that the "resolve as relation id, fall back to
  `Movie.id`" logic from §5.2 has two call sites (`stream_xc_movie`, `xc_get_vod_info`), so it was
  pulled out as a shared helper instead of being duplicated.
* **`validate_category_custom_properties(props)`** — not in §4's function list. §6.2 asks for
  validation on the serializer; §6.3 separately requires `update_group_settings` to reject bad input
  with a 400. That view never goes through the serializer (it bulk-writes `M3UVODCategoryRelation`
  directly, same as the pre-existing `ChannelGroupM3UAccount` write path it mirrors), so the validation
  logic was written once here and called from both places.

### 12.2 `apps/vod/serializers.py` (§6.2)

Built as specified. `M3UVODCategoryRelationSerializer` was previously read-only everywhere it's used
(nested in `VODCategorySerializer`); adding write validation to it is forward-looking (matches the
`ChannelGroupM3UAccountSerializer` pattern named in §6.2) but the actual enforcement for the real
write path is in `update_group_settings` (§12.3), since that view doesn't use this serializer.

### 12.3 `apps/m3u/api_views.py` (§6.3)

Built as specified: merge instead of replace, cache invalidation at the end of the action, 400 on bad
`language`/`quality`. One correction made during implementation and review: the first draft validated
the raw request payload but then wrote `ensure_custom_properties_dict(setting.get("custom_properties"))`
(the *unvalidated* raw dict) into the merge — silently dropping the validator's lowercasing of
`language`. Fixed to thread the validator's normalised return value through to the write.

### 12.4 `apps/vod/tasks.py` (§6.4)

Built as specified for `process_movie_batch` / `process_series_batch` / `batch_process_episodes`,
including for series relations — §6.4's prose lists `process_series_batch` alongside the other two,
even though §3.2's schema section only shows the `language` key on `M3UMovieRelation` /
`M3UEpisodeRelation`. Series relations got it too: §6.6's dedup key is `(series_id, language)`, which
needs a `rel_lang` on the series relation to mean anything, so treating §3.2 as incomplete rather than
authoritative here.

**Addition beyond §6.4's file list:** `refresh_movie_advanced_data` (the on-demand detailed-info
refresh, not part of the list-batch ingestion §6.4 describes) also now sets `language` from
`detailed_info.audio` when the list-batch scan didn't already find one. This one wasn't a discretionary
addition — the *only* place a movie relation's `custom_properties` ever gains a `detailed_info` key at
all is this refresh function; `process_movie_batch`'s `movie_data` is the basic list payload and never
contains `detailed_info`. Without this change, §4's documented `detailed_info.audio` source would be
dead code that could never fire.

### 12.5 `apps/output/views.py` (§6.5, §6.6, §6.8)

Built as specified, including the movies-anchor / series-winner asymmetry from §11.0(c). Structural
difference from §6.5's prose: instead of one `_xc_fetch_priority_distinct_relations`-style function
handling both the language-on and language-off cases, language-on gets two new dedicated functions,
`_xc_movie_language_relations` and `_xc_series_language_relations`, and `xc_get_vod_streams` /
`xc_get_series` each branch on `vod_language_enabled()` to pick between old and new. Reason: the
existing function's Postgres `DISTINCT ON` fast path can't dedupe on *resolved* language, because
resolution requires a Python-side category-metadata lookup that isn't expressible as a SQL join
without re-fetching `M3UVODCategoryRelation` per query (defeating the point of the cached lookup in
§4.1). The language-on path is pure Python grouping over the same narrow `.values()` query (§6.5's
"pass 1"), which turned out to work identically on Postgres and the non-Postgres fallback, so there's
no vendor branch in the new functions at all — one less thing to keep in sync with the old function's
Postgres-specific code path.

`xc_get_vod_info` (§6.8 area, technically part of the ID-scheme change in §5.2): switched to
`resolve_movie_relation` (relation-id-first, `Movie.id` fallback) when the feature is on, matching
`stream_xc_movie`. Also changed `movie_data.stream_id` in its response from always `movie.id` to
`movie_relation.id` when the feature is on — not spelled out in §6 text, but required for a client to
get back the same id namespace it requested with. `xc_get_vod_categories` genuinely untouched, as §6.8
said.

### 12.6 `apps/proxy/vod_proxy/views.py` (§6.7) — the largest deviation

§6.7 describes the required behaviour correctly but names the wrong function for where the ID
resolution has to happen. Tracing the actual call graph: `_get_content_and_relation`'s `content_id`
parameter is **always a UUID** — every URL route that reaches it (`/proxy/vod/<type>/<uuid:content_id>/...`)
declares it as `<uuid:content_id>`, and `_find_idle_vod_session`/`_select_vod_stream` only ever call it
with a `Movie.uuid` or `Episode.uuid`. The raw XC integer `stream_id` (what §5.2's "relation id first,
`Movie.id` fallback" guard actually applies to) only exists in `stream_xc_movie` and `xc_get_vod_info` —
two separate entry points that resolve it *before* ever reaching `_get_content_and_relation`, then hand
off a UUID. So the guard was implemented in those two functions (via `resolve_movie_relation`), not in
`_get_content_and_relation` itself, which is unchanged.

That in turn means the resolved language has to be threaded through as data, not resolved a second time
downstream. Implemented by adding an optional `content_language` parameter, threaded
`stream_xc_movie` → `stream_vod` → `_select_vod_stream`, defaulting to a module-level sentinel
(`_LANGUAGE_UNSET`) so every other caller (the direct `/proxy/vod/...` UUID routes, `stream_xc_episode`,
`stream_vod_head`) is provably untouched — `is not _LANGUAGE_UNSET` is the only new branch condition,
and it's `False` unless `stream_xc_movie` explicitly resolved a language.

Also implemented §6.7's candidate ranking as **reorder-only, never filter**: a new
`_order_candidates_by_language` helper sorts the *entire* candidate list by
`(language matches, quality_rank, -priority, id)` rather than restricting to the language group and
falling back to the full set only on an empty result. Same outcome — a non-matching relation is never
excluded, only ranked behind matching ones — but it means the existing capacity-walk loop in
`_select_vod_stream` (try each candidate until one has spare capacity) already *is* the fallback path;
there's no separate "group empty, now fall back" branch to keep in sync with it. One rule not called
out in §6.7: an explicit provider/stream pin via the pre-existing `?m3u_account_id=`/`?stream_id=`
query params (`_parse_preferred_vod_params`) takes priority over language-group ranking — a user who
manually picked a provider shouldn't have that silently overridden by quality ranking.

`stream_vod_head` (the HEAD-request variant, used for content-length probing against an
already-selected session's URL) was deliberately **not** threaded with `content_language` — it's
reached only via the direct UUID route after `stream_xc_movie` already made the real selection on the
initial GET, so it doesn't originate from an XC `stream_id` and has nothing to resolve.

### 12.7 §8 test list — one bullet reinterpreted

§8's `xc_get_vod_streams` bullet says "same language ⇒ one entry, and higher quality wins even when
the lower-quality provider has higher account priority." Taken literally for movies, this contradicts
§5.1/§11.0(c)'s explicit, decided anchor rule (`min(id)`, independent of quality). Implemented as: this
statement is true for **series** (winner nomination, tested directly — see
`test_higher_quality_wins_over_higher_priority_within_same_language`), and for movies it's true only of
*playback selection* (§6.7), not the list `stream_id`. Tests assert the anchor is quality-independent
for movies (`test_same_language_group_collapses_to_anchor_min_id`,
`test_anchor_is_stable_when_a_higher_quality_relation_is_added`) and quality-dependent for series.

### 12.8 Test coverage added (§8)

Nine new test files across `apps/vod/tests/`, `apps/m3u/tests/`, `apps/output/tests/`, and
`apps/proxy/vod_proxy/tests/`, covering every §8 bullet including the two most specific ones: anchor
stability when a higher-quality relation joins the group, and the deliberate `Movie.id` /
`M3UMovieRelation.id` collision case. **Not yet run** — this environment has no local Django/Postgres
install and the only reachable `dispatcharr` container is the separate production deployment (not this
checkout), so verification was limited to `py_compile` and manual code review. Run
`python manage.py test apps.vod apps.m3u apps.output apps.proxy.vod_proxy` before merging.

### 12.9 Not implemented

Everything in §10 (Deferred / follow-up) remains deferred, as planned: no UI, no global-default-language
core setting, no ingest-time quality precompute, no language-aware failover beyond the §6.7 fallback.
