# 0007 — Two narrow source contracts with declared limits

**Status:** Accepted, 2026-09-28 · **Amended by:** [0021](0021-contract-field-additions.md) · **Ticket:** [#20](https://github.com/Ian-Costa18/AviAnki/issues/20)

Q1–Q5 were decided with the user on 2026-08-25. Q6 (statelessness) was decided afterwards on the recommendation made in that session.

## Decision

### Two contracts (Q1)

Anything with **a choice to make** is an asset: many candidates, one winner, pinnable, carrying its own licence. A species list has no candidates. So there are two interfaces.

```python
class SpeciesSource(ABC):
    name: str
    republishable: bool
    def regions(self) -> list[Region]: ...                       # GADM level-1, see 0008
    def species_for(self, region: RegionId) -> list[SpeciesRecord]: ...
        # species id, sci name, common name, frequency rank, 12 monthly values

class AssetSource(ABC):
    name: str
    supplies: frozenset[AssetKind]        # {PHOTO, AUDIO, DESCRIPTION}
    republishable: bool
    limits: Limits                        # declared, not enforced here (Q6)
    def candidates(self, species: list[SpeciesId], kind: AssetKind, limit: int) -> dict[SpeciesId, list[Candidate]]: ...
    def fetch(self, candidate: Candidate) -> FetchedAsset: ...    # bytes + final licence record
    def resolve_pin(self, token: str) -> Candidate: ...           # opaque, source-native token
```

### Three verbs (Q2)

`candidates` returns metadata only. `fetch` returns bytes. `resolve_pin` exists because an iNaturalist photo pin is `(observation_id, photo_id)`: there is no `/v1/photos/{id}` endpoint, so only the source knows how to turn its own token back into a candidate.

These stay **outside** the interface and are owned by the pipeline:

- the licence allowlist
- cross-source ordering
- measured filters
- verification
- normalisation and transcoding
- the pin file
- throttling and caching

`candidates` takes a *list* of species, so a source can batch requests (Commons accepts `|`-joined titles) inside a single metered call.

`Candidate` and `FetchedAsset` carry exactly the per-asset record from the licence research §5.1 and nothing source-specific:

- `source`, `source_asset_id`, `source_url`, `file_url`
- `licence_id` (exact and versioned), `licence_url`
- `creator`, `creator_url`, `attribution_text`, `title`
- `copyright_notice`, `modifications[]`, `prior_modifications`, `restrictions`
- `retrieved_at`, `source_terms_version`

### Combining sources (Q3)

- **Ordered fill.** For each role, walk the sources in their configured order ([0005](0005-media-sources.md)) and stop once you have N accepted assets.
- **The order is freest first.** Keyless and cheap sources come before keyed or throttled ones. Licence strictness is an asset-level tiebreak that ranks *below* identifiability.
- **Absence is not failure.** A source returns an empty list when it has nothing. It **raises** on errors such as timeouts, 429s or 5xx responses. The pipeline moves on from absence and fails the species loudly on errors, keeping that species' previous catalog entry ([0014](0014-catalog-rebuilds.md)).

### Species and region identity (Q4, Q5)

See [0008](0008-species-and-region-identity.md).

### Sources are pure (Q6)

Sources don't touch disk, clocks or sleeps. Each declares:

```python
@dataclass(frozen=True)
class Limits:
    requests_per_second: float
    max_concurrency: int          # Wikimedia: 1 (serial)
    daily_request_budget: int | None   # iNaturalist: 10_000
    needs_secret: str | None      # env var name; checked at startup
```

The pipeline's `core.http` client wraps every call with throttling, retry that honours `Retry-After`, a daily budget, an on-disk cache keyed by `(source, request)`, and one User-Agent: `AviAnki-catalog/<version> (https://github.com/Ian-Costa18/AviAnki)`.

**The daily budget is the deciding reason** for this design. iNaturalist's 10,000 requests a day spans the whole build, so only a central choke point can enforce it.

### Republishable gates the catalog

A source with `republishable = False` (eBird) can't be registered for catalog builds at all. The per-asset licence allowlist is a separate, second gate.

## Consequences

- Adding a source means one folder under `sources/` and an entry in the per-role order list.
- `Candidate` is the type most at risk of growing. It's held to the §5.1 field list, and any new field needs an ADR.
