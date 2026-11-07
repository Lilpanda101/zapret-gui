"""
diagnostics/words.py - Единственный источник правды (SSOT) для фраз BlockCheck,
статусов доступности, рекомендаций и текстов ошибок диагностики.
"""

# Статусы экспресс-проверок и карточек
STATUS_NOT_CHECKED = "Не проверялось"
STATUS_CHECKING = "Проверка..."
STATUS_BLOCKED_OR_TIMEOUT = "Заблокирован / Таймаут"
STATUS_ERROR = "Ошибка (ERROR)"
STATUS_DIAGNOSTICS_RUNNING = "Запуск глубокой диагностики ТСПУ..."
STATUS_BLOCKCHECK2_PREPARING = "Подготовка Blockcheck2. Текущий движок будет остановлен...\n"

# Семейства и типы блокировок
VERDICTS = {
    "PASS": {
        "title": "Блокировка не обнаружена",
        "description": "Сайт доступен напрямую без видимого вмешательства ТСПУ.",
        "recommendation": "Обход DPI для данного хоста не требуется.",
        "badge_text": "Доступен (PASS)",
        "badge_class": "badge-ok",
        "severity": "LOW",
    },
    "DNS_SPOOFING": {
        "title": "Подмена DNS (DNS Spoofing / Poisoning)",
        "description": "Провайдер или ТСПУ перехватывает DNS-запросы и возвращает фиктивный/заглушечный IP.",
        "recommendation": "Включите шифрованный DNS (DoT / DoH) в настройках или DNS-AI / Cloudflare.",
        "badge_text": "DNS Подмена (CRITICAL)",
        "badge_class": "badge-bad",
        "severity": "CRITICAL",
    },
    "TCP_RST_INJECTION": {
        "title": "Внедрение TCP RST (RST Injection)",
        "description": "ТСПУ внедряет инъекционные TCP RST пакеты при установлении соединения.",
        "recommendation": "Используйте пресеты с разделением SYN/ACK или фильтрацией RST (fake, syndata).",
        "badge_text": "TCP RST (CRITICAL)",
        "badge_class": "badge-bad",
        "severity": "CRITICAL",
    },
    "TLS_SNI_DROP": {
        "title": "Сброс по TLS SNI (SNI Filter / Drop)",
        "description": "ТСПУ сбрасывает соединение при обнаружении доменного имени в ClientHello.",
        "recommendation": "Примените пресеты со сплитом TLS (split, multidisorder, fakesplit) или фейковым SNI.",
        "badge_text": "TLS SNI Drop (CRITICAL)",
        "badge_class": "badge-bad",
        "severity": "CRITICAL",
    },
    "HTTP_BLOCKPAGE": {
        "title": "HTTP-заглушка провайдера / РКН",
        "description": "Провайдер перенаправляет HTTP трафик на страницу с сообщением о блокировке.",
        "recommendation": "Используйте HTTPS или активируйте модуль tpws / nfqws http host case/fake.",
        "badge_text": "HTTP Заглушка (CRITICAL)",
        "badge_class": "badge-bad",
        "severity": "CRITICAL",
    },
    "QUIC_BLACKHOLE": {
        "title": "Блокировка QUIC / HTTP/3 (UDP Drop)",
        "description": "ТСПУ глушит UDP-трафик протокола QUIC (порт 443).",
        "recommendation": "Включите блокировку QUIC в настройках приложения для автоматического отката на TCP.",
        "badge_text": "QUIC Block (WARNING)",
        "badge_class": "badge-warn",
        "severity": "WARNING",
    },
    "IP_BLOCK": {
        "title": "Блокировка по IP-адресу (Routing / Drop)",
        "description": "Трафик к IP-адресу назначения полностью дропается на уровне маршрутизации.",
        "recommendation": "Обход DPI на L7 бессилен против блокировки IP; требуется прокси или альтернативный IP.",
        "badge_text": "IP Блокировка (CRITICAL)",
        "badge_class": "badge-bad",
        "severity": "CRITICAL",
    },
    "WHITELIST_RESTRICTION": {
        "title": "Режим «белых списков» (Внутренний контур)",
        "description": "Отечественные ресурсы (Яндекс, VK) доступны, тогда как все зарубежные узлы блокируются.",
        "recommendation": "Сетевая связность ограничена белыми списками провайдера / региона.",
        "badge_text": "Белый список (CRITICAL)",
        "badge_class": "badge-bad",
        "severity": "CRITICAL",
    },
    "SITE_ACCESS_RESTRICTED": {
        "title": "Сайт закрыт владельцем (403/429/Капча)",
        "description": "Сайт отвечает ошибкой авторизации, лимитом запросов или Cloudflare Turnstile/Капчей. Это не блокировка провайдера.",
        "recommendation": "ТСПУ не вмешивается: целевой ресурс сам ограничивает доступ для вашего клиента/IP.",
        "badge_text": "Ограничен сайтом (WARN)",
        "badge_class": "badge-warn",
        "severity": "WARNING",
    },
    "UNKNOWN": {
        "title": "Неопределенный статус блокировки",
        "description": "Характер проблемы не удалось однозначно идентифицировать сигнатурным анализом.",
        "recommendation": "Попробуйте запустить глубокий тест Blockcheck2 для подбора стратегии.",
        "badge_text": "Неизвестно (WARN)",
        "badge_class": "badge-warn",
        "severity": "WARNING",
    },
}

def get_verdict_words(key: str) -> dict:
    """Возвращает метаданные вердикта по ключу или дефолтный UNKNOWN."""
    return VERDICTS.get(key, VERDICTS["UNKNOWN"])
