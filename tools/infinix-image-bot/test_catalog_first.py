"""Offline regression tests for rate-limited Infinix bulk catalog cache."""
from pathlib import Path
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

import bot
import catalog_first as cf


class CatalogFirstTests(unittest.TestCase):
    def test_strict_code_and_name_before_detail(self):
        device=bot.BY_CODE["X6858"][0]
        rows=[
            ("ph","120","NOTE 50","X6858"),
            ("ph","121","NOTE 50 Pro","X6858"),
            ("ph","122","NOTE 50","NOT-A-CODE"),
        ]
        strict,uncertain,reason=cf.classify(bot.CATALOG,rows,set(),set())
        self.assertEqual(len(strict),1)
        self.assertEqual(strict[0]["deviceId"],device["deviceId"])
        self.assertEqual(len(uncertain),1)
        self.assertEqual(uncertain[0]["status"],"NAME_CONFLICT_REVIEW_ONLY")
        self.assertEqual(reason["sku_not_unique_catalog_match"],1)

    def test_already_published_or_staged_not_reaccepted(self):
        device=bot.BY_CODE["X6858"][0]
        row=[("ph","120","NOTE 50","X6858")]
        self.assertEqual(len(cf.classify(bot.CATALOG,row,{device["deviceId"]},set())[0]),0)
        self.assertEqual(len(cf.classify(bot.CATALOG,row,set(),{device["deviceId"]})[0]),0)

    def test_durable_sqlite_cache_and_offline_reuse(self):
        with tempfile.TemporaryDirectory(dir=bot.BOT/"output") as p:
            with closing(cf.database(Path(p)/"index.sqlite")) as conn:
                page={"items":[{"id":"117","name":"NOTE 50","sku":"X6858"}],"total":1}
                with patch.object(cf,"fetch_catalog_page",return_value=page) as remote:
                    first=cf.fetch_market(conn,"ph",now=100,ttl=500,offline=False)
                    self.assertEqual(first["productsSeen"],1)
                    self.assertTrue(first["bulkSupported"])
                    self.assertEqual(remote.call_count,1)
                with patch.object(cf,"fetch_catalog_page",side_effect=AssertionError("NO_NETWORK")):
                    second=cf.fetch_market(conn,"ph",now=200,ttl=500,offline=True)
                self.assertEqual(second["cacheHits"],1)
                self.assertEqual(second["requestsSent"],0)
                found=conn.execute("SELECT name,sku FROM products WHERE product_id='117'").fetchone()
                self.assertEqual(found,("NOTE 50","X6858"))

    def test_fallback_pagination_resets_per_family(self):
        """An accumulated 300 matches must not stop a second 250-row family."""
        with tempfile.TemporaryDirectory(dir=bot.BOT/"output") as temp:
            def stub(_market, term, page):
                if not term:
                    return {"items": [], "total": 0}
                if term in ("HOT", "NOTE"):
                    count = 250
                    start = 1000 if term == "HOT" else 2000
                    first = (page - 1) * 100
                    rows = [{"id": start + i, "name": f"{term} {i}", "sku": f"X{i+1000}"}
                            for i in range(first, min(first + 100, count))]
                    return {"items": rows, "total": count}
                return {"items": [], "total": 0}
            with closing(cf.database(Path(temp)/"f.sqlite")) as conn:
                with patch.object(cf, "fetch_catalog_page", side_effect=stub) as fetching:
                    report=cf.fetch_market(conn,"my",now=100,ttl=0)
                self.assertFalse(report["bulkSupported"])
                self.assertIsNone(report["error"])
                self.assertEqual(report["productsSeen"],500)
                calls={(call.args[1],call.args[2]) for call in fetching.call_args_list}
                self.assertIn(("HOT",3),calls)
                self.assertIn(("NOTE",3),calls)
                self.assertFalse(report["pagesTruncated"])
                self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_page_cap_reports_incomplete_inventory(self):
        with tempfile.TemporaryDirectory(dir=bot.BOT/"output") as temp:
            def stub(_market,term,page):
                rows=[{"id": (page-1)*100+i+1, "name":f"A{i}", "sku":f"X{i+3000}"}
                      for i in range(100)]
                return {"items":rows,"total":480}
            with closing(cf.database(Path(temp)/"f.sqlite")) as conn:
                with patch.object(cf,"fetch_catalog_page",side_effect=stub):
                    report=cf.fetch_market(conn,"my",now=101,ttl=0)
            self.assertTrue(report["bulkSupported"])
            self.assertTrue(report["pagesTruncated"])
            self.assertEqual(report["distinctSourceProducts"],300)

    def test_malformed_page_fails_but_never_claims_empty_success(self):
        with tempfile.TemporaryDirectory(dir=bot.BOT/"output") as p:
            with closing(cf.database(Path(p)/"index.sqlite")) as conn:
                with patch.object(cf,"fetch_catalog_page",return_value={"items":[],"total":0}):
                    result=cf.fetch_market(conn,"my",now=100,ttl=20)
                self.assertIsNotNone(result["error"])
                self.assertFalse(result["bulkSupported"])

    def test_limits_disallow_non_infinix_or_unbounded_requests(self):
        with self.assertRaises(ValueError):
            cf.fetch_catalog_page("google","",1)
        with self.assertRaises(ValueError):
            cf.fetch_catalog_page("my","INFINIX EVERYTHING",1)
        with self.assertRaises(ValueError):
            cf.run(["my"]*7,max_details=0)
        with self.assertRaises(ValueError):
            cf.run(["my"],max_details=50)


if __name__=="__main__":
    unittest.main()
