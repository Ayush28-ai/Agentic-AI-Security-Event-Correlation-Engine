import sqlite3
import json
import os
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "./shared/soc_incidents.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name  TEXT NOT NULL,
            timestamp    TEXT NOT NULL,
            risk_level   TEXT NOT NULL,
            ops_cpu      REAL DEFAULT 0,
            ops_memory   REAL DEFAULT 0,
            ops_disk     REAL DEFAULT 0,
            analysis     TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_control (
            device_name  TEXT PRIMARY KEY,
            status       TEXT DEFAULT 'active',
            updated_at   TEXT
        )
    """)
    conn.commit()
    conn.close()

def store_incident(device_name, timestamp, risk_level, ops, analysis):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO incidents
            (device_name, timestamp, risk_level, ops_cpu, ops_memory, ops_disk, analysis)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (device_name, timestamp, risk_level,
          ops.get("cpu", 0), ops.get("memory", 0), ops.get("disk", 0),
          json.dumps(analysis)))
    conn.commit()
    conn.close()

def get_latest(limit=50):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_by_device(device_name, limit=20):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM incidents WHERE device_name=? ORDER BY id DESC LIMIT ?",
        (device_name, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_device_status(device_name):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM agent_control WHERE device_name=?", (device_name,)
    ).fetchone()
    conn.close()
    return dict(row) if row else {"device_name": device_name, "status": "active"}

def set_device_status(device_name, status):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO agent_control (device_name, status, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(device_name) DO UPDATE
        SET status=excluded.status, updated_at=excluded.updated_at
    """, (device_name, status, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
