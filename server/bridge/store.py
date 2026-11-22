"""Lasting storage: accounts, friends, saved boards and tables in progress.

On Azure this is Table Storage in a storage account of its own (BRIDGE_TABLES_URL, signed in with the Container
App's identity), so it survives every deploy. Anywhere else it is one SQLite file in the data folder, which is
enough for a laptop and the tests but is lost when the container restarts.

Every record is a JSON object, kept gzipped. Records are addressed like Table Storage: table, partition, row.
"""
from __future__ import annotations

import gzip
import json
import os
import threading
from pathlib import Path
from typing import Any

CHUNK = 60_000  # Table Storage keeps at most 64 KB in one property; longer records are split across several
MAX_CHUNKS = 15


def _pack(data: dict) -> bytes:
    return gzip.compress(json.dumps(data, separators=(",", ":")).encode())


def _unpack(blob: bytes) -> dict:
    return json.loads(gzip.decompress(blob))


class Store:
    durable = False  # survives a deploy: only then are accounts offered

    def get(self, table: str, pk: str, rk: str) -> dict | None:
        raise NotImplementedError

    def put(self, table: str, pk: str, rk: str, data: dict) -> None:
        raise NotImplementedError

    def query(self, table: str, pk: str) -> list[tuple[str, dict]]:
        """All rows in one partition, as (row key, record), in row-key order."""
        raise NotImplementedError

    def delete(self, table: str, pk: str, rk: str) -> None:
        raise NotImplementedError

    def dump(self) -> dict[str, list[dict]]:
        """Every record in every table, for a backup: {table: [{"pk", "rk", "data"}]}."""
        raise NotImplementedError


class SqliteStore(Store):
    def __init__(self, path: Path | str, durable: bool = False):
        self.durable = durable
        import sqlite3  # here, not at the top: the app's offline engine runs in a browser that has no sqlite3

        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS kv (tbl TEXT, pk TEXT, rk TEXT, data BLOB, "
                        "PRIMARY KEY (tbl, pk, rk))")
        self.db.commit()

    def get(self, table, pk, rk):
        with self.lock:
            row = self.db.execute("SELECT data FROM kv WHERE tbl=? AND pk=? AND rk=?", (table, pk, rk)).fetchone()
        return _unpack(row[0]) if row else None

    def put(self, table, pk, rk, data):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES (?, ?, ?, ?)", (table, pk, rk, _pack(data)))
            self.db.commit()

    def query(self, table, pk):
        with self.lock:
            rows = self.db.execute("SELECT rk, data FROM kv WHERE tbl=? AND pk=? ORDER BY rk",
                                   (table, pk)).fetchall()
        return [(rk, _unpack(d)) for rk, d in rows]

    def delete(self, table, pk, rk):
        with self.lock:
            self.db.execute("DELETE FROM kv WHERE tbl=? AND pk=? AND rk=?", (table, pk, rk))
            self.db.commit()

    def dump(self):
        with self.lock:
            rows = self.db.execute("SELECT tbl, pk, rk, data FROM kv ORDER BY tbl, pk, rk").fetchall()
        out: dict[str, list[dict]] = {}
        for tbl, pk, rk, data in rows:
            out.setdefault(tbl, []).append({"pk": pk, "rk": rk, "data": _unpack(data)})
        return out


class AzureTableStore(Store):
    durable = True

    def __init__(self, service):
        self.service = service
        self.tables: dict[str, Any] = {}
        self.lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "AzureTableStore":
        from azure.data.tables import TableServiceClient
        if os.environ.get("BRIDGE_TABLES_CONNECTION"):  # a connection string: the local emulator in tests
            return cls(TableServiceClient.from_connection_string(os.environ["BRIDGE_TABLES_CONNECTION"]))
        from azure.identity import DefaultAzureCredential
        return cls(TableServiceClient(endpoint=os.environ["BRIDGE_TABLES_URL"], credential=DefaultAzureCredential()))

    def _table(self, name: str):
        with self.lock:
            if name not in self.tables:
                self.tables[name] = self.service.create_table_if_not_exists("bridge" + name)
            return self.tables[name]

    @staticmethod
    def _key(k: str) -> str:
        # characters Table Storage refuses in keys
        return "".join("_" if c in "/\\#?" or ord(c) < 32 else c for c in k)

    def get(self, table, pk, rk):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            e = self._table(table).get_entity(self._key(pk), self._key(rk))
        except ResourceNotFoundError:
            return None
        return self._decode(e)

    def put(self, table, pk, rk, data):
        blob = _pack(data)
        if len(blob) > CHUNK * MAX_CHUNKS:
            raise ValueError(f"record too large to store ({len(blob)} bytes)")
        entity = {"PartitionKey": self._key(pk), "RowKey": self._key(rk), "rk": rk,
                  "n": (len(blob) + CHUNK - 1) // CHUNK}
        for i in range(entity["n"]):
            entity[f"b{i}"] = blob[i * CHUNK:(i + 1) * CHUNK]
        from azure.data.tables import UpdateMode
        self._table(table).upsert_entity(entity, mode=UpdateMode.REPLACE)

    def query(self, table, pk):
        rows = self._table(table).query_entities("PartitionKey eq @pk", parameters={"pk": self._key(pk)})
        out = [(e.get("rk", e["RowKey"]), self._decode(e)) for e in rows]
        return sorted(out, key=lambda r: r[0])

    def delete(self, table, pk, rk):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            self._table(table).delete_entity(self._key(pk), self._key(rk))
        except ResourceNotFoundError:
            pass

    def dump(self):
        out: dict[str, list[dict]] = {}
        for t in self.service.list_tables():
            if not t.name.startswith("bridge"):
                continue
            client = self.service.get_table_client(t.name)
            out[t.name.removeprefix("bridge")] = [
                {"pk": e["PartitionKey"], "rk": e.get("rk", e["RowKey"]), "data": self._decode(e)}
                for e in client.list_entities()]
        return out

    @staticmethod
    def _decode(e) -> dict:
        return _unpack(b"".join(bytes(e[f"b{i}"]) for i in range(int(e["n"]))))


def open_store() -> Store:
    if os.environ.get("BRIDGE_TABLES_URL") or os.environ.get("BRIDGE_TABLES_CONNECTION"):
        return AzureTableStore.from_env()
    from .game.room import data_dir
    # accounts need storage that outlives the container; a laptop or the tests can say a local file will do
    return SqliteStore(data_dir() / "bridge.db", durable=os.environ.get("BRIDGE_ACCOUNTS") == "1")
