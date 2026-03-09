import pandas as pd
import pytest

from src import odds_scraper


@pytest.mark.parametrize(
    ("moneyline", "expected"),
    [(150, 2.5), (-200, 1.5), (0, None), ("bad", None)],
)
def test_moneyline_to_decimal_handles_valid_and_invalid_values(moneyline, expected):
    assert odds_scraper.moneyline_to_decimal(moneyline) == expected


def test_parse_html_table_parses_single_game_and_handles_season_rollover():
    html = """
    <table>
      <tr>
        <th>Date</th><th>Rot</th><th>VH</th><th>Team</th><th>1st</th><th>2nd</th><th>3rd</th><th>Final</th><th>Open</th><th>Close</th>
      </tr>
      <tr>
        <td>0105</td><td>1</td><td>V</td><td>Montreal</td><td>1</td><td>1</td><td>0</td><td>2</td><td>120</td><td>130</td>
      </tr>
      <tr>
        <td>0105</td><td>2</td><td>H</td><td>Toronto</td><td>1</td><td>1</td><td>1</td><td>3</td><td>-140</td><td>-150</td>
      </tr>
    </table>
    """

    df = odds_scraper.parse_html_table(html, "2023-24")

    assert len(df) == 1
    assert df.iloc[0]["date"] == "2024-01-05"
    assert df.iloc[0]["away_team"] == "MTL"
    assert df.iloc[0]["home_team"] == "TOR"
    assert df.iloc[0]["home_win"] == 1
    assert df.iloc[0]["away_odds"] == 2.3
    assert df.iloc[0]["home_odds"] == pytest.approx(1.667, rel=1e-3)


def test_load_all_historical_odds_deduplicates_and_sorts(monkeypatch):
    monkeypatch.setattr(
        odds_scraper,
        "SEASONS",
        [("2023-24", "a"), ("2022-23", "b")],
    )

    def _fake_scrape(season, url, cache_dir):
        if season == "2023-24":
            return pd.DataFrame(
                [
                    {"date": "2024-01-03", "home_team": "AAA", "away_team": "BBB", "home_win": 1},
                    {"date": "2024-01-01", "home_team": "CCC", "away_team": "DDD", "home_win": 0},
                ]
            )

        return pd.DataFrame(
            [
                {"date": "2024-01-03", "home_team": "AAA", "away_team": "BBB", "home_win": 1},
                {"date": "2024-01-02", "home_team": "EEE", "away_team": "FFF", "home_win": 1},
            ]
        )

    monkeypatch.setattr(odds_scraper, "scrape_season", _fake_scrape)

    combined = odds_scraper.load_all_historical_odds(n_seasons=2)

    assert list(combined["date"]) == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert len(combined) == 3
