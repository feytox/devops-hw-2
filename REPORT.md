# Отчёт

Окружение: CachyOS (Linux 7.2.9), Docker 29.8.2, Compose 5.6.0, dive 0.13.1.

Стек `notes-hw2`:
- `web`: nginx, сеть front, порт 18090
- `app`: Flask, сети front + back
- `db`: postgres:18, сеть back (тут хранятся заметки)
- `cache`: redis, сеть back (здесь счётчик посещений)

## 1. Запуск

```
$ docker compose up -d --build --wait && docker compose ps
NAME                SERVICE   STATUS                   PORTS
notes-hw2-app-1     app       Up 4 seconds             8000/tcp
notes-hw2-cache-1   cache     Up 9 seconds (healthy)   6379/tcp
notes-hw2-db-1      db        Up 9 seconds (healthy)   5432/tcp
notes-hw2-web-1     web       Up 3 seconds             0.0.0.0:18090->80/tcp
$ curl localhost:18090/
Привет, Вадик! Посещений: 1
$ curl localhost:18090/notes
1: control-note-1
```

Зависимости закреплены в `app/requirements.txt` через `==`, транзитивные тоже. `pip install` идёт отдельным слоем до `COPY` кода, поэтому после правки кода этот слой берётся из кеша:

```
#8 [3/5] COPY app/requirements.txt .
#8 CACHED
#9 [4/5] RUN pip install --no-cache-dir     -r requirements.txt
#9 CACHED
#10 [5/5] COPY app/ .
```

## 2. Том БД

Том `pgdata` подключён к `/var/lib/postgresql`. После `docker compose rm -sf db && docker compose up -d --wait` контейнер новый, а заметка на месте:

```
$ docker compose exec db psql -U notes_user -d notes -c 'TABLE notes;'
  1 | control-note-1
```

Сохраняются заметки в PostgreSQL. Персистентность в Redis выключена (`--save "" --appendonly no`), поэтому после пересоздания `cache` счётчик начинается с 1.

## 3. Холодный бэкап

```
$ docker compose down
$ docker run --rm -v notes-hw2_pgdata:/data:ro -v "$PWD/backup:/backup" ubuntu:24.04 \
    tar czf /backup/pgdata.tgz --numeric-owner -C /data .
$ docker volume rm notes-hw2_pgdata
$ docker compose create db          # пустой том с метками compose
$ docker run --rm -v notes-hw2_pgdata:/data ubuntu:24.04 ls -A /data
(пусто)
$ docker run --rm -v notes-hw2_pgdata:/data -v "$PWD/backup:/backup:ro" ubuntu:24.04 \
    tar xzf /backup/pgdata.tgz --numeric-owner -C /data
$ docker compose up -d --wait
$ docker compose images db
notes-hw2-db-1      postgres            18                  linux/amd64         74935e722416
$ docker compose exec db psql -U notes_user -d notes -c 'TABLE notes;'
  1 | control-note-1
```

`--numeric-owner` сохраняет uid 999 у файлов postgres.

## 4. Сети

```
$ docker compose exec web getent hosts db
$ docker compose exec web nc -zv -w 3 172.18.0.3 5432
nc: 172.18.0.3 (172.18.0.3:5432): Operation timed out
$ docker compose exec app getent hosts db cache
172.18.0.3      db
172.18.0.2      cache
$ docker compose exec app python -c '...'
db: PostgreSQL 18.6 | notes: 1
cache: PING -> True
```

Почему app не становится маршрутизатором: к БД он подключается сам, через свой интерфейс в back. Чужие пакеты к нему вообще не попадают. 

У web маршрут по умолчанию ведёт на хост (можно увидеть через `ip route get 172.18.0.3`), а хост режет трафик между bridge-сетями правилом Docker `-A DOCKER ! -i br-<back> -o br-<back> -j DROP`.

## 5. Переменные и имя проекта

Креды БД, порт и теги образов вынесены в `.env`. В Git лежит только пример `.env.example`

`docker compose config`: (пароль замаскировал)

```yaml
name: notes-hw2
services:
  app:
    restart: unless-stopped
    environment:
      DB_HOST: db
      POSTGRES_DB: notes
      POSTGRES_PASSWORD: "***"
      POSTGRES_USER: notes_user
      REDIS_HOST: cache
    networks:
      back: null
      front: null
    build:
      context: /home/feytox/coding/devops/docker-hw-2/repo
      dockerfile: Dockerfile
    depends_on:
      cache:
        condition: service_healthy
        required: true
      db:
        condition: service_healthy
        required: true
  cache:
    restart: unless-stopped
    command:
      - redis-server
      - --save
      - ""
      - --appendonly
      - 'no'
    image: redis:8.8-alpine
    networks:
      back: null
    healthcheck:
      test:
        - CMD
        - redis-cli
        - ping
      timeout: 2s
      interval: 2s
      retries: 15
  db:
    restart: unless-stopped
    environment:
      POSTGRES_DB: notes
      POSTGRES_PASSWORD: "***"
      POSTGRES_USER: notes_user
    image: postgres:18
    networks:
      back: null
    volumes:
      - type: volume
        source: pgdata
        target: /var/lib/postgresql
        volume: {}
    healthcheck:
      test:
        - CMD-SHELL
        - pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB
      timeout: 2s
      interval: 2s
      retries: 15
      start_period: 5s
  web:
    restart: unless-stopped
    image: nginx:1.30-alpine
    networks:
      front: null
    volumes:
      - type: bind
        source: /home/feytox/coding/devops/docker-hw-2/repo/nginx/default.conf
        target: /etc/nginx/conf.d/default.conf
        read_only: true
        bind: {}
    depends_on:
      app:
        condition: service_started
        required: true
    ports:
      - mode: ingress
        target: 80
        published: "18090"
        protocol: tcp
networks:
  back:
    name: notes-hw2_back
  front:
    name: notes-hw2_front
volumes:
  pgdata:
    name: notes-hw2_pgdata
```

Имя проекта `notes-hw2` задано через `name:` в `compose.yaml`. Его перезаписывают `COMPOSE_PROJECT_NAME` и `-p`, а без всех трёх берётся имя каталога. От имени проекта строятся имена ресурсов: контейнеры `notes-hw2-app-1`, сети `notes-hw2_front`/`_back`, том `notes-hw2_pgdata`.

`down` удаляет контейнеры и сети, но не тома: после него заметки на месте. `down -v` удаляет и том `notes-hw2_pgdata`, после него `/notes` отдаёт `(заметок нет)`.

## 6. dive

Изменения: база `python:3.14-slim` заменена на `python:3.14-alpine`, приложение запускается от `appuser` через `COPY --chown`, в образ копируется только `app.py`.

|                             | до (slim) | после (alpine) |
|-----------------------------|-----------|----------------|
| Размер                      | 235 MB    | 137 MB         |
| efficiency                  | 97.6 %    | 93.0 %         |
| wastedBytes                 | 5.7 MB    | 12.8 MB        |
| userWastedPercent           | 6.8 %     | 15.0 %         |
| dive (правила по умолчанию) | PASS      | FAIL           |

Почти весь выигрыш дала корневая ФС: 86.7 MB у Debian против 10.1 MB у Alpine. Слой `pip install` почти тот же (45 -> 42 MB). 

Потери в обоих случаях пришли из базы: у slim это apt/dpkg, у alpine openssl в двух слоях. Голый `python:3.14-alpine` даёт те же 12.8 MB, наши слои добавляют только 3 KB (`/etc/passwd`, `/etc/group`, `/etc/shadow` после `adduser`). Поэтому меньший образ получает FAIL.

При этом со сменой образа поведение самого приложения не изменилось, всё работает точно так же корректно.

## 7*. develop.watch

`compose.override.yaml` добавляет к `app` блок `develop.watch`: `app.py` синхронизируется с перезапуском (`sync+restart`), а изменение `requirements.txt` или `Dockerfile` пересобирает образ (`rebuild`). Базовая конфигурация (`compose.yaml`) от объединённой отличается только этим блоком.

```
Watch enabled
Syncing service "app" after 1 changes were detected
service(s) ["app"] restarted
Rebuilding service(s) ["app"] after changes were detected...
...
 Image notes-hw2-app Built
 Container notes-hw2-app-1 Recreated
```

Результат: после правки `app.py` ответ сменился на `Привет, Вадик (watch)! Посещений: 17`, после `LABEL` в Dockerfile у `app` новый образ (`f350f8f6677c` -> `c993798c0b04`) и метка `dev.watch=demo`.

## 8*. dive в CI

`.github/workflows/dive.yml` собирает образ и запускает `CI=true dive --ci-config .dive-ci`. Пороги: efficiency >= 0.90, wasted <= 15 MB, userWasted <= 20 %. Они рассчитаны на неустранимые 12.8 MB базы и ловят потери в наших слоях. 

С лишним `RUN chown -R` по site-packages получается 94 MB потерь, все три правила падают в FAIL, run в GitHub тоже падает.

- успешный run (`master`, 3/3 PASS): https://github.com/feytox/devops-hw-2/actions/runs/37778585041/job/113315637327
- упавший run (`ci-regress`, 3/3 FAIL): https://github.com/feytox/devops-hw-2/actions/runs/37779480969/job/113318649926
