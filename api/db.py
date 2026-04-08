import sqlite3
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "berum.sqlite3"


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate() -> None:
    conn = connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS merchants (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              api_key_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_merchants_api_key_hash ON merchants(api_key_hash);

            CREATE TABLE IF NOT EXISTS products (
              id TEXT PRIMARY KEY,
              merchant_id TEXT NOT NULL,
              name TEXT NOT NULL,
              currency TEXT NOT NULL,
              mrp REAL NOT NULL,
              base_price REAL NOT NULL,
              floor_price REAL NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              FOREIGN KEY (merchant_id) REFERENCES merchants(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_products_merchant ON products(merchant_id);

            CREATE TABLE IF NOT EXISTS bargain_sessions (
              id TEXT PRIMARY KEY,
              merchant_id TEXT NOT NULL,
              product_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              attempts_used INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL,
              accepted_price REAL,
              order_id TEXT,
              previous_customer INTEGER NOT NULL DEFAULT 0,
              device_hash TEXT NOT NULL,
              email_hash TEXT NOT NULL,
              mobile_hash TEXT NOT NULL,
              FOREIGN KEY (merchant_id) REFERENCES merchants(id) ON DELETE CASCADE,
              FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_product ON bargain_sessions(product_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_identity ON bargain_sessions(device_hash, email_hash, mobile_hash);

            CREATE TABLE IF NOT EXISTS quotes (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              merchant_id TEXT NOT NULL,
              product_id TEXT NOT NULL,
              amount REAL NOT NULL,
              currency TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (session_id) REFERENCES bargain_sessions(id) ON DELETE CASCADE,
              FOREIGN KEY (merchant_id) REFERENCES merchants(id) ON DELETE CASCADE,
              FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_quotes_session ON quotes(session_id);

            CREATE TABLE IF NOT EXISTS payments (
              id TEXT PRIMARY KEY,
              quote_id TEXT NOT NULL,
              merchant_id TEXT NOT NULL,
              amount REAL NOT NULL,
              currency TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (quote_id) REFERENCES quotes(id) ON DELETE CASCADE,
              FOREIGN KEY (merchant_id) REFERENCES merchants(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_payments_quote ON payments(quote_id);
            """
        )
        conn.commit()
    finally:
        conn.close()

