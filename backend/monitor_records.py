"""Transactions for deleting analysis history and reports."""

import json

from fastapi import HTTPException

from . import monitor_workspace as workspace, storage

REPORT = "monitor_report"


def history_entry(db, identifier):
    _, analysis = workspace.read(db, identifier, (workspace.ANALYSIS,))
    if analysis.get("snapshot"):
        raise KeyError(identifier)


def linked_reports(db, analysis_id):
    rows = db.execute(
        "SELECT id, body FROM objects WHERE kind = ? "
        "AND (json_extract(body, '$.analysis_id') = ? "
        "OR json_extract(body, '$.source_analysis_id') = ?) ORDER BY created DESC",
        (REPORT, analysis_id, analysis_id),
    )
    return [(identifier, json.loads(body)) for identifier, body in rows]


def deletion_preview(identifier):
    with storage.connect() as db:
        db.execute("BEGIN")
        history_entry(db, identifier)
        return {
            "reports": [
                {"id": key, "title": report["title"], "conclusion": report.get("conclusion", "")[:120]}
                for key, report in linked_reports(db, identifier)
            ]
        }


def delete_reports(db, reports):
    db.executemany(
        "DELETE FROM objects WHERE kind = ? AND id = ?",
        [(REPORT, identifier) for identifier, _ in reports],
    )
    snapshots = {report["analysis_id"] for _, report in reports}
    removed = []
    for identifier in snapshots:
        deleted = db.execute(
            "DELETE FROM objects WHERE kind = ? AND id = ? AND json_extract(body, '$.snapshot') = 1 "
            "AND NOT EXISTS (SELECT 1 FROM objects WHERE kind = ? AND json_extract(body, '$.analysis_id') = ?)",
            (workspace.ANALYSIS, identifier, REPORT, identifier),
        )
        if deleted.rowcount:
            removed.append(identifier)
    return removed


def delete_analysis(identifier, expected_reports):
    with storage.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        history_entry(db, identifier)
        reports = linked_reports(db, identifier)
        report_ids = [key for key, _ in reports]
        if set(report_ids) != expected_reports:
            raise HTTPException(409, "关联报告已变化，请核对后重新确认")
        snapshots = delete_reports(db, reports)
        # The marker distinguishes an explicitly deleted result from an expired draft in chat.
        workspace.write(db, workspace.DELETED_ANALYSIS, identifier, {})
        return {"report_ids": report_ids, "analysis_ids": [identifier, *snapshots]}


def delete_report(identifier):
    with storage.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        _, report = workspace.read(db, identifier, (REPORT,))
        snapshots = delete_reports(db, [(identifier, report)])
    return {"report_ids": [identifier], "analysis_ids": snapshots}
