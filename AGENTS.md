# Alwan release repository agent rules

Before modifying compatibility/**, read compatibility/CONTRACT.md.
Before modifying device-media/**, read tools/infinix-image-bot/README.md and the media integrity guard/workflow.

Do not push unvalidated production data. Prefer a branch plus pull request.
Do not weaken validators or integrity guards merely to make a change pass.
When a gate fails, report the exact policy/error code and repair the underlying data.

Compatibility data and device media are independently updatable production channels. APK/application releases are separate.
