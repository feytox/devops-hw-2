import os

import psycopg
import redis
from flask import Flask, request

app = Flask(__name__)
cache = redis.Redis(
    host=os.environ.get("REDIS_HOST", "cache"),
    port=int(os.environ.get("REDIS_PORT", "6379")),
    decode_responses=True,
)


def db_connect():
    return psycopg.connect(
        host=os.environ.get("DB_HOST", "db"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def create_table():
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                text text NOT NULL
            )
            """
        )


@app.get("/")
def hello():
    visits = cache.incr("visits")
    return f"Привет, Вадик! Посещений: {visits}\n"


@app.post("/notes")
def add_note():
    text = (request.get_json(silent=True) or {}).get("text", "").strip()
    if not text:
        return "Нужно поле text\n", 400
    with db_connect() as conn:
        conn.execute("INSERT INTO notes (text) VALUES (%s)", (text,))
    return f"'{text}' сохранена\n", 201


@app.get("/notes")
def list_notes():
    with db_connect() as conn:
        rows = conn.execute("SELECT id, text FROM notes ORDER BY id").fetchall()
    return "".join(f"{note_id}: {text}\n" for note_id, text in rows) or "(заметок нет)\n"


create_table()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
