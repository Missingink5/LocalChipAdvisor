# Review and Audit Semantic Contract

Status: S02 validated domain contract; persistence and qualification integration are deferred to S05.

This document defines required semantics before any review or audit
database tables are designed. It is not a SQL schema.

## 1. Existing behavior that must be preserved

The current catalog model has a binary evidence-level state:

- `EvidenceRef.reviewed`

The current publication gate permits a draft product to become a
PUBLISHED product only when the required product fields are present
and their bound evidence satisfies the existing publication checks.

For evidence used by a publication field, the gate currently requires:

- the evidence object exists
- the evidence belongs to the same product
- the evidence belongs to the same knowledge-base version
- `reviewed` is true
- the evidence field matches the product field
- the evidence uses a decisive limit kind

The published SQLite store independently requires:

- the product is already PUBLISHED
- all evidence IDs bound by the product are supplied
- supplied evidence is reviewed
- supplied evidence belongs to the same product
- supplied evidence belongs to the same knowledge-base version

These checks remain safety gates. A future audit trail must not weaken
or silently bypass them.

## 2. Existing information that is not sufficient provenance

The following facts are not, by themselves, an auditable human review
record:

- `EvidenceRef.reviewed = true`
- `publication_status = PUBLISHED`
- successful passage through the publication gate
- presence of an evidence ID in `evidence_ids_by_field`
- presence of an evidence row in the published SQLite catalog

Those facts describe current state. They do not prove who made the
review decision, when it was made, what conclusion was reached, or
what basis supported that decision.

## 3. Required semantic content of a review record

Every persisted human review decision must identify, at minimum:

### Review subject

The record must unambiguously identify the reviewed object.

The identity must include enough version context that a decision for
one version cannot silently qualify a different version.

The contract must support distinct review subject categories rather
than treating every review as the same operation.

Initial semantic categories include:

- document review
- parameter or evidence review

Additional categories may be introduced only when their qualification
meaning is defined explicitly.

### Review conclusion

A review record must contain an explicit conclusion.

A missing conclusion must never be interpreted as approval.

The conclusion semantics must distinguish at least:

- accepted or approved for the stated review scope
- rejected
- not yet decided or otherwise not qualified

Exact enum names are intentionally deferred until the domain model is
implemented.

### Review basis

A review decision must record the basis used by the human reviewer.

The basis must be specific enough to audit the decision later.

Depending on the reviewed object, this may include references to:

- source document identity and version
- evidence IDs
- page or section locators
- parameter applicability conditions
- other review records that are explicitly relevant

A free-standing boolean approval with no basis is insufficient.

### Operator

A human review decision must identify the operator who submitted the
decision.

The system must not manufacture an operator for historical records.

### Recorded time

A persisted review decision must have a recorded time.

The time records when that decision was persisted. It must not be used
to fabricate an unknown historical approval time.

## 4. Review scopes are not interchangeable

Document review and parameter or evidence review have different
qualification meaning.

Document review may establish that:

- source identity is correct
- source version is correct
- product-to-document correspondence is correct
- parsing or page quality is acceptable for cited use

Document review must not automatically mark all extracted parameters
as reviewed.

Parameter or evidence review may establish that a specific technical
claim has been checked for:

- numeric or categorical value
- limit or rating meaning
- applicability conditions
- source support

Review of one parameter or evidence object must not automatically
qualify unrelated document chunks or unrelated parameters.

## 5. Publication provenance

A publication audit record must be able to answer:

- which product and knowledge-base version was published
- which qualifying review decisions supported publication
- who performed or authorized the publication action
- when the publication action was recorded

Publication provenance is separate from the current product state.

`publication_status = PUBLISHED` must not be treated as a substitute
for the publication audit record.

## 6. History and supersession

Review and publication history must be retained.

A later decision must not silently overwrite the historical decision
that preceded it.

When a source version, reviewed object version, or review decision
changes, the system must preserve enough history to determine:

- what was previously approved
- what superseded or invalidated it
- which version is currently eligible

The precise persistence mechanism is deferred to the database design.

## 7. Revocation and invalidation semantics

A review system must support loss of qualification.

Examples include:

- source document version changes
- evidence content changes
- applicability conditions change
- a reviewer revokes or rejects a previous decision

Invalidation must not erase history.

Any retrieval index, cache, publication eligibility, or other derived
qualification that depends on an invalidated review must not continue
to treat the old decision as current.

## 8. Current MP4570 provenance constraint

No new review or audit implementation may fabricate historical facts
for the existing MP4570 published catalog.

Current observations show technical consistency between the stored
draft evidence and published evidence, but the repository does not
currently prove the historical human approval event.

Therefore, until explicit provenance evidence is supplied:

- do not change source metadata to `human_reviewed=true`
- do not invent a reviewer
- do not invent a review time
- do not invent an approval basis
- do not invent a publication authorization record
- do not automatically revert the existing published catalog

The unresolved state remains a provenance gap.

## 9. Separation from requirement review

`RequirementReview` is part of interactive user requirement parsing
and confirmation.

It is not a knowledge review record and must not be reused as the
human-review provenance model.

## 10. Deferred implementation decisions

This contract intentionally does not yet define:

- SQLite table names
- SQL column names
- SQL data types
- primary keys
- foreign keys
- schema migration version for review tables
- CLI command syntax

Those decisions must follow this semantic contract rather than define
the semantics implicitly.


## 11. S02 executable domain decisions (2026-09-06)

`domain/review.py::ReviewRecord` is an immutable, validated decision value.
Required fields are `review_id`, `object_type`, `object_id`, `object_version`,
`conclusion`, `basis`, `operator`, and timezone-aware `recorded_at`.
`supersedes` optionally identifies an earlier decision; self-reference is rejected.
Empty/whitespace identity, version, basis and operator values are rejected.
No timestamp, reviewer or approval is automatically supplied.

- `object_type`: `document` or `evidence`; these scopes are not interchangeable.
- `conclusion`: `approved`, `rejected`, `pending`, or `revoked`.
- `object_version`: evidence uses its exact knowledge-base version; document
  identity/version must bind to the registered content hash, not just a filename.
- `review_id`: an explicit unique event identifier. The future repository must
  reject reuse with changed content; this value object alone cannot prove uniqueness.
- `recorded_at`: the time the event is recorded, not an invented historical approval
  time. Aware non-UTC inputs are valid; persistence serializes the same instant in UTC.
- A later event uses a new review ID and preserves the earlier immutable event.
  The repository must verify supersession targets exist and identify the same subject
  and version, and reject conflicting concurrent successors rather than guess.

Constructing a ReviewRecord does not authenticate a human, persist a decision,
change `EvidenceRef.reviewed`, publish a product, or resolve legacy provenance.
A nonempty basis is only a structural requirement, not proof that its content is true.

## 12. S05 persistence and cross-store acceptance handoff

S02 does not create knowledge tables ahead of S05. The following design is required
when `knowledge/repository.py` and `review_knowledge.py` are implemented:

1. Store append-only review events keyed by review_id; link supersession explicitly.
   Corrections and revocations append events; no UPDATE/DELETE of prior decisions.
2. Resolve document/evidence subjects against authoritative registries with exact
   versions/content hashes; nonexistent subject, missing source, mismatched version,
   and dangling supersession are errors and roll back the transaction.
3. Catalog evidence links use `(catalog_snapshot_id, knowledge_base_version,
   evidence_id)` and registered document/chunk/span IDs, never an evidence ID alone.
   Verify snapshot hash, product association and span/source version before activation.
4. Publication audit records bind product ID + KB version to explicit review IDs,
   an operator and aware recorded time; they never derive approval from PUBLISHED alone.
5. Document approval cannot grant parameter approval. Rejected/pending/revoked events
   cannot grant qualification. A change in content/version requires new review.
6. Invalidation preserves history and prevents dependent new snapshots/caches from
   treating revoked evidence as eligible. S17 implements activation/cache lifecycle.
7. `review_knowledge.py inspect --knowledge-db ... --object-id ...` is read-only.
   Creation, help, subject-type/version options and error tests must exist before
   issuing a real command. Submission requires explicit operator, conclusion and basis;
   no approve-all default. This CLI is NOT implemented by S02.

S05 acceptance cases: missing source; wrong KB version; wrong product; nonexistent
chunk/span; changed snapshot hash; duplicate event with different content; dangling
supersession; document-only approval used as parameter approval; rejection/revocation;
transaction failure preserving all previous history. These are future integration
acceptance cases, not claims of passing S02 persistence tests.

## 13. Legacy MP4570 disposition

The historical approval remains unverified. Technical S02 completion does not close
B06 as an approved historical publication. Preserve current live catalog/source/draft
states and request actual human provenance separately. Formal qualification expansion
is held pending that evidence; public document development may continue per S02.
