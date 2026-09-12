# Editorial crawler and workflow update

Scope: Update the existing crawler and editorial workflow while preserving uncommitted work and historical publication records. No new platform posts are part of this implementation.

Goal: Replace context-poor, repetitive auto packs with traceable candidate research plus explicit editorial decisions; connect publication observations without falsely learning user taste.

Architecture: SQLite remains authoritative. Add provenance and editorial annotation/review tables without rewriting historical dates or raw images. Crawling preserves each image's own text, prioritizes linked detail pages and filters obvious site assets. Candidate generation consumes operational decisions, deduplicates across outputs, preserves composition, and produces drafts requiring an explicit thesis/role/reason review. Existing UI gets an operational tagging/review entry. Stable pack identity is used for filesystem and DB publication records. Metrics remain time-stamped observations separate from taste feedback.

Workstreams:
1. Crawler provenance: per-image alt/caption/context, entry/detail-page classification and discovery priority, no inferred image age, source ID resolution, intake website-asset rejection, existing backlog enrichment on next fetch. Tests with fixture HTML plus isolated SQLite.
2. Graph scoring: matching concept preference weights must change score; accept source URL identity without inventing nodes; no actual graph mutation during tests. Test positive/negative effects and source aliases.
3. Publication feedback: stable pack IDs and file import; preserve submitted-under-review status; append idempotent metrics observations; do not automatically convert distribution into taste. Surface bridge failures; duplicate submissions/snapshots must not reapply graph changes.
4. Editorial workflow: six operational groups, facts with evidence and editorial author/scope; pack-specific roles and decisions, candidate/global exclusions separated; dedupe per run and preserve original pixels; candidate drafts become approved only with explicit thesis plus per-image evidence/role and sequence rationale; frontend review and tagging usable locally. Import prior review examples as assistant annotations, retain unknown dates. Regenerate a distinct new draft batch and verify live endpoints after deployment.

Validation: meaningful failing tests before behavior changes; isolated temporary DB and graph; no external posting or paid AI calls in tests. Run complete introduced suite, syntax checks, sample DB rehearsal, then back up live DB/files, deploy only changed paths relative to recorded baseline, restart only known target services when needed, read back annotations and publication records. Verify historical publication registry remains one entry and new packs don't reuse it. Do not report deployment based solely on file existence.

No invented old-photo quota; sources should be evaluated by provenance and editorial usability. Media and product images remain eligible for a concrete topic; true website assets are excluded. No blanket retagging by uncertain existing keywords.
