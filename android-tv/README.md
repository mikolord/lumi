# lumi для Android TV и Huawei Vision S

Нативный клиент личной фототеки. Для просмотра нужен установленный сервер Lumi в Docker: [инструкция](../README.md).

[Скачать APK](https://github.com/mikolord/lumi/releases/download/tv-v0.7.4/lumi-tv-0.7.4.apk) · [Все выпуски](https://github.com/mikolord/lumi/releases)

## Возможности

Вход по паролю или QR, альбомы, люди, фото и видео, слайд-шоу, изменение плотности сетки и переход по датам с пульта. Выход в верхнюю навигацию с левого края и открытие таймлайна с правого.

Зашифрованный кэш миниатюр хранится на устройстве; повторный показ проверяет доступ к файлам на сервере. Защищённые фотографии и оригиналы не сохраняются в этот кэш.

## Сборка и выпуск

Нужны JDK 21 и Android SDK 35. Запусти `build.ps1`: он выполнит JVM-тесты, сборку, lint и проверку подписи, затем подготовит APK и `release/tv/version.json`. Для обновления поверх существующей установки используй прежний ключ подписи. Приватные ключи в Git не добавляются.

После коммита и отправки исходников выполни `python release/publish_github.py --source-commit <SHA коммита публичного репозитория>`. Скрипт получает учётные данные из Git Credential Manager, создаёт релиз `tv-vX.Y.Z`, прикладывает APK и публикует манифест в ветке `tv-updates`. В приложение GitHub-токен не встраивается.

Приложение запрашивает `https://raw.githubusercontent.com/mikolord/lumi/tv-updates/tv/version.json`, затем скачивает APK по прямой ссылке GitHub Releases. Проверка пакета, версии, SHA-256 и подписи остаётся обязательной.

## Плитка Huawei Vision S

Запускаемая MainActivity объявляет широкую картинку 496×280 как `icon`, `banner` и `logo`, одновременно с CATEGORY_LAUNCHER и CATEGORY_LEANBACK_LAUNCHER. Это следует примеру Huawei Vision S: https://forums.developer.huawei.com/forumPortal/en/topic/0202585440415910074 . В 0.7.4 одна широкая карточка назначена также на уровне application: icon, banner и logo. Это исключает выбор квадратной иконки приложения вместо карточки запускаемого экрана. Сборка проверяет готовый APK скриптом release/Test-Launcher.ps1.
