# 3. Защищённый вход

Скопируйте только connector на свой сервер. Создайте отдельного непривилегированного пользователя и private data (0700), например `/srv/agent-phone/private`. Не используйте private data Telegram-агента как DATA_DIR. Локальная SQLite хранит только auth, binding, fingerprint/status/budget, без сообщений, транскриптов и памяти.

На своей машине/сервере из connector:

```sh
python3 setup_owner.py --data-dir /srv/agent-phone/private
python3 server.py --data-dir /srv/agent-phone/private --port 8765
```

Сначала установите server env по `env.example`: реальные EXISTING_* из вашего runtime; private connector token; APP_ORIGIN. Вход — ваша новая фраза, вводится интерактивно. Не передавайте её через argv и не публикуйте env/hash/SQLite. Секреты хранятся только на сервере, env file 0600. Формат файла для systemd EnvironmentFile — не shell script.

Без конфигурации получите `needs_human_existing_agent_adapter`/owner setup. Голос по умолчанию выключен. Не копируйте credentials другой системы.

Server слушает 127.0.0.1. Для телефона выставьте HTTPS APP_ORIGIN и dedicated domain root, proxy из `connector-deploy/` после подстановки собственного домена/TLS. `nginx -t` до применения. Cookie HttpOnly/SameSite=Strict/Secure на HTTPS. POST требует точного Origin; Host закреплён. Не доверяем forwarded owner IDs. Не открывайте 8765/8766 наружу, не разрешайте CORS.

Service/nginx — UNTESTED deploy templates, не команда менять действующий бот. TLS/DNS/login на вашем сервере требуют owner acceptance. Отдельный connector нельзя использовать как proxy произвольных URLs или shell/tools.
