import asyncio
import io
import json
import time
from datetime import timedelta
from threading import Event
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from openpyxl import Workbook
from pypdf import PdfReader
from backend import monitor_api, storage

from test_platform import client as client_fixture
from test_agent_protocol import FakeClient, FakeResponse, token, tool

BASE = "/api/v2"
client = client_fixture


def checked(response):
    assert response.status_code == 200, response.text
    return response.json()


def upload(client, payload, filename, sheet=None):
    item = checked(client.post(BASE + "/uploads", files={"file": (filename, payload)}))
    path = BASE + "/uploads/" + item["token"]
    preview = checked(client.get(path, params={"sheet": sheet} if sheet else {}))
    return checked(
        client.post(
            path + "/confirm",
            json={
                "sheet": sheet,
                "time_column": preview["time_column"],
                "channels": [
                    {"name": c, "unit": "mm", "type": "挠度"}
                    for c in preview["columns"][1:]
                ],
            },
        )
    )


def run(client, method, ds="monitor-demo", version=None, *, scope=None, **params):
    return client.post(
        BASE + "/analyses",
        headers=workspace_headers(scope) if scope else {},
        json={
            "dataset_id": ds,
            "method": method,
            "parameters": params,
            "version_id": version,
        },
    )


def workspace_headers(scope):
    return {"X-Workbench-Session": scope}


def scan_intervals(client, dataset, method=None, version=None, *, scope=None, **params):
    return client.post(
        BASE + f"/datasets/{dataset}/observation-intervals",
        headers=workspace_headers(scope) if scope else {},
        json={"version_id": version, "method": method, "parameters": params},
    )


def test_observation_scan_breaks_gaps_and_uses_precise_boundaries(client):
    first = pd.Timestamp("2025-01-01T08:05:37.250")
    start_second = first + pd.Timedelta(days=1)
    rows = [(first + pd.Timedelta(minutes=12 * i), i, i + 2) for i in range(20)]
    duplicate = first + pd.Timedelta(hours=4)
    rows += [(duplicate, 1, 2), (duplicate, 3, 4), (duplicate + pd.Timedelta(minutes=12), 5, "")]
    rows += [(start_second + pd.Timedelta(minutes=15 * i), i, i + 2) for i in range(10)]
    text = "时间,测点 A,测点 B\n" + "\n".join(f"{time},{a},{b}" for time, a, b in rows)
    ds = upload(client, text.encode(), "观测区间.csv")
    dsid = ds["id"]
    channels = ["测点 A", "测点 B"]

    invalid = run(client, "fft", dsid, channels=channels)
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "observation_interval_required"
    found = checked(scan_intervals(client, dsid, channels=channels))
    assert [window["samples"] for window in found["intervals"]] == [20, 10]
    assert [window["interval_seconds"] for window in found["intervals"]] == [720, 900]
    assert found["diagnostics"]["missing_rows"] == 1
    assert found["diagnostics"]["duplicate_rows"] == 2
    assert found["diagnostics"]["longest_samples"] == 20

    [window] = checked(scan_intervals(client, dsid, "filter", channels=channels, cutoff_hz=0.0002))["intervals"]
    assert window["start"] == "2025-01-01T08:05:37.250"
    assert window["end"] == "2025-01-01T11:53:37.250"
    assert window["duration_seconds"] == 19 * 720
    assert checked(scan_intervals(client, dsid, "filter", channels=channels))["intervals"] == [window]
    result = checked(run(client, "filter", dsid, channels=channels, cutoff_hz=0.0002,
                         start=window["start"], end=window["end"]))
    assert result["range"] == [window["start"], window["end"]]
    stl = checked(scan_intervals(client, dsid, "stl", channels=channels, period_seconds=2880))
    assert stl["intervals"] == [window]
    trimmed = checked(scan_intervals(client, dsid, start=first.isoformat(), end=(first + pd.Timedelta(minutes=60)).isoformat()))
    assert trimmed["intervals"] == [] and trimmed["diagnostics"]["longest_samples"] == 6


def test_observation_scan_preserves_boundary_at_cadence_change_and_forecast_rules(client):
    start = pd.Timestamp("2025-01-01T08:05:37")
    seconds = [i * 60 for i in range(8)] + [420 + 120 * i for i in range(1, 8)]
    body = "时间,测点\n" + "\n".join(f"{start + pd.Timedelta(seconds=t)},{i}" for i, t in enumerate(seconds))
    ds = upload(client, body.encode(), "间隔变化.csv")
    found = checked(scan_intervals(client, ds["id"]))
    assert [item["interval_seconds"] for item in found["intervals"]] == [120, 60]
    assert found["intervals"][0]["start"] == found["intervals"][1]["end"]
    assert found["diagnostics"]["cadence_breaks"] == 1
    forecast = checked(scan_intervals(client, "monitor-demo", "forecast", channels=["跨中 A"], steps=24))
    assert forecast["intervals"][0]["samples"] >= 102
    scope = uuid4().hex
    processed = checked(run(client, "resample", scope=scope, channels=["跨中 A"], interval_seconds=3600))
    draft = processed["created_version_id"]
    assert scan_intervals(client, "monitor-demo", "forecast", draft, channels=["跨中 A"]).status_code == 404
    scoped = checked(scan_intervals(client, "monitor-demo", "forecast", draft, scope=scope, channels=["跨中 A"]))
    assert scoped["diagnostics"]["requires_original"] and scoped["intervals"] == []


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("stl", {"period_seconds": 86400}),
        ("fft", {}),
        ("welch", {}),
        ("filter", {"cutoff_hz": 0.00004}),
        ("moving", {"window": 9}),
        ("savgol", {"window": 9}),
        ("detrend", {}),
        ("lag", {"channels": ["跨中 A", "跨中 B"]}),
        ("forecast", {"steps": 24}),
    ],
)
def test_ai_continuous_tools_scan_and_wait_for_selection(client, monkeypatch, method, params):
    monkeypatch.setenv("AI_API_KEY", "protocol-test")
    scope = uuid4().hex
    headers = workspace_headers(scope)
    fake = FakeClient([
        FakeResponse([tool("dataset_overview")]),
        FakeResponse([tool("run_analysis", json.dumps({"method": method, "parameters": params}))]),
    ])
    monkeypatch.setattr("backend.agent.httpx.AsyncClient", lambda **kwargs: fake)
    response = client.post(BASE + "/chat", headers=headers, json={
        "dataset_id": "monitor-demo", "context": {"channels": ["跨中 B"]},
        "question": f"运行 {method}",
    })
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["status"] == "awaiting_interval"
    assert len(fake.requests) == 2
    entry = next(event for event in events if event.get("status") == "awaiting_interval" and "result" in event)
    action = entry["result"]["observation_scan"]
    assert action["method"] == method
    assert action["parameters"]["channels"] == params.get("channels", ["跨中 B"])
    assert all(action["parameters"][key] == value for key, value in params.items())
    assert action["result"]["intervals"][0]["samples"] == 287
    assert checked(client.get(BASE + "/analyses")) == []
    [conversation] = checked(client.get(BASE + "/conversations?dataset_id=monitor-demo", headers=headers))
    assert conversation["turns"][-1]["tools"][-1] == entry
    assert conversation["context"]["method"] == method

    if method == "stl":
        window = action["result"]["intervals"][0]
        settings = {**action["parameters"], "start": window["start"], "end": window["end"]}
        retried = checked(run(client, method, version=action["version_id"], scope=scope, **settings))
        assert retried["range"] == [window["start"], window["end"]]
        assert retried["parameters"]["period_seconds"] == 86400


def test_ai_scan_reports_no_candidates_in_selected_range(client, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "protocol-test")
    fake = FakeClient([
        FakeResponse([tool("dataset_overview")]),
        FakeResponse([tool("run_analysis", '{"method":"fft","parameters":{}}')]),
    ])
    monkeypatch.setattr("backend.agent.httpx.AsyncClient", lambda **kwargs: fake)
    response = client.post(BASE + "/chat", json={
        "dataset_id": "monitor-demo", "question": "分析这个时段",
        "context": {"channels": ["跨中 A"], "start": "2025-10-01T01:00:00", "end": "2025-10-01T04:00:00"},
    })
    assert response.status_code == 200
    [conversation] = checked(client.get(BASE + "/conversations?dataset_id=monitor-demo"))
    action = conversation["turns"][-1]["tools"][-1]["result"]["observation_scan"]
    assert action["result"]["intervals"] == []
    assert action["result"]["diagnostics"]["longest_samples"] == 4
    assert action["parameters"]["end"] == "2025-10-01T04:00:00"


def test_ai_scan_results_follow_temporary_version_access(client, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "protocol-test")
    scope = uuid4().hex
    version = checked(run(client, "moving", scope=scope, channels=["跨中 A"], window=9))
    fake = FakeClient([
        FakeResponse([tool("dataset_overview")]),
        FakeResponse([tool("run_analysis", '{"method":"fft","parameters":{}}')]),
    ])
    monkeypatch.setattr("backend.agent.httpx.AsyncClient", lambda **kwargs: fake)
    response = client.post(BASE + "/chat", headers=workspace_headers(scope), json={
        "dataset_id": "monitor-demo", "version_id": version["created_version_id"],
        "question": "分析当前版本", "context": {"channels": ["跨中 A"]},
    })
    assert response.status_code == 200
    path = BASE + "/conversations?dataset_id=monitor-demo"
    [own] = checked(client.get(path, headers=workspace_headers(scope)))
    [other] = checked(client.get(path, headers=workspace_headers(uuid4().hex)))
    assert own["turns"][-1]["tools"][-1]["result"]["observation_scan"]["result"]["intervals"]
    assert other["turns"][-1]["tools"][-1]["result"]["observation_scan"]["result"] is None


def test_workspace_chains_and_saves_selected_output(client):
    dataset_path = BASE + "/datasets/monitor-demo"
    versions = dataset_path + "/versions"
    scope = uuid4().hex
    headers = workspace_headers(scope)
    point = {"channels": ["跨中 B"]}

    original = checked(client.get(versions))[0]["id"]
    assert run(client, "stl", period_seconds=86400, **point).status_code == 422
    cleaned = checked(run(client, "clean", scope=scope, fill_seconds=14400, **point))
    clean_id = cleaned["created_version_id"]
    assert cleaned["temporary"] is True
    assert cleaned["rows"][0]["处理后空值"] == 0
    assert {v["id"] for v in checked(client.get(versions, headers=headers))} == {original, clean_id}
    assert {v["id"] for v in checked(client.get(versions, headers=workspace_headers(uuid4().hex)))} == {original}
    assert client.get(versions + f"/{clean_id}/csv").status_code == 404
    assert client.get(versions + f"/{clean_id}/csv", headers=headers).text.count("\n") == 337
    assert client.get(BASE + f"/analyses/{cleaned['id']}").status_code == 404

    assert run(client, "stl", version=clean_id, scope=scope, period_seconds=1, **point).status_code == 422
    decomposition = checked(run(client, "stl", version=clean_id, scope=scope, period_seconds=86400, **point))
    records = checked(client.get(dataset_path + "/records", params={"version_id": clean_id}, headers=headers))
    assert decomposition["version_id"] == clean_id
    assert decomposition["series"][0]["points"][47][1] == records["rows"][47][-1]
    assert checked(client.get(BASE + f"/analyses/{decomposition['id']}", headers=headers))["temporary"]

    sampled = checked(run(client, "resample", version=clean_id, scope=scope, interval_seconds=7200, **point))
    filtered = checked(run(client, "filter", version=sampled["created_version_id"], scope=scope,
                           cutoff_hz=0.00003, **point))
    filter_id = filtered["created_version_id"]
    spectrum = checked(run(client, "fft", version=filter_id, scope=scope, **point))
    assert spectrum["version_id"] == filter_id and spectrum["created_version_id"] is None
    save_path = versions + f"/{filter_id}/save"
    assert client.post(save_path, headers=workspace_headers(uuid4().hex), json={"label": "越界"}).status_code == 404
    saved = checked(client.post(save_path, headers=headers, json={"label": "插值重采样滤波"}))
    assert saved["id"] == filter_id and saved["temporary"] is False
    assert [s["method"] for s in saved["steps"]] == ["clean", "resample", "filter"]
    repeated = checked(client.post(save_path, headers=headers, json={"label": "重复提交"}))
    assert repeated["label"] == saved["label"]
    assert {v["id"] for v in checked(client.get(versions))} == {original, filter_id}
    assert client.get(versions + f"/{filter_id}/csv").status_code == 200
    assert checked(client.get(BASE + f"/analyses/{spectrum['id']}"))["temporary"] is False
    assert checked(run(client, "fft", version=filter_id, **point))["version_id"] == filter_id


def test_discard_keeps_independent_report_and_recipe(client, monkeypatch):
    dataset_path = BASE + "/datasets/monitor-demo"
    versions = dataset_path + "/versions"
    scope = uuid4().hex
    headers = workspace_headers(scope)
    original = checked(client.get(versions))[0]["id"]
    point = {"channels": ["跨中 B"]}
    cleaned = checked(run(client, "clean", scope=scope, fill_seconds=14400, **point))
    clean_id = cleaned["created_version_id"]
    recipe = checked(client.post(
        BASE + "/recipes", headers=headers, json={"version_id": clean_id, "name": "插值步骤"},
    ))
    replay = checked(client.post(
        BASE + f"/recipes/{recipe['id']}/apply", headers=headers,
        json={"dataset_id": "monitor-demo", "mapping": {"跨中 B": "跨中 B"}},
    ))
    assert replay["temporary"] is True
    assert replay["created_version_id"] != clean_id
    filtered = checked(run(client, "filter", version=clean_id, scope=scope, cutoff_hz=0.00004, **point))
    analysis = checked(run(client, "fft", version=filtered["created_version_id"], scope=scope, **point))
    report = checked(client.post(BASE + "/reports", headers=headers, json={"analysis_id": analysis["id"]}))
    assert report["analysis_id"] != analysis["id"]
    discarded = checked(client.delete(versions + f"/{clean_id}", headers=headers))
    assert discarded["version_id"] == original
    assert set(discarded["discarded_versions"]) == {clean_id, filtered["created_version_id"]}
    assert analysis["id"] in discarded["discarded_analyses"]
    assert client.get(BASE + f"/analyses/{analysis['id']}", headers=headers).status_code == 404
    assert client.get(versions + f"/{replay['created_version_id']}/csv", headers=headers).status_code == 200
    snapshot = checked(client.get(BASE + f"/analyses/{report['analysis_id']}"))
    assert snapshot["snapshot"] and snapshot["series"] == analysis["series"]
    assert client.get(BASE + f"/reports/{report['id']}/pdf").content.startswith(b"%PDF")
    expired = monitor_api.workspace.now() + timedelta(hours=25)
    monkeypatch.setattr(monitor_api.workspace, "now", lambda: expired)
    assert client.get(versions + f"/{replay['created_version_id']}/csv", headers=headers).status_code == 404
    assert client.get(BASE + f"/analyses/{report['analysis_id']}").status_code == 200


def test_chat_can_continue_from_workspace_version(client, monkeypatch):
    scope = uuid4().hex
    headers = workspace_headers(scope)
    cleaned = checked(run(client, "clean", scope=scope, fill_seconds=14400, channels=["跨中 B"]))
    fake = FakeClient([
        FakeResponse([tool("dataset_overview")]),
        FakeResponse([tool("run_analysis", json.dumps({"method": "filter", "parameters": {
            "cutoff_hz": 0.00004,
        }}))]),
        FakeResponse([token("已滤波。")]),
    ])
    monkeypatch.setenv("AI_API_KEY", "protocol-test")
    monkeypatch.setattr("backend.agent.httpx.AsyncClient", lambda **kwargs: fake)
    response = client.post(BASE + "/chat", headers=headers, json={
        "dataset_id": "monitor-demo", "version_id": cleaned["created_version_id"],
        "context": {"channels": ["跨中 B"]}, "question": "对当前数据做低通滤波",
    })
    assert response.status_code == 200 and "event: analysis" in response.text
    [conversation] = checked(client.get(BASE + "/conversations?dataset_id=monitor-demo", headers=headers))
    tool_result = next(t["result"] for t in conversation["turns"][0]["tools"] if t["name"] == "run_analysis")
    analysis_id = tool_result["analysis_id"]
    result = checked(client.get(BASE + f"/analyses/{analysis_id}", headers=headers))
    assert result["version_id"] == cleaned["created_version_id"] and result["temporary"]
    assert client.get(BASE + f"/analyses/{analysis_id}").status_code == 404
    [other_tab] = checked(client.get(BASE + "/conversations?dataset_id=monitor-demo"))
    tool_status = next(t["result"] for t in other_tab["turns"][0]["tools"] if t["name"] == "run_analysis")
    assert tool_status["unavailable"] and "analysis_id" not in tool_status


def test_history_deletion_conflict_cascade_and_retains_data_version(client):
    analysis = checked(run(client, "filter", cutoff_hz=0.00004, channels=["跨中 A"]))
    route = BASE + "/analyses/" + analysis["id"]
    report_route = BASE + "/reports"
    first = checked(client.post(report_route, json={"analysis_id": analysis["id"]}))
    # Reports saved before source tracking used the analysis ID directly.
    legacy = {k: v for k, v in first.items() if k not in ("id", "source_analysis_id")}
    storage.save("monitor_report", legacy, first["id"])
    preview = checked(client.get(route + "/deletion-preview"))
    assert preview["reports"] == [{
        "id": first["id"], "title": first["title"], "conclusion": first["conclusion"]
    }]

    extra = checked(client.post(report_route, json={"analysis_id": analysis["id"]}))
    stale = client.request("DELETE", route, json={"report_ids": [first["id"]]})
    assert stale.status_code == 409
    assert client.get(route).status_code == 200
    assert client.get(report_route + f"/{first['id']}/pdf").content.startswith(b"%PDF")
    assert {p["id"] for p in checked(client.get(route + "/deletion-preview"))["reports"]} == {
        first["id"], extra["id"]
    }
    deleted = checked(client.request("DELETE", route, json={"report_ids": [first["id"], extra["id"]]}))
    assert set(deleted["report_ids"]) == {first["id"], extra["id"]}
    assert checked(client.get(report_route)) == []
    assert client.get(route).status_code == 404
    assert client.get(report_route + f"/{extra['id']}/pdf").status_code == 404
    assert analysis["id"] not in {item["id"] for item in checked(client.get(BASE + "/analyses"))}
    assert client.post(report_route, json={"analysis_id": analysis["id"]}).status_code == 404
    version = analysis["created_version_id"]
    assert client.get(BASE + f"/datasets/monitor-demo/versions/{version}/csv").status_code == 200


def test_report_deletion_preserves_shared_snapshot_until_last_reference(client):
    headers = workspace_headers(scope := uuid4().hex)
    analysis = checked(run(client, "clean", scope=scope, fill_seconds=14400))
    report_route = BASE + "/reports"
    first = checked(client.post(report_route, headers=headers, json={"analysis_id": analysis["id"]}))
    snapshot_id = first["analysis_id"]
    snapshot_route = BASE + "/analyses/" + snapshot_id
    second = checked(client.post(report_route, json={"analysis_id": snapshot_id}))

    assert first["source_analysis_id"] == second["source_analysis_id"] == analysis["id"]
    assert checked(client.delete(report_route + "/" + first["id"]))["analysis_ids"] == []
    assert checked(client.get(snapshot_route))["snapshot"]
    assert client.get(report_route + f"/{second['id']}/pdf").content.startswith(b"%PDF")
    assert checked(client.delete(report_route + "/" + second["id"]))["analysis_ids"] == [snapshot_id]
    assert client.get(snapshot_route).status_code == 404
    assert client.get(BASE + "/analyses/" + analysis["id"], headers=headers).status_code == 200


def test_deepseek_tool_calls_and_deleted_conversation_link(client, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "protocol-test")
    monkeypatch.setenv("AI_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("AI_MODEL", "deepseek-flash")
    fake = FakeClient([
        FakeResponse([tool("dataset_overview")]),
        FakeResponse([tool("run_analysis", json.dumps({"method": "trend", "parameters": {
            "channels": ["跨中 A"],
        }}))]),
        FakeResponse([token("已完成趋势分析。")]),
    ])
    monkeypatch.setattr("backend.agent.httpx.AsyncClient", lambda **kwargs: fake)
    response = client.post(BASE + "/chat", json={
        "dataset_id": "monitor-demo", "question": "查看跨中 A 的趋势",
    })
    assert response.status_code == 200
    assert "event: analysis" in response.text and "event: token" in response.text
    assert [request["thinking"] for request in fake.requests] == [{"type": "disabled"}] * 3
    assert fake.requests[0]["tool_choice"] == monitor_api.MonitorChat.first_tool
    assert fake.requests[2]["messages"][-1]["role"] == "tool"

    chat_path = BASE + "/conversations?dataset_id=monitor-demo"
    [saved] = checked(client.get(chat_path))
    assert saved["turns"][0]["status"] == "complete"
    result = next(t["result"] for t in saved["turns"][0]["tools"] if t["name"] == "run_analysis")
    route = BASE + "/analyses/" + result["analysis_id"]
    checked(client.request("DELETE", route, json={"report_ids": []}))
    [updated] = checked(client.get(chat_path))
    result = next(t["result"] for t in updated["turns"][0]["tools"] if t["name"] == "run_analysis")
    assert result["deleted"] and "analysis_id" not in result


def test_csv_import_quality_version_and_limits(client):
    raw = "\n".join(
        [
            "时间,跨中挠度",
            "2025-01-01 08:00:00.001,1",
            "2025-01-01 08:00:01.001,5",
            "2025-01-01 08:00:01.001,7",
            "2025-01-01 08:00:02.001,5",
            "时间无效,9",
            "2025-01-01 08:00:03.001,故障",
            "2025-01-01 08:00:04.001,2",
            "2025-01-01 08:00:05.001,",
        ]
    )
    ds = upload(client, raw.encode("gb18030"), "未见过的挠度.csv")
    dsid = ds["id"]
    assert ds["start"].endswith(".001") and ds["invalid_times"] == 1
    quality = checked(run(client, "quality", dsid))
    assert {r["kind"] for r in quality["issues"]} == {
        "缺测",
        "非数值",
        "无效时间",
        "重复时间",
    }
    assert quality["rows"][0]["重复时间行"] == 2
    assert (
        checked(client.get(BASE + f"/datasets/{dsid}/records", params={"row": 6}))[
            "issue"
        ]["kind"]
        == "无效时间"
    )
    data = checked(run(client, "clean", dsid, duplicate="mean", fill_seconds=2))
    version = data["created_version_id"]
    records = checked(
        client.get(BASE + f"/datasets/{dsid}/records", params={"version_id": version})
    )
    assert [r[-1] for r in records["rows"]] == [1, 6, 5, 3.5, 2, None]
    assert client.get(BASE + f"/datasets/{dsid}/original").content == raw.encode(
        "gb18030"
    )
    rules = {
        "channel": "跨中挠度",
        "unit": "mm",
        "upper": 4,
        "duration": 1,
        "source": "核查演示",
    }
    event = checked(run(client, "limits", dsid, version, rule=rules))["events"]
    assert len(event) == 1 and event[0]["持续秒数"] == 1 and event[0]["最大值"] == 6
    assert run(client, "trend", version=version).status_code == 422
    recipe = checked(
        client.post(
            BASE + "/recipes", json={"version_id": version, "name": "去重与补值"}
        )
    )
    another = upload(client, raw.replace("跨中挠度", "测点甲").encode(), "另一个.csv")
    replay = checked(
        client.post(
            BASE + f"/recipes/{recipe['id']}/apply",
            json={
                "dataset_id": another["id"],
                "mapping": {"跨中挠度": "测点甲"},
            },
        )
    )
    assert replay["steps"][0]["parameters"]["channels"] == ["测点甲"]
    assert replay["created_version_id"] != version


def workbook_fixture():
    book = Workbook()
    book.active.title = "说明"
    book.active.append(["以下工作表包含观测记录"])
    sheet = book.create_sheet("观测数据")
    sheet.append(["采样时间", "桥面一", "桥面二", "常量"])
    expected = np.random.default_rng(12).standard_normal(144)
    times = pd.date_range("2025-01-01", periods=len(expected), freq="100ms")
    n = np.arange(len(times))
    for i, t in enumerate(times):
        sheet.append(
            [
                t.to_pydatetime(),
                np.sin(2 * np.pi * n[i] / 12),
                float(expected[i - 4]) if i >= 4 else 0,
                2.0,
            ]
        )
    sheet["B3"].number_format = "0.000"
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def test_xlsx_spectrum_stl_and_constant_handling(client):
    ds = upload(client, workbook_fixture(), "桥面试验.xlsx", "观测数据")
    assert ds["sheet"] == "观测数据" and ds["interval"] == 0.1
    args = {"channels": ["桥面一"]}
    spectrum = checked(run(client, "fft", ds["id"], **args))
    assert spectrum["rows"][0]["主要频率 Hz"] == pytest.approx(1 / 1.2)
    stl = checked(run(client, "stl", ds["id"], period_seconds=1.2, **args))
    assert stl["rows"][0]["周期采样点"] == 12
    raw, trend, cycle, residual = ([y for _, y in s["points"]] for s in stl["series"])
    np.testing.assert_allclose(raw, np.array(trend) + cycle + residual, atol=1e-10)
    assert run(client, "stl", ds["id"], period_seconds=20, **args).status_code == 422
    assert run(client, "lag", ds["id"], channels=["桥面一", "常量"]).status_code == 422
    corr = checked(run(client, "correlation", ds["id"], channels=["桥面一", "常量"]))
    assert corr["rows"][0]["相关系数"] is None
    assert (
        client.post(
            BASE + "/uploads",
            files={"file": ("too-large.csv", b"0" * (20 * 1024 * 1024 + 1))},
        ).status_code
        == 422
    )


def test_lag_irregular_and_event_summary(client):
    rng = np.random.default_rng(17)
    a = rng.normal(size=100)
    b = np.r_[np.zeros(3), a[:-3]]
    stamps = pd.date_range("2025-03-01", periods=100, freq="s")
    rows = [f"{t},{x},{y}" for t, x, y in zip(stamps, a, b)]
    ds = upload(client, ("时间,A,B\n" + "\n".join(rows)).encode(), "同步记录.csv")
    lag = checked(run(client, "lag", ds["id"], max_lag=10))
    assert max(lag["rows"], key=lambda r: r["相关系数"])["时滞秒"] == 3
    irregular = upload(
        client, ("时间,A,B\n" + "\n".join(rows[:7] + rows[8:])).encode(), "不规则.csv"
    )
    assert run(client, "welch", irregular["id"]).status_code == 422
    data = checked(run(client, "anomaly", channels=["跨中 A"], threshold=6))
    assert any(
        r["开始"].startswith("2025-10-08") and "持续偏移" in r["触发依据"]
        for r in data["events"]
    )


def test_forecast_sequential_rules_and_report(client):
    result = checked(
        run(
            client,
            "forecast",
            channels=["跨中 A"],
            steps=8,
            rule={
                "channel": "跨中 A",
                "unit": "mm",
                "upper": 2.7,
                "source": "用户演示限值",
            },
        )
    )
    assert len(result["forecast"]) == 8 and len(result["backtest"]) == 24
    assert all(r["训练截止"] < r["时间"] for r in result["backtest"])
    assert len(set(r["训练截止"] for r in result["backtest"])) == 3
    assert all(r["下界"] <= r["预测"] <= r["上界"] for r in result["forecast"])
    assert any(r["模型"] == "末值基准" for r in result["rows"])
    too_short = run(client, "forecast", channels=["跨中 A"], end="2025-10-01")
    missing = run(client, "forecast", channels=["跨中 B"])
    assert too_short.status_code == missing.status_code == 422
    report = checked(client.post(BASE + "/reports", json={"analysis_id": result["id"]}))
    pdf = client.get(BASE + f"/reports/{report['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    reader = PdfReader(io.BytesIO(pdf.content))
    contents = "".join(p.extract_text() for p in reader.pages)
    assert all(
        text in contents for text in ("分析结论", "分析图表", "处理步骤", "SARIMAX")
    )
    assert client.get(BASE + f"/analyses/{result['id']}/csv").text.count("\n") > 336


def test_sse_chat_tools_and_inheritance(client, monkeypatch):
    payload = {"dataset_id": "monitor-demo", "question": "请画跨中 A 的趋势"}
    assert client.post(BASE + "/chat", json=payload).status_code == 503
    fake = FakeClient(
        [
            FakeResponse([tool("dataset_overview")]),
            FakeResponse(
                [
                    tool(
                        "run_analysis",
                        json.dumps(
                            {"method": "trend", "parameters": {"channels": ["跨中 A"]}}
                        ),
                    )
                ]
            ),
            FakeResponse([token("趋势图已计算。")]),
            FakeResponse([tool("dataset_overview")]),
            FakeResponse(
                [
                    tool(
                        "run_analysis",
                        json.dumps(
                            {"method": "trend", "parameters": {"start": "2025-10-10"}}
                        ),
                    )
                ]
            ),
            FakeResponse([token("已缩小时间范围。")]),
        ]
    )
    monkeypatch.setenv("AI_API_KEY", "protocol-test")
    monkeypatch.setattr("backend.agent.httpx.AsyncClient", lambda **kwargs: fake)
    first = client.post(BASE + "/chat", json=payload)
    assert first.status_code == 200 and "event: analysis" in first.text
    [saved] = checked(client.get(BASE + "/conversations?dataset_id=monitor-demo"))
    second = client.post(
        BASE + "/chat",
        json={**payload, "question": "从十月十日开始", "conversation_id": saved["id"]},
    )
    assert second.status_code == 200 and "event: analysis" in second.text
    [saved] = checked(client.get(BASE + "/conversations?dataset_id=monitor-demo"))
    assert saved["context"]["channels"] == ["跨中 A"]
    assert saved["context"]["start"] == "2025-10-10"
    assert len(saved["turns"]) == 2


def test_cancelled_analysis_stops_before_persistence(monkeypatch):
    stopped = Event()

    class Disconnected:
        async def is_disconnected(self):
            return True

    def prepare(body, check, scope):
        try:
            for _ in range(200):
                check()
                time.sleep(0.005)
            raise AssertionError("worker did not receive cancellation")
        finally:
            stopped.set()

    def persist(*args):
        pytest.fail("cancelled calculation was persisted")

    monkeypatch.setattr(monitor_api, "prepare", prepare)
    monkeypatch.setattr(monitor_api, "persist", persist)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(monitor_api.run(None, Disconnected()))
    assert stopped.is_set()


def test_signal_transform_preserves_original_and_resampling_is_explicit(client):
    params = {"channels": ["跨中 A"], "window": 5}
    result = checked(run(client, "savgol", **params))
    processed = checked(
        client.get(
            BASE + "/datasets/monitor-demo/records",
            params={"version_id": result["created_version_id"]},
        )
    )
    original = checked(client.get(BASE + "/datasets/monitor-demo/records"))
    assert processed["rows"][0][2] != original["rows"][0][2]
    assert processed["rows"][0][3] == original["rows"][0][3]
    assert processed["rows"][0][2] == pytest.approx(result["series"][1]["points"][0][1])
    aggregate = checked(run(client, "resample", interval_seconds=7200))
    updated = checked(
        client.get(
            BASE + "/datasets/monitor-demo/records",
            params={"version_id": aggregate["created_version_id"]},
        )
    )
    assert updated["total"] == 168
    assert updated["rows"][0][2] == pytest.approx(
        np.mean([r[2] for r in original["rows"][:2]])
    )


def test_service_health_and_downloadable_import_template(client, tmp_path):
    health = checked(client.get(BASE + "/health"))
    assert health == {
        "service": "bridge-insight",
        "api_version": 2,
        "workspace_drafts": True,
        "record_deletion": True,
        "observation_intervals": True,
        "chat_observation_intervals": True,
        "ai_configured": False,
    }
    (tmp_path / ".env").write_text(
        "AI_API_KEY=placeholder-for-configuration-test", encoding="utf-8"
    )
    configured = checked(client.get(BASE + "/health"))
    assert configured == {**health, "ai_configured": True}
    template = client.get(BASE + "/import-template.csv")
    assert template.status_code == 200
    dataset = upload(client, template.content, "monitor-template.csv")
    assert dataset["samples"] == 72 and dataset["regular"]
    assert checked(run(client, "trend", dataset["id"]))["series"]


def test_launcher_rejects_legacy_server_with_matching_page_title(monkeypatch):
    from scripts import launch

    requests = []
    responses = {
        "/": (200, launch.TITLE),
        "/api/v2/health": (404, b'{"detail":"Not Found"}'),
    }

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, path):
            requests.append(path)
            self.status, self.body = responses[path]

        def getresponse(self):
            return self

        def read(self, amount):
            return self.body[:amount]

        def close(self):
            pass

    monkeypatch.setattr(launch, "HTTPConnection", Connection)
    assert not launch.platform_ready(8000)
    assert requests == ["/", "/api/v2/health"]
    responses["/api/v2/health"] = (200, b'{"service":"bridge-insight","api_version":2}')
    assert not launch.platform_ready(8000)
    responses["/api/v2/health"] = (
        200, b'{"service":"bridge-insight","api_version":2,"workspace_drafts":true}',
    )
    assert not launch.platform_ready(8000)
    responses["/api/v2/health"] = (
        200, b'{"service":"bridge-insight","api_version":2,"workspace_drafts":true,"record_deletion":true}',
    )
    assert not launch.platform_ready(8000)
    responses["/api/v2/health"] = (
        200, b'{"service":"bridge-insight","api_version":2,"workspace_drafts":true,'
        b'"record_deletion":true,"observation_intervals":true}',
    )
    assert not launch.platform_ready(8000)
    responses["/api/v2/health"] = (
        200, b'{"service":"bridge-insight","api_version":2,"workspace_drafts":true,'
        b'"record_deletion":true,"observation_intervals":true,"chat_observation_intervals":true}',
    )
    assert launch.platform_ready(8000)


def test_upload_rejects_duplicate_headers_and_invalid_time_with_specific_feedback(
    client,
):
    response = client.post(
        BASE + "/uploads",
        files={"file": ("duplicate.csv", "时间,跨中,跨中\n2025-01-01,1,2\n".encode())},
    )
    assert response.status_code == 422 and "重复列名" in response.json()["detail"]
    item = checked(
        client.post(
            BASE + "/uploads",
            files={"file": ("bad-time.csv", "时间,测点\n45931,1\n".encode())},
        )
    )
    response = client.post(
        BASE + "/uploads/" + item["token"] + "/confirm",
        json={
            "time_column": "时间",
            "channels": [{"name": "测点", "type": "挠度", "unit": "mm"}],
        },
    )
    assert response.status_code == 422 and "第 2 行" in response.json()["detail"]
