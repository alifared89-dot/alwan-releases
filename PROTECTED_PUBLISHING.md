# Alwan production publishing gate (data + device media)

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
- The historical **89-case bot regression suite plus exact compositor/pixel-preservation tests** now run on PRIVATE `alwan-bot-control/.github/workflows/private_bot_regressions.yml`, triggered on every PRIVATE PR and main push, with **read-only** checkout of public media/compatibility fixtures. PUBLIC `legacy_bot_regressions.yml` and `infinix_bot_crop_ci.yml` are retired after full private CI parity. Three public release-guard regression files remain public and byte-identical; production validation still runs in PUBLIC required checks.
- The existing `infinix_device_images.yml` discovery and manually confirmed media staging workflow **still uses the old bot**. It may fail if that old bot fails and is **not** yet migrated to phone/Termux. Eleven unused research modules were byte-verified in PRIVATE and retired without changing this manual publisher. Do not delete **any remaining publisher dependencies** or disable human review until an independently tested PRIVATE replacement is ready.
- Changing required validator code or its tests is a **separate release-security change**, subject to all two mandatory checks, baseline comparison, destructive-fixture regressions, and approval. Never load privileged private source into public PR jobs.

## Bot publication

The existing `Infinix Device Images` workflow still supports `discover` and `publish`, including explicit human approval. `publish` now:

1. Reads the exact production main media state.
2. Verifies staged new media against the old state and device catalog.
3. Creates a uniquely named `media/reviewed-infinix-<run>-<attempt>` branch and pushes **only** there.
4. Opens a PR targeting main.
5. Explicitly triggers the two validation workflows using `workflow_dispatch` on that branch. This step matters: PRs created with `GITHUB_TOKEN` do not automatically trigger `pull_request` workflows.
6. Leaves the PR unmerged for review. Only a successful merge publishes to phones. Never uses `git push HEAD:main`.

If GitHub disallows Actions-created PRs, it prints `ALWAN-PUBLISH-PR-DENIED` and a link to open a PR from the safely pushed branch. Do not disable either validator to work around this.

## One-time repository owner configuration

Repository: `alifared89-dot/alwan-releases`.

**First:** Settings → Actions → General → Workflow permissions:

- Keep permissions for normal workflows as restricted as practical (the publishing workflow explicitly requests contents:write, pull-requests:write and actions:write).
- Enable **Allow GitHub Actions to create and approve pull requests** if the option is available and disabled. It is required for automated PR creation using `GITHUB_TOKEN`. Bot-made PRs are not automatically approved by this change.

**Then:** Settings → Rules → Rulesets → New branch ruleset (or Settings → Branches → Add branch protection rule). Target **main** only:

- Require a pull request before merging.
- Require status checks to pass before merging, with these **exact job contexts**:
  - `compatibility-contract`
  - `media-integrity`
- Disallow force pushes and branch deletion.
- Do not add an exemption/bypass for the publishing bot.
- Prefer requiring branches to be up to date before merging if your normal workflow can accommodate rebases.

Both required CI jobs run on **every** PUBLIC PR, even documentation-only changes, and support explicit dispatch on bot-created branches. **All 89 legacy bot tests and image crop regressions run privately**, while the PUBLIC release validators still execute independent media/compatibility contract tests. Public legacy bot code and manual publisher remain temporarily, but their source is frozen against modification by the mandatory release scope guard.

## Operator checklist (after a PR is merged)

- Check main's two CI job results and published manifests.
- Confirm there are no record/file deletions and that manifest versions increase when content changes.
- Test an existing handset and a newly activated handset. Data will not arrive before merge, and media not yet collected/published will remain absent.
- Do not change APK, licensing, schema or existing production data to work around the gate.

This design does not claim that automated CI can independently establish legal image reuse rights or physically validate spare-part compatibility.
