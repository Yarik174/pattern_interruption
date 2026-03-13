"""
Settings and configuration routes (Telegram setup).
"""
from __future__ import annotations

import os

from flask import Blueprint

settings_bp = Blueprint('settings', __name__)


def _pkg():
    """Late-import the package so reads see monkeypatched values."""
    import src.routes as _rt
    return _rt


@settings_bp.route('/settings/telegram')
def telegram_setup_page() -> str:
    """Telegram setup page."""
    rt = _pkg()

    bot_configured = bool(os.environ.get('TELEGRAM_BOT_TOKEN'))
    chat_configured = bool(os.environ.get('TELEGRAM_CHAT_ID'))
    is_active = bot_configured and chat_configured
    bot_info = None

    if rt.telegram_notifier and is_active:
        bot_info = rt.telegram_notifier.test_connection()
        if not bot_info.get('ok'):
            bot_info = None

    return rt.render_template(
        'telegram_setup.html',
        bot_configured=bot_configured,
        chat_configured=chat_configured,
        is_active=is_active,
        bot_info=bot_info,
    )
