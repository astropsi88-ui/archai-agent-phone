# 2. Подключить существующий runtime

`contract.py` содержит `HTTPAdapter` и `CallableAdapter`. Binding только server-side: `agentId`, `conversationId`, `ownerId`. Ответ runtime повторяет все три поля; browser получает только agentId/conversationId и разрешённые сообщения. Несовпадение даёт ошибку.

HTTP контракт: только server-to-server POST `/connector/describe`, `/connector/history`, `/connector/turn`; JSON, Bearer token, HTTPS или loopback. Redirect запрещён. Describe возвращает binding. History принимает binding + limit=100 и возвращает binding + messages. Turn принимает binding + message + UUID requestId + channel (`phone-text`/`phone-voice`); возвращает binding + assistant message + replayed. Message: `{id: string, role: user|assistant, content: string}`. History — не более 100 сообщений, сообщение — не более 12000 символов. Обход получения истории через Telegram sendMessage не подходит.

Runtime обязан авторизовать owner mapping, вести durable idempotency, хранить user+assistant в своей canonical history, сериализовать каналы. При неоднозначном исходе requestId повторно не выполняется connector. Даже после его restart. В существующем runtime дедупликация также обязательна.

Для TG-only Python runtime готов `tg_runtime_bridge.make_bridge(existing_service, ...)`. Это маленький loopback HTTP server в уже работающем процессе. `existing_service.describe(payload)`, `.history(payload)` и `.turn(payload, cancel=Event, deadline=monotonic)` должны быть вашим facade к действующему callable. Передайте существующий объект; не фабрику нового агента. Пример внизу файла показывает подключение потока. Если ваш callable async — facade безопасно планирует его в существующий loop и ждёт ограниченное время. Конкретные имена entrypoint зависят от вашего бота; автоматической совместимости нет.

HTTP разрыв не доставляет cancellation событие в remote runtime немедленно. Пример bridge имеет свой deadline 15 секунд; adapter ждёт максимум 15 секунд. Прерывание прекращает следующий этап/STT/TTS/звук. Уже сохранённая реплика может остаться в canonical history: обновите её. Runtime обязан сам ограничивать обработку. При in-process CallableAdapter Event передаётся напрямую.

## Необязательное расширение fileIds

turn принимает до трёх fileIds. message может быть пустым при наличии файлов; оригиналы и fileIds атомарно связывает существующий runtime. Не включайте attachments=true без полного upstream файлового контракта. [Подробности](07_ATTACHMENTS_AND_UPDATES.md).
