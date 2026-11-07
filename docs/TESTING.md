# Перевірки за областю зміни

Backend-команди виконуються з `backend/` з активованим наявним venv:

```bash
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
# .\.venv\Scripts\Activate.ps1
python -m ruff check app/<changed_file>.py tests/test_<feature>.py
python -m ruff format --check app/<changed_file>.py tests/test_<feature>.py
python -m pytest tests/test_<feature>.py tests/test_<consumer>.py
```

Замінювати `<...>` реальними шляхами. `python` має належати venv; без активації використовувати `.venv/bin/python` або `.venv/Scripts/python.exe`. Форматування — окрема явна операція лише над зміненими файлами. Claude hooks не запускають backend-wide auto-fix чи повний pytest автоматично.

Матриця задає стартовий набір; додати consumers зміненої межі. Усі backend test paths нижче стосуються `backend/tests/`.

| Зміна | Перевірки |
|---|---|
| GSI / сигнали | `test_gsi_samples_and_advice.py`, `test_gsi_in_match.py`, `test_spectator_gsi.py`, `test_fuzz_live_gsi.py`; skill/position tests у разі дотику |
| Decision / policy / coaches | `test_decision_points_recommender.py`, `test_hero_safety.py`, `test_laning_post_laning_coaches.py`; hero/support cases; `test_advice_i18n.py` у разі зміни видимого тексту |
| Scheduler / frequency / shared state | Усі `test_evaluate_*_gate.py`, `test_scheduler_spacing.py`, `test_scheduler_state_snapshot.py`, `test_advice_frequency.py`, `test_replay_demo_data.py`; широкий state refactor → увесь backend |
| Tracker / store / persistence | `test_player_history.py`, `test_history_backup.py`, `test_backup_atomicity.py`, `test_cache_corruption.py`, `test_match_notes.py`, `test_match_advice_log.py`; нові failure/restart/thread cases; `test_packaging_runtime.py` у разі paths/lifecycle |
| Analysis / facts | `test_player_history.py`, пов'язані role/lane/build/death tests, `test_personal_baseline.py`, `test_focus_goal.py`; перевірити review/cache versions |
| AI client / facts / questions | `test_coach_ai.py`, `test_diagnostics.py`; fake providers, metric swaps, total deadline/idempotency; без live AI викликів |
| Profile / cosmetics / friends | `test_player_profile.py`, `test_cosmetics.py`, `test_friend_compare.py`; launcher `test/friends.test.js`, Worker profile tests у разі public contract |
| HTTP / logging / IPC | `test_api_smoke.py`, `test_diagnostics.py`, відповідний feature suite; launcher syntax + відповідний Node test; Electron smoke для main/preload/backend boundary |
| Launcher helper | З `frontend/launcher/`: `node --test test/<feature>.test.js`, `npm run check`; увесь `npm test` допустимий перед здачею |
| Renderer / locales / CSS | Launcher `test/i18n.test.js` + relevant helpers; реальні DOM-сценарії та UK/EN на підтримуваних масштабах для layout/interaction |
| Записи матчів за згодою | `test_match_records.py`, `test_match_record_upload.py` (очищення копії, відсутність нік/ID/токена/номера матчу/часу в байтах), `test_fetch_recordings.py`; launcher `test/match-upload.test.js`; Worker `test/session.test.js`, `api.test.js`, `test/integration/sessions.test.js` (справжній local D1 + R2) |
| Worker | З `services/api/`: `npm test`; SQL/retention/concurrency додатково потребують local D1 + migrations |
| Hero / meta data | `test_hero_coverage.py`, `test_core_heroes.py`, `test_supports.py`, `test_stratz_builds.py` і відповідна live-логіка; site generator check |
| Packaging / dependencies | `test_packaging_runtime.py`, launcher `test/package-files.test.js`, full affected suites, clean install і Windows build/smoke |
| Release notes / generated site | `build_changelog.py --check`, `build_site.py --check`; звичайна правка тексту не потребує повного backend чи NSIS |

Shell glob передається native pytest по-різному в bash і PowerShell. Для scheduler-перевірок розгортати шляхи переносно з `backend/`:

```bash
python -c "import pathlib,subprocess,sys; paths=sorted(str(p) for p in pathlib.Path('tests').glob('test_evaluate_*_gate.py')); paths += ['tests/test_scheduler_spacing.py','tests/test_scheduler_state_snapshot.py','tests/test_advice_frequency.py','tests/test_replay_demo_data.py']; sys.exit(subprocess.call([sys.executable,'-m','pytest',*paths]))"
```

Невідомий шлях, shared schema/config/store/main/preload, залежності чи міжшаровий refactor потребують ширших перевірок зачепленої підсистеми. Перевірити staged, unstaged і untracked зміни. Новий data-workflow PR може не запустити CI, бо його створено workflow token: до злиття перевірити diff і виконати backend tests локально.

## Повна перевірка

З `backend/` з активним venv:

```bash
python -m ruff check .
python -m ruff format --check .
python ../scripts/check_types.py
python -m mypy --strict ../scripts/check_types.py
python -m pytest --junitxml=/tmp/wardly-backend-tests.xml
python -m compileall -q app scripts packaging tests
python ../scripts/build_changelog.py --check
python ../scripts/build_site.py --check
```

На Windows шлях XML замінити на доступний тимчасовий файл. Зберегти exit status pytest і перевірити поточний XML: tests > 0, failures/errors = 0; skipped повідомляти окремо. Locked mypy gate блокує нові помилки й вимагає видаляти resolved allowances; 176 наявних помилок залишаються відомим боргом. Команди prune і межі перевірки — [TYPE_CHECKING.md](TYPE_CHECKING.md).

З `frontend/launcher/`: `npm run check`, `npm test`. З `services/api/`: `npm test` запускає unit tests та integration tests transfer на справжньому local D1/Miniflare. Окремо доступні `npm run test:unit` і `npm run test:integration`. Backend tests використовують TestClient + SQLite і чисті domain modules; інші Worker SQL paths поки використовують fake D1/R2, тому в разі зміни їхньої атомарності треба розширювати реальні D1 перевірки. Межі harness — [TRANSFER_ATOMICITY.md](TRANSFER_ATOMICITY.md).

`backend/tests/conftest.py` скидає shared state, вимикає OpenDota й зазвичай не запускає фонових threads. Зміни queue/lifespan перевіряти справжніми threads + Events і context-managed TestClient. Fault tests перевіряють recovery/rollback/відповідь користувачеві; не послаблювати assertions і не замінювати перевірку zero-test запуском.

## Runtime і збирання

Launcher сам запускає backend. Standalone dev-сервер: з `backend/` `USE_LLM=false OPENDOTA_ENABLED=false python -m uvicorn app.main:app --reload`; не запускати його паралельно для налагодження launcher. Перевірити `/health` і функціональний запит, а не лише PID/порт.

На Linux без дисплея, з `frontend/launcher/` зі встановленими Electron і Xvfb:

```bash
xvfb-run -a ./node_modules/.bin/electron . --no-sandbox --smoke-test=/tmp/wardly-smoke.json
```

Використовувати новий result path або прибрати власний попередній результат перед запуском. Перевірити exit status і JSON поточного запуску: `ok=true`, усі steps успішні, зокрема відмальовування обох вікон, player API, recommendation і graceful shutdown. У підготовленому cloud-середовищі спершу `source /workspace/.local/share/dota-ai-coach/headless-env.sh`. Localhost-запити слугують внутрішньою перевіркою.

Для Ctrl+K перевірити на справжньому Electron: відкриття палітри, пошук Settings, Enter, порожній результат і Escape. Збереженого regression harness поки немає. `scripts/site-shots/` містить real-renderer screenshot helpers, які можна використати під час його додавання.

Windows packaging: з кореня `scripts/build-windows.ps1`, потім `scripts/smoke-windows.ps1`. `-SkipBackend` підходить лише frontend-змінам за наявності валідного backend build; release потребує повного build. Linux Electron smoke не замінює Windows installer, watcher і реальної Dota GSI перевірки.

Linux packaging: з кореня `scripts/build-linux.sh` (потрібні `libarchive-tools`/`bsdtar`, `zstd`, для smoke ще `xvfb`), потім `scripts/smoke-linux.sh`: backend `/health` і права 0700/0600, `--smoke-test` розпакованого застосунку та AppImage (`--appimage-extract-and-run`) під `xvfb-run`, вміст і метадані `.pacman`/`.deb`. Це не перевіряє реальний робочий стіл, overlay поверх Dota і трей; див. [PACKAGING_LINUX.md](PACKAGING_LINUX.md). Backend: `python -m pytest tests/test_packaging_runtime.py`.

Після перевірки: `git diff --check`, перегляд фінального diff і untracked files. Логи, SQLite, записи матчів і локальні результати не комітити. Звіт має розрізняти passed, failed, skipped і unrun перевірки. Portable runner і version gate: [DEV_RUNNER.md](DEV_RUNNER.md); `python scripts/dev.py check --changed --dry-run` показує поточні шляхи, profiles, argv і cwd. Actual Electron smoke й local D1 harness уже існують; їхні межі описано вище.

## Перевірити виправлення на записі (0.53.58)

`backend/scripts/replay_check.py` проганяє чотири очищені синтетичні матчі — керрі (Juggernaut), мід (Shadow Fiend), офлейн (Axe), саппорт (Crystal Maiden) — через увесь живий шлях (`/gsi` → `/overlay/recommendation`, годинник планувальника = годинник гри) і порівнює показані поради й підказки мапи з прийнятими результатами в `backend/tests/replay_golden/<case>.json`. Рядок результату — `MM:SS DECISION_POINT mode`: що й коли показано, без формулювання, тому правка тексту не вважається зміною поведінки. Перед кожним кейсом стан застосунку скидається як у `tests/conftest.py`, результат не залежить від порядку.

```
cd backend
python scripts/replay_check.py                      # усі кейси, різниця з прийнятими
python scripts/replay_check.py --case offlane_axe --text   # з текстом карток
python scripts/replay_check.py --update             # прийняти нову поведінку (дифф — у PR)
```

`tests/test_replay_golden.py` запускає всі кейси (~35 с) і в разі розбіжності друкує додані та зниклі рядки й команду для відтворення. Зміна live-правил, планувальника, decision points чи підказок мапи потребує цього тесту; навмисна зміна поведінки оновлює еталони в тому самому PR.
