import io
import os
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import storage, analysis, knowledge, reports, agent

load_dotenv(storage.ROOT / ".env")
ACTIVE = set()


@asynccontextmanager
async def lifespan(app):
    for identifier, title, df in analysis.demo_frames():
        try:
            storage.get("dataset", identifier)
        except KeyError:
            storage.save(
                "dataset",
                {
                    "name": title,
                    "source": "可复现模拟数据 / seed 20261115",
                    "simulation": True,
                    "records": df.to_dict("records"),
                },
                identifier,
            )
    knowledge.seed()
    yield


app = FastAPI(title="桥安智析 API", version="1.0.0", lifespan=lifespan)


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(KeyError)
async def missing(request, exc):
    return JSONResponse({"detail": "记录不存在"}, status_code=404)


@app.middleware("http")
async def local_guard(request, call_next):
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
        from urllib.parse import urlparse

        if urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "拒绝跨站写入请求"}, status_code=403)
    return await call_next(request)


@app.get("/api/status")
def status():
    return {
        "ai_configured": bool(os.getenv("AI_API_KEY")),
        "model": os.getenv("AI_MODEL", "qwen-plus"),
        "embedding_model": os.getenv("EMBEDDING_MODEL", "text-embedding-v2"),
        "version": "1.0.0",
    }


def dataset_meta(d):
    return {k: v for k, v in d.items() if k != "records"} | {
        "samples": len(d["records"]),
        "start": d["records"][0]["date"],
        "end": d["records"][-1]["date"],
        "suggested_reference_end": d["records"][min(179, len(d["records"]) - 1)][
            "date"
        ],
    }


@app.get("/api/datasets")
def datasets():
    return [dataset_meta(d) for d in storage.listing("dataset")]


@app.post("/api/datasets")
async def upload_dataset(file: UploadFile = File(...)):
    content = await file.read(10 * 1024 * 1024 + 1)
    df = analysis.validate_csv(content)
    d = storage.save(
        "dataset",
        {
            "name": Path(file.filename or "导入数据").name,
            "source": "用户导入 / 来源与健康基准需用户核实",
            "simulation": False,
            "records": df.to_dict("records"),
        },
    )
    (storage.DATA / "uploads").mkdir(exist_ok=True)
    (storage.DATA / "uploads" / f"{d['id']}.csv").write_bytes(content)
    return dataset_meta(d)


@app.get("/api/datasets/{identifier}/csv")
def csv(identifier):
    import pandas as pd

    content = (
        pd.DataFrame(storage.get("dataset", identifier)["records"])
        .to_csv(index=False)
        .encode("utf-8-sig")
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="monitoring.csv"'},
    )


class AnalysisInput(BaseModel):
    dataset_id: str
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


@app.post("/api/analyses")
def run_analysis(body: AnalysisInput):
    import datetime

    datetime.date.fromisoformat(body.start)
    datetime.date.fromisoformat(body.end)
    data = storage.get("dataset", body.dataset_id)
    result = analysis.analyze(data["records"], body.start, body.end)
    return storage.save("analysis", {"dataset_id": body.dataset_id, **result})


@app.get("/api/analyses/{identifier}")
def get_analysis(identifier):
    return storage.get("analysis", identifier)


@app.get("/api/documents")
def documents():
    return storage.listing("document")


@app.post("/api/documents")
async def upload_document(
    file: UploadFile = File(...),
    source: str = Form("用户提供"),
    scope: str = Form("用户提供资料，适用范围待核实"),
):
    content = await file.read(10 * 1024 * 1024 + 1)
    title = Path(file.filename or "资料").name
    text = knowledge.extract(content, title)
    return knowledge.add_document(title, text, source[:1000], scope[:500])


@app.get("/api/search")
async def search(q: str):
    if not 1 <= len(q) <= 300:
        raise ValueError("检索内容须为 1 至 300 字符")
    return await knowledge.search(q)


class ChatInput(BaseModel):
    analysis_id: str
    conversation_id: str | None = None
    question: str = Field(min_length=1, max_length=2000)


@app.get("/api/conversations")
def conversations(analysis_id: str):
    return [
        c for c in storage.listing("conversation") if c["analysis_id"] == analysis_id
    ]


@app.post("/api/chat")
async def chat(body: ChatInput, request: Request):
    if not os.getenv("AI_API_KEY"):
        raise HTTPException(
            503,
            "未配置 AI_API_KEY。统计分析可正常使用；请在本机 .env 配置密钥并重启服务，才能使用真实 AI。",
        )
    a = storage.get("analysis", body.analysis_id)
    c = (
        storage.get("conversation", body.conversation_id)
        if body.conversation_id
        else storage.save("conversation", {"analysis_id": a["id"], "turns": []})
    )
    if c["analysis_id"] != a["id"]:
        raise ValueError("会话不属于当前分析，请新建会话")
    if c["id"] in ACTIVE:
        raise HTTPException(409, "该会话正在处理中")
    ACTIVE.add(c["id"])

    async def events():
        try:
            yield agent.event("conversation", {"id": c["id"]})
            async for chunk in agent.stream_chat(request, a, c, body.question):
                yield chunk
        finally:
            ACTIVE.discard(c["id"])

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ReportInput(BaseModel):
    analysis_id: str
    conclusion: str = Field(default="", max_length=20000)
    conversation_id: str | None = None


@app.post("/api/reports")
def new_report(body: ReportInput):
    citations = []
    if body.conversation_id:
        c = storage.get("conversation", body.conversation_id)
        if c["analysis_id"] != body.analysis_id:
            raise ValueError("会话与分析不匹配")
        completed = [turn for turn in c["turns"] if turn["status"] == "complete"]
        citations = list(
            {r["id"]: r for turn in completed for r in turn["citations"]}.values()
        )
        if completed and not body.conclusion.strip():
            conclusion = "AI 分析初稿，需人工复核：\n" + completed[-1]["answer"]
            return reports.create_report(
                body.analysis_id, conclusion[:20000], citations
            )
    return reports.create_report(body.analysis_id, body.conclusion, citations)


@app.get("/api/reports")
def report_list():
    return storage.listing("report")


class EditReport(BaseModel):
    conclusion: str = Field(max_length=20000)


@app.patch("/api/reports/{identifier}")
def edit_report(identifier, body: EditReport):
    report = storage.get("report", identifier)
    report.pop("id")
    report["conclusion"] = body.conclusion
    return storage.save("report", report, identifier)


@app.get("/api/reports/{identifier}/pdf")
def pdf(identifier):
    content = reports.report_pdf(storage.get("report", identifier))
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="bridge-report.pdf"'},
    )


DIST = storage.ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
