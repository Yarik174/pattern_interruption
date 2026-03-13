"""
Backward-compatibility shim for MultiLeaguePatternEngine.

Core pattern logic has moved to ``src.patterns.universal.UniversalPatternAnalyzer``.
This module preserves the original ``MultiLeaguePatternEngine`` class with the
full API (including ``get_all_upcoming_with_analysis``, odds matching, EV
calculation, and the ``main()`` CLI) so existing callers keep working.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.multi_league_loader import MultiLeagueLoader, LEAGUES
from src.patterns.universal import UniversalPatternAnalyzer


class MultiLeaguePatternEngine(UniversalPatternAnalyzer):
    """Full multi-league engine with odds / EV / upcoming analysis.

    Inherits all pattern logic from ``UniversalPatternAnalyzer`` and
    adds the league-loading, odds-matching, and EV methods that are
    specific to the multi-league workflow.
    """

    def __init__(self, critical_length: int = 5):
        super().__init__(critical_length=critical_length)
        self.loader = MultiLeagueLoader()

    # ------------------------------------------------------------------
    # Override load_leagues to use the internal loader
    # ------------------------------------------------------------------

    def load_leagues(self, league_names, n_seasons=5):
        return super().load_leagues(
            league_names, n_seasons=n_seasons, loader=self.loader,
        )

    # ------------------------------------------------------------------
    # Analyze a specific match (original 3-arg signature)
    # ------------------------------------------------------------------

    def analyze_match(self, league_name_or_home, away_team=None, __third=None, **kwargs):
        """Backward-compatible overload.

        Supports both:
          - ``analyze_match(league_name, home_team, away_team)``  (original)
          - ``analyze_match(home_team, away_team, league_name=...)``  (new)
        """
        if __third is not None:
            # Original 3-arg call: (league_name, home_team, away_team)
            league_name = league_name_or_home
            home_team = away_team
            away_team_actual = __third
        else:
            # New-style: (home_team, away_team, league_name=...)
            home_team = league_name_or_home
            away_team_actual = away_team
            league_name = kwargs.pop("league_name", "")

        return super().analyze_match(
            home_team, away_team_actual, league_name=league_name, **kwargs
        )

    # ------------------------------------------------------------------
    # Upcoming matches with full analysis
    # ------------------------------------------------------------------

    def get_all_upcoming_with_analysis(self, league_names=None, include_odds=True):
        if league_names is None:
            league_names = list(LEAGUES.keys())

        for league in league_names:
            if league not in self.team_patterns:
                self.analyze_team_patterns(league)

        upcoming = self.loader.get_all_upcoming(league_names)

        all_odds = {}
        if include_odds:
            all_odds = self.loader.fetch_all_odds(league_names)

        analyzed = []
        for game in upcoming:
            league = game['league']
            analysis = self.analyze_match(league, game['home_team'], game['away_team'])
            analysis.update({
                'date': game.get('date'),
                'time': game.get('time'),
                'game_id': game.get('id')
            })

            if league in all_odds:
                odds_data = self._match_odds(game, all_odds[league])
                analysis['odds'] = odds_data

                if odds_data and analysis['max_score'] >= 3:
                    if league == 'NHL':
                        ev = self.calc_ev(analysis, odds_data)
                        analysis['ev'] = ev
                    else:
                        analysis['ev'] = {
                            'bet_on': None,
                            'available': False,
                            'note': 'EV unavailable for this league (no calibrated model)'
                        }

            analyzed.append(analysis)

        analyzed.sort(key=lambda x: x['max_score'], reverse=True)
        return analyzed

    # ------------------------------------------------------------------
    # Odds matching
    # ------------------------------------------------------------------

    def _match_odds(self, game, league_odds):
        home = game['home_team']
        away = game['away_team']

        for key, odds in league_odds.items():
            odds_home = odds.get('home_team', '').lower()
            odds_away = odds.get('away_team', '').lower()

            if (home.lower() in odds_home or odds_home in home.lower() or
                away.lower() in odds_away or odds_away in away.lower()):
                return odds

            home_parts = home.lower().split()
            away_parts = away.lower().split()

            for part in home_parts:
                if len(part) > 3 and part in odds_home:
                    for apart in away_parts:
                        if len(apart) > 3 and apart in odds_away:
                            return odds
        return None

    # ------------------------------------------------------------------
    # Legacy EV wrapper (delegates to base class calc_ev)
    # ------------------------------------------------------------------

    def _calc_ev(self, analysis, odds_data):
        return self.calc_ev(analysis, odds_data)

    def _estimate_cpp_probability(self, patterns, synergy):
        return self.estimate_cpp_probability(patterns, synergy)

    def _get_pattern_weight(self, pattern_type):
        return self.pattern_weights.get(pattern_type, 1.0)

    def _estimate_break_prob(self, score, league='NHL'):
        return self.estimate_break_prob(score, league)


def main():
    """Test entry-point (preserved from original)."""
    engine = MultiLeaguePatternEngine(critical_length=5)

    leagues = ['KHL', 'SHL', 'Liiga', 'DEL']
    engine.load_leagues(leagues, n_seasons=4)

    for league in leagues:
        engine.print_summary(league)

    print("\n" + "=" * 60)
    print("Upcoming matches with strong signals")
    print("=" * 60)

    upcoming = engine.get_all_upcoming_with_analysis(leagues)

    strong = [m for m in upcoming if m['max_score'] >= 3]
    print(f"\nFound {len(strong)} matches with Score >= 3:")

    for m in strong[:10]:
        print(f"\n{m['league']}: {m['away_team']} @ {m['home_team']}")
        print(f"  Score: {m['max_score']} (home={m['home_score']}, away={m['away_score']})")
        print(f"  Home streak: {m['home_pattern'].get('overall_streak', 0)}")
        print(f"  Away streak: {m['away_pattern'].get('overall_streak', 0)}")
        print(f"  {m['recommendation']}")


if __name__ == '__main__':
    main()
