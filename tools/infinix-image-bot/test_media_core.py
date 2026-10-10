"""Network-policy tests that verify brand-neutral interfaces without live HTTP."""
import io
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError

import media_core as core


class FakeResponse:
    status = 200
    def __init__(self, url, payload=b"ok"):
        self.url=url
        self.payload=payload
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def geturl(self): return self.url
    def read(self,n): return self.payload[:n]


class BrandIndependentTransportTest(unittest.TestCase):
    def setUp(self): core.reset_session_state_for_tests()

    def test_same_core_serves_multiple_brand_adapters(self):
        for brand,host in (("infinix","wap.my.infinixmobility.com"),
                           ("tecno","example.tecno.test"),
                           ("samsung","example.samsung.test")):
            with self.subTest(brand=brand):
                policy=core.SourcePolicy(brand,frozenset({host}),"Alwan-test",min_interval=0)
                url=f"https://{host}/catalog.json"
                opened=Mock(return_value=FakeResponse(url,b'{"ok":1}'))
                raw,real=core.fetch_https(url,100,host,policy,opener=opened)
                self.assertEqual((raw,real),(b'{"ok":1}',url))
                self.assertEqual(opened.call_count,1)
                with self.assertRaisesRegex(ValueError,"untrusted"):
                    core.fetch_https("https://evil.test/image.png",100,host,policy,opener=opened)
                self.assertEqual(opened.call_count,1)

    def test_malicious_redirect_target_is_never_accepted(self):
        host="example.vendor.test"
        policy=core.SourcePolicy("vendor",frozenset({host}),"Alwan",0)
        opened=Mock(return_value=FakeResponse("https://evil.test/steal",b"unsafe"))
        with self.assertRaisesRegex(ValueError,"untrusted"):
            core.fetch_https(f"https://{host}/media.png",100,host,policy,opener=opened)
        self.assertEqual(opened.call_count,1)

    def test_429_retry_after_is_honored_if_bounded(self):
        host="example.vendor.test";url=f"https://{host}/photo.png"
        policy=core.SourcePolicy("vendor",frozenset({host}),"Alwan",0)
        http_error=HTTPError(url,429,"rate-limited",{"Retry-After":"2"},io.BytesIO())
        opened=Mock(side_effect=[http_error,FakeResponse(url)])
        waited=[]
        raw,_=core.fetch_https(url,100,host,policy,
                               opener=opened,clock=lambda:100,sleep=waited.append)
        self.assertEqual(raw,b"ok")
        self.assertEqual(waited,[2.0])
        self.assertEqual(opened.call_count,2)

    def test_429_large_retry_after_pauses_host_without_retry(self):
        host="example.vendor.test";url=f"https://{host}/photo.png"
        policy=core.SourcePolicy("vendor",frozenset({host}),"Alwan",0)
        err=HTTPError(url,429,"slow down",{"Retry-After":"120"},io.BytesIO())
        opened=Mock(side_effect=[err,FakeResponse(url)])
        with self.assertRaisesRegex(core.SourceUnavailable,"Retry-After"):
            core.fetch_https(url,100,host,policy,opener=opened,clock=lambda:100,sleep=lambda _:None)
        with self.assertRaisesRegex(core.SourceUnavailable,"paused"):
            core.fetch_https(url,100,host,policy,opener=opened,clock=lambda:101,sleep=lambda _:None)
        self.assertEqual(opened.call_count,1)

    def test_403_not_retried(self):
        host="example.vendor.test";url=f"https://{host}/photo.png"
        policy=core.SourcePolicy("vendor",frozenset({host}),"Alwan",0)
        err=HTTPError(url,403,"denied",{},io.BytesIO())
        opened=Mock(side_effect=[err,FakeResponse(url)])
        with self.assertRaisesRegex(core.SourceUnavailable,"403"):
            core.fetch_https(url,100,host,policy,opener=opened,clock=lambda:100,sleep=lambda _:None)
        self.assertEqual(opened.call_count,1)

    def test_payload_and_url_credentials_blocked(self):
        host="vendor.test";url=f"https://{host}/"
        policy=core.SourcePolicy("vendor",frozenset({host}),"Alwan",0)
        with self.assertRaises(ValueError):
            core.fetch_https(f"https://admin@{host}/",100,host,policy,opener=Mock())
        with self.assertRaisesRegex(ValueError,"exceeds"):
            core.fetch_https(url,10,host,policy,opener=Mock(return_value=FakeResponse(url,b"12345678901")))


if __name__=="__main__":
    unittest.main()
