"""Explicitly run after configuring .env; consumes real API quota."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx


async def main():
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8000", timeout=180
    ) as client:
        status = (await client.get("/api/status")).json()
        if not status["ai_configured"]:
            raise SystemExit(
                "AI_API_KEY is not configured. No real AI acceptance performed."
            )
        response = await client.post(
            "/api/analyses",
            json={"dataset_id": "drift", "start": "2025-01-01", "end": "2025-06-29"},
        )
        response.raise_for_status()
        a = response.json()
        events = []
        async with client.stream(
            "POST",
            "/api/chat",
            json={
                "analysis_id": a["id"],
                "question": "先调用异常分析工具核对异常数量，再检索温度补偿的专业资料；引用检索片段解释频率下降是否能由温度解释。",
            },
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        Path("output").mkdir(exist_ok=True)
        Path("output/live-ai-results.json").write_text(
            json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        complete = any(e.get("status") == "complete" and "usage" in e for e in events)
        tools = [e for e in events if e.get("name") and e.get("status") == "complete"]
        citations = [e for e in events if e.get("items")]
        hybrid = any(e.get("result", {}).get("mode") == "hybrid" for e in tools)
        print(
            json.dumps(
                {
                    "complete": complete,
                    "tools": len(tools),
                    "citations": len(citations),
                    "hybrid_retrieval": hybrid,
                },
                indent=2,
            )
        )
        if not (complete and tools and citations and hybrid):
            raise SystemExit(
                "Real AI acceptance incomplete; inspect output/live-ai-results.json."
            )


if __name__ == "__main__":
    asyncio.run(main())
