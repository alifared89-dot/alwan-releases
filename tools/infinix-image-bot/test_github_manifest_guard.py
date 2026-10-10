"""GitHub public manifest guard tests without external requests."""
from unittest.mock import patch
import base64
import io
import json
import unittest

import bot
import github_manifest_guard as guard


class FakeHttp:
    status=200
    def __init__(self,data,url=guard.API):
        self.data=data
        self.url=url
    def geturl(self):
        return self.url
    def read(self,n):
        return self.data[:n]
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False


class GithubGuardTests(unittest.TestCase):
    def test_no_write_and_manifest_comparison(self):
        manifest=json.loads((bot.MEDIA/"device_media_manifest.json").read_text())
        wrapper={"type":"file","path":guard.PATH,"encoding":"base64",
                 "content":base64.b64encode(json.dumps(manifest).encode()).decode()}
        with patch.object(guard.urllib.request,"urlopen",return_value=FakeHttp(json.dumps(wrapper).encode())):
            status=guard.check_remote_manifest()
        self.assertTrue(status["manifestsIdentical"])
        self.assertTrue(status["readOnly"])
        self.assertEqual(status["githubImages"],33)

    def test_guard_rejects_foreign_redirect(self):
        with patch.object(guard.urllib.request,"urlopen",
                          return_value=FakeHttp(b"{}",url="https://evil.test/data")):
            with self.assertRaisesRegex(RuntimeError,"outside"):
                guard.check_remote_manifest()


if __name__=="__main__":
    unittest.main()
