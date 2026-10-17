import os
import time
import unittest
from unittest import mock

import requests

from radar.sources import beatapi

CFG = {
    "services": [{"id": "seo", "name": "SEO", "beatapi_queries": ["looking for SEO expert"]}],
    "sources": {"beatapi": {"enabled": True, "time_range": "week", "max_results": 5,
                            "platform_groups": [["reddit.com"], ["linkedin.com", "x.com"]]}},
}


def resp(status=200, body=None):
    r = mock.Mock(spec=requests.Response)
    r.status_code = status
    r.json.return_value = body if body is not None else {}
    r.text = str(body)
    return r


class BeatAPITests(unittest.TestCase):
    def setUp(self):
        os.environ["BEATAPI_API_KEY"] = "test-key"
        p = mock.patch("radar.sources.beatapi.time.sleep")
        p.start()
        self.addCleanup(p.stop)

    def test_missing_key_is_skipped_with_note(self):
        os.environ.pop("BEATAPI_API_KEY")
        posts, notes = beatapi.collect(CFG, 0)
        self.assertEqual(posts, [])
        self.assertIn("BEATAPI_API_KEY", notes[0])

    def test_parses_filters_and_sends_correct_request(self):
        now = time.time()
        body = {"results": [
            {"title": "Need SEO help", "url": "https://www.reddit.com/r/SEO/comments/1/x", "snippet": "hire me an expert"},
            {"title": "Elsewhere", "url": "https://example.com/blog", "snippet": "not an allowed host"},
            {"title": "Old", "url": "https://www.reddit.com/r/SEO/comments/2/y", "published_at": "2020-01-01T00:00:00Z"},
            {"title": "No url"},
        ]}
        with mock.patch("requests.Session.post", return_value=resp(200, body)) as post:
            posts, notes = beatapi.collect(CFG, now - 3600)
        self.assertEqual(notes, [])
        self.assertEqual([p.url for p in posts], ["https://www.reddit.com/r/SEO/comments/1/x"])
        p = posts[0]
        self.assertEqual((p.source, p.id, p.meta["platform"]), ("beatapi", "beatapi:" + p.url, "reddit.com"))
        self.assertTrue(p.meta["unverified"])
        sent = post.call_args_list[0].kwargs["json"]
        self.assertEqual(sent["include_domains"], ["reddit.com"])
        self.assertEqual(sent["time_range"], "week")
        self.assertEqual(post.call_count, 2)            # 1 service x 1 query x 2 groups

    def test_bad_key_stops_immediately_and_never_leaks_key(self):
        err = {"error": {"code": "invalid_api_key", "message": "bad key"}}
        with mock.patch("requests.Session.post", return_value=resp(401, err)) as post:
            posts, notes = beatapi.collect(CFG, 0)
        self.assertEqual(posts, [])
        self.assertEqual(post.call_count, 1)
        self.assertIn("401", notes[0])
        self.assertNotIn("test-key", notes[0])

    def test_rate_limit_retries_then_succeeds(self):
        rl = resp(429, {"error": {"code": "rate_limit_exceeded", "retry_after_seconds": 1}})
        ok = resp(200, {"results": []})
        with mock.patch("requests.Session.post", side_effect=[rl, ok, ok]) as post:
            posts, notes = beatapi.collect(CFG, 0)
        self.assertEqual(notes, [])
        self.assertEqual(post.call_count, 3)

    def test_network_errors_trip_circuit_breaker(self):
        cfg = {"services": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
               "sources": {"beatapi": {"platform_groups": [["reddit.com"]]}}}
        with mock.patch("requests.Session.post", side_effect=requests.ConnectionError("boom")):
            posts, notes = beatapi.collect(cfg, 0)
        self.assertEqual(posts, [])
        self.assertIn("searches failed", notes[0])


if __name__ == "__main__":
    unittest.main()
