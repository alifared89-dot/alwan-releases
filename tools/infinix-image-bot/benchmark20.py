#!/usr/bin/env python3
"""Reproducible 20-missing-device cold/warm live network benchmark.

Does not delete or overwrite production SQLite or source cache. Uses a fresh,
separate temporary evidence cache for cold and warm passes. Neither approval
nor stage nor GitHub files are touched. Source-code stays vendor-independent.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import random
import threading
import time
import shutil

import bot
import evidence_cache as cache
import media_core
import official_model_evidence as scan

SAMPLE_SEED=20261010
SIZE=20
OUTPUT=bot.BOT/"output"/"benchmark20-engine-upgrade.json"


def cohort20():
    published={x["deviceId"] for x in json.loads(
        (bot.MEDIA/"device_media_manifest.json").read_text())["entries"]}
    staged_path=bot.BOT/"output/selected-review-audit.json"
    staged={x["deviceId"] for x in json.loads(staged_path.read_text())["items"]}
    other=[d for d in bot.CATALOG if d["deviceId"] not in published|staged]
    leads=scan.index_exact_names(scan.index.DB_PATH)
    available_ids={row["deviceId"] for row in leads}
    leads_in_scope=[d for d in other if d["deviceId"] in available_ids]
    random.Random(SAMPLE_SEED).shuffle(leads_in_scope)
    choose=leads_in_scope[:SIZE]
    if len(choose)<SIZE:
        unavailable=[d for d in other if d["deviceId"] not in available_ids]
        random.Random(SAMPLE_SEED).shuffle(unavailable)
        choose.extend(unavailable[:SIZE-len(choose)])
    assert len(choose)==SIZE and len({d["deviceId"] for d in choose})==SIZE
    return choose,available_ids


class CountedOpener:
    def __init__(self,previous):
        self.previous=previous
        self.lock=threading.Lock()
        self.attempts=0
    def open(self,request,timeout=18):
        with self.lock:
            self.attempts+=1
        return self.previous.open(request,timeout=timeout)


def run():
    cohort,available_ids=cohort20()
    ids={x["deviceId"] for x in cohort}
    manifest_path=bot.MEDIA/"device_media_manifest.json"
    manifest_before=manifest_path.read_bytes()
    review_path=bot.BOT/"output/selected-review-audit.json"
    audit_before=review_path.read_bytes()
    old_root=cache.ROOT
    old_opener=media_core._OPENER
    counted=CountedOpener(old_opener)
    media_core._OPENER=counted
    try:
        with TemporaryDirectory(prefix="benchmark20-ephemeral-",dir=bot.BOT/"output") as tmp:
            cache.ROOT=Path(tmp)/"isolated-sources"
            media_core.reset_session_state_for_tests()
            cold=scan.run(max_models=SIZE,sources_per_model=2,images_per_model=3,
                          device_ids=ids,offline=False)
            after_cold=counted.attempts
            warm=scan.run(max_models=SIZE,sources_per_model=2,images_per_model=3,
                          device_ids=ids,offline=True)
            after_warm=counted.attempts
    finally:
        cache.ROOT=old_root
        media_core._OPENER=old_opener
        media_core.reset_session_state_for_tests()
    assert manifest_before==manifest_path.read_bytes()
    assert audit_before==review_path.read_bytes()
    cold_ids={x["deviceId"] for x in cold["candidatesForVisualReview"]}
    warm_ids={x["deviceId"] for x in warm["candidatesForVisualReview"]}
    if cold_ids != warm_ids:
        raise RuntimeError("warm cache changes original identity candidates")
    if after_warm != after_cold:
        raise RuntimeError("offline warmed scan unexpectedly contacted the network")
    metric={
        "cohortSize":len(cohort),"seed":SAMPLE_SEED,
        "officialProductLeadsInCohort":sum(d["deviceId"] in available_ids for d in cohort),
        "withoutOfficialStorefrontLead":sum(d["deviceId"] not in available_ids for d in cohort),
        "cold":cold["summary"],"warm":warm["summary"],
        "realHttpAttemptsCold":after_cold,"realHttpAttemptsWarm":after_warm-after_cold,
        "coldCandidateIds":sorted(cold_ids),"warmCandidateIds":sorted(warm_ids),
        "imageIdentityDifferenceColdWarm":len(cold_ids.symmetric_difference(warm_ids)),
        "manualReviewApprovalsCreated":0,"gitWrites":0,
        "falsePositiveRate":"NOT_MEASURABLE_WITHOUT_NEW_HUMAN_GOLD_STANDARD",
        "cohort":[{"deviceId":d["deviceId"],"name":d["name"],
                    "modelCodes":d["modelCodes"],
                    "officialSourceLead":d["deviceId"] in available_ids} for d in cohort],
    }
    report={"mode":"BRAND_ADAPTER_20_MISSING_DEVICES_REAL_NETWORK_BENCHMARK",
            "generatedAt":datetime.now(timezone.utc).isoformat(),"measurement":metric,
            "limitations":[
                "The 9 or more models without an official product lead are real missing Infinix devices but no source page was fetched for them.",
                "Cold and warm compare the same 20-device cohort; they do not imply cold-search improvement without a measured old-code A/B test.",
                "Model codes and front/back color are not automatically confirmed by a visual classifier.",
                "Only isolated temporary benchmark cache was discarded. Normal device cache was not purged.",
            ]}
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    dst=Path.home()/"storage/downloads/Alwan-Infinix-Bot-Benchmark-20.json"
    shutil.copy2(OUTPUT,dst)
    print(json.dumps({key:val for key,val in metric.items()
                      if key not in {"cohort","coldCandidateIds","warmCandidateIds"}},
                     ensure_ascii=False),flush=True)
    print("REPORT_FILE",dst,flush=True)
    return report


if __name__=="__main__":
    run()
