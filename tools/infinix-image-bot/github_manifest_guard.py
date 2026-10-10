#!/usr/bin/env python3
"""Read-only GitHub API distribution guard for Alwan Infinix staging.

Refuses to treat local repository metadata as current when upstream changed.
Queries only exact whitelisted public repository and manifest endpoint, with
a strict content size limit. No auth, push, write, or modification on GitHub.
"""
from __future__ import annotations
import base64
import json
import urllib.request
import urllib.parse

import bot

OWNER_REPO = "alifared89-dot/alwan-releases"
PATH = "device-media/device_media_manifest.json"
API = f"https://api.github.com/repos/{OWNER_REPO}/contents/{PATH}?ref=main"
MAX_REPLY_BYTES = 250_000


def check_remote_manifest() -> dict:
    request=urllib.request.Request(API,headers={
        "Accept":"application/vnd.github+json",
        "User-Agent":"Alwan-Infinix-Media-Bot/1.0"})
    with urllib.request.urlopen(request,timeout=15) as resp:
        if resp.status != 200:
            raise RuntimeError("GitHub API returned non-200")
        final=urllib.parse.urlsplit(resp.geturl())
        if final.scheme!="https" or final.hostname!="api.github.com":
            raise RuntimeError("GitHub API URL redirected outside api.github.com")
        raw=resp.read(MAX_REPLY_BYTES+1)
    if len(raw)>MAX_REPLY_BYTES:
        raise ValueError("oversized manifest API response")
    body=json.loads(raw)
    if body.get("type")!="file" or body.get("path")!=PATH or body.get("encoding")!="base64":
        raise ValueError("GitHub API response does not contain expected media manifest")
    decoded=base64.b64decode(body["content"],validate=False)
    if len(decoded)>MAX_REPLY_BYTES:
        raise ValueError("decoded manifest too large")
    remote=json.loads(decoded)
    local=json.loads((bot.MEDIA/"device_media_manifest.json").read_text())
    remote_devices={x["deviceId"] for x in remote.get("entries",[])}
    local_devices={x["deviceId"] for x in local.get("entries",[])}
    equal=remote==local
    return {
        "repository":OWNER_REPO, "branch":"main",
        "githubManifestVersion":remote.get("manifestVersion"),
        "localManifestVersion":local.get("manifestVersion"),
        "githubImages":len(remote_devices),
        "localImages":len(local_devices),
        "githubAheadDeviceIds":sorted(remote_devices-local_devices),
        "localAheadDeviceIds":sorted(local_devices-remote_devices),
        "manifestsIdentical":equal,
        "readOnly":True,
    }


if __name__=="__main__":
    result=check_remote_manifest()
    print(json.dumps(result,ensure_ascii=False))
    if not result["manifestsIdentical"]:
        raise SystemExit("ERROR: local manifest is stale. Refresh before staging/publishing.")
