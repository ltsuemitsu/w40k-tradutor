# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_profiles import (
    batch_tiers,
    profile_summary,
    recommended_workers,
    resolve_profile,
    save_every_batches,
)
from tradutor import SmartGlossary


class TestModelProfiles(unittest.TestCase):
    def test_flash_bulk_workers(self):
        self.assertEqual(recommended_workers("deepseek-v4-flash"), 8)
        s, m, l, x = batch_tiers("deepseek-v4-flash")
        self.assertGreaterEqual(s, 80)
        self.assertEqual(save_every_batches("deepseek-v4-flash"), 8)

    def test_glm52_quality(self):
        self.assertEqual(recommended_workers("glm-5.2"), 3)
        s, m, l, x = batch_tiers("glm-5.2")
        self.assertLessEqual(l, 12)

    def test_kimi_coding_url(self):
        mid, p = resolve_profile("kimi-for-coding")
        self.assertIn("kimi.com/coding", p["url"])

    def test_summary_nonempty(self):
        self.assertIn("workers=", profile_summary("deepseek-v4-flash"))


class TestCacheStableGlossary(unittest.TestCase):
    def test_format_for_prompt_alpha_stable(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = os.path.join(td.name, "g.json")
        import json
        data = {
            "terms": [
                {"term_english": "Zebra", "term_translated": "ZebraPT", "category": "x", "usage_count": 99},
                {"term_english": "Alpha", "term_translated": "AlphaPT", "category": "x", "usage_count": 1},
            ]
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        g = SmartGlossary(path, "preserve")
        a = g.format_for_prompt()
        # bump usage — must NOT change prompt order (cache stability)
        g.entries["zebra"]["usage_count"] = 1000
        b = g.format_for_prompt()
        self.assertEqual(a, b)
        self.assertLess(a.find("Alpha"), a.find("Zebra"))


if __name__ == "__main__":
    unittest.main()
