CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
 id BIGSERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('owner','member')));
CREATE UNIQUE INDEX IF NOT EXISTS one_owner ON users(role) WHERE role='owner';
CREATE TABLE IF NOT EXISTS sessions (
 token TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 csrf TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts (key TEXT PRIMARY KEY, failures INTEGER NOT NULL, blocked_until DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS photos (id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS containers (
 id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('rack','cabinet','shelf','box','bag','loose')),
 description TEXT NOT NULL DEFAULT '', photo_id TEXT REFERENCES photos(id),
 parent_id BIGINT REFERENCES containers(id) ON DELETE RESTRICT, level INTEGER,
 floor_note TEXT NOT NULL DEFAULT '', CHECK(parent_id IS NULL OR parent_id<>id),
 UNIQUE(parent_id,level));
CREATE INDEX IF NOT EXISTS container_parent ON containers(parent_id);
CREATE TABLE IF NOT EXISTS products (
 id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 unit TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('count','percent')), photo_id TEXT NOT NULL REFERENCES photos(id));
CREATE TABLE IF NOT EXISTS tags (id BIGSERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS product_tags (
 product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
 tag_id BIGINT NOT NULL REFERENCES tags(id), PRIMARY KEY(product_id,tag_id));
CREATE TABLE IF NOT EXISTS stocks (
 id BIGSERIAL PRIMARY KEY, product_id BIGINT NOT NULL REFERENCES products(id),
 container_id BIGINT NOT NULL REFERENCES containers(id), quantity NUMERIC(14,3) NOT NULL CHECK(quantity>=0),
 description TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS stock_container ON stocks(container_id);
CREATE TABLE IF NOT EXISTS movements (
 id BIGSERIAL PRIMARY KEY, item_name TEXT NOT NULL, action TEXT NOT NULL,
 detail TEXT NOT NULL, username TEXT NOT NULL, created_at TEXT NOT NULL);
