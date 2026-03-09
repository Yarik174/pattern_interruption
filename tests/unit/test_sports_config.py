from src.sports_config import SportType, match_league


def test_match_league_requires_country_for_generic_football_names():
    assert match_league("England: Premier League", SportType.FOOTBALL) == "EPL"
    assert match_league("England: Premier League 2", SportType.FOOTBALL) == "Unknown"
    assert match_league("Armenia: Premier League", SportType.FOOTBALL) == "Unknown"
    assert match_league("Germany: Bundesliga", SportType.FOOTBALL) == "Bundesliga"
    assert match_league("Austria: Bundesliga", SportType.FOOTBALL) == "Unknown"


def test_match_league_keeps_specific_matches_for_other_sports():
    assert match_league("USA: NBA", SportType.BASKETBALL) == "NBA"
    assert match_league("Poland: PlusLiga", SportType.VOLLEYBALL) == "PlusLiga"
