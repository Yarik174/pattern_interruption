import pytest

from src.config import PATTERN_BREAK_RATES
from src.feature_builder import FeatureBuilder


def test_build_features_returns_single_sample_after_min_history(games_factory):
    builder = FeatureBuilder()
    games = games_factory(
        [
            (f"2024-01-{day:02d}", "AAA", "BBB", day % 2, f"game-{day}")
            for day in range(1, 22)
        ]
    )

    features_df, targets, game_info = builder.build_features(games)

    assert len(features_df) == 1
    assert len(targets) == 1
    assert len(game_info) == 1
    assert features_df.isna().sum().sum() == 0


@pytest.mark.parametrize(
    ("features", "context", "expected"),
    [
        ({"home_win_streak": 4, "away_win_streak": 0, "h2h_win_streak": 3, "overall_win_streak": 5}, "home", 3),
        ({"home_win_streak": 4, "away_win_streak": 0, "h2h_win_streak": 3, "overall_win_streak": 0}, "home", 2),
        ({"home_win_streak": 4, "away_win_streak": 0, "h2h_win_streak": 0, "overall_win_streak": 0}, "home", 1),
        ({"home_win_streak": 0, "away_win_streak": -4, "h2h_win_streak": -3, "overall_win_streak": -5}, "away", -3),
        ({"home_win_streak": 0, "away_win_streak": -4, "h2h_win_streak": -3, "overall_win_streak": 0}, "away", -2),
        ({"home_win_streak": 0, "away_win_streak": 0, "h2h_win_streak": 0, "overall_win_streak": 0}, "home", 0),
    ],
)
def test_calculate_synergy(features, context, expected):
    builder = FeatureBuilder()

    assert builder._calculate_synergy(features, context) == expected


def test_calculate_critical_synergy_counts_aligned_patterns():
    builder = FeatureBuilder()

    critical_count, aligned = builder._calculate_critical_synergy(
        {
            "home_streak_critical": 1,
            "h2h_streak_critical": 1,
            "overall_streak_critical": 1,
            "home_alt_critical": 0,
            "home_win_streak": 4,
            "h2h_win_streak": 3,
            "overall_win_streak": 5,
        },
        "home",
    )

    assert critical_count == 3
    assert aligned == 3


def test_calculate_critical_synergy_drops_alignment_for_conflicting_directions():
    builder = FeatureBuilder()

    critical_count, aligned = builder._calculate_critical_synergy(
        {
            "home_streak_critical": 1,
            "h2h_streak_critical": 1,
            "overall_streak_critical": 1,
            "home_alt_critical": 0,
            "home_win_streak": 4,
            "h2h_win_streak": -3,
            "overall_win_streak": 5,
        },
        "home",
    )

    assert critical_count == 3
    assert aligned == 0


def test_calculate_target_combined_marks_broken_pattern():
    builder = FeatureBuilder()

    broken = builder._calculate_target_combined(
        {
            "total_critical_patterns": 1,
            "overall_streak_critical": 1,
            "overall_win_streak": 5,
            "home_streak_critical": 0,
            "h2h_streak_critical": 0,
            "home_alt_critical": 0,
            "h2h_alt_critical": 0,
            "overall_alt_critical": 0,
        },
        {"total_critical_patterns": 0},
        actual_result=0,
    )

    kept = builder._calculate_target_combined(
        {
            "total_critical_patterns": 1,
            "overall_streak_critical": 1,
            "overall_win_streak": 5,
            "home_streak_critical": 0,
            "h2h_streak_critical": 0,
            "home_alt_critical": 0,
            "h2h_alt_critical": 0,
            "overall_alt_critical": 0,
        },
        {"total_critical_patterns": 0},
        actual_result=1,
    )

    assert broken == 1
    assert kept == 0


def test_calculate_weighted_break_probability_uses_expected_weights():
    builder = FeatureBuilder()
    features = {
        "home_streak_critical": 1,
        "overall_streak_critical": 1,
        "h2h_alt_critical": 1,
        "home_alt_critical": 0,
        "h2h_streak_critical": 0,
        "overall_alt_critical": 0,
    }

    result = builder._calculate_weighted_break_probability(features, "home")
    expected = (
        PATTERN_BREAK_RATES["home_streak"] * 1.0
        + PATTERN_BREAK_RATES["overall_streak"] * 1.2
        + PATTERN_BREAK_RATES["h2h_alternation"] * 1.0
    ) / 3.2

    assert result == pytest.approx(expected)
