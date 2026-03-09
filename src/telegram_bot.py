"""
Telegram Bot для уведомлений о прогнозах
"""
import requests
import os
import logging
import json
from typing import Optional, Dict, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SPORT_DISPLAY = {
    'hockey': {'icon': '🏒', 'name_ru': 'Хоккей'},
    'football': {'icon': '⚽', 'name_ru': 'Футбол'},
    'basketball': {'icon': '🏀', 'name_ru': 'Баскетбол'},
    'volleyball': {'icon': '🏐', 'name_ru': 'Волейбол'},
}


class TelegramNotifier:
    """Отправка уведомлений в Telegram"""
    
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or os.environ.get('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID')
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None
    
    def is_configured(self) -> bool:
        """Проверка настроен ли бот"""
        return bool(self.bot_token and self.chat_id)
    
    def send_message(self, text: str, parse_mode: str = 'HTML') -> bool:
        """
        Отправить сообщение в Telegram
        
        Args:
            text: Текст сообщения
            parse_mode: Режим парсинга (HTML или Markdown)
            
        Returns:
            True если успешно отправлено
        """
        if not self.is_configured():
            logger.warning("Telegram бот не настроен. Установите TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID")
            return False
        
        try:
            response = requests.post(
                f"{self.api_url}/sendMessage",
                json={
                    'chat_id': self.chat_id,
                    'text': text,
                    'parse_mode': parse_mode
                },
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("Telegram уведомление отправлено")
                return True
            else:
                logger.error(f"Telegram API error: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False
    
    def send_prediction_alert(self, prediction: Dict) -> bool:
        """
        Отправить уведомление о новом прогнозе
        
        Args:
            prediction: Данные прогноза
            
        Returns:
            True если успешно отправлено
        """
        confidence_score = self._resolve_confidence_score(prediction)
        confidence_emoji = self._get_confidence_emoji(confidence_score)
        sport = self._get_sport_display(prediction)
        patterns = self._parse_patterns_data(prediction.get('patterns_data'))
        bet_on, odds = self._resolve_bet_details(prediction, patterns)

        market = prediction.get('bet_type') or prediction.get('prediction_type') or 'winner'
        bookmaker = prediction.get('bookmaker') or '-'

        message = f"""
{confidence_emoji} <b>НОВЫЙ ПРОГНОЗ</b>

<b>Спорт:</b> {sport['icon']} {sport['name_ru']}
<b>Лига:</b> {prediction.get('league', '-')}
<b>Матч:</b> {prediction.get('home_team', '')} vs {prediction.get('away_team', '')}
<b>Дата:</b> {self._format_date(prediction.get('match_date'))}

<b>Прогноз:</b> {bet_on}
<b>Коэффициент:</b> {odds}
<b>Уверенность:</b> {confidence_score}/10

<b>Рынок:</b> {market}
<b>Букмекер:</b> {bookmaker}
"""

        if patterns.get('pattern_type'):
            message += f"\n<b>Паттерн:</b> {patterns['pattern_type']}"
        
        return self.send_message(message.strip())
    
    def send_daily_summary(self, predictions: List[Dict], stats: Dict) -> bool:
        """
        Отправить дневную сводку
        
        Args:
            predictions: Список прогнозов за день
            stats: Статистика
            
        Returns:
            True если успешно отправлено
        """
        message = f"""
<b>ДНЕВНАЯ СВОДКА</b>

<b>Всего прогнозов:</b> {len(predictions)}
<b>Выиграно:</b> {stats.get('wins', 0)}
<b>Проиграно:</b> {stats.get('losses', 0)}
<b>Ожидают:</b> {stats.get('pending', 0)}

<b>Win Rate:</b> {stats.get('win_rate', 0):.1f}%
<b>ROI:</b> {stats.get('roi', 0):+.1f}%
"""

        sport_breakdown = self._build_sport_breakdown(predictions)
        if sport_breakdown:
            message += "\n\n<b>По видам спорта:</b>\n"
            for item in sport_breakdown:
                message += f"{item['icon']} {item['name_ru']}: {item['count']}\n"
        
        return self.send_message(message.strip())
    
    def send_error_alert(self, error_message: str) -> bool:
        """
        Отправить алерт о критической ошибке
        
        Args:
            error_message: Текст ошибки
            
        Returns:
            True если успешно отправлено
        """
        from datetime import datetime
        timestamp = datetime.now().strftime('%d.%m.%Y %H:%M')
        
        message = f"""
<b>СИСТЕМНАЯ ОШИБКА</b>

<b>Время:</b> {timestamp}

{error_message}

<i>Проверьте логи системы</i>
"""
        return self.send_message(message.strip())
    
    def _get_confidence_emoji(self, confidence: int) -> str:
        """Эмодзи по уровню уверенности"""
        if confidence >= 8:
            return ""
        elif confidence >= 6:
            return ""
        elif confidence >= 4:
            return ""
        else:
            return ""
    
    def _format_date(self, dt) -> str:
        """Форматирование даты"""
        if dt is None:
            return '-'
        try:
            if hasattr(dt, 'strftime'):
                return dt.strftime('%d.%m.%Y %H:%M')
            return str(dt)
        except Exception:
            return '-'

    def _parse_patterns_data(self, patterns) -> Dict:
        """Нормализовать patterns_data к словарю."""
        if isinstance(patterns, dict):
            return patterns
        if isinstance(patterns, str) and patterns:
            try:
                parsed = json.loads(patterns)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return {}
        return {}

    def _resolve_confidence_score(self, prediction: Dict) -> int:
        """Получить уверенность в шкале 1-10."""
        score = prediction.get('confidence_1_10')
        if isinstance(score, (int, float)) and score > 0:
            return max(1, min(10, int(round(score))))

        confidence = prediction.get('confidence')
        if isinstance(confidence, (int, float)):
            if confidence <= 1:
                return max(1, min(10, int(round(confidence * 10))))
            return max(1, min(10, int(round(confidence))))

        return 5

    def _get_sport_display(self, prediction: Dict) -> Dict[str, str]:
        """Читаемое название спорта для уведомления."""
        sport_slug = str(prediction.get('sport_type') or 'hockey').lower()
        return SPORT_DISPLAY.get(sport_slug, {'icon': '🎯', 'name_ru': sport_slug.title()})

    def _resolve_bet_details(self, prediction: Dict, patterns: Dict) -> tuple[str, object]:
        """Определить сторону ставки и коэффициент."""
        home_team = prediction.get('home_team', '')
        away_team = prediction.get('away_team', '')
        outcome = prediction.get('predicted_outcome', '')
        bet_on = patterns.get('bet_on') or patterns.get('target')
        target_odds = patterns.get('target_odds')

        if bet_on == 'home':
            return home_team or outcome or '-', target_odds or prediction.get('home_odds', '-')
        if bet_on == 'away':
            return away_team or outcome or '-', target_odds or prediction.get('away_odds', '-')

        if outcome == 'home':
            return home_team or '-', prediction.get('home_odds', '-')
        if outcome == 'away':
            return away_team or '-', prediction.get('away_odds', '-')
        if outcome == home_team:
            return home_team or '-', target_odds or prediction.get('home_odds', '-')
        if outcome == away_team:
            return away_team or '-', target_odds or prediction.get('away_odds', '-')

        return outcome or '-', target_odds or '-'

    def _build_sport_breakdown(self, predictions: List[Dict]) -> List[Dict[str, object]]:
        """Сгруппировать дневную сводку по видам спорта."""
        counts = {}
        for prediction in predictions:
            sport = self._get_sport_display(prediction)
            key = str(prediction.get('sport_type') or 'hockey').lower()
            if key not in counts:
                counts[key] = {
                    'icon': sport['icon'],
                    'name_ru': sport['name_ru'],
                    'count': 0
                }
            counts[key]['count'] += 1

        ordered = ['hockey', 'football', 'basketball', 'volleyball']
        result = []
        for key in ordered:
            if key in counts:
                result.append(counts[key])
        for key, value in counts.items():
            if key not in ordered:
                result.append(value)
        return result
    
    def test_connection(self) -> Dict:
        """
        Тест подключения к Telegram API
        
        Returns:
            Информация о боте или ошибка
        """
        if not self.bot_token:
            return {'ok': False, 'error': 'TELEGRAM_BOT_TOKEN not set'}
        
        try:
            response = requests.get(
                f"{self.api_url}/getMe",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    bot_info = data.get('result', {})
                    return {
                        'ok': True,
                        'bot_username': bot_info.get('username'),
                        'bot_name': bot_info.get('first_name')
                    }
            
            return {'ok': False, 'error': response.text}
            
        except Exception as e:
            return {'ok': False, 'error': str(e)}


def create_bot_instructions() -> str:
    """
    Инструкции по созданию Telegram бота
    """
    return """
## Создание Telegram бота

### Шаг 1: Создать бота
1. Откройте Telegram и найдите @BotFather
2. Отправьте команду /newbot
3. Введите имя бота (например: "Hockey Predictor")
4. Введите username бота (например: hockey_predictor_bot)
5. Скопируйте полученный токен (API Token)

### Шаг 2: Получить Chat ID
1. Напишите своему боту любое сообщение
2. Откройте в браузере: https://api.telegram.org/bot<ВАШ_ТОКЕН>/getUpdates
3. Найдите "chat":{"id": ЧИСЛО} - это ваш Chat ID

### Шаг 3: Добавить секреты в Replit
Добавьте два секрета:
- TELEGRAM_BOT_TOKEN = ваш API токен
- TELEGRAM_CHAT_ID = ваш Chat ID
"""


def send_prediction_notification(prediction: Dict) -> bool:
    """Совместимый хелпер для AutoMonitor."""
    notifier = TelegramNotifier()
    return notifier.send_prediction_alert(prediction)
