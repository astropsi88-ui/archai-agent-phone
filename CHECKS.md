# Проверки и границы готовности

## Публичный кандидат — 13 октября 2026

На Windows проверена именно эта версия исходников: **20 из 20 Python-тестов пройдены** (39,544 секунды), без внешних провайдеров и платных вызовов. Исправлены закрытие SQLite при резервном копировании и ошибке привязки, обращение к локальному тестовому серверу и сохранение системных переменных при запуске тестового процесса в Windows. Дополнительно проверена гонка таймера: истёкший срок завершает голосовой запрос как `timed_out`, даже если callback таймера ещё не вызван.

На Linux та же версия кода также прошла **20 из 20 Python-тестов** (15,729 секунды). Проверены контрольные суммы всех 32 файлов payload извлечённого публичного архива. Квитанция и полный лог сохранены вне публичного пакета.

Независимая проверка пяти изменённых файлов не выявила блокирующих ошибок. Перечень файлов и контрольные суммы пересчитаны для публичного кандидата; исходный архив сохранён отдельно. Следующие результаты Chromium и 19 тестов относятся к исходному серверному комплекту и не означают повторную проверку браузера после этих правок.

TESTED на синтетическом existing runtime: 19 Python тестов; owner/Origin/Host/JSON/limits, pinned agent/conversation и owner isolation, TG→phone→TG history/memory continuity, HTTP→callable bridge, cancel до submit/STT/TTS, timeout, busy, ambiguous commit, replay и настоящий process restart, default-off provider gates, инъекционные gateway/OpenAI STT/TTS adapter проверки без внешних вызовов, audio TTL без платной регенерации, daily budget после restart, backup/restore/SHA/tamper.

TESTED в настоящем headless Chromium с синтетическим микрофоном: вход и история, AudioContext на gesture, одна отправка по stop, WAV 16 kHz mono PCM16, фон→mic stop без отправки записи, public-only CacheStorage, reconnect без POST replay, logout. Это browser acceptance, не приёмка на реальном телефоне и не прослушивание голоса.

UNTESTED/needs_human: ваш backend entrypoint/mapping, owner login на вашем сервере, реальные STT/TTS credentials/gateway, реальные речь/качество голоса/списания, iPhone/Android установка/микрофон/воспроизведение, публичные DNS/TLS/nginx/systemd deployment и восстановление production. Mock не заменяет этих проверок.

В ZIP есть `tests/test_connector.py` и `tests/fake_existing.py` — только синтетические fixtures. После распаковки из корня комплекта: `python3 tests/test_connector.py`. В тестах нет платных вызовов. Фразы и токены тестов искусственные и не подходят для production. SHA256SUMS и MANIFEST.json описывают payload (не самих себя). ZIP checksum рядом с архивом. Самопроверка checksum: `sha256sum -c SHA256SUMS`.

## Проверки обновления 14 октября 2026

20 исходных Python-тестов и 9 новых attachment transport/linkage тестов PASS на Windows. Среди новых проверок — реальные HTTP-запросы через локальный bridge к синтетическому runtime, файл без текста, текст/завершённый голос+fileIds, потерянная квитанция, восстановление edge-процесса без повторного append, типы/размеры/owner/Origin и fingerprint. 29 UI, 12 SW/cache и 12 supplied-decision проверок выполняют настоящие JS-модули в synthetic VM, без настоящего браузера, микрофона, модельной классификации или провайдера. Node 18+ нужен только для этих offline JS-тестов.

Публичный live PDF parser/media reader, durable storage вашего runtime, настоящий мобильный autoplay, all-page content понимание, и end-to-end work dispatch не приняты. Тестовая FileRuntime хранит только искусственные данные в памяти и не является production storage. Не переносите её в рабочий агент. Предыдущее Chromium/mock и Linux доказательство относится к прежнему неизменному коду и не является Linux-проверкой этой версии. Подробнее [обновление](route/07_ATTACHMENTS_AND_UPDATES.md).
