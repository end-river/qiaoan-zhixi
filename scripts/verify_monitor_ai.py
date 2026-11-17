"""Verify live model tool calls on the monitoring workspace after configuring .env."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx


async def ask(client, question, conversation_id=None):
    events = {}
    kind = ""
    async with client.stream(
        "POST",
        "/api/v2/chat",
        json={
            "dataset_id": "monitor-demo",
            "conversation_id": conversation_id,
            "question": question,
        },
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                events.setdefault(kind, []).append(json.loads(line[6:]))
    if not any(
        row.get("status") == "complete" for row in events.get("done", [])
    ) or not events.get("analysis"):
        raise SystemExit(f"实时对话未生成完整分析。服务消息：{events.get('error', [])}")
    return events


async def verify(port):
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{port}", timeout=180
    ) as client:
        status = await client.get("/api/v2/health")
        status.raise_for_status()
        if not status.json()["ai_configured"]:
            raise SystemExit("请在本机 .env 中配置密钥，再执行真实对话验收。")
        first = await ask(client, "画出跨中 A 测点的挠度趋势，查看整个记录。")
        second = await ask(
            client,
            "沿用刚才的测点和趋势图，只看 2025 年 10 月 10 日及之后的数据。",
            first["conversation"][-1]["id"],
        )
        identifiers = [events["analysis"][-1]["id"] for events in (first, second)]
        for index, identifier in enumerate(identifiers):
            response = await client.get(f"/api/v2/analyses/{identifier}")
            response.raise_for_status()
            result = response.json()
            if (
                result["method"] != "trend"
                or result["parameters"]["channels"] != ["跨中 A"]
                or not result["series"]
            ):
                raise SystemExit("实际工具调用的测点或方法与请求不匹配。")
            if index == 1 and not result["range"][0].startswith("2025-10-10"):
                raise SystemExit("追问未正确更新分析时间范围。")
        output = (
            Path(__file__).resolve().parents[1]
            / "output"
            / "monitor-live-ai-results.json"
        )
        output.parent.mkdir(exist_ok=True)
        output.write_text(
            json.dumps(
                {"first": first, "follow_up": second}, ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        print(f"真实模型生成两次分析并正确更新时段。结果保存至 {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    asyncio.run(verify(parser.parse_args().port))
