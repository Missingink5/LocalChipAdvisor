"""SQLite storage and deterministic product filtering."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np

from .models import (
    CandidateResult,
    CheckState,
    Constraint,
    Evidence,
    Operator,
    ParsedQuery,
    Product,
)

PRODUCT_COLUMNS = tuple(Product.model_fields)
BOOL_FIELDS = {
    "aec_q100", "automotive", "i2c", "spi", "ocp", "ovp", "uvlo", "otp",
    "short_circuit_protection",
}


class ChipStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    def init_db(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
              product_id TEXT PRIMARY KEY, part_number TEXT UNIQUE NOT NULL,
              family TEXT, category TEXT NOT NULL, topology TEXT NOT NULL,
              vin_min_v REAL, vin_max_v REAL, vout_min_v REAL, vout_max_v REAL,
              vout_max_ratio_to_vin REAL, iout_max_a REAL,
              aec_q100 INTEGER, automotive INTEGER, i2c INTEGER,
              spi INTEGER, ocp INTEGER, ovp INTEGER, uvlo INTEGER, otp INTEGER,
              short_circuit_protection INTEGER, package_type TEXT,
              reviewed INTEGER NOT NULL DEFAULT 0, datasheet_id TEXT
            );
            CREATE TABLE IF NOT EXISTS evidence_chunks (
              evidence_id TEXT PRIMARY KEY, product_id TEXT NOT NULL,
              part_number TEXT NOT NULL, document_id TEXT NOT NULL, page INTEGER NOT NULL,
              section TEXT, field_name TEXT, text TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0,
              chunk_hash TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
              evidence_id UNINDEXED, part_number, section, text
            );
            CREATE TABLE IF NOT EXISTS chunk_embeddings (
              evidence_id TEXT NOT NULL, chunk_hash TEXT NOT NULL,
              embedding_model TEXT NOT NULL, embedding_dimension INTEGER NOT NULL,
              embedding BLOB NOT NULL,
              PRIMARY KEY (evidence_id, embedding_model)
            );
            CREATE TABLE IF NOT EXISTS query_embedding_cache (
              query_hash TEXT NOT NULL, embedding_model TEXT NOT NULL,
              embedding_dimension INTEGER NOT NULL, embedding BLOB NOT NULL,
              PRIMARY KEY (query_hash, embedding_model)
            );
            """
        )
        self.conn.commit()

    def upsert_product(self, product: Product) -> None:
        values = product.model_dump()
        cols = ", ".join(PRODUCT_COLUMNS)
        marks = ", ".join("?" for _ in PRODUCT_COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in PRODUCT_COLUMNS if c != "product_id")
        self.conn.execute(
            f"INSERT INTO products ({cols}) VALUES ({marks}) "
            f"ON CONFLICT(product_id) DO UPDATE SET {updates}",
            [values[c] for c in PRODUCT_COLUMNS],
        )
        self.conn.commit()

    def get_product_by_part_number(self, part_number: str) -> Product | None:
        row = self.conn.execute(
            "SELECT * FROM products WHERE upper(part_number)=upper(?)", (part_number,)
        ).fetchone()
        return _row_to_product(row) if row else None

    def filter_products(self, parsed: ParsedQuery) -> list[CandidateResult]:
        clauses = ["reviewed = 1"]
        args: list[Any] = []
        if parsed.category:
            clauses.append("lower(category) = lower(?)")
            args.append(parsed.category)
        if parsed.topology:
            clauses.append("lower(topology) = lower(?)")
            args.append(parsed.topology)
        rows = self.conn.execute(
            "SELECT * FROM products WHERE " + " AND ".join(clauses), args
        ).fetchall()
        results: list[CandidateResult] = []
        for row in rows:
            product = _row_to_product(row)
            checks = {f"{c.field}:{i}": _check_constraint(product, c)
                      for i, c in enumerate(parsed.constraints)}
            vin_request = _requested_value(parsed, "vin_v")
            vout_request = _requested_value(parsed, "vout_v")
            if vin_request is not None and vout_request is not None:
                if product.vout_max_ratio_to_vin is None:
                    checks["vout_vs_vin"] = CheckState.UNKNOWN
                else:
                    checks["vout_vs_vin"] = (
                        CheckState.PASS
                        if vout_request <= product.vout_max_ratio_to_vin * vin_request
                        else CheckState.FAIL
                    )
            hard_states = [checks[f"{c.field}:{i}"] for i, c in enumerate(parsed.constraints) if c.hard]
            if "vout_vs_vin" in checks:
                hard_states.append(checks["vout_vs_vin"])
            if CheckState.FAIL in hard_states:
                continue
            overall = CheckState.UNKNOWN if CheckState.UNKNOWN in hard_states else CheckState.PASS
            results.append(CandidateResult(product=product, checks=checks, overall=overall))
        return sorted(results, key=lambda item: (item.overall != CheckState.PASS, item.product.part_number))

    def insert_evidence(self, evidence: Evidence) -> None:
        chunk_hash = hashlib.sha256(evidence.text.encode("utf-8")).hexdigest()
        old = self.conn.execute(
            "SELECT chunk_hash FROM evidence_chunks WHERE evidence_id=?", (evidence.evidence_id,)
        ).fetchone()
        if old and old[0] == chunk_hash:
            return
        part_row = self.conn.execute(
            "SELECT part_number FROM products WHERE product_id=?", (evidence.product_id,)
        ).fetchone()
        part_number = part_row[0] if part_row else evidence.product_id
        with self.conn:
            self.conn.execute("DELETE FROM evidence_fts WHERE evidence_id=?", (evidence.evidence_id,))
            self.conn.execute(
                """INSERT OR REPLACE INTO evidence_chunks
                (evidence_id, product_id, part_number, document_id, page, section,
                 field_name, text, reviewed, chunk_hash) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (evidence.evidence_id, evidence.product_id, part_number, evidence.document_id,
                 evidence.page, evidence.section, evidence.field_name, evidence.text,
                 evidence.reviewed, chunk_hash),
            )
            self.conn.execute(
                "INSERT INTO evidence_fts(evidence_id,part_number,section,text) VALUES (?,?,?,?)",
                (evidence.evidence_id, part_number, evidence.section or "", evidence.text),
            )

    def search_fts(self, query: str, *, product_ids: list[str] | None = None,
                   limit: int = 20) -> list[Evidence]:
        terms = [t for t in _fts_terms(query) if t]
        if not terms:
            return []
        expression = " OR ".join(f'"{t}"' for t in terms[:12])
        sql = """SELECT c.* FROM evidence_fts f
                 JOIN evidence_chunks c ON c.evidence_id=f.evidence_id
                 WHERE evidence_fts MATCH ? AND c.reviewed=1"""
        args: list[Any] = [expression]
        if product_ids:
            sql += f" AND c.product_id IN ({','.join('?' for _ in product_ids)})"
            args.extend(product_ids)
        sql += " ORDER BY bm25(evidence_fts) LIMIT ?"
        args.append(limit)
        return [_row_to_evidence(r) for r in self.conn.execute(sql, args).fetchall()]

    def evidence_for_product(self, product_id: str) -> list[Evidence]:
        rows = self.conn.execute(
            "SELECT * FROM evidence_chunks WHERE product_id=? AND reviewed=1 ORDER BY page,evidence_id",
            (product_id,),
        ).fetchall()
        return [_row_to_evidence(r) for r in rows]

    def save_chunk_embedding(self, evidence_id: str, model: str, vector: list[float]) -> None:
        row = self.conn.execute(
            "SELECT chunk_hash FROM evidence_chunks WHERE evidence_id=?", (evidence_id,)
        ).fetchone()
        if not row:
            raise KeyError(evidence_id)
        array = np.asarray(vector, dtype=np.float32)
        self.conn.execute(
            """INSERT OR REPLACE INTO chunk_embeddings
            (evidence_id,chunk_hash,embedding_model,embedding_dimension,embedding)
            VALUES (?,?,?,?,?)""",
            (evidence_id, row[0], model, array.size, array.tobytes()),
        )
        self.conn.commit()

    def get_embeddings_for_filtered_chunks(
        self, product_ids: list[str], model: str
    ) -> list[tuple[Evidence, np.ndarray]]:
        if not product_ids:
            return []
        marks = ",".join("?" for _ in product_ids)
        rows = self.conn.execute(
            f"""SELECT c.*, e.embedding, e.embedding_dimension
            FROM evidence_chunks c JOIN chunk_embeddings e ON e.evidence_id=c.evidence_id
            WHERE c.product_id IN ({marks}) AND c.reviewed=1 AND e.embedding_model=?
            AND e.chunk_hash=c.chunk_hash""",
            [*product_ids, model],
        ).fetchall()
        return [(_row_to_evidence(r), np.frombuffer(r["embedding"], dtype=np.float32).copy()) for r in rows]

    def cache_query_embedding(self, query: str, model: str, vector: list[float]) -> None:
        array = np.asarray(vector, dtype=np.float32)
        self.conn.execute(
            "INSERT OR REPLACE INTO query_embedding_cache VALUES (?,?,?,?)",
            (_query_hash(query), model, array.size, array.tobytes()),
        )
        self.conn.commit()

    def load_cached_query_embedding(self, query: str, model: str) -> np.ndarray | None:
        row = self.conn.execute(
            "SELECT embedding FROM query_embedding_cache WHERE query_hash=? AND embedding_model=?",
            (_query_hash(query), model),
        ).fetchone()
        return np.frombuffer(row[0], dtype=np.float32).copy() if row else None


def _query_hash(query: str) -> str:
    normalized = " ".join(query.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _fts_terms(query: str) -> list[str]:
    import re
    return re.findall(r"[A-Za-z0-9_.+/-]+|[\u4e00-\u9fff]{2,}", query)


def _row_to_product(row: sqlite3.Row) -> Product:
    data = {key: row[key] for key in PRODUCT_COLUMNS}
    for key in BOOL_FIELDS | {"reviewed"}:
        if data[key] is not None:
            data[key] = bool(data[key])
    return Product.model_validate(data)


def _row_to_evidence(row: sqlite3.Row) -> Evidence:
    return Evidence.model_validate({key: row[key] for key in Evidence.model_fields})


def _check_constraint(product: Product, constraint: Constraint) -> CheckState:
    if constraint.operator == Operator.RANGE_CONTAINS:
        pair = {"vin_v": (product.vin_min_v, product.vin_max_v),
                "vout_v": (product.vout_min_v, product.vout_max_v)}.get(constraint.field)
        if pair is None or pair[0] is None or pair[1] is None:
            return CheckState.UNKNOWN
        try:
            return CheckState.PASS if pair[0] <= float(constraint.value) <= pair[1] else CheckState.FAIL
        except (TypeError, ValueError):
            return CheckState.UNKNOWN
    if constraint.field not in Product.model_fields:
        return CheckState.UNKNOWN
    actual = getattr(product, constraint.field)
    if actual is None:
        return CheckState.UNKNOWN
    try:
        if constraint.operator == Operator.EQ:
            passed = actual == constraint.value
        elif constraint.operator == Operator.GTE:
            passed = float(actual) >= float(constraint.value)
        elif constraint.operator == Operator.LTE:
            passed = float(actual) <= float(constraint.value)
        else:
            return CheckState.UNKNOWN
    except (TypeError, ValueError):
        return CheckState.UNKNOWN
    return CheckState.PASS if passed else CheckState.FAIL


def _requested_value(parsed: ParsedQuery, field: str) -> float | None:
    for constraint in parsed.constraints:
        if constraint.hard and constraint.field == field:
            try:
                return float(constraint.value)
            except (TypeError, ValueError):
                return None
    return None
