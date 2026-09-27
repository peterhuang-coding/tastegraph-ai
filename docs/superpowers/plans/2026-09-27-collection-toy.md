# Toy Collection Implementation Plan

> Execution: bounded cc-plan packages in isolated staging, primary integrates and verifies.

**Goal:** Deliver a single-toy archive and editable export with trustworthy evidence and correction protection.
**Architecture:** Existing FastAPI/static UI; private assets and versioned object documents in isolated SQLite tables; explicit research adapter.
**Tech Stack:** Python, SQLite, Pillow, FastAPI, vanilla JS/CSS; no new framework.

## Wave 1 (parallel, non-overlapping)
- [x] Backend package: services/collections.py, api/routes/collections.py, tests/test_collections.py, tests/test_collections_api.py. Implement frozen design contract; write meaningful behavior tests first and retain observed red/green evidence. No model/network calls.
- [x] Frontend package: static/collections.html, static/js/collections.js, static/css/collections.css. Use frozen contract, safe DOM rendering, preserve edits, private defaults, real empty/error states. Validate with browser behaviors and JS syntax; generated regex-based source tests were not adopted.
- [x] Primary: inspect both results and logs, verify original inputs unchanged, integrate only declared files; router/index wiring and isolated preview.

## Wave 2 (after both verified)
- [x] Add bounded configured identification/research execution if supported dependencies and budget permit; explicit permissions; no fake source evidence or progress. Separate model propositions from confirmed claims. Test cancellation and stale results with a deterministic adapter; record live capability gaps.
- [x] Browser E2E single synthetic toy: create, upload public/private images, evidence, draft, edit, export, reload and negative cases.

## Delivery
- [ ] Run related regression suites, diff checks and public-data boundary review. Commit/push task branch; do not merge or deploy.
- [ ] Notion C1待验收 and unchecked; Hub evidence and exact remaining real-item validation; the fixed approved session budget.

## Scope delivered for owner acceptance
This slice implements archive/edit/export plus local OCR and encyclopedia background lookup. It does not implement multimodal toy identity matching, version authentication, autonomous primary-source deep research, generated narrative alternatives or a real-owner time-savings study. The first real object is still required. Model-generated implementation and review outputs are treated as unverified until tests/browser checks; the core public documentation contains no private collection data.
