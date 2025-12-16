import sqlite3

DB_NAME = "hashhedge_oracle.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_pubkey TEXT NOT NULL,
            deposit_address TEXT NOT NULL,
            redeem_script_hex TEXT NOT NULL,
            amount INTEGER NOT NULL,
            direction TEXT NOT NULL,
            status TEXT DEFAULT 'PENDING',
            tx_hex TEXT,
            nonce TEXT
        )
    ''')
    try:
        c.execute("ALTER TABLE contracts ADD COLUMN nonce TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def db_create_contract(user_pub, address, script_hex, amount, direction, nonce):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        INSERT INTO contracts (user_pubkey, deposit_address, redeem_script_hex, amount, direction, nonce)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_pub, address, script_hex, amount, direction, nonce))
    order_id = c.lastrowid
    conn.commit()
    conn.close()
    return order_id

def db_get_contract(order_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM contracts WHERE id = ?", (order_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def db_update_status(order_id, status, tx_hex=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if tx_hex:
        c.execute("UPDATE contracts SET status = ?, tx_hex = ? WHERE id = ?", (status, tx_hex, order_id))
    else:
        c.execute("UPDATE contracts SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()

def db_delete_contract(order_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM contracts WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()

def db_get_pending_contracts():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM contracts WHERE status = 'PENDING'")
    contracts = [dict(row) for row in c.fetchall()]
    conn.close()
    return contracts
