# 6. Backup и recovery

До своего deploy сохраните connector code, private env и owner binding отдельно от публичного ZIP. Данные существующего агента резервируются его собственным штатным способом, а не этим connector. Код/MD бесплатны, private backups не публикуются.

```sh
python3 backup.py /safe/new-edge-backup --data-dir /srv/agent-phone/private
python3 backup.py /safe/new-edge-backup --verify
```

Backup пишет только в новый каталог, SQLite online backup и SHA receipt. Состав: owner-password.hash + edge.sqlite3. Проверка checksum и восстановление login/journal протестированы на синтетических данных. Там нет истории/памяти агента. Private env с provider keys резервируйте отдельно своим защищённым способом.

Восстановление: остановите только свой connector, сохраните его текущие данные; проверьте backup, перенесите проверенный каталог в новое private DATA_DIR, права 0700/0600, верните прежний env/binding, запустите только connector. Проверьте login → прежний agentId/conversationId → каноническую history. Смена binding блокируется, нужна осознанная проверка owner. Не сбрасывайте журнал «неизвестных» запросов ради повторного платного выполнения.

После restart unfinished turn отмечается unknown_after_restart. Audio/transcript/result RAM не восстанавливаются. Кнопка истории читает существующий backend. Реплика с прежним requestId заново не отправляется; текст уже мог быть сохранён у агента. При потерянном ответе сначала история, затем решение владельца о новом запросе.

Если забыта фраза входа: backup → остановить только connector → владельцу вручную переместить old hash и обнулить sessions в копии edge DB → снова интерактивный setup_owner. Не восстанавливайте доступ удалением памяти бота. Реальный server recovery и TLS/deploy пока требуют отдельной приёмки.
