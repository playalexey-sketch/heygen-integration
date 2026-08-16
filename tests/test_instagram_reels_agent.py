import json
import tempfile
import unittest
from pathlib import Path

import instagram_reels_agent as agent


class NormalizeTests(unittest.TestCase):
    def test_normalizes_nested_analytics_metrics(self):
        reel = agent.normalize_reel(
            {
                "postCode": "ABC_123",
                "url": "https://www.instagram.com/reel/ABC_123/",
                "metrics": {
                    "like_count": 1500,
                    "comment_count": 55,
                    "play_count": 50000,
                    "save_count": 120,
                    "share_count": 180,
                    "repost_count": 3,
                },
            },
            "test",
        )
        self.assertEqual(reel.shortcode, "ABC_123")
        self.assertEqual(reel.likes, 1500)
        self.assertEqual(reel.saves, 120)
        self.assertEqual(reel.shares, 180)
        self.assertEqual(reel.plays, 50000)

    def test_parses_compact_counts(self):
        self.assertEqual(agent.to_int("1.2k"), 1200)
        self.assertEqual(agent.to_int("2M"), 2_000_000)
        self.assertIsNone(agent.to_int(None))


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.strict = agent.Thresholds(
            min_likes=1000,
            min_saves=100,
            min_shares=100,
            match="all",
            missing_metrics="exclude",
        )

    def reel(self, likes=1000, saves=100, shares=100):
        return agent.Reel(
            shortcode="TEST01",
            url="https://www.instagram.com/reel/TEST01/",
            likes=likes,
            saves=saves,
            shares=shares,
        )

    def test_strict_filter_requires_all_metrics(self):
        reel = self.reel()
        self.assertTrue(agent.qualify(reel, self.strict))
        self.assertEqual(reel.qualification, "qualified")

    def test_strict_filter_rejects_one_low_private_metric(self):
        reel = self.reel(saves=99)
        self.assertFalse(agent.qualify(reel, self.strict))
        self.assertEqual(reel.qualification, "excluded")

    def test_any_filter_accepts_either_save_or_share_threshold(self):
        thresholds = agent.Thresholds(match="any")
        reel = self.reel(saves=1, shares=150)
        self.assertTrue(agent.qualify(reel, thresholds))

    def test_missing_metrics_are_not_treated_as_zero(self):
        reel = self.reel(saves=None, shares=None)
        self.assertFalse(agent.qualify(reel, self.strict))
        self.assertIn("missing metrics", reel.qualification_reason)

    def test_missing_metrics_can_be_reported_as_unverified(self):
        thresholds = agent.Thresholds(missing_metrics="include-unverified")
        reel = self.reel(saves=None, shares=None)
        self.assertTrue(agent.qualify(reel, thresholds))
        self.assertEqual(reel.qualification, "unverified-candidate")


class ReportTests(unittest.TestCase):
    def test_deterministic_script_contains_required_cta(self):
        reel = agent.Reel(
            shortcode="MONEY1",
            url="https://www.instagram.com/reel/MONEY1/",
            caption="деньги доход цена скромность",
            likes=2000,
            saves=200,
            shares=150,
            qualification="qualified",
        )
        analysis = agent.deterministic_analysis(reel)
        self.assertIn("цифру 2", analysis["cta"])
        self.assertIn("цифру 2", analysis["new_script"])

    def test_snapshot_loader_preserves_missing_private_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.json"
            path.write_text(
                json.dumps(
                    {
                        "reels": [
                            {
                                "shortCode": "ABC123",
                                "likesCount": 1234,
                                "savesCount": None,
                                "sharesCount": None,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            reels = agent.load_snapshot(path)
        self.assertEqual(reels[0].likes, 1234)
        self.assertIsNone(reels[0].saves)
        self.assertIsNone(reels[0].shares)


if __name__ == "__main__":
    unittest.main()
