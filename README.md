# FinderBot

Telegram-бот: **песни по названию через Soulseek** и **видео по ссылке**
(YouTube / TikTok / Instagram).

## Возможности

- 🎵 Пользователь присылает название («артист - трек») → поиск в Soulseek через
  [sockseek](https://github.com/fiso64/sockseek) → список найденных файлов
  кнопками (формат · битрейт · размер) → бот скачивает и отправляет mp3/flac
  с обложкой и тегами.
- 🎬 Присылает ссылку (YouTube/TikTok/Instagram — настраиваемый список) →
  yt-dlp выбирает лучший формат, бот отправляет mp4 под лимит Telegram 50 МБ;
  длинные видео сжимаются ffmpeg'ом (x264, двухпроход), сверхдлинные можно
  получить как аудио-mp3.
- 🔐 **Публичный бот с личными аккаунтами**: каждый пользователь подключает
  свой Soulseek-логин через `/login` (пароль шифруется Fernet и хранится
  в SQLite; сообщения с паролем удаляются из чата). Владелец может
  пользоваться дефолтными кредами из `.env`.
- ⚙️ Очередь задач (воркеры, лимит на пользователя), прогресс с редактированием
  сообщения, рейт-лимит, кэш `file_id` (повторная ссылка репостится без
  повторной загрузки), только личные чаты.

## Быстрый старт (Windows)

```bat
git clone https://github.com/hertbex/FinderBot.git
cd FinderBot
start.bat          :: venv + pip install + install_tools + запуск
```

Первый запуск создаст `.venv`, поставит зависимости и скачает в `tools/bin`
свежие **sockseek.exe**, **ffmpeg.exe**, **ffprobe.exe** (SHA-256 sockseek
проверяется по релизу v3.0.6).

Перед запуском:

1. `.env.example` → скопируйте как `.env`
2. вписать `BOT_TOKEN` (от [@BotFather](https://t.me/BotFather))
3. желательно `ADMIN_USER_ID` (свой ID — [@userinfobot](https://t.me/userinfobot))
4. для песен без логина — можно задать свои `SOULSEEK_USER`/`SOULSEEK_PASS`
   (используются, только если ботом пользуетесь вы сами, и никак иначе)

Проверка окружения: `python scripts/doctor.py`.

## Запуск на VPS (Docker)

```bash
git clone https://github.com/hertbex/FinderBot.git && cd FinderBot
cp .env.example .env && nano .env    # BOT_TOKEN и ADMIN_USER_ID
docker compose up -d --build
docker compose logs -f
```

Образ содержит ffmpeg; sockseek linux-x64 ставится при сборке (SHA подписан).
Данные: `./data` (SQLite + ключ), `./downloads` (временные файлы).

> ⚠️ С датацентровых IP YouTube часто требует капчу — укажите
> `YTDLP_PROXY` (например, резидентный socks5). Instagram нынче требует
> login для залоченных постов — положите `cookies.txt` (Netscape) и укажите
> путь в `YTDLP_COOKIES`.

## Команды бота

| Команда   | Что делает                                                        |
|-----------|-------------------------------------------------------------------|
| `/start`  | приветствие                                                       |
| `/help`   | справка                                                           |
| `/login`  | подключить свой Soulseek-аккаунт (FSM в личке)                    |
| `/me`     | какой аккаунт подключён                                           |
| `/logout` | отвязать аккаунт                                                  |
| `/status` | ваши задачи и состояние очереди                                   |
| `/cancel` | отменить текущую задачу/ввод                                      |

Чтобы скачать музыку: пришлите **любой текст**, не являющийся ссылкой, —
например `Radiohead - Creep`.
Чтобы скачать видео: пришлите **ссылку** на YouTube/TikTok/Instagram.

## Soulseek аккаунт

SLSK-сеть требует аккаунт; регистрация на [slsknet.org](https://www.slsknet.org/news/index.php)
периодически закрыта — если у вас его нет, заранее достаньте (или воспользуйтесь
никотин-билдами с собственным логином). Бот держит бесплатный слушающий порт
выключенным (`--no-listen`) — соединения идут в пассивном режиме.

## Куда смотреть в коде

```
src/finderbot/
├── app.py            # сборка: сервисы, роутеры, Dispatcher
├── config.py         # все настройки (.env, pydantic-settings)
├── middleware/       # доступ (только ЛС) + рейт-лимит
├── routers/
│   ├── auth.py       # /login FSM, удаление сообщений с паролем
│   ├── song.py       # поиск/кнопки/очередь mp3
│   ├── video.py      # ссылки/сжатие/аудио-fallback
│   └── start.py      # команды
├── services/
│   ├── queue.py      # пул воркеров, per-user лимиты, отмена
│   ├── progress.py   # троттилинг-редактирование прогресса
│   └── sender.py     # отправка с кэшем file_id
├── storage/          # sqlite + Fernet-шифрование паролей
├── tools/
│   ├── sockseek.py   # async-обёртка CLI, парсинг --print-json-full
│   ├── ytdlp.py      # probe/download, формат-стратегии
│   ├── ffmpeg.py     # двухпроходное сжатие, обложки, превью
│   └── videoplan.py  # решение: купить/сжать/аудио/отказ
└── utils/            # allowlist хостов, форматирование
tests/                # pytest: сокет без сети, отмена, парсеры
```

## Изменение лимитов

`.env`: `WORKERS`, `QUEUE_PER_USER`, `REQUESTS_PER_MINUTE`, `MAX_FILE_MB`,
`MAX_VIDEO_MINUTES`, таймауты поиска/скачивания.

## Дисклеймер

Бот — оболочка над вашим личным доступом к интересным вам источникам.
Файлы после отправки удаляются (`KEEP_FILES=false`). Пожалуйста, не занимайтесь
распространением защищённого контента.
