# KeyDeck

KeyDeck — приложение для Windows, превращающее рабочий стол в настраиваемую панель быстрого доступа, похожую на Stream Deck.

- компактное окно и значок в системном трее;
- сетка кнопок, несколько страниц и переход между ними колёсиком мыши;
- назначение действий и сочетаний клавиш на кнопки;
- плагины с отдельными настройками;
- уведомление о новых версиях и обновление прямо из приложения.

## Установка для пользователей

1. Откройте [последний релиз KeyDeck](https://github.com/Scworch/KeyDeck/releases/latest).
2. Скачайте файл `KeyDeck-vX.Y.Z.exe` и сохраните его в постоянную папку, например:
   `%LOCALAPPDATA%\Programs\KeyDeck\KeyDeck.exe`.
3. Запустите `KeyDeck.exe`. При запросе Windows подтвердите запуск с правами администратора.

Для использования релизной версии Python и отдельная установка зависимостей не нужны. Не запускайте программу прямо из временной папки загрузок: обновление заменяет EXE по его текущему пути.

Windows Defender SmartScreen может показать предупреждение, так как релиз пока не подписан цифровым сертификатом. Перед запуском проверяйте источник загрузки и SHA-256 в `SHA256SUMS.txt`, приложенном к релизу.

### Настройки и обновления

Исполняемый файл находится в выбранной вами папке, а пользовательские данные — отдельно:

- `%LOCALAPPDATA%\KeyDeck\config\settings.json` — конфигурация панели;
- `%LOCALAPPDATA%\KeyDeck\plugins\` — настройки и кэши плагинов.

Обновление заменяет только EXE, проверяет его SHA-256 и сохраняет пользовательские данные. Перед установкой новая версия скачивается во временную папку; при ошибке замены восстанавливается предыдущий EXE. Программа проверяет GitHub Releases при запуске и предлагает установить обновление; проверить вручную можно через меню значка в трее → **Check for Updates**.

Релизные сборки рассчитаны на Windows x64. Они собираются из исходников проекта GitHub Actions при публикации тега `vX.Y.Z`.

## Ярлык на рабочем столе

Замените путь, если установили EXE в другую папку, и выполните в PowerShell:

```powershell
$exe = Join-Path $env:LOCALAPPDATA 'Programs\KeyDeck\KeyDeck.exe'
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut(
    (Join-Path $env:USERPROFILE 'Desktop\KeyDeck.lnk')
)
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = Split-Path $exe
$shortcut.Save()
```

Для ярлыка в меню «Пуск» используйте путь `%APPDATA%\Microsoft\Windows\Start Menu\Programs\KeyDeck.lnk`.

## Запуск через Task Scheduler

У KeyDeck есть настройка автозапуска: включите её в настройках приложения, чтобы оно зарегистрировало задание `KeyDeck_AutoStart`. Если нужно создать задачу вручную, запустите PowerShell от имени администратора, проверьте путь к EXE и выполните:

```powershell
$exe = Join-Path $env:LOCALAPPDATA 'Programs\KeyDeck\KeyDeck.exe'
$action = New-ScheduledTaskAction -Execute $exe -WorkingDirectory (Split-Path $exe)
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'KeyDeck' -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force
```

Удалить задачу:

```powershell
Unregister-ScheduledTask -TaskName 'KeyDeck' -Confirm:$false
```

Для запуска приложения достаточно войти в свою учётную запись Windows; не выбирайте запуск без входа пользователя, так как KeyDeck использует интерактивный рабочий стол и системный трей.

## Установка из исходников

Для разработки или запуска без готового релизного EXE установите Python 3.11+ и выполните в корне репозитория:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m keydeck
```

Сборка Windows EXE локально:

```powershell
python -m pip install -r requirements-build.txt
python scripts\build_executable.py
```

Сборка создаёт `dist\KeyDeck.exe` из файлов проекта, исключая игнорируемые локальные настройки и кэши. Автоматическое обновление заменяет только релизный EXE; запуск из исходников покажет страницу релиза, откуда можно скачать готовую сборку.

## Плагины и совместимость

Плагины находятся в `plugins/<plugin_name>/`. `manifest.json` определяет точку входа, `plugin.py` содержит логику, а локальные настройки и кэши хранятся отдельно от программы.

- **ResolutionSwitcher** меняет разрешение через стандартный Windows Display API. Целевой режим должен поддерживаться монитором и драйвером.
- **NVIDIA RTX Video Super Resolution** использует NVIDIA NvCpl API. Ему необходимы поддерживаемая RTX-видеокарта, совместимый драйвер и установленное приложение NVIDIA App. На ПК без подходящего оборудования эта функция недоступна; другие плагины KeyDeck продолжат работать.
- **Wave Link** требует установленного Wave Link и совместимого .NET Framework runtime; для перенаправления аудио дополнительно используется Windows COM audio API.

## Данные и конфиденциальность

Настройки слотов, параметры плагинов и кэши остаются на компьютере пользователя. Они не входят в релизный EXE и не удаляются при обновлении. Файл `.gitignore` исключает локальные настройки и кэши плагинов из Git.

## Лицензия

KeyDeck распространяется по лицензии MIT. См. [LICENSE](LICENSE).
