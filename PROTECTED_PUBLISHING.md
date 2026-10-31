# Alwan production publishing gate (data + device media)

> **Operating-location update (2026-10-31):** The Mac is now the only active research, original-image and SQLite workstation. Phone/Termux collection statements below are historical; do not execute phone research bots. The installed phone app, its data, activation, backups, and credentials are untouched. Existing mandatory human/source reviews, public PR gates and integrity checks remain unchanged. Private authoritative policy: `alwan-bot-control/MAC_PRIMARY_OPERATING_POLICY_20261031.md` (approved and merged in private PR #47). No production behavior is changed by this documentation update.


Applies to every brand and every future phone model. The mobile app consumes **only main-branch production files**; PR branches do not reach installed devices.

## Permanent safety contract

1. Never directly push compatibility data or device media to main, including from an image bot or AI conversation. Use a branch + Pull Request (PR).
2. Never delete previously published raw data files, ZIP archives, device IDs, brand IDs or parts/compatibility/evidence/fact IDs. Correct information in place and append missing records. Broken ZIP references may be intentionally migrated, but historical ZIP files and all device-image records must remain available.
3. Production release metadata is generated and verified; do not fabricate SHA-256, byte lengths, URLs, dependency IDs or update version tokens.
4. All proposed PRs must pass **both** `Compatibility Data Contract / compatibility-contract` and `Infinix Media Integrity / media-integrity`. Despite its historical name, the image integrity check validates new model links for all brands.
5. Validation failures block the merge and report named `ALWAN-DATA-*` or `ALWAN-MEDIA-*` reasons. Fix only the affected data without bypassing tests.
6. Data collection/review can run independently from publishing and is not blocked by this gate. Published image rights, hardware-code identity and part fit still require human/source assessment.

## Independent release integrity vs. optional legacy research tests (20 Oct 2026)

- The **required** `compatibility-contract` and `media-integrity` jobs run brand-neutral validators and their complete **42-case production regression suite** from `.github/release-guards/`. Those scripts were byte-verified against the previous production validators in [PR #36](https://github.com/alifared89-dot/alwan-releases/pull/36), and tested against the unchanged live data/ZIPs before cutover.
- The historical **89-case bot regression suite plus exact compositor/pixel-preservation tests** now run on PRIVATE `alwan-bot-control/.github/workflows/private_bot_regressions.yml`, triggered on every PRIVATE PR and main push, with **read-only** checkout of public media/compatibility fixtures. PUBLIC `legacy_bot_regressions.yml` and `infinix_bot_crop_ci.yml` are retired after full private CI parity. Three media-guard regression tests remain in `.github/release-guards/`, with old duplicated `tools/**/test_*.py` copies retired after matching PRIVATE and independent public Git blob SHA. Production validation still runs in PUBLIC required checks.
- All 10 historical PUBLIC manual publisher source/config assets and `infinix_device_images.yml` were retired as ONE complete, original-Git-SHA-pinned batch. PRIVATE keeps exact source copies and research tests. The LIVE bot and SQLite/original photos remain on the PHONE; PRIVATE GitHub offers read-only manual discovery, while reviewed media PR staging uses the Mac. The required PUBLIC CI still runs its independent 42-case suite with unchanged client files. Published client artifacts and distribution bytes were not changed by source cleanup.
- Changing required validator code or its tests is a **separate release-security change**, subject to all two mandatory checks, baseline comparison, destructive-fixture regressions, and approval. Never load privileged private source into public PR jobs.

## Image publication: private review, public protected PR

The historical PUBLIC image bot/Actions source was removed. It is **not** required by installed applications: clients fetch only `latest.json`, `compatibility/**`, `device-media/**`, `brand-media/**` and approved downloads.

1. **PHONE / Termux** remains the source of collection, original photos, local SQLite and model-code evidence. Do not overwrite, reset or restart its research automatically.
2. **PRIVATE `alwan-bot-control`** owns the research bot source and optional manual GitHub Actions discovery (`.github/workflows/private_image_discovery.yml`) with `contents: read`. Human review of correct code, market, front/back, colors and redistribution rights happens privately; official shop imagery **does not by itself grant reuse rights**.
3. **Trusted Mac** stages reviewed photos using PRIVATE `maintenance.stage_reviewed_media_pr`, which requires actual original/output byte SHA-256 matches, catalog/model identity, true PNG geometry, an explicit human-rights evidence packet and a manual `--submit --confirm STAGE_PROTECTED_REVIEW_PR_ONLY`. Default mode is a local, disposable dry run that does **not** open a PR. Missing or fake evidence must never be used for actual publishing.
4. A legitimate reviewed batch can create only a NEW `media/human-reviewed-private-...` branch and PUBLIC Pull Request. It cannot push `main`, cannot overwrite existing media, cannot self-approve and cannot auto-merge. Both mandatory compatibility/media jobs run on the PR; after **human** review, merging updates clients.
5. The current phone research originals are **NOT licensed/approved for publication** merely because the bot verified SHA, source URLs or model codes. Do not use synthetic test evidence in real publication. Keep unpublished material PRIVATE.

No PRIVATE bot token or runner secret may be exposed to PUBLIC CI. Do not reintroduce `tools/**` or the old `infinix_device_images.yml` in PUBLIC. Prior public source remains in old Git commits: no history rewrite.

## One-time repository owner configuration

Repository: `alifared89-dot/alwan-releases`.

For the PUBLIC repository, keep all standard GitHub Actions permissions at `contents: read` where possible. There is **no longer a PUBLIC research/publishing workflow** requesting write or Actions-dispatch permissions. Manual reviewed PR staging runs on the authenticated **owner's Mac**, not inside PUBLIC CI. Never commit or print tokens.

Settings → Rules → Rulesets → New branch ruleset (or Settings → Branches → Add branch protection rule). Target **main** only:

- Require a pull request before merging.
- Require status checks to pass before merging, with these **exact job contexts**:
  - `compatibility-contract`
  - `media-integrity`
- Disallow force pushes and branch deletion.
- Do not add an exemption/bypass for the publishing bot.
- Prefer requiring branches to be up to date before merging if your normal workflow can accommodate rebases.

Both required CI jobs run on **every** PUBLIC PR, including documentation-only changes. The full **89 historical bot tests and image crop tests run PRIVATE**, while independent PUBLIC media/compatibility contract tests remain in `.github/release-guards/`. The public scope guard prohibits reintroducing retired bot source or mixing this one-time cutover with application-facing data changes.

## Operator checklist (after a PR is merged)

- Check main's two CI job results and published manifests.
- Confirm there are no record/file deletions and that manifest versions increase when content changes.
- Test an existing handset and a newly activated handset. Data will not arrive before merge, and media not yet collected/published will remain absent.
- Do not change APK, licensing, schema or existing production data to work around the gate.

This design does not claim that automated CI can independently establish legal image reuse rights or physically validate spare-part compatibility.
