# Hockey Pattern Prediction System

## Overview
The Hockey Pattern Prediction System is a multi-league system designed to predict outcomes of hockey matches across several leagues (NHL, KHL, SHL, Liiga, DEL). It analyzes historical match data to identify recurring patterns in results. The core idea is that when a pattern reaches a critical length (e.g., 5+ repetitions), it has a high probability of breaking. The system aims to provide profitable betting recommendations based on these pattern breaks and calculated Expected Value (EV).

The project's vision is to leverage data-driven pattern recognition and machine learning to achieve a consistent positive Return on Investment (ROI) in sports betting. By integrating multiple leagues and sophisticated pattern analysis, the system seeks to identify valuable betting opportunities that might be overlooked by traditional predictive models.

## User Preferences
I prefer clear and concise explanations.
I value iterative development and regular updates on progress.
Please ask for confirmation before implementing significant architectural changes or adding new external dependencies.
I prefer to focus on high-level design and strategy, rather than micro-optimizations initially.
Ensure all generated code is well-commented and follows standard Python best practices.

## System Architecture
The system is built around a core pattern recognition engine that identifies various types of patterns, including home series, away series, head-to-head records, and alternating win/loss sequences. It utilizes both a Random Forest model for general predictions and a Critical Pattern Prediction (CPP) logic for identifying high-confidence pattern breaks.

**UI/UX Decisions:**
The web interface features a clean, modern design with a dark theme. It supports multiple leagues through distinct tabs (NHL, KHL, SHL, Liiga, DEL) and includes match cards with visual indicators for identified patterns. The design is responsive for mobile use. Filters for signal strength are provided to help users prioritize recommendations.

**Technical Implementations:**
- **Data Loading:** `data_loader.py` handles NHL data via an API with caching. `multi_league_loader.py` fetches data for European leagues using API-Sports.
- **Pattern Engine:** `pattern_engine.py` is central to identifying and analyzing patterns, including calculating their "weights" or reliability.
- **Feature Engineering:** `feature_builder.py` creates features for machine learning models, incorporating series lengths, alternations, synergies, and deep H2H statistics.
- **Prediction Models:**
    - **Random Forest:** `model.py` implements a Random Forest classifier with probability calibration. It uses 112 features and achieves an accuracy of ~54.44%.
    - **LSTM Sequence Model:** `sequence_model.py` uses a PyTorch-based LSTM neural network to predict match winners and period totals by analyzing sequences of past game statistics for each team.
- **CPP Logic:** This logic determines pattern breaks based on predefined critical lengths and rules (e.g., a winning streak of 5+ implies a high chance of a loss). Synergy (multiple patterns pointing to the same outcome) is a key factor for bet recommendations.
- **EV Calculation:** Expected Value (EV) is calculated for recommended bets using the CPP prediction's implied probability and available odds.
- **API Endpoints:** A Flask web server (`app.py`) exposes several API endpoints for upcoming matches, match analysis (for specific teams or all upcoming games), and multi-league summaries.
- **Configuration & Artifacts:** `config.py` manages system parameters, and `artifacts.py` handles saving training results, model metrics, feature importance, and trained models.

**Supported Patterns & Logic:**
- **Critical Lengths:** Patterns are considered critical at specific lengths (e.g., overall series ≥5, home series ≥4, H2H series ≥3).
- **Break Rules:** Specific rules dictate the predicted outcome upon a pattern break (e.g., a winning streak break predicts a loss).
- **Synergy:** Multiple patterns indicating the same outcome increase prediction confidence and are required for EV calculation.

## External Dependencies
- **NHL API:** For NHL match data.
- **API-Sports:** For KHL, SHL, Liiga, and DEL match data.
- **The Odds API:** For real-time betting odds, primarily integrated for NHL, SHL, and Liiga. Requires an API key.
- **Kaggle Dataset:** Used for historical odds data (specifically `data/odds/sportsbook-nhl-*.csv`).
- **Flask:** Python web framework for the API and UI.
- **PyTorch:** Deep learning framework used for the LSTM Sequence Model.
- **Scikit-learn:** For Random Forest model, feature processing, and model evaluation.
- **XGBoost, LightGBM:** Other machine learning libraries used for model comparison (though Random Forest is the primary model).