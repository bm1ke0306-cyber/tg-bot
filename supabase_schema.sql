-- ═══════════════════════════════════════════════════════
--  Family Task Tracker — Supabase Schema
--  Выполнить в Supabase SQL Editor
-- ═══════════════════════════════════════════════════════

-- Расширение для генерации UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── Таблица пользователей (whitelist) ─────────────────
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id BIGINT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- ─── Таблица задач ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title        TEXT NOT NULL,
    description  TEXT,
    assigned_to  UUID NOT NULL REFERENCES users(id),
    created_by   UUID NOT NULL REFERENCES users(id),
    deadline     TIMESTAMPTZ,
    priority     INT DEFAULT 2 CHECK (priority BETWEEN 1 AND 3),
    status       TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'done')),
    is_recurring BOOLEAN DEFAULT FALSE,
    created_at   TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- ─── Таблица регулярных задач ──────────────────────────
CREATE TABLE IF NOT EXISTS recurring_tasks (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title             TEXT NOT NULL,
    assigned_to       UUID NOT NULL REFERENCES users(id),
    recurrence_type   TEXT NOT NULL CHECK (recurrence_type IN ('daily', 'weekly', 'interval')),
    recurrence_value  INT DEFAULT 1,
    weekday           INT CHECK (weekday BETWEEN 0 AND 6),
    last_completed_at TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT now()
);

-- ─── Индексы ───────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_tasks_assigned   ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_tasks_status     ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_deadline   ON tasks(deadline);
CREATE INDEX IF NOT EXISTS idx_recurring_assign ON recurring_tasks(assigned_to);

-- ─── Row Level Security (RLS) — отключить для бота ─────
-- Бот использует service_role или anon-ключ.
-- Если используете anon-ключ, нужно отключить RLS
-- или настроить политики.
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE recurring_tasks ENABLE ROW LEVEL SECURITY;

-- Политика: разрешить всё для authenticated и anon
CREATE POLICY "Allow all for anon" ON users
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Allow all for anon" ON tasks
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Allow all for anon" ON recurring_tasks
    FOR ALL USING (true) WITH CHECK (true);

-- ═══════════════════════════════════════════════════════
--  Начальные данные: добавьте своих пользователей
-- ═══════════════════════════════════════════════════════
-- ЗАМЕНИТЕ telegram_id и имена на реальные!

-- INSERT INTO users (telegram_id, name) VALUES
--   (123456789, 'Папа'),
--   (987654321, 'Мама'),
--   (111111111, 'Лёва'),
--   (222222222, 'Мила');
