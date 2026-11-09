"""Local image/template library and durable RX/TX message history."""
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from PIL import Image
from .image_document import Document, load_image, png_bytes


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Library:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                    created TEXT NOT NULL, image BLOB NOT NULL, thumbnail BLOB NOT NULL,
                    document TEXT, metadata TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY, created TEXT NOT NULL, direction TEXT NOT NULL, text TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_image(self, name, image, *, kind="image", document=None, metadata=None):
        if kind not in ("image", "rx", "tx", "template"):
            raise ValueError("Invalid gallery category")
        name = name.strip()[:200]
        if not name:
            raise ValueError("A name is required")
        image = load_image(image)
        thumb = image.copy()
        thumb.thumbnail((160, 120), Image.Resampling.LANCZOS)
        serialized = document.to_json() if document is not None else None
        with self.connection() as db:
            return db.execute("INSERT INTO images(name,kind,created,image,thumbnail,document,metadata) VALUES(?,?,?,?,?,?,?)",
                (name, kind, utc_now(), png_bytes(image), png_bytes(thumb), serialized, json.dumps(metadata or {}))).lastrowid

    def images(self, *, kind=None, search="", limit=100, offset=0):
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,name,kind,created,thumbnail,metadata FROM images WHERE (? IS NULL OR kind=?) "
                "AND instr(lower(name || ' ' || metadata),lower(?))>0 ORDER BY id DESC LIMIT ? OFFSET ?",
                (kind, kind, search, limit, offset))]

    def image(self, identity):
        with self.connection() as db:
            row = db.execute("SELECT * FROM images WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise ValueError("This library entry no longer exists")
        result = dict(row)
        with Image.open(BytesIO(result["image"])) as image:
            result["image"] = image.convert("RGBA")
        result["document"] = Document.from_json(result["document"]) if result["document"] else None
        result["metadata"] = json.loads(result["metadata"])
        return result

    def rename(self, identity, name):
        if not name.strip():
            raise ValueError("A name is required")
        with self.connection() as db:
            db.execute("UPDATE images SET name=? WHERE id=?", (name.strip()[:200], identity))

    def remove(self, identity):
        with self.connection() as db:
            db.execute("DELETE FROM images WHERE id=?", (identity,))

    def duplicate(self, identity, name):
        item = self.image(identity)
        return self.add_image(name, item["image"], kind=item["kind"], document=item["document"], metadata=item["metadata"])

    def add_message(self, text, direction="RX", created=None):
        if direction not in ("RX", "TX") or not isinstance(text, str) or len(text) > 10000:
            raise ValueError("Invalid message")
        created = created or utc_now()
        with self.connection() as db:
            identity = db.execute("INSERT INTO messages(created,direction,text) VALUES(?,?,?)",
                                  (created, direction, text)).lastrowid
        return dict(id=identity, created=created, direction=direction, text=text)

    def messages(self, search="", *, limit=500, offset=0):
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM messages WHERE instr(lower(text),lower(?))>0 ORDER BY id DESC LIMIT ? OFFSET ?",
                (search, limit, offset))]

    def save_draft(self, document, context=None):
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO preferences(key,value) VALUES('tx_draft',?)", (document.to_json(),))
            db.execute("INSERT OR REPLACE INTO preferences(key,value) VALUES('tx_context',?)", (json.dumps(context or {}),))

    def draft(self):
        with self.connection() as db:
            row = db.execute("SELECT value FROM preferences WHERE key='tx_draft'").fetchone()
        return Document.from_json(row[0]) if row else None

    def draft_context(self):
        with self.connection() as db:
            row = db.execute("SELECT value FROM preferences WHERE key='tx_context'").fetchone()
        context = json.loads(row[0]) if row else {}
        if not isinstance(context, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in context.items()):
            raise ValueError("Invalid draft context")
        return context


def message_line(item):
    time = datetime.fromisoformat(item["created"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return f"[{time}] {item['direction']}  {item['text']}\n"
