@echo off
REM Сервер обновлений RC Foto — раздаёт release\tv на порту 8099.
REM Запусти после перезагрузки компьютера, чтобы ТВ видел обновления.
python "%~dp0update_feed_server.py"
pause
