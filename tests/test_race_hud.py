import unittest

from race_hud import compare_placements


def hud(rank, entrants=14):
    return [
        (None, "LAP", .99),
        (None, "1/2", .99),
        (None, f"{rank}/{entrants}", .98),
    ]


class RaceHudTest(unittest.TestCase):
    def test_repeated_rank_change_ignores_lap_counter(self):
        frames = [hud(5), hud(5), hud(4), hud(6), hud(6), hud(7)]
        self.assertEqual(compare_placements(frames), {"before": 5, "after": 6, "entrants": 14})

    def test_changed_field_size_does_not_verify_rank_loss(self):
        self.assertIsNone(compare_placements([hud(5)] * 3 + [hud(6, 15)] * 3))

    def test_disappearing_hud_and_bare_dnf_do_not_verify_player_result(self):
        for frames in ([None] * 3, [[(None, "DNF", .99)]] * 3):
            with self.subTest(frames=frames):
                self.assertIsNone(compare_placements([hud(5)] * 3 + frames))

    def test_explicit_player_dnf_requires_repeat(self):
        dnf = [(None, "You did not finish the race", .99)]
        self.assertIsNone(compare_placements([hud(5)] * 3 + [dnf, None, None]))
        self.assertEqual(compare_placements([hud(5)] * 3 + [dnf, dnf, None]), {
            "before": 5, "after": None, "entrants": 14, "result": "did_not_finish",
        })
