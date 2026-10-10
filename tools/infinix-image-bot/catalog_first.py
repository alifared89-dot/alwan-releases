#!/usr/bin/env python3
"""Bounded catalog-first acquisition for Infinix on Termux.

One official catalog request per market when possible; cached SQLite observations
and corroborated page leads for missing devices. Fallback to bounded family APIs
ONLY when bulk unsupported. Not a downloader, publisher, or image approver.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from contextlib import closing
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import urllib.parse

import bot
import multimarket_scan as mm
from official_index import normalize_name

DB_PATH = bot.BOT / "output" / "catalog-first.sqlite"
CACHE_SECONDS = 12*3600
MAX_MARKETS = 6
MAX_DETAILS = 20
MAX_WORKERS = 4
PAGE_SIZE = 100
MAX_PAGES = 3
# If broad query is unsupported, these are previously verified Infinix families.
FALLBACK_FAMILIES = ("HOT","NOTE","SMART","ZERO","XPAD","GT 20 Pro","GT 30 Pro")
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS queries(
       market TEXT NOT NULL, term TEXT NOT NULL, page INTEGER NOT NULL,
       fetched_at INTEGER NOT NULL, payload TEXT NOT NULL,
       PRIMARY KEY(market,term,page))""",
    """CREATE TABLE IF NOT EXISTS products(
       market TEXT NOT NULL, product_id TEXT NOT NULL,
       name TEXT NOT NULL, sku TEXT NOT NULL, seen_at INTEGER NOT NULL,
       PRIMARY KEY(market,product_id))""",
    """CREATE INDEX IF NOT EXISTS ix_products_sku ON products(sku)""",
)


def database(path:Path=DB_PATH):
    path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    for schema in SCHEMA:
        conn.execute(schema)
    conn.commit()
    return conn


def fetch_catalog_page(market:str,term:str,page:int):
    if market not in mm.MARKETS or not 1<=page<=MAX_PAGES or term not in ("",*FALLBACK_FAMILIES):
        raise ValueError("out of scope storefront query")
    host=mm.MARKETS[market][0]
    url=f"https://{host}/api/V1/xpark-app/app-search?"+urllib.parse.urlencode(
        {"q":term,"page":page,"page_size":PAGE_SIZE})
    raw,_=mm.get(url,mm.MAX_API_BYTES,host)
    data=json.loads(raw)
    if not isinstance(data,dict) or data.get("code")!=200:
        raise ValueError("official storefront application status is not 200")
    category=(data.get("data") or {}).get("category") or {}
    items=category.get("items") or []
    if not isinstance(items,list):
        raise ValueError("unexpected catalog result schema")
    total=int(category.get("total") or 0)
    if total<0:
        raise ValueError("negative official catalog total")
    return {"items":items,"total":total}


def cached_page(conn,market,term,page,now:int,ttl:int,offline:bool)->tuple[dict,bool]:
    found=conn.execute("SELECT fetched_at,payload FROM queries WHERE market=? AND term=? AND page=?",
                       (market,term,page)).fetchone()
    if found is not None and (offline or now-int(found[0])<=ttl):
        return json.loads(found[1]),True
    if offline:
        raise ValueError(f"offline cache miss for {market}:{term!r}:{page}")
    # No speculative retries beyond transient HTTP failures in mm.get().
    data=fetch_catalog_page(market,term,page)
    conn.execute("INSERT OR REPLACE INTO queries(market,term,page,fetched_at,payload) VALUES(?,?,?,?,?)",
                 (market,term,page,now,json.dumps(data,ensure_ascii=False)))
    conn.commit()  # checkpoint after every successful network page
    return data,False


def fetch_market(conn,market:str,now:int,ttl:int,offline:bool=False)->dict:
    status={"market":market,"requestsSent":0,"cacheHits":0,"queriesChecked":0,
            "productsSeen":0,"bulkSupported":None,"error":None,
            "distinctSourceProducts":0,"pagesTruncated":False}
    observed={}
    def read_term(term):
        total_pages=0
        term_ids=set()  # paginate each query independently, not the union across families
        for page in range(1,MAX_PAGES+1):
            data,hit=cached_page(conn,market,term,page,now,ttl,offline)
            status["queriesChecked"]+=1
            status["cacheHits"]+=int(hit)
            status["requestsSent"]+=int(not hit)
            total_pages+=1
            for row in data["items"]:
                pid=str(row.get("id") or "").strip()
                name=str(row.get("name") or "").strip()
                if not pid.isdigit() or not name or len(name)>200:
                    continue
                sku=str(row.get("sku") or "").strip().upper()[:90]
                observed[pid]=(name,sku)
                term_ids.add(pid)
            if not data["items"]:
                if len(term_ids)<data["total"]:
                    status["pagesTruncated"]=True
                break
            if len(term_ids)>=data["total"]:
                break
            if page==MAX_PAGES:
                status["pagesTruncated"]=True
        return total_pages
    try:
        try:
            read_term("")
            status["bulkSupported"]=len(observed)>0
        except Exception as exc:
            status["bulkSupported"]=False
            status["bulkFailure"]=f"{type(exc).__name__}: {str(exc)[:110]}"
        if not status["bulkSupported"]:
            for term in FALLBACK_FAMILIES:
                read_term(term)
        # Don't confuse an empty broken API with valid zero inventory.
        if not observed:
            raise ValueError("no products from full/fallback official API index")
        for pid,(name,sku) in observed.items():
            conn.execute("""INSERT OR REPLACE INTO products(market,product_id,name,sku,seen_at)
                            VALUES(?,?,?,?,?)""",(market,pid,name,sku,now))
        conn.commit()
        status["distinctSourceProducts"]=len(observed)
        status["productsSeen"]=len(observed)
    except Exception as exc:
        status["error"]=f"{type(exc).__name__}: {str(exc)[:180]}"
    return status


def classify(local_catalog:list[dict],rows:list[tuple],published:set[str],staged:set[str]):
    """Name fuzzy matching is a review hint, never a bypass of exact deviceId/SKU."""
    by_id={d["deviceId"]:d for d in local_catalog}
    reasons=Counter()
    verified_leads=[]
    uncertain=[]
    seen=set()
    for market,pid,name,sku in rows:
        model=bot.match_storefront_code(sku)
        if not model:
            reasons["sku_not_unique_catalog_match"]+=1
            continue
        code,device,match_type=model
        if device["deviceId"] not in by_id:
            reasons["device_not_in_scope"]+=1
            continue
        if device["deviceId"] in published:
            reasons["already_published"]+=1
            continue
        if device["deviceId"] in staged:
            reasons["already_staged"]+=1
            continue
        key=(market,pid)
        if key in seen:continue
        seen.add(key)
        info={"deviceId":device["deviceId"],"modelCode":code,"catalogName":device["name"],
              "sourceName":name,"market":market,"productId":pid,
              "sourceSku":sku,"matchType":match_type}
        if normalize_name(device["name"])!=normalize_name(name):
            info["status"]="NAME_CONFLICT_REVIEW_ONLY"
            uncertain.append(info)
            reasons["code_matches_but_name_conflicts"]+=1
        else:
            info["status"]="SKU_AND_NAME_LEAD"
            verified_leads.append(info)
            reasons["strict_sku_and_name_leads"]+=1
    return verified_leads,uncertain,dict(reasons)


def run(markets:list[str],db_path:Path=DB_PATH,offline:bool=False,
        max_details:int=15,cache_age:int=CACHE_SECONDS)->dict:
    if not markets or len(markets)>MAX_MARKETS or len(set(markets))!=len(markets):
        raise ValueError("1-6 distinct markets")
    if any(m not in mm.MARKETS for m in markets) or not 0<=max_details<=MAX_DETAILS:
        raise ValueError("unsupported source or details limit")
    if cache_age<0:
        raise ValueError("invalid cache ttl")
    started=time.monotonic()
    now=int(time.time())
    with closing(database(db_path)) as conn:
        statuses=[]
        # ONE writer connection, serial source queries: safe SQLite persistence
        # without thread-unsafe connections or uncontrolled cross-market volume.
        for market in markets:
            statuses.append(fetch_market(conn,market,now,cache_age,offline))
        # Use rows confirmed in THIS run (including valid cached pages),
        # not obsolete products from an older incomplete snapshot.
        rows=[tuple(x) for x in conn.execute(
            "SELECT market,product_id,name,sku FROM products WHERE seen_at=? AND market IN ("+
            ",".join("?" for m in markets)+") ORDER BY market,product_id",[now,*markets])]
    published={x["deviceId"] for x in json.loads(
        (bot.MEDIA/"device_media_manifest.json").read_text())["entries"]}
    audit=bot.BOT/"output/selected-review-audit.json"
    staged={x["deviceId"] for x in json.loads(audit.read_text())["items"]} if audit.is_file() else set()
    leads,ambiguous,reasons=classify(bot.CATALOG,rows,published,staged)
    # Corroboration is limited; all unvisited leads remain candidates, not accepted.
    def check(item):
        result=dict(item)
        try:
            match=bot.BY_ID[item["deviceId"]]
            detail=mm.inspect_official_detail(item["market"],
                        {"id":item["productId"]},match,item["modelCode"])
            result["sourcePageUrl"]=detail["finalUrl"]
            result["galleryImageUrls"]=detail["galleryImageUrls"]
            result["modelEvidence"]=detail["evidenceLevel"]
            result["status"]="DETAIL_VERIFIED_NEEDS_VISUAL_REVIEW" if detail["galleryImageUrls"] else "NO_VALID_IMAGES"
        except Exception as exc:
            result["status"]="DETAIL_REJECTED"
            result["error"]=f"{type(exc).__name__}: {str(exc)[:160]}"
        return result
    # Deduplicate SKU and device ID before spending detail-page requests.
    seen_ids=set()
    tasks=[]
    for row in sorted(leads,key=lambda x:(x["deviceId"],x["market"])):
        if row["deviceId"] in seen_ids:continue
        seen_ids.add(row["deviceId"])
        tasks.append(row)
    verified=[]
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS,max(1,max_details))) as pool:
        future={pool.submit(check,x):x for x in tasks[:max_details]}
        for job in as_completed(future):verified.append(job.result())
    verified.sort(key=lambda x:x["deviceId"])
    totals={"markets":len(markets),"cachedOrNewSourceProducts":len(rows),
            "httpRequestsMade":sum(s["requestsSent"] for s in statuses),
            "cacheHits":sum(s["cacheHits"] for s in statuses),
            "sourcesWithErrors":sum(bool(s["error"]) for s in statuses),
            "strictDeviceLeads":len(leads),
            "uniqueDeviceLeads":len(tasks),
            "ambiguousNameLeads":len(ambiguous),
            "detailsChecked":len(verified),
            "verifiedPagesWithImageUrls":sum(x["status"]=="DETAIL_VERIFIED_NEEDS_VISUAL_REVIEW" for x in verified),
            "downloadedImages":0,"publishedImages":0,
            "elapsedSeconds":round(time.monotonic()-started,1)}
    report={"mode":"READ_ONLY_CATALOG_FIRST","createdAt":datetime.now(timezone.utc).isoformat(),
            "summary":totals,"sources":statuses,"matchReasons":reasons,
            "verifiedDetailLeads":verified,"remainingStrictLeads":tasks[max_details:],
            "ambiguousNameLeads":ambiguous,"notice":"No visual image approvals or publishing in this process"}
    out=bot.BOT/"output"
    out.mkdir(exist_ok=True)
    (out/"catalog-first-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(totals,ensure_ascii=False),flush=True)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--market",action="append",choices=tuple(mm.MARKETS))
    parser.add_argument("--max-details",type=int,default=15)
    parser.add_argument("--cache-hours",type=float,default=12)
    parser.add_argument("--offline",action="store_true")
    args=parser.parse_args()
    report=run(args.market or ["iq","my"],offline=args.offline,
               max_details=args.max_details,cache_age=int(args.cache_hours*3600))
    if report["summary"]["sourcesWithErrors"]:
        raise SystemExit(2)
