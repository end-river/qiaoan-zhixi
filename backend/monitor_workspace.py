"""Local, tab-scoped analysis data and its promotion to saved versions."""

import json
from datetime import datetime, timedelta, timezone

from fastapi import Header

from . import storage

VERSION = "monitor_version"
ANCESTOR = "monitor_version_ancestor"
DRAFT_VERSION = "monitor_draft_version"
ANALYSIS = "monitor_analysis"
DELETED_ANALYSIS = "monitor_deleted_analysis"
DRAFT_ANALYSIS = "monitor_draft_analysis"
SESSION = "monitor_workspace_session"


def now():
    return datetime.now(timezone.utc)


def write(db, kind, identifier, body):
    db.execute(
        "INSERT OR REPLACE INTO objects VALUES (?,?,?,?)",
        (identifier, kind, json.dumps(body, ensure_ascii=False, allow_nan=False),
         now().isoformat()),
    )


def session(
    scope: str | None = Header(None, alias="X-Workbench-Session", pattern=r"^[a-f0-9]{32}$"),
):
    if scope is None:
        return None
    cutoff = (now() - timedelta(hours=24)).isoformat()
    with storage.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        expired = db.execute(
            "DELETE FROM objects WHERE kind = ? AND created < ? RETURNING id",
            (SESSION, cutoff),
        ).fetchall()
        if expired:
            db.executemany(
                "DELETE FROM objects WHERE kind IN (?, ?) AND json_extract(body, '$._scope') = ?",
                [
                    (DRAFT_VERSION, DRAFT_ANALYSIS, key.removeprefix("workspace:"))
                    for (key,) in expired
                ],
            )
        write(db, SESSION, "workspace:" + scope, {})
    return scope


def read(db, identifier, kinds, scope=None):
    row = db.execute(
        "SELECT kind, body FROM objects WHERE id = ?", (identifier,)
    ).fetchone()
    if row and row[0] in kinds:
        kind, encoded = row
        body = json.loads(encoded)
        owner = body.pop("_scope", None)
        if owner is None or owner == scope:
            return kind, body
    raise KeyError(identifier)


def read_version(db, dataset, version_id, scope):
    kind, body = read(db, version_id, (VERSION, ANCESTOR, DRAFT_VERSION), scope)
    if body["dataset_id"] != dataset["id"]:
        raise ValueError("数据版本不属于所选数据集")
    return kind, body


def version(dataset, version_id=None, scope=None):
    identifier = version_id or dataset["original_id"]
    with storage.connect() as db:
        _, body = read_version(db, dataset, identifier, scope)
    return {"id": identifier, **body}


def version_meta(identifier, kind, body, first=None, last=None):
    records = body.get("records")
    if records:
        first, last = records[0][0], records[-1][0]
    meta = {
        "id": identifier,
        **{k: v for k, v in body.items() if k not in ("records", "issues", "saved_from_workspace")},
        "temporary": kind == DRAFT_VERSION,
    }
    if first and last:
        meta["range"] = [first, last]
    return meta


def versions(dataset_id, scope):
    with storage.connect() as db:
        rows = db.execute(
            "SELECT id, kind, json_remove(body, '$.records', '$.issues', '$._scope'), "
            "json_extract(body, '$.records[0][0]'), json_extract(body, '$.records[#-1][0]') "
            "FROM objects WHERE (kind = ? OR "
            "(kind = ? AND json_extract(body, '$._scope') = ?)) "
            "AND json_extract(body, '$.dataset_id') = ? ORDER BY created DESC",
            (VERSION, DRAFT_VERSION, scope, dataset_id),
        )
        return [
            version_meta(identifier, kind, json.loads(body), first, last)
            for identifier, kind, body, first, last in rows
        ]


def analysis(identifier, scope):
    with storage.connect() as db:
        kind, body = read(db, identifier, (ANALYSIS, DRAFT_ANALYSIS), scope)
    return {"id": identifier, **body, "temporary": kind == DRAFT_ANALYSIS}


def analysis_links(identifiers, scope):
    if not identifiers:
        return {}
    with storage.connect() as db:
        rows = db.execute(
            "SELECT id, kind FROM objects WHERE id IN (SELECT value FROM json_each(?)) "
            "AND (kind IN (?, ?) OR (kind = ? AND json_extract(body, '$._scope') = ?))",
            (json.dumps(sorted(identifiers)), ANALYSIS, DELETED_ANALYSIS, DRAFT_ANALYSIS, scope),
        )
        return dict(rows)


def visible_versions(identifiers, scope):
    if not identifiers:
        return set()
    with storage.connect() as db:
        rows = db.execute(
            "SELECT id FROM objects WHERE id IN (SELECT value FROM json_each(?)) "
            "AND (kind IN (?, ?) OR (kind = ? AND json_extract(body, '$._scope') = ?))",
            (json.dumps(sorted(identifiers)), VERSION, ANCESTOR, DRAFT_VERSION, scope),
        )
        return {identifier for (identifier,) in rows}


def store_result(dataset, result, identifier, new_versions, scope):
    with storage.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        kind, _ = read_version(db, dataset, result["version_id"], scope)
        temporary = bool(scope and (new_versions or kind == DRAFT_VERSION))
        owner = {"_scope": scope} if temporary else {}
        for version_id, body in new_versions:
            write(db, DRAFT_VERSION if temporary else VERSION, version_id, body | owner)
        write(db, DRAFT_ANALYSIS if temporary else ANALYSIS, identifier, result | owner)
    return {"id": identifier, **result, "temporary": temporary}


def scoped_rows(db, kind, dataset_id, scope):
    return db.execute(
        "SELECT id, body FROM objects WHERE kind = ? "
        "AND json_extract(body, '$._scope') = ? "
        "AND json_extract(body, '$.dataset_id') = ?",
        (kind, scope, dataset_id),
    ).fetchall()


def save_version(dataset, identifier, label, scope):
    with storage.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        kind, body = read_version(db, dataset, identifier, scope)
        if kind == VERSION and body.get("saved_from_workspace"):
            return version_meta(identifier, kind, body)
        if kind != DRAFT_VERSION:
            raise ValueError("请选择临时数据进行保存")
        parent = body["parent_id"]
        while parent:
            parent_kind, parent_body = read_version(db, dataset, parent, scope)
            if parent_kind != DRAFT_VERSION:
                break
            write(db, ANCESTOR, parent, parent_body)
            parent = parent_body["parent_id"]
        body = body | {"label": label, "saved_from_workspace": True}
        write(db, VERSION, identifier, body)

        for analysis_id, encoded in scoped_rows(db, DRAFT_ANALYSIS, dataset["id"], scope):
            result = json.loads(encoded)
            output = result["created_version_id"]
            if output == identifier or (output is None and result["version_id"] == identifier):
                result.pop("_scope")
                write(db, ANALYSIS, analysis_id, result)
        return version_meta(identifier, VERSION, body)


def discard_version(dataset, identifier, scope):
    with storage.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        kind, body = read_version(db, dataset, identifier, scope)
        if kind != DRAFT_VERSION:
            raise ValueError("只有临时数据可以放弃")

        dependents = {}
        for key, encoded in scoped_rows(db, DRAFT_VERSION, dataset["id"], scope):
            parent = json.loads(encoded)["parent_id"]
            dependents.setdefault(parent, []).append(key)
        removed = {identifier}
        pending = [identifier]
        while pending:
            children = dependents.get(pending.pop(), [])
            removed.update(children)
            pending.extend(children)

        discarded_analyses = []
        for key, encoded in scoped_rows(db, DRAFT_ANALYSIS, dataset["id"], scope):
            result = json.loads(encoded)
            if result["version_id"] in removed or result["created_version_id"] in removed:
                discarded_analyses.append(key)
        db.executemany(
            "DELETE FROM objects WHERE id = ?",
            [(key,) for key in [*removed, *discarded_analyses]],
        )

        parent = body["parent_id"]
        fallback_kind, fallback = read_version(db, dataset, parent, scope)
        while fallback_kind == ANCESTOR:
            parent = fallback["parent_id"]
            fallback_kind, fallback = read_version(db, dataset, parent, scope)
        return {
            "version_id": parent,
            "discarded_versions": sorted(removed),
            "discarded_analyses": discarded_analyses,
        }
