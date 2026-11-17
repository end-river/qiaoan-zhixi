import io
import json
import os
import asyncio
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from backend import ai_config, analysis, storage, knowledge, agent
from backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA", tmp_path)
    monkeypatch.setattr(ai_config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("AI_API_KEY", raising=False)
    with TestClient(app) as client:
        yield client


def frame(name="drift"):
    return next(df for k, _, df in analysis.demo_frames() if k == name)


def run(client, name="drift"):
    response = client.post(
        "/api/analyses",
        json={"dataset_id": name, "start": "2025-01-01", "end": "2025-06-29"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("case", ["normal", "drift", "sensor"])
def test_end_to_end_case(client, case):
    data = run(client, case)
    assert data["reference"]["count"] == 180
    assert data["summary"]["evaluated"] == 185
    assert len(data["dates"]) == 365
    r = client.post("/api/reports", json={"analysis_id": data["id"]}).json()
    assert r["summary"] == data["summary"]
    pdf = client.get("/api/reports/" + r["id"] + "/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    from pypdf import PdfReader

    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "统计" in text and "参考区间" in text
    assert (
        client.patch(
            "/api/reports/" + r["id"], json={"conclusion": "人工复核结论"}
        ).json()["conclusion"]
        == "人工复核结论"
    )


def test_labels_never_influence_prediction():
    df = frame()
    a = analysis.analyze(df.to_dict("records"), "2025-01-01", "2025-06-29")
    df["damage"] = 1 - df.damage
    b = analysis.analyze(df.to_dict("records"), "2025-01-01", "2025-06-29")
    c = analysis.analyze(
        df.drop(columns="damage").to_dict("records"), "2025-01-01", "2025-06-29"
    )
    assert a["score"] == b["score"] == c["score"]
    assert a["flags"] == b["flags"] == c["flags"]
    assert c["metrics"] is None


def test_temperature_model_recovers_known_slopes():
    a = analysis.analyze(frame("normal").to_dict("records"), "2025-01-01", "2025-06-29")
    np.testing.assert_allclose(
        [m["slope"] for m in a["models"]],
        [-0.0025, -0.0028, -0.0035, -0.004],
        atol=0.00015,
    )
    assert a["summary"]["anomalies"] < 10


@pytest.mark.parametrize(
    "bad", ["missing", "duplicate", "nan", "infinity", "negative", "date", "label"]
)
def test_validation_errors(client, bad):
    df = frame()
    if bad == "missing":
        df = df.drop(columns="f1")
    if bad == "duplicate":
        df.loc[1, "date"] = df.loc[0, "date"]
    if bad == "nan":
        df.loc[1, "f1"] = np.nan
    if bad == "infinity":
        df.loc[1, "f1"] = np.inf
    if bad == "negative":
        df.loc[1, "f1"] = -1
    if bad == "date":
        df.loc[1, "date"] = "invalid"
    if bad == "label":
        df.loc[1, "damage"] = 3
    response = client.post(
        "/api/datasets",
        files={"file": ("bad.csv", df.to_csv(index=False).encode(), "text/csv")},
    )
    assert response.status_code == 422


def test_upload_without_labels_and_reanalysis(client):
    df = frame().drop(columns="damage")
    response = client.post(
        "/api/datasets",
        files={"file": ("new.csv", df.to_csv(index=False).encode(), "text/csv")},
    )
    assert response.status_code == 200
    first = run(client, response.json()["id"])
    second = client.post(
        "/api/analyses",
        json={
            "dataset_id": response.json()["id"],
            "start": "2025-01-01",
            "end": "2025-05-01",
        },
    ).json()
    assert first["metrics"] is None
    assert first["id"] != second["id"] and first["score"] != second["score"]


def test_bad_baseline_and_singular_covariance(client):
    r = client.post(
        "/api/analyses",
        json={"dataset_id": "normal", "start": "2025-01-01", "end": "2025-01-10"},
    )
    assert r.status_code == 422
    df = frame("normal")
    for col in analysis.FREQ:
        df[col] = 3.9 - 0.002 * df.temperature
    result = analysis.analyze(df.to_dict("records"), "2025-01-01", "2025-06-29")
    assert np.isfinite(result["score"]).all()
    df.temperature = 15
    with pytest.raises(ValueError, match="温差"):
        analysis.analyze(df.to_dict("records"), "2025-01-01", "2025-06-29")


def test_unconfigured_ai_honest_failure(client):
    a = run(client)
    r = client.post("/api/chat", json={"analysis_id": a["id"], "question": "分析异常"})
    assert r.status_code == 503 and "未配置" in r.json()["detail"]


def test_sources_and_no_match(client):
    results = client.get("/api/search", params={"q": "温度补偿异常"}).json()
    assert results["mode"] == "keyword" and results["warning"]
    assert results["results"] and all(
        r["source"] and r["section"] for r in results["results"]
    )
    assert (
        client.get("/api/search", params={"q": "xylophonezzquux"}).json()["results"]
        == []
    )
    response = client.post(
        "/api/documents",
        files={
            "file": (
                "guide.md",
                "# 校准\n请核查传感器校准记录。".encode(),
                "text/markdown",
            )
        },
    )
    assert response.status_code == 200
    assert client.get("/api/search", params={"q": "校准记录"}).json()["results"]


def test_scanned_pdf_rejected():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(595, 842)
    data = io.BytesIO()
    writer.write(data)
    with pytest.raises(ValueError, match="扫描 PDF"):
        knowledge.extract(data.getvalue(), "scan.pdf")


def test_tool_allowlist_and_arguments(client):
    a = run(client)
    with pytest.raises(ValueError):
        asyncio.run(agent.execute("run_python", {"code": "print(1)"}, a))
    with pytest.raises(ValueError):
        asyncio.run(agent.execute("detect_anomalies", {"bad": 1}, a))
    with pytest.raises(ValueError):
        asyncio.run(
            agent.execute(
                "compare_periods",
                {
                    "start_a": "2025-02-01",
                    "end_a": "2025-01-01",
                    "start_b": "2025-08-01",
                    "end_b": "2025-08-05",
                },
                a,
            )
        )
    overview = asyncio.run(agent.execute("data_overview", {}, a))
    assert overview["summary"] == a["summary"]


def test_report_cannot_use_another_analysis_conversation(client):
    a = run(client, "drift")
    b = run(client, "normal")
    conversation = storage.save("conversation", {"analysis_id": b["id"], "turns": []})
    assert (
        client.post(
            "/api/reports",
            json={"analysis_id": a["id"], "conversation_id": conversation["id"]},
        ).status_code
        == 422
    )


def test_report_carries_completed_ai_draft_and_sources(client):
    a = run(client)
    evidence = client.get("/api/search", params={"q": "温度补偿"}).json()["results"][0]
    conversation = storage.save(
        "conversation",
        {
            "analysis_id": a["id"],
            "turns": [
                {
                    "status": "complete",
                    "answer": f"请参考 [{evidence['id']}] 复核。",
                    "citations": [evidence],
                },
                {"status": "cancelled", "answer": "未完成内容", "citations": []},
            ],
        },
    )
    response = client.post(
        "/api/reports",
        json={"analysis_id": a["id"], "conversation_id": conversation["id"]},
    )
    assert response.status_code == 200
    report = response.json()
    assert report["conclusion"].startswith("AI 分析初稿")
    assert evidence["id"] in report["conclusion"] and report["citations"] == [evidence]
    assert "未完成内容" not in report["conclusion"]


def test_cross_site_write_blocked(client):
    assert (
        client.post(
            "/api/analyses",
            headers={"origin": "https://untrusted.example"},
            json={"dataset_id": "drift", "start": "2025-01-01", "end": "2025-06-29"},
        ).status_code
        == 403
    )
