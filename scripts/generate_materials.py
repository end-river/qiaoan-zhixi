import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    PageBreak,
    Table,
    TableStyle,
    Image,
)
from backend import storage, analysis, reports

ROOT = storage.ROOT
OUT = ROOT / "output" / "pdf"
OUT.mkdir(parents=True, exist_ok=True)
font = Path("C:/Windows/Fonts/simsun.ttc")
pdfmetrics.registerFont(TTFont("Chinese", str(font), subfontIndex=0))
navy = colors.HexColor("#15394b")
teal = colors.HexColor("#07868c")
muted = colors.HexColor("#6e8795")
styles = {
    "body": ParagraphStyle(
        "body",
        fontName="Chinese",
        fontSize=10.5,
        leading=19,
        textColor=navy,
        wordWrap="CJK",
        spaceAfter=10,
    ),
    "h1": ParagraphStyle(
        "h1", fontName="Chinese", fontSize=25, leading=36, textColor=navy, spaceAfter=18
    ),
    "h2": ParagraphStyle(
        "h2",
        fontName="Chinese",
        fontSize=15,
        leading=24,
        textColor=teal,
        spaceBefore=14,
        spaceAfter=11,
    ),
    "small": ParagraphStyle(
        "small",
        fontName="Chinese",
        fontSize=9,
        leading=16,
        textColor=muted,
        wordWrap="CJK",
        spaceAfter=8,
    ),
}


def p(text, style="body"):
    return Paragraph(escape(text), styles[style])


def table(rows, widths):
    t = Table(
        [[p(str(v), "small") for v in row] for row in rows],
        colWidths=widths,
        hAlign="LEFT",
    )
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf4f4")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2ebef")),
            ]
        )
    )
    return t


story = []


def page(number, title):
    if story:
        story.append(PageBreak())
    story.extend(
        [
            p("BRIDGE INSIGHT  /  TECHNICAL DOCUMENT", "small"),
            p(f"{number:02d}  {title}", "h1"),
        ]
    )


def section(title, text):
    story.append(p(title, "h2"))
    story.extend(p(line) for line in text.split("\n") if line.strip())


page(1, "桥安智析")
story.append(p("桥梁监测 AI 分析工作台", "h1"))
story.append(p("从环境变化中识别异常，让每一步判断回到证据。", "h2"))
story.append(Spacer(1, 22))
story.append(
    table(
        [
            ["项目定位", "面向桥梁监测分析人员的可追溯分析工作台"],
            ["参赛赛道", "AI WEB 网页开发挑战赛"],
            ["版本与日期", "1.0.0 / 2026-11-15"],
            ["学校 / 组别", "【待填】 / 【待填】"],
            ["参赛成员 / 指导老师", "【待填】 / 【待填】"],
            ["当前验收状态", "统计分析、前端和报告已验证；真实模型调用待配置密钥验收"],
        ],
        [125, 380],
    )
)
section(
    "作品概述",
    "用户导入监测数据并指定健康参考区间，系统计算温度补偿与异常指标；AI 通过受限工具解释结果，结合有来源的资料提供复核建议，最终生成可编辑、可追溯的报告。",
)
section(
    "真实性说明",
    "三个演示案例均为固定种子生成的模拟数据，不是 Z24 实测数据。AI 接口与混合检索已经实现，但本版本没有真实 API 成功调用记录。统计异常不构成结构损伤定位或法定安全鉴定。",
)
page(2, "需求与产品设计")
section(
    "用户问题",
    "监测人员面对长期模态频率曲线，既要判断环境温度带来的变化，也要核查异常是否具有持续性和多通道一致性。仅有曲线或单一异常数值无法直接支持复检决策。",
)
story.append(
    table(
        [
            ["页面", "关键任务"],
            [
                "分析工作台",
                "导入或选择案例、指定参考区间、运行分析、检查图表与评估指标",
            ],
            ["AI 分析助手", "多轮提问、工具执行状态、流式回答、资料引用与图表证据入口"],
            ["专业资料库", "导入文本 PDF/MD/TXT、按章节检索、核对来源和适用边界"],
            ["报告中心", "保存独立分析快照、编辑结论、导出中文 PDF"],
        ],
        [110, 395],
    )
)
section(
    "交互原则",
    "深蓝导航与浅色分析画布降低图表阅读负担；青色表示分析与行动，橙色用于告警。手机切换为底部导航，图表随容器缩放。\n加载、失败、无数据和模型未配置均有独立反馈。AI 不可用时，统计分析及报告仍可独立运行。",
)
section(
    "首版边界",
    "本地单用户研究工作台；不包含真实传感器接入、三维桥梁、多桥资产管理、图片病害识别和法定鉴定业务。公网发布属于后续工作。",
)
page(3, "系统架构与数据流")
story.append(
    table(
        [
            ["层级", "实现与职责"],
            ["前端", "React 19、TypeScript、Vite、ECharts；四页面状态与交互"],
            ["接口", "FastAPI，同源提供前端和 /api；CSV 与文本资料导入"],
            ["计算工具", "NumPy/Pandas；温度回归、3σ、正则化马氏距离和时间段对比"],
            ["模型与检索", "百炼兼容接口；Qwen Plus、Embedding、关键词与向量混合检索"],
            ["本地存储", "SQLite 保存数据集、分析快照、会话、资料、向量缓存及报告"],
            ["导出与测试", "ReportLab 中文 PDF；Pytest、TypeScript 构建与浏览器验证"],
        ],
        [110, 395],
    )
)
section(
    "主流程",
    "CSV → 格式与质量校验 → 健康区间确认 → 回归与残差 → 多变量异常 → 不可变分析快照。\n用户问题 → Agent → 工具白名单 → 结构化证据 → 模型解释 → 引用片段 → 可编辑报告。",
)
section(
    "接口与持久化",
    "/api/datasets 管理案例；/api/analyses 生成分析快照；/api/documents 和 /api/search 管理资料；/api/chat 返回 SSE；/api/reports 生成与编辑报告。\nSSE 事件包括 conversation、status、token、tool、citations、done 和 error。对话记录保存完成、失败、取消及轮次上限状态，同时记录用量和耗时。",
)
section(
    "兼容与安全",
    "后端仅监听 127.0.0.1；拒绝跨站写入；敏感配置只在服务端环境变量中读取。未使用模型生成的 Python、SQL 或系统命令。导入文件按格式和大小校验，不从上传文件名构造任意写入路径。",
)
page(4, "统计方法与证据")
section(
    "温度补偿",
    "对每阶模态频率拟合 f = a + bT，仅使用用户指定的健康参考区间。残差 r = f - (a + bT) 用于描述不能被当前线性温度模型解释的变化。\n参考样本至少 30 条，参考温差至少 1°C。参考区间若含异常或未覆盖后续温度范围，模型结论可能失效。",
)
section(
    "异常检测",
    "单通道以基准残差标准差构建 3σ 标记。多变量以四阶残差组成向量，计算 d² = (r-μ)ᵀ(Σ+λI)⁺(r-μ)。正则项和伪逆避免协方差退化造成计算失败。\n以参考段 d² 的经验 99.9% 分位为阈值。参考段超阈值单独统计，运营告警仅计算参考区间之后的数据。连续三个监测样本超阈值时记录告警起点。",
)
section(
    "指标与解释",
    "damage 标签可选，仅用于后续评估。输出 TP、FP、FN、TN、误报率、漏报率和首次命中延迟；无标签时不计算这些指标。\n不使用旧版任意映射的“健康分数”作为桥梁安全结论。单通道尖峰和多模态漂移仅作为不同的核查线索。",
)
section(
    "限制",
    "线性温度模型不覆盖所有环境影响；小样本经验阈值不等于理论误报概率；模态关联不能证明因果；模拟案例结果不能代替真实工程验证。",
)
page(5, "AI 集成与知识检索")
section(
    "选型理由",
    "Qwen Plus 提供中文交互与 Function Calling。兼容 API 将供应商配置与分析逻辑分离。首轮指定数据概览工具，取得计算证据后才展示回答文本。真实集成效果待配置密钥验收。",
)
story.append(
    table(
        [
            ["工具", "能力边界"],
            ["data_overview", "读取当前案例、参考区间与样本信息"],
            ["temperature_compensation", "读取回归系数与残差尺度"],
            ["detect_anomalies", "读取异常阈值、告警及评估结果"],
            ["compare_periods", "按日期范围比较均值和残差"],
            ["search_knowledge", "检索资料片段，返回来源和适用范围"],
            ["prepare_report", "整理当前分析要点，不自动替用户保存报告"],
        ],
        [180, 325],
    )
)
section(
    "检索增强生成",
    "文本按章节分块；关键词得分与向量余弦得分加权排序。向量按服务地址、模型名称和内容哈希缓存。未配置密钥或向量服务失败时，明确标为关键词检索，不冒充混合检索。\n内置资料是项目方法说明、数据质量清单和 FHWA 公开资料短导读。不是完整规范库；国外资料不作为中国规范使用。",
)
section(
    "约束与优化",
    "最多六轮调用、每轮最多八个工具请求；参数白名单验证；超时和用户取消显式处理。资料文本视为数据，不能覆盖系统指令。未检索到依据时说明不足。流式返回回答文本和工具执行状态，不暴露隐藏推理过程。",
)
page(6, "界面与核心功能")
shot = ROOT / "output" / "screenshots" / "workbench.jpg"
if shot.exists():
    from PIL import Image as PILImage

    with PILImage.open(shot) as im:
        w, h = im.size
    width = min(505, 390 * w / h)
    story.append(Image(str(shot), width=width, height=width * h / w))
section(
    "分析工作台",
    "真实运行页面截图。参考区间配置与当前分析快照分开，修改日期后需要重新计算。残差、原始/预测曲线与马氏距离图支持交互缩放，报告基于已经保存的分析结果。",
)
section(
    "证据与报告",
    "检索结果显示片段、章节、来源与适用范围。报告保存分析编号、参数和引用快照；编辑结论后需先保存再导出。模型不可用时，报告明确说明尚无资料引用。",
)
page(7, "测试与部署")
section(
    "验证结果",
    "2026-11-15：29 项自动化测试通过，TypeScript 类型检查及 Vite 生产构建通过。浏览器验证桌面与手机页面、统计计算、资料检索与引用跳转、报告创建和缺密钥错误提示。",
)
story.append(
    table(
        [
            ["模拟案例", "TP / FP / FN / TN", "误报率", "漏报率", "延迟"],
            ["正常温变", "0 / 2 / 0 / 183", "1.08%", "不适用", "不适用"],
            ["渐进漂移", "68 / 1 / 7 / 109", "0.91%", "9.33%", "5 天"],
            ["传感器尖峰", "5 / 2 / 0 / 178", "1.11%", "0%", "0 天"],
        ],
        [105, 165, 80, 80, 75],
    )
)
section(
    "测试范围",
    "标签隔离、回归系数、奇异协方差、参考区间不足、温差不足、CSV 异常、资料格式、扫描 PDF 拒绝、跨分析引用拒绝。\nAI 离线协议覆盖 SSE、工具参数错误、六轮上限、超时、断网、取消存储、向量降级和缓存。这些测试不是实际模型验收。",
)
section(
    "运行方式",
    "依赖版本由 requirements.lock.txt 与 package-lock.json 锁定。Windows 双击安装依赖后启动平台，访问 http://127.0.0.1:8000。所有数据默认保存到 runtime 目录。\n配置 .env 后重启服务，运行 scripts/verify_live_ai.py 才进行真实模型验收。该脚本会消耗用户自己的 API 额度。",
)
section(
    "待完成事项",
    "真实模型与向量服务验收、团队信息填写、设置远程代码仓库及评审权限、准备比赛演示材料并完成官网提交。",
)
page(8, "创新、局限与参考")
section(
    "创新与价值",
    "把自然语言分析、确定性统计工具和资料证据串成可复核流程；将异常结果、参考参数和引用保存为报告快照。\n通过正常温变、渐进漂移与尖峰三类对照案例，呈现不同异常证据及误报漏报，帮助使用者理解方法边界。应用创新尚需与真实用户访谈和实际数据验证共同支撑。",
)
section(
    "后续工作",
    "配置模型后完成真实调用验收。接入经过授权的真实监测数据与专业语料，由专业人员审查结果和引用的适用范围。",
)
section(
    "参考来源",
    "[1] 比赛官网：https://www.boxuegu.com/matchTrack/detail/?id=10037\n[2] Qwen Plus：https://help.aliyun.com/zh/model-studio/qwen-plus\n[3] Function Calling：https://help.aliyun.com/zh/model-studio/qwen-function-calling\n[4] Embedding：https://help.aliyun.com/zh/model-studio/embedding-interfaces-compatible-with-openai\n[5] FHWA Bridge Preservation Guide：https://www.fhwa.dot.gov/bridge/preservation/guide/guide.pdf",
)
section(
    "原创与贡献声明",
    "本项目在既有桥梁分析思路上重新实现产品、接口、交互和测试。开发使用 AI 辅助，Git 如实记录过程；参赛者需审阅并能够解释代码。团队身份信息未获提供，保留待填，不虚构。",
)


def footer(canvas, doc):
    canvas.setStrokeColor(colors.HexColor("#dce7ec"))
    canvas.line(45, 38, 550, 38)
    canvas.setFont("Chinese", 8)
    canvas.setFillColor(muted)
    canvas.drawString(45, 25, "桥安智析 | 技术文档 | 2026-11-15")
    canvas.drawRightString(550, 25, f"{doc.page:02d}")


doc = SimpleDocTemplate(
    str(OUT / "桥安智析_技术文档.pdf"),
    pagesize=(595.28, 841.89),
    leftMargin=45,
    rightMargin=45,
    topMargin=42,
    bottomMargin=48,
    title="桥安智析技术文档",
    author="桥安智析",
)
doc.build(story, onFirstPage=footer, onLaterPages=footer)
from tempfile import TemporaryDirectory

# Keep the example out of the user's working report and analysis lists.
with TemporaryDirectory(dir=OUT.parent) as temporary:
    storage.DATA = Path(temporary)
    _, title, frame = next(
        case for case in analysis.demo_frames() if case[0] == "drift"
    )
    records = frame.to_dict("records")
    storage.save(
        "dataset",
        {"name": title, "source": "可复现模拟数据 / seed 20261115", "records": records},
        "drift",
    )
    a = storage.save(
        "analysis",
        {
            "dataset_id": "drift",
            **analysis.analyze(records, "2025-01-01", "2025-06-29"),
        },
    )
    r = reports.create_report(a["id"])
    (OUT / "桥安智析_分析报告示例.pdf").write_bytes(reports.report_pdf(r))
metrics = {
    k: analysis.analyze(df.to_dict("records"), "2025-01-01", "2025-06-29")["metrics"]
    for k, _, df in analysis.demo_frames()
}
(ROOT / "output" / "benchmark.json").write_text(
    json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
)
print("PDFs created:", [p.name for p in OUT.glob("*.pdf")])
