# Device Media

Remote device-media distribution for Alwan.

- distribution.json: stable entry point used by the app.
- device_media_manifest.json: validated runtime media manifest.
- chunks/: immutable ZIP payloads referenced by the distribution manifest.

No test/seed device images are published. Production media must pass the project quality, provenance, model-code, and license checks before publication.
