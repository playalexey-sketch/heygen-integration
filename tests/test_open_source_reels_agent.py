import datetime as dt
import unittest

import open_source_reels_agent as agent


class FakePost:
    shortcode = "ABC123xyz"
    date_utc = dt.datetime(2026, 8, 1, 12, 30)
    caption = "Тест отношений и семейной системы"
    likes = 1500
    comments = 120
    video_view_count = 45000
    video_duration = 61.5
    video_url = "https://cdn.example/reel.mp4"
    url = "https://cdn.example/cover.jpg"
    _node = {"play_count": 50000, "is_pinned": True}


class OpenSourceAgentTests(unittest.TestCase):
    def test_instaloader_post_normalization(self):
        reel = agent.post_to_reel(FakePost(), "competitor")
        self.assertEqual(reel.shortcode, "ABC123xyz")
        self.assertEqual(reel.likes, 1500)
        self.assertEqual(reel.comments, 120)
        self.assertEqual(reel.plays, 50000)
        self.assertEqual(reel.duration_seconds, 61.5)
        self.assertTrue(reel.is_pinned)
        self.assertIn("instaloader", reel.source)

    def test_open_source_stack_is_pinned(self):
        self.assertEqual(agent.STACK["instaloader"]["commit"], "5434692")
        self.assertEqual(agent.STACK["reels-vault"]["license"], "MIT")
        self.assertEqual(agent.STACK["parth-dl"]["license"], "MIT")


if __name__ == "__main__":
    unittest.main()
