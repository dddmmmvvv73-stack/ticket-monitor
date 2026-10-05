-- База продаж и афиши по всей РФ — по DATA_MODEL.md (утверждена 04.10.2026).
-- Применяется повторно без вреда (IF NOT EXISTS); изменения схемы — новыми блоками в конце файла.

-- ---------------------------------------------------------------- справочники

-- Билетный оператор (TICKET_PLATFORMS.md, раздел 7)
CREATE TABLE IF NOT EXISTS operators (
    id            text PRIMARY KEY,                 -- kassir, yandex, vladimirkoncert, odk33, custom …
    name          text NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('regional', 'federal', 'aggregator', 'venue_site', 'custom')),
    engine        text,                             -- движок: vladimirkoncert (5 сайтов), kassir, yandex …
    sites         text[] NOT NULL DEFAULT '{}',
    regions       text[] NOT NULL DEFAULT '{}',
    caps          jsonb NOT NULL DEFAULT '{}',      -- что отдаёт: схема / свободные / остаток, цены, организатор …
    limits        jsonb NOT NULL DEFAULT '{}',      -- паузы, частота, антибот
    connected_at  date,
    notes         text
);

CREATE TABLE IF NOT EXISTS cities (
    id         serial PRIMARY KEY,
    name       text NOT NULL UNIQUE,
    fo         text,                                -- федеральный округ
    tz         text NOT NULL DEFAULT 'Europe/Moscow',
    ext        jsonb NOT NULL DEFAULT '{}'          -- номера у операторов: Кассир (поддомен, suburbId), Яндекс (id)
);

CREATE TABLE IF NOT EXISTS venues (
    id          serial PRIMARY KEY,
    city_id     int NOT NULL REFERENCES cities(id),
    name        text NOT NULL,                      -- каноническое название
    name_key    text NOT NULL,                      -- curation.venue_key без города
    kind        text CHECK (kind IN ('rental', 'repertory', 'mixed')),
    kind_src    text CHECK (kind_src IN ('user', 'auto')),
    kind_at     timestamptz,
    address     text,
    lat         double precision,
    lon         double precision,
    UNIQUE (city_id, name_key)
);

-- Все написания площадки у операторов (словарь venue_aliases + склейка)
CREATE TABLE IF NOT EXISTS venue_names (
    venue_id   int NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    city_id    int NOT NULL REFERENCES cities(id),
    name_key   text NOT NULL,
    name       text,
    source     text NOT NULL DEFAULT 'auto',
    PRIMARY KEY (city_id, name_key)
);

-- Зал (эталон мест) и его места: ключ места «зона|ряд|место» (seatmap.seat_key)
CREATE TABLE IF NOT EXISTS halls (
    id         serial PRIMARY KEY,
    venue_id   int NOT NULL REFERENCES venues(id),
    name       text,
    capacity   int,                                 -- кресел в эталоне (без «не кресел» вроде Meet & Greet)
    ext        jsonb NOT NULL DEFAULT '{}'          -- откуда эталон, номер зала у операторов
);
CREATE TABLE IF NOT EXISTS hall_seats (
    hall_id    int NOT NULL REFERENCES halls(id) ON DELETE CASCADE,
    seat_key   text NOT NULL,
    zone       text,
    row_name   text,
    place      text,
    x          double precision,
    y          double precision,
    kind       text NOT NULL DEFAULT 'seat' CHECK (kind IN ('seat', 'admission', 'service')),
    PRIMARY KEY (hall_id, seat_key)
);
-- Рассадка — вариант зала (отпечаток seatmap.layout_signature)
CREATE TABLE IF NOT EXISTS layouts (
    id         text PRIMARY KEY,
    hall_id    int NOT NULL REFERENCES halls(id) ON DELETE CASCADE,
    seats      int,
    seat_keys  text[]
);
-- Бронь зала: авто (места, занятые во всех мероприятиях), серии, ручная (ряды)
CREATE TABLE IF NOT EXISTS hall_reserve (
    hall_id    int NOT NULL REFERENCES halls(id) ON DELETE CASCADE,
    seat_key   text NOT NULL,                       -- для ручной брони рядов — «зона|ряд»
    kind       text NOT NULL CHECK (kind IN ('auto', 'series', 'manual_row')),
    layout_id  text,
    since      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hall_id, seat_key, kind)
);

-- ---------------------------------------------------------------- проекты (разметка на годы — DATA_MODEL.md, 3.1)

-- Артист / коллектив: пометка «гастроль» здесь действует на все его программы
CREATE TABLE IF NOT EXISTS artists (
    id         serial PRIMARY KEY,
    name       text NOT NULL,
    key        text NOT NULL UNIQUE,
    mark       text CHECK (mark IN ('tour', 'local')),
    mark_at    timestamptz,
    created    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
    id         serial PRIMARY KEY,
    title      text NOT NULL,
    artist_id  int REFERENCES artists(id),
    format     text,
    sphere     text,
    genre      text,
    mark       text CHECK (mark IN ('tour', 'local')),   -- ваша пометка (приоритет над всем)
    mark_at    timestamptz,
    scope      text NOT NULL DEFAULT '',                 -- одноимённые постановки: 'venue:<id>' / 'org:<организатор>'
    created    timestamptz NOT NULL DEFAULT now()
);

-- Написания проекта: ключ названия (db.projects.title_key) → проект. Один ключ у разных проектов — только с разным scope
CREATE TABLE IF NOT EXISTS project_names (
    key        text NOT NULL,
    scope      text NOT NULL DEFAULT '',
    project_id int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    example    text,
    source     text NOT NULL DEFAULT 'auto' CHECK (source IN ('auto', 'user', 'migrated', 'legacy_key')),
    created    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (key, scope)
);

-- Очередь подсказок: новое название похоже на размеченный проект — применить?
CREATE TABLE IF NOT EXISTS project_suggestions (
    id          serial PRIMARY KEY,
    key         text NOT NULL,
    title       text NOT NULL,
    project_id  int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    reason      text NOT NULL,                      -- тот же артист / почти тот же ключ / тот же организатор
    score       real NOT NULL,
    status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'accepted', 'rejected')),
    created     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (key, project_id)
);

-- ---------------------------------------------------------------- сеансы, карточки, запасы, наблюдения

CREATE TABLE IF NOT EXISTS sessions (
    id            bigserial PRIMARY KEY,
    project_id    int REFERENCES projects(id),
    venue_id      int REFERENCES venues(id),
    hall_id       int REFERENCES halls(id),
    starts_at     timestamptz,                      -- момент начала (по поясу города)
    local_date    date NOT NULL,
    local_time    time,
    status        text NOT NULL DEFAULT 'on_sale'
                  CHECK (status IN ('announced', 'on_sale', 'sold_out', 'sales_closed', 'done', 'cancelled', 'postponed', 'removed')),
    status_log    jsonb NOT NULL DEFAULT '[]',      -- история статусов и переносов (старые даты)
    track_sales   boolean NOT NULL DEFAULT false,   -- «следим за продажами» (гастроль)
    track_since   timestamptz,
    tour          text CHECK (tour IN ('tour', 'local')),
    tour_src      text,                             -- project / artist / venue / auto
    tour_why      text,
    sphere        text,
    format        text,
    genre         text,
    niche_src     jsonb NOT NULL DEFAULT '{}',
    age           text,
    pushkin       boolean NOT NULL DEFAULT false,
    title         text,                             -- название для показа (лучшее из карточек)
    first_seen    date,
    last_seen     date,
    result        jsonb                             -- итог на дату (DATA_MODEL.md, 3.7)
);
CREATE INDEX IF NOT EXISTS sessions_date ON sessions (local_date);
CREATE INDEX IF NOT EXISTS sessions_project ON sessions (project_id);
CREATE INDEX IF NOT EXISTS sessions_track ON sessions (track_sales, local_date);

-- Карточка сеанса у оператора; ext_key — внешний номер (как ключи keys: k:event:N, y:<id>:<дата>@<город>, vk:N)
CREATE TABLE IF NOT EXISTS listings (
    id            bigserial PRIMARY KEY,
    session_id    bigint REFERENCES sessions(id) ON DELETE SET NULL,
    operator_id   text NOT NULL REFERENCES operators(id),
    ext_key       text NOT NULL,
    url           text,
    title         text,
    title_api     text,
    price_min     numeric,
    price_max     numeric,
    organizer     text,
    sale_opening  timestamptz,
    first_seen    date,
    last_seen     date,
    ext           jsonb NOT NULL DEFAULT '{}',
    UNIQUE (operator_id, ext_key)
);
CREATE INDEX IF NOT EXISTS listings_session ON listings (session_id);

-- Когда номер впервые появился у оператора (market/seen.json) — в том числе давно исчезнувшие
CREATE TABLE IF NOT EXISTS listing_seen (
    operator_id   text NOT NULL REFERENCES operators(id),
    ext_key       text NOT NULL,
    first_seen    date NOT NULL,
    PRIMARY KEY (operator_id, ext_key)
);

-- Запас билетов: сеанс × касса (у Яндекса — ещё и касса из sessionServices)
CREATE TABLE IF NOT EXISTS pools (
    id            bigserial PRIMARY KEY,
    session_id    bigint NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    operator_id   text NOT NULL REFERENCES operators(id),
    service       text NOT NULL DEFAULT '',
    listing_id    bigint REFERENCES listings(id) ON DELETE SET NULL,
    shared_group  int,                              -- общий запас с другими кассами сеанса — одна группа
    has_scheme    boolean,
    hidden        boolean NOT NULL DEFAULT false,
    UNIQUE (session_id, operator_id, service)
);

-- Наблюдение: пишется только при изменении (иначе — checked_at у последнего)
CREATE TABLE IF NOT EXISTS observations (
    id             bigserial PRIMARY KEY,
    pool_id        bigint NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
    ts             timestamptz NOT NULL,
    checked_at     timestamptz,                     -- последний сбор с тем же результатом
    free           int,
    free_by_price  jsonb,                           -- {цена: штук}
    total          int,                             -- мест всего, если оператор даёт
    taken          int,
    sale_status    text,
    hidden         boolean NOT NULL DEFAULT false,
    anomaly        boolean NOT NULL DEFAULT false,  -- «весь зал занят» и т. п. (seatmap.is_flip)
    gross          numeric,
    free_seats     text[],                          -- свободные места по эталону (если скачана схема)
    raw_ref        text                             -- сырой ответ в архиве
);
CREATE INDEX IF NOT EXISTS observations_pool_ts ON observations (pool_id, ts);

-- Продажи по местам (решение 04.10: в базе)
CREATE TABLE IF NOT EXISTS seat_sales (
    pool_id     bigint NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
    seat_key    text NOT NULL,
    ts          timestamptz NOT NULL,
    price       numeric,
    kind        text NOT NULL DEFAULT 'sale' CHECK (kind IN ('sale', 'return')),
    PRIMARY KEY (pool_id, seat_key, ts)
);

-- Распоясовка сеанса по версиям (DATA_MODEL.md, 3.8)
CREATE TABLE IF NOT EXISTS price_maps (
    session_id  bigint NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seat_key    text NOT NULL,
    price       numeric NOT NULL,
    valid_from  timestamptz NOT NULL,
    estimated   boolean NOT NULL DEFAULT false,     -- цена занятого места по соседям
    PRIMARY KEY (session_id, seat_key, valid_from)
);

-- ---------------------------------------------------------------- ваша разметка и служебное

CREATE TABLE IF NOT EXISTS session_edits (
    ext_key     text PRIMARY KEY,                   -- номер карточки, к которой привязана правка (как в curation.edits)
    fields      jsonb NOT NULL,
    at          timestamptz
);
CREATE TABLE IF NOT EXISTS niche_overrides (
    title_key   text PRIMARY KEY,
    sphere      text, format text, genre text,
    at          timestamptz
);
CREATE TABLE IF NOT EXISTS ai_cache (
    title_key   text PRIMARY KEY,
    sphere      text, format text, genre text
);
CREATE TABLE IF NOT EXISTS settings (
    key         text PRIMARY KEY,
    value       jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_runs (
    id          bigserial PRIMARY KEY,
    operator_id text REFERENCES operators(id),
    kind        text,                               -- market / competitors / sales
    started     timestamptz NOT NULL,
    finished    timestamptz,
    sessions    int,
    errors      int,
    blocked     int,
    summary     text
);
CREATE TABLE IF NOT EXISTS migrations_log (
    id          serial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    step        text NOT NULL,
    report      jsonb
);

-- ---------------------------------------------------------------- 04.10: живые данные продаж (шаг 5)
-- Справочная часть (афиша, проекты, сеансы, карточки) пока пересобирается из JSON каждый час (db.migrate);
-- живая часть (запасы касс, наблюдения, продажи, залы из схем) не стирается никогда и привязана к постоянному
-- номеру карточки у оператора (listing_key = listings.ext_key), а не к номерам строк, которые при пересборке меняются.

ALTER TABLE pools DROP CONSTRAINT IF EXISTS pools_session_id_fkey;
ALTER TABLE pools DROP CONSTRAINT IF EXISTS pools_listing_id_fkey;
ALTER TABLE pools ALTER COLUMN session_id DROP NOT NULL;
ALTER TABLE pools ADD COLUMN IF NOT EXISTS listing_key text;
ALTER TABLE pools ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'json';   -- json — из файлов (пересобирается), live — сбор продаж
ALTER TABLE pools ADD COLUMN IF NOT EXISTS ext jsonb NOT NULL DEFAULT '{}';       -- номер сеанса у оператора, кассы Яндекса, зал …
ALTER TABLE pools ADD COLUMN IF NOT EXISTS next_check timestamptz;
ALTER TABLE pools DROP CONSTRAINT IF EXISTS pools_session_id_operator_id_service_key;
CREATE UNIQUE INDEX IF NOT EXISTS pools_live_key ON pools (operator_id, listing_key, service) WHERE source = 'live';
CREATE INDEX IF NOT EXISTS pools_listing ON pools (listing_key);

ALTER TABLE observations ADD COLUMN IF NOT EXISTS summary jsonb;        -- сводка оператора (у Яндекса — только для поиска изменений)
ALTER TABLE observations ADD COLUMN IF NOT EXISTS seat_prices jsonb;    -- свободные места схемы: {место: цена} — распоясовка по версиям

-- Продажи по ценам между наблюдениями (где нет схемы мест — только так)
CREATE TABLE IF NOT EXISTS price_sales (
    pool_id     bigint NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
    ts_from     timestamptz NOT NULL,
    ts_to       timestamptz NOT NULL,
    price       numeric NOT NULL,
    qty         int NOT NULL,                       -- > 0 продано, < 0 вернулось / открыли места
    anomaly     boolean NOT NULL DEFAULT false,
    PRIMARY KEY (pool_id, ts_to, price)
);

-- Залы из схем операторов (эталон мест): ключ — 'yandex:<номер зала>' и т. п.; площадка — по городу и названию
CREATE TABLE IF NOT EXISTS live_halls (
    key         text PRIMARY KEY,
    city        text,
    venue       text,
    capacity    int,
    seats       jsonb NOT NULL,                     -- [[место, зона, ряд, номер, x, y], …] без «не кресел»
    updated     timestamptz NOT NULL DEFAULT now()
);
-- Живые таблицы не должны стираться каскадом при пересборке справочной части (TRUNCATE operators CASCADE)
ALTER TABLE pools DROP CONSTRAINT IF EXISTS pools_operator_id_fkey;
ALTER TABLE collection_runs DROP CONSTRAINT IF EXISTS collection_runs_operator_id_fkey;
ALTER TABLE collection_runs ADD COLUMN IF NOT EXISTS report jsonb;

-- 05.10: «открыли места» (разом освободилось ≥ 20 мест — новая квота, а не возвраты)
ALTER TABLE seat_sales DROP CONSTRAINT IF EXISTS seat_sales_kind_check;
ALTER TABLE seat_sales ADD CONSTRAINT seat_sales_kind_check CHECK (kind IN ('sale', 'return', 'release'));
ALTER TABLE price_sales ADD COLUMN IF NOT EXISTS released boolean NOT NULL DEFAULT false;
