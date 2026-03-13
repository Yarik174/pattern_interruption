# Refactoring Coordination

## Status: IN PROGRESS

## Agents & Zones

| Agent | Zone | Status |
|-------|------|--------|
| Agent 1 - Loaders | Consolidate 5 loaders → abstract base + implementations | IN PROGRESS |
| Agent 2 - Pattern Engines | Merge 3 pattern engines → generic + sport plugins | IN PROGRESS |
| Agent 3 - OddsMonitor Split | Extract DecisionEngine, QualityGate from 1200 LOC monster | IN PROGRESS |
| Agent 4 - Config & DI | Merge config.py + sports_config.py, fix global state | IN PROGRESS |
| Agent 5 - Routes & Types | Split routes.py, add type hints to core modules | IN PROGRESS |

## Coordination Rules
- Each agent works in its own git worktree (isolated branch)
- No agent modifies files outside its zone
- Shared interfaces documented here

## Shared Interfaces (agents update this)

### DataLoader ABC (Agent 1 creates)
```python
# src/loaders/base.py
class BaseLoader(ABC):
    @abstractmethod
    def load_matches(self, league: str, season: str) -> list[MatchData]: ...
    @abstractmethod
    def load_odds(self, match_id: str) -> OddsData | None: ...
```

### PatternAnalyzer ABC (Agent 2 creates)
```python
# src/patterns/base.py
class BasePatternAnalyzer(ABC):
    @abstractmethod
    def analyze(self, team: str, matches: list[MatchData]) -> PatternResult: ...
    @abstractmethod
    def detect_streak(self, results: list[str]) -> StreakInfo: ...
```

### DecisionEngine (Agent 3 creates)
```python
# src/decision/engine.py
class DecisionEngine:
    def evaluate(self, prediction: Prediction, odds: OddsData) -> Decision: ...
```

### Config (Agent 4 creates)
```python
# src/config/settings.py
class Settings:
    sports: dict[str, SportConfig]
    api: APIConfig
    monitoring: MonitorConfig
```
