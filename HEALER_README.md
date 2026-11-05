# Auto-Healing System для Zapret GUI

## Что добавлено

### 1. healer.py - Auto-Healing Daemon
Фоновый демон, который:
- Проверяет доступность Google, YouTube, Discord, Cloudflare каждые 30 секунд
- При 3+ подряд сбоях автоматически перезапускает движок
- При повторных сбоях переключает на следующий пресет
- Защита от бесконечных рестартов (max 10 в час, cooldown 60 сек)
- Логирование в /tmp/zapret-healer.log

### 2. Watchdog в engine.sh
- Скрипт /tmp/zapret-watchdog.sh проверяет:
  - Жив ли процесс nfqws
  - Существуют ли nftables правила
- При сбое автоматически рестартует zapret-nfqws
- Запускается как systemd service

### 3. MirrorHealthMonitor в updater.py
- Фоновая проверка зеркал каждые 5 минут
- Автоматическое переключение на живое зеркало
- Уведомление если все зеркала недоступны

### 4. UI в main.py
- Переключатель Auto-Healing в настройках
- Индикатор статуса healer
- Автоматический запуск/остановка при старте/выходе

## Как использовать

1. Включи Auto-Healing в настройках (по умолчанию включено)
2. Демон автоматически следит за соединением
3. При сбоях сам перезапускает/переключает пресеты
4. Логи: /tmp/zapret-healer.log и /tmp/zapret-gui.log

## Ручное управление

```bash
# Проверить статус healer
python3 -c "from healer import get_healer; h = get_healer(); print(h.get_status())"

# Запустить healer вручную
python3 healer.py

# Посмотреть логи
tail -f /tmp/zapret-healer.log
```
