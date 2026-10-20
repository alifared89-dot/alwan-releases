# Alwan compatibility data contract

This directory is production data consumed directly by installed Alwan apps.

## Mandatory workflow for every human, bot, or AI agent

1. Read this file before editing compatibility data.
2. Edit payload data only. Do not invent hashes, byte counts, versions, or catalog dependency metadata.
3. Internal maintainer only: use the verified `tools/compatibility/rebuild_release.py` from the **PRIVATE** `alifared89-dot/alwan-bot-control` repository against a disposable working copy of this public compatibility directory. Example from the private checkout after cloning the public releases into `public-release/`: `python tools/compatibility/rebuild_release.py --root public-release/compatibility`. Never run a rebuild against a live client or published `main`; stage only reviewed payload and manifest changes through a new PR.
   The builder generates a **local, ignored** `build_report.json` in the working compatibility directory; never publish it or add it to a commit.
4. From the public release working copy, run the independent **PUBLIC PRODUCTION GUARD**: `python .github/release-guards/validate_release.py --root compatibility --report /tmp/compatibility-validation-report.json`. The protected GitHub Actions job runs this validation and additional immutable-baseline record-preservation checks on every PR.
5. Work through a branch and pull request. Require both Compatibility Data Contract and Infinix Media Integrity to pass before merging. The media integrity check is brand-neutral for new image/model IDs.
6. Never weaken or bypass the validator merely to make a dataset publish.

The validator mirrors the production app's fail-closed contract: catalog/category schema, hashes and byte sizes, catalog dependency, IDs, references, evidence-to-part identifiers, evidence-to-model codes, facts, and differences.

Every rejection is actionable. Errors use stable codes such as ALWAN-DATA-EVIDENCE-PART, ALWAN-DATA-EVIDENCE-MODEL, ALWAN-DATA-HASH, and ALWAN-DATA-CATALOG-VERSION. The workflow also uploads compatibility-validation-report.json so an automated conversation can read the exact reason and repair the data instead of guessing.

Deletion of existing published device, brand, part, group, evidence, fact or difference identities is forbidden. Corrections to existing records are allowed in place and new records can be appended. The Compatibility Data Contract runs an additional baseline-preservation guard before any merge. A future schema change requires a deliberate coordinated app+validator change; never silently bypass the production reader contract.
