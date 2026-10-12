# Alwan compatibility data contract

This directory is production data consumed directly by installed Alwan apps.

## Mandatory workflow for every human, bot, or AI agent

1. Read this file before editing compatibility data.
2. Edit payload data only. Do not invent hashes, byte counts, versions, or catalog dependency metadata.
3. Run: python tools/compatibility/rebuild_release.py --root compatibility
4. Run: python tools/compatibility/validate_release.py --root compatibility --report compatibility-validation-report.json
5. Work through a branch and pull request. Require both Compatibility Data Contract and Infinix Media Integrity to pass before merging. The media integrity check is brand-neutral for new image/model IDs.
6. Never weaken or bypass the validator merely to make a dataset publish.

The validator mirrors the production app's fail-closed contract: catalog/category schema, hashes and byte sizes, catalog dependency, IDs, references, evidence-to-part identifiers, evidence-to-model codes, facts, and differences.

Every rejection is actionable. Errors use stable codes such as ALWAN-DATA-EVIDENCE-PART, ALWAN-DATA-EVIDENCE-MODEL, ALWAN-DATA-HASH, and ALWAN-DATA-CATALOG-VERSION. The workflow also uploads compatibility-validation-report.json so an automated conversation can read the exact reason and repair the data instead of guessing.

Deletion of existing published device, brand, part, group, evidence, fact or difference identities is forbidden. Corrections to existing records are allowed in place and new records can be appended. The Compatibility Data Contract runs an additional baseline-preservation guard before any merge. A future schema change requires a deliberate coordinated app+validator change; never silently bypass the production reader contract.
