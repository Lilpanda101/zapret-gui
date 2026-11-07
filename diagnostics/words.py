"""
diagnostics/words.py - Единственный источник правды (SSOT) для фраз BlockCheck,
статусов доступности, рекомендаций и текстов ошибок диагностики.
"""

from typing import Any, Dict

# Статусы экспресс-проверок и карточек
STATUS_NOT_CHECKED = "Не проверялось"
STATUS_CHECKING = "Проверка..."
STATUS_BLOCKED_OR_TIMEOUT = "Заблокирован / Таймаут"
STATUS_ERROR = "Ошибка (ERROR)"
STATUS_DIAGNOSTICS_RUNNING = "Запуск глубокой диагностики ТСПУ..."
STATUS_BLOCKCHECK2_PREPARING = "Подготовка Blockcheck2. Текущий движок будет остановлен...\n"

# Семейства и типы блокировок
VERDICTS: Dict[str, Dict[str, Any]] = {
    "PASS": {
        "title": "Блокировка не обнаружена",
        "description": "Цензура и фильтрация ТСПУ не обнаружены. Ресурс доступен напрямую.",
        "recommendation": "Специальные правила обхода и desync не требуются.",
        "badge_text": "Доступен (PASS)",
        "badge_class": "badge-ok",
        "severity": "PASS",
    },
    "DNS_SPOOFING": {
        "title": "Подмена DNS (DNS Spoofing / Poisoning)",
        "description": "Провайдер или ТСПУ перехватывает DNS-запросы и возвращает фиктивный/заглушечный IP с недостоверным сертификатом.",
        "recommendation": "Включите шифрованный DNS (DoT / DoH) в настройках или DNS-AI / Cloudflare.",
        "badge_text": "DNS подмена (CRITICAL)",
        "badge_class": "badge-bad",
        "severity": "CRITICAL",
    },
    "DNS_NO_ADDRESS": {
        "title": "Не удалось узнать адрес сервера",
        "description": "DNS компьютеру не называет адрес хоста (NXDOMAIN / SERVFAIL). Браузер без DoH не откроет сайт.",
        "recommendation": "Проверьте DNS-серверы системы или переключитесь на DoT/DoH в настройках.",
        "badge_text": "Нет адреса (FAIL)",
        "badge_class": "badge-bad",
        "severity": "CRITICAL",
    },
    "TCP_RST_INJECTION": {
        "title": "Внедрение TCP RST (RST Injection)",
        "description": "ТСПУ внедряет инъекционные TCP RST пакеты при установлении соединения.",
        "recommendation": "Используйте пресеты с разделением SYN/ACK или фильтрацией RST (fake, syndata).",
        "badge_text": "TCP RST инжект (CRITICAL)",
        "badge_class": "badge-bad",
        "severity": "CRITICAL",
    },
    "TLS_SNI_DROP": {
        "title": "Сброс по TLS SNI (SNI Filter / Drop)",
        "description": "ТСПУ отбрасывает пакеты ClientHello со сбросом соединения при обнаружении TLS SNI.",
        "recommendation": "Примените фрагментацию TLS SNI (split2/multisplit) или пресеты со сплитом TLS (split, multidisorder, fakesplit).",
        "badge_text": "TLS SNI сброс (CRITICAL)",
        "badge_class": "badge-bad",
        "severity": "CRITICAL",
    },
    "TLS_REPLY_WINDOW": {
        "title": "Фильтрация по первым байтам ответа (Reply Window)",
        "description": "Фильтр режет TLS с адреса по первым байтам ответа сервера в пределах окна приёма. С окном 1 байт ответ доходит дважды, а с 1 КБ сбрасывается.",
        "recommendation": "Используйте модификацию размера окна TCP (параметр wssize в nfqws/winws2).",
        "badge_text": "Окно ответа (CRITICAL)",
        "badge_class": "badge-bad",
        "severity": "CRITICAL",
    },
    "HTTP_BLOCKPAGE": {
        "title": "HTTP-заглушка провайдера / РКН",
        "description": "Провайдер перенаправляет HTTP трафик на страницу с сообщением о блокировке.",
        "recommendation": "Используйте HTTPS или активируйте модуль tpws / nfqws http host case/fake.",
        "badge_text": "HTTP заглушка (WARNING)",
        "badge_class": "badge-warn",
        "severity": "WARNING",
    },
    "QUIC_BLACKHOLE": {
        "title": "Блокировка QUIC / HTTP/3 (UDP Drop)",
        "description": "ТСПУ глушит UDP-трафик протокола QUIC (порт 443).",
        "recommendation": "Включите блокировку QUIC в настройках приложения для автоматического отката на TCP.",
        "badge_text": "QUIC блокировка (WARNING)",
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
        "description": "Разрешённые имена (max.ru, ya.ru, vk.com) отвечают, а тестируемый хост и нейтральные блокируются.",
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
    "UNSTABLE": {
        "title": "Сайт открывается через раз",
        "description": "Соединение то проходит, то обрывается: нестабильный фильтр, потеря пакетов или плавающий DPI.",
        "recommendation": "Проверьте стабильность пресета или подберите стратегию с повышенной устойчивостью.",
        "badge_text": "Через раз (WARN)",
        "badge_class": "badge-warn",
        "severity": "WARNING",
    },
    "CUT_WINDOW": {
        "title": "Сайт грузится не до конца",
        "description": "Соединение успешно устанавливается, но обрывается на передаче данных (обрыв 12–36 КБ).",
        "recommendation": "ТСПУ блокирует передачу больших пакетов; используйте деление потока (split/disorder) или wssize.",
        "badge_text": "Не до конца (FAIL)",
        "badge_class": "badge-bad",
        "severity": "CRITICAL",
    },
    "SECONDARY_BROKEN": {
        "title": "Основной сайт открывается, но сломаны вторичные",
        "description": "Главная страница доступна, но вспомогательные ресурсы (CDN, медиа, API) блокируются.",
        "recommendation": "Добавьте сопутствующие домены в список обхода или используйте пресет с глобальным перехватом.",
        "badge_text": "Вторичные сбои (WARN)",
        "badge_class": "badge-warn",
        "severity": "WARNING",
    },
    "TIMEOUT": {
        "title": "Таймаут соединения (Timeout)",
        "description": "Превышено время ожидания ответа: возможен глубокий сброс пакетов ТСПУ или недоступность маршрута.",
        "recommendation": "Проверьте сетевой маршрут к серверу или используйте альтернативные DNS/IP адреса.",
        "badge_text": "Таймаут (WARNING)",
        "badge_class": "badge-warn",
        "severity": "WARNING",
    },
    "ERROR": {
        "title": "Ошибка выполнения диагностики",
        "description": "Произошел внутренний сбой сетевого сокета или ошибка разрешения доменного имени.",
        "recommendation": "Проверьте подключение к интернету и корректность написания доменного адреса.",
        "badge_text": "Сбой теста (ERROR)",
        "badge_class": "badge-bad",
        "severity": "CRITICAL",
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

def get_verdict_words(key: str) -> Dict[str, Any]:
    """Возвращает метаданные вердикта по ключу или дефолтный UNKNOWN."""
    return VERDICTS.get(key, VERDICTS["UNKNOWN"])
