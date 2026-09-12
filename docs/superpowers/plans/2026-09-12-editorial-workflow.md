# Editorial Workflow Implementation Plan

> Execute in the current session using focused agents with disjoint file ownership, then integration review.

**Goal:** Implement the approved traceable crawler and operational curation workflow in local services.
**Architecture:** Additive SQLite provenance/review records; common selection policy and stable publication identity; existing server/static pages.
**Tech Stack:** Python, SQLite/aiosqlite, FastAPI, browser JavaScript; tests use unittest/pytest with temporary data.

- [x] Capture running-code baseline in isolated worktree and preserve dirty live changes.
- [x] Crawler: fixture with >5 images and missing alt catches misalignment; detail-link priority and website asset tests; implement own-image provenance and persistence.
- [x] Graph: small graph asserts changing north_star→concept changes score; source URL resolves existing source nodes; fix graph reads and caller integration.
- [x] Feedback: temporary DB/files import a manual pack; repeated observations retain one event, under-review zero cannot change weights; make bridge failures observable and use canonical IDs.
- [x] Editorial: test date evidence/unknowns, asset exclusions, dedupe and fact-vs-decision scopes, review requirements; implement store/API/editorial review page.
- [x] Candidate integration: test no cross-pack repeats, keep original image bytes, candidate status explicit, approved reviews exported and registered. Use actual stored evidence instead of a decorative shared-keyword rationale.
- [x] Review all module changes against scope, run full isolated regression suite and inspect new batch; resolve every introduced failure.
- [x] Back up database and changed runtime files; deploy only approved changed files and required dependencies; restart known services with canonical data paths.
- [x] Verify live UI/API, run a bounded crawler smoke request and candidate generation, import existing annotations and Rams identity idempotently; keep real platform observations unchanged.
- [x] Save verification evidence, implementation docs and recoverable Hub summary.
