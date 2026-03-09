import pandas as pd

from src.pattern_engine import PatternEngine


def test_find_streaks_ignores_sequences_shorter_than_three():
    engine = PatternEngine()

    streaks = engine._find_streaks("WWLLLWWW")

    assert streaks == [
        {"pattern": "LLL", "length": 3, "position": 2, "next_result": "W"},
        {"pattern": "WWW", "length": 3, "position": 5, "next_result": None},
    ]


def test_find_alternations_requires_minimum_length_four():
    engine = PatternEngine()

    short_patterns = engine._find_alternations("WLW")
    long_patterns = engine._find_alternations("WLWLL")

    assert short_patterns == []
    assert any(pattern["pattern"] == "WLWL" for pattern in long_patterns)
    assert any(pattern["next_result"] == "L" for pattern in long_patterns if pattern["pattern"] == "WLWL")


def test_find_complex_patterns_detects_repeated_blocks_of_two_and_three():
    engine = PatternEngine()

    patterns = engine._find_complex_patterns("WLWLWLWWLWWLWWL")

    assert any(pattern["unit"] == "WL" and pattern["length"] == 6 for pattern in patterns)
    assert any(pattern["unit"] == "WWL" and pattern["length"] == 9 for pattern in patterns)


def test_get_pattern_features_collects_home_h2h_and_overall_critical_flags(games_factory):
    engine = PatternEngine()
    games = games_factory(
        [
            ("2024-01-01", "AAA", "BBB", 1),
            ("2024-01-02", "AAA", "CCC", 1),
            ("2024-01-03", "DDD", "AAA", 0),
            ("2024-01-04", "AAA", "BBB", 1),
            ("2024-01-05", "EEE", "AAA", 0),
            ("2024-01-06", "AAA", "BBB", 1),
        ]
    )

    features = engine.get_pattern_features("AAA", "BBB", games, games["date"].max() + pd.Timedelta(days=1))

    assert features["home_win_streak"] == 4
    assert features["away_win_streak"] == 2
    assert features["h2h_win_streak"] == 3
    assert features["overall_win_streak"] == 6
    assert features["home_streak_critical"] == 1
    assert features["h2h_streak_critical"] == 1
    assert features["overall_streak_critical"] == 1
    assert features["home_alternation_len"] == 0
    assert features["total_critical_patterns"] == 3
