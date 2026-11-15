import io
import os
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from . import storage


def create_report(analysis_id, conclusion="", citations=None):
    analysis = storage.get("analysis", analysis_id)
    dataset = storage.get("dataset", analysis["dataset_id"])
    s = analysis["summary"]
    default = f"在指定参考区间之后的 {s['evaluated']} 个样本中，{s['anomalies']} 个样本超过马氏距离经验阈值。"
    default += (
        " 结果提示需要进一步核查的数据变化，不构成结构损伤定位或法定安全等级鉴定。"
    )
    return storage.save(
        "report",
        {
            "title": dataset["name"] + " · 监测分析报告",
            "analysis_id": analysis_id,
            "dataset_name": dataset["name"],
            "source": dataset["source"],
            "conclusion": conclusion or default,
            "citations": citations or [],
            "reference": analysis["reference"],
            "summary": s,
            "limitations": analysis["limitations"],
            "metrics": analysis["metrics"],
        },
    )


def render_pdf(title, sections):
    font_path = Path(os.getenv("CJK_FONT_PATH", "C:/Windows/Fonts/simsun.ttc"))
    font_name = "BridgeChinese"
    if font_path.exists():
        pdfmetrics.registerFont(TTFont(font_name, str(font_path), subfontIndex=0))
    else:
        font_name = "STSong-Light"
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=(595.28, 841.89),
        leftMargin=45,
        rightMargin=45,
        topMargin=50,
        bottomMargin=48,
        title=title,
        author="桥安智析",
    )
    body = ParagraphStyle(
        "body",
        fontName=font_name,
        fontSize=10.5,
        leading=16,
        textColor=colors.HexColor("#263c4d"),
        wordWrap="CJK",
        spaceAfter=6,
    )
    heading = ParagraphStyle(
        "heading",
        parent=body,
        fontSize=15,
        leading=21,
        textColor=colors.HexColor("#087f8c"),
        spaceBefore=12,
        spaceAfter=7,
        keepWithNext=True,
    )
    big = ParagraphStyle(
        "title", parent=heading, fontSize=23, leading=31, spaceAfter=14
    )
    story = [
        Paragraph(escape(title), big),
        Paragraph("BRIDGE INSIGHT / 桥梁监测分析工作台", body),
        Spacer(1, 12),
    ]
    for section, content in sections:
        story.append(Paragraph(escape(section), heading))
        for line in content.split("\n"):
            if line.strip():
                story.append(Paragraph(escape(line), body))

    def footer(canvas, document):
        canvas.setStrokeColor(colors.HexColor("#dce5eb"))
        canvas.line(45, 38, 550, 38)
        canvas.setFont(font_name, 9)
        canvas.drawString(45, 25, "桥安智析 | 分析结果需专业人员复核")
        canvas.drawRightString(550, 25, str(document.page))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def report_pdf(report):
    a = storage.get("analysis", report["analysis_id"])
    s = report["summary"]
    refs = (
        "\n".join(
            f"[{r['id']}] {r['title']} / {r['section']}\n来源：{r['source']}\n适用范围：{r['scope']}\n证据摘录：{r['text']}"
            for r in report["citations"]
        )
        or "尚未附加资料引用；本报告当前结论仅依据统计分析。"
    )
    metrics = report["metrics"]
    metric_text = "无真实标签，不能计算误报、漏报与检测延迟。"
    if metrics:
        fp = (
            "不适用"
            if metrics["false_positive_rate"] is None
            else f"{metrics['false_positive_rate'] * 100:.2f}%"
        )
        miss = (
            "不适用"
            if metrics["miss_rate"] is None
            else f"{metrics['miss_rate'] * 100:.2f}%"
        )
        delay = (
            "不适用"
            if metrics["detection_delay_days"] is None
            else f"{metrics['detection_delay_days']} 天"
        )
        metric_text = f"仅评价参考区间之后的已标注样本。TP={metrics['tp']}，FP={metrics['fp']}，FN={metrics['fn']}，TN={metrics['tn']}。\n误报率：{fp}；漏报率：{miss}；首次命中延迟：{delay}。\n模拟数据指标不可外推为真实桥梁性能。"
    return render_pdf(
        report["title"],
        [
            (
                "01 / 数据与参数",
                f"数据来源：{report['source']}\n分析编号：{report['analysis_id']}\n参考区间：{report['reference']['start']} 至 {report['reference']['end']}；参考样本 {report['reference']['count']} 个。\n总样本 {s['samples']}；参考期后评估 {s['evaluated']}；异常 {s['anomalies']}。\n马氏距离平方阈值：{s['threshold']:.4f}；连续三点告警起点：{s['onset'] or '未触发'}。",
            ),
            ("02 / 分析结论（可编辑）", report["conclusion"]),
            (
                "03 / 可核查的计算证据",
                "\n".join(
                    f"{m['mode']}：f = {m['intercept']:.6f} + ({m['slope']:.6f}) × T；参考残差标准差 {m['reference_std']:.6f} Hz"
                    for m in a["models"]
                ),
            ),
            ("04 / 资料证据", refs),
            (
                "05 / 建议与局限",
                "先核查采集链路、传感器校准记录及温度覆盖范围；必要时由专业人员组织现场复检。\n"
                + "\n".join(report["limitations"]),
            ),
            ("06 / 评估范围", metric_text),
        ],
    )
