import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  Database,
  FileText,
  FlaskConical,
  HelpCircle,
  LayoutDashboard,
  LoaderCircle,
  Play,
  Plus,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  Upload,
  X,
  AlertTriangle,
  ExternalLink,
  Settings2,
  Link2,
} from "lucide-react";
import { api, post } from "./api";
import { base, colors } from "./chartTheme";
import type {
  Analysis,
  Citation,
  Dataset,
  Document,
  Report,
  Status,
  Turn,
} from "./types";

const pages = [
  { id: "workbench", title: "分析工作台", icon: LayoutDashboard },
  { id: "assistant", title: "AI 分析助手", icon: Sparkles },
  { id: "library", title: "专业资料库", icon: BookOpen },
  { id: "reports", title: "报告中心", icon: FileText },
];
const tools: Record<string, string> = {
  data_overview: "查看数据概览",
  temperature_compensation: "温度效应分析",
  detect_anomalies: "异常证据分析",
  compare_periods: "时间区间对比",
  search_knowledge: "检索专业资料",
  prepare_report: "整理报告要点",
};
const format = (n: number | undefined, d = 2) =>
  n === undefined
    ? "—"
    : n.toLocaleString("zh-CN", { maximumFractionDigits: d });
const percent = (n: number | null) =>
  n === null ? "不适用" : (n * 100).toFixed(1) + "%";
const LazyChart = lazy(() =>
  import("./Chart").then((module) => ({ default: module.Chart })),
);

function Chart(props: {
  option: Record<string, unknown>;
  height: number;
  group?: string;
}) {
  return (
    <Suspense
      fallback={
        <div
          role="status"
          className="chart-loading"
          style={{ height: props.height }}
        >
          正在加载图表
        </div>
      }
    >
      <LazyChart {...props} />
    </Suspense>
  );
}

export default function App() {
  const [page, setPage] = useState(
    localStorage.getItem("bridge-page") || "workbench",
  );
  const [datasets, setDatasets] = useState<Dataset[]>([]),
    [selected, setSelected] = useState("drift");
  const [analysis, setAnalysis] = useState<Analysis | null>(null),
    [start, setStart] = useState(""),
    [end, setEnd] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [toast, setToast] = useState("");
  const [status, setStatus] = useState<Status | null>(null),
    [mode, setMode] = useState(0),
    [view, setView] = useState("residual");
  const [docs, setDocs] = useState<Document[]>([]),
    [query, setQuery] = useState("温度补偿与异常复核"),
    [searchResult, setSearchResult] = useState<{
      mode: string;
      warning: string | null;
      results: Citation[];
    } | null>(null),
    [docId, setDocId] = useState<string | null>(null);
  const [reports, setReports] = useState<Report[]>([]),
    [reportId, setReportId] = useState(""),
    [draft, setDraft] = useState("");
  const [citationTarget, setCitationTarget] = useState("");
  const [question, setQuestion] = useState(""),
    [turns, setTurns] = useState<Turn[]>([]),
    [conversation, setConversation] = useState<string | null>(null),
    [streaming, setStreaming] = useState(false),
    [progress, setProgress] = useState("");
  const abort = useRef<AbortController | null>(null),
    chatEnd = useRef<HTMLDivElement>(null);
  const csvInput = useRef<HTMLInputElement>(null),
    docInput = useRef<HTMLInputElement>(null);
  const selectedData = datasets.find((d) => d.id === selected);
  const selectedReport = reports.find((r) => r.id === reportId);
  const currentDoc = docs.find((d) => d.id === docId);
  const navigate = (id: string) => {
    setPage(id);
    localStorage.setItem("bridge-page", id);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 4000);
  };
  async function reloadDatasets() {
    const list = await api<Dataset[]>("/datasets");
    setDatasets(list);
    return list;
  }
  async function reloadReports() {
    const list = await api<Report[]>("/reports");
    setReports(list);
    return list;
  }
  useEffect(() => {
    Promise.all([
      reloadDatasets(),
      api<Status>("/status").then(setStatus),
      api<Document[]>("/documents").then(setDocs),
      reloadReports(),
    ]).catch((e) => setError(e.message));
    const saved = localStorage.getItem("bridge-analysis");
    if (saved)
      api<Analysis>("/analyses/" + saved)
        .then((a) => {
          setAnalysis(a);
          setSelected(a.dataset_id);
          setStart(a.reference.start);
          setEnd(a.reference.end);
        })
        .catch(() => localStorage.removeItem("bridge-analysis"));
    return () => abort.current?.abort();
  }, []);
  useEffect(() => {
    if (selectedData && (!analysis || analysis.dataset_id !== selected)) {
      setStart(selectedData.start);
      setEnd(selectedData.suggested_reference_end);
    }
  }, [selectedData, selected, analysis]);
  useEffect(() => {
    const controller = new AbortController();
    setTurns([]);
    setConversation(null);
    if (analysis)
      api<{ id: string; turns: Turn[] }[]>(
        "/conversations?analysis_id=" + analysis.id,
        { signal: controller.signal },
      )
        .then(([latest]) => {
          if (latest && !controller.signal.aborted) {
            setConversation(latest.id);
            setTurns(latest.turns);
          }
        })
        .catch((e) => {
          if (!controller.signal.aborted) setError(e.message);
        });
    return () => controller.abort();
  }, [analysis?.id]);
  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns, progress]);
  const activeAnalysis = analysis?.dataset_id === selected ? analysis : null;
  async function run() {
    if (!selectedData) return;
    setBusy(true);
    setError("");
    try {
      const a = await api<Analysis>(
        "/analyses",
        post({ dataset_id: selected, start, end }),
      );
      setAnalysis(a);
      localStorage.setItem("bridge-analysis", a.id);
      notify("分析完成，图表与证据已更新");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function upload(file: File | undefined, type: "dataset" | "document") {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      if (type === "document") {
        form.append("source", "用户导入：" + file.name);
        form.append("scope", "用户提供资料，适用范围待核实");
      }
      const result = await api<{ id: string }>(
        "/" + (type === "dataset" ? "datasets" : "documents"),
        { method: "POST", body: form },
      );
      if (type === "dataset") {
        await reloadDatasets();
        setSelected(result.id);
        setAnalysis(null);
        localStorage.removeItem("bridge-analysis");
        setTurns([]);
        setConversation(null);
      } else {
        setDocs(await api<Document[]>("/documents"));
        setDocId(result.id);
      }
      notify("文件已导入，请核对内容");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function search() {
    setBusy(true);
    setError("");
    try {
      setSearchResult(await api("/search?q=" + encodeURIComponent(query)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function createReport() {
    if (!activeAnalysis || streaming) return;
    setBusy(true);
    try {
      const r = await api<Report>(
        "/reports",
        post({ analysis_id: activeAnalysis.id, conversation_id: conversation }),
      );
      await reloadReports();
      setReportId(r.id);
      setDraft(r.conclusion);
      navigate("reports");
      notify("报告已保存，可编辑结论后导出");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function saveReport() {
    if (!selectedReport) return;
    setBusy(true);
    try {
      await api("/reports/" + selectedReport.id, {
        ...post({ conclusion: draft }),
        method: "PATCH",
      });
      await reloadReports();
      notify("报告修改已保存");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function openCitation(c: Citation) {
    setDocId(c.document_id);
    setCitationTarget(c.id);
    navigate("library");
  }
  const [chartTarget, setChartTarget] = useState("");
  function openChart(id: string) {
    setChartTarget(id);
    navigate("workbench");
  }
  useEffect(() => {
    const target =
      page === "library" && citationTarget
        ? "citation-" + citationTarget
        : page === "workbench" && chartTarget;
    if (target)
      document
        .getElementById(target)
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [page, docId, citationTarget, chartTarget]);
  async function ask(text = question) {
    if (!activeAnalysis || !text.trim() || streaming) return;
    setQuestion("");
    setError("");
    setStreaming(true);
    setProgress("正在连接真实模型");
    const controller = new AbortController();
    abort.current = controller;
    const turn: Turn = {
      question: text,
      answer: "",
      tools: [],
      citations: [],
      status: "running",
    };
    setTurns((t) => [...t, turn]);
    const update = (f: (t: Turn) => Turn) =>
      setTurns((ts) => ts.map((t, i) => (i === ts.length - 1 ? f(t) : t)));
    try {
      const response = await fetch("/api/chat", {
        ...post({
          analysis_id: activeAnalysis.id,
          conversation_id: conversation,
          question: text,
        }),
        signal: controller.signal,
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "模型调用失败");
      }
      const reader = response.body!.getReader(),
        decoder = new TextDecoder();
      let buffer = "";
      let terminal = false;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let split;
        while ((split = buffer.indexOf("\n\n")) >= 0) {
          const block = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);
          const kind = block.match(/event: (.+)/)?.[1];
          const raw = block
            .split("\n")
            .find((l) => l.startsWith("data: "))
            ?.slice(6);
          if (!raw) continue;
          const data = JSON.parse(raw);
          if (kind === "conversation") setConversation(data.id);
          if (kind === "status") setProgress(data.text);
          if (kind === "token")
            update((t) => ({ ...t, answer: t.answer + data.text }));
          if (kind === "tool")
            update((t) => ({
              ...t,
              tools: [
                ...t.tools.filter(
                  (v) => !(v.name === data.name && v.status === "running"),
                ),
                data,
              ],
            }));
          if (kind === "citations")
            update((t) => ({ ...t, citations: data.items }));
          if (kind === "error") {
            terminal = true;
            update((t) => ({
              ...t,
              status: "error",
              answer: t.answer + "\n" + data.message,
            }));
          }
          if (kind === "done") {
            terminal = true;
            update((t) => ({
              ...t,
              status: data.status,
              elapsed: data.elapsed,
              usage: data.usage,
            }));
          }
        }
      }
      if (!terminal) throw new Error("模型响应流提前中断，请重试。");
    } catch (e) {
      const stopped = (e as Error).name === "AbortError";
      update((t) => ({
        ...t,
        status: stopped ? "cancelled" : "error",
        answer:
          t.answer +
          (stopped
            ? "\n已停止生成，已有结果仅供核查。"
            : "\n" + (e as Error).message),
      }));
    } finally {
      setStreaming(false);
      setProgress("");
      abort.current = null;
    }
  }
  function chooseDataset(id: string) {
    if (streaming) return;
    setSelected(id);
    setError("");
    if (analysis?.dataset_id !== id) {
      setAnalysis(null);
      localStorage.removeItem("bridge-analysis");
      setConversation(null);
      setTurns([]);
    }
  }
  const scoreOption = activeAnalysis
    ? {
        ...base,
        legend: undefined,
        grid: { left: 52, right: 25, top: 25, bottom: 48 },
        xAxis: {
          type: "category",
          data: activeAnalysis.dates,
          axisLine: { lineStyle: { color: "#dfe7ec" } },
          axisTick: { show: false },
          axisLabel: { formatter: (v: string) => v.slice(5) },
        },
        yAxis: {
          type: "value",
          name: "距离平方",
          splitLine: { lineStyle: { color: "#edf2f5", type: "dashed" } },
        },
        dataZoom: [{ type: "inside" }],
        series: [
          {
            name: "马氏距离²",
            type: "line",
            data: activeAnalysis.score,
            showSymbol: false,
            lineStyle: { width: 2, color: "#078b92" },
            areaStyle: { color: "#078b92", opacity: 0.07 },
            markLine: {
              symbol: "none",
              label: { formatter: "阈值 {c}", position: "insideEndTop" },
              lineStyle: { color: "#d59046", type: "dashed" },
              data: [
                { yAxis: Number(activeAnalysis.summary.threshold.toFixed(2)) },
              ],
            },
          },
          {
            name: "监测异常",
            type: "scatter",
            data: activeAnalysis.dates
              .map((d, i) =>
                activeAnalysis.flags[i] ? [d, activeAnalysis.score[i]] : null,
              )
              .filter(Boolean),
            itemStyle: { color: "#da785e" },
            symbolSize: 5,
          },
        ],
      }
    : {};
  const frequencyOption = activeAnalysis
    ? {
        ...base,
        xAxis: {
          type: "category",
          data: activeAnalysis.dates,
          axisLine: { lineStyle: { color: "#dfe7ec" } },
          axisTick: { show: false },
          axisLabel: { formatter: (v: string) => v.slice(5) },
        },
        yAxis: {
          type: "value",
          scale: true,
          name: "Hz",
          splitLine: { lineStyle: { color: "#edf2f5", type: "dashed" } },
        },
        dataZoom: [
          { type: "inside" },
          {
            type: "slider",
            height: 15,
            bottom: 5,
            borderColor: "transparent",
            fillerColor: "#078b921a",
            handleStyle: { color: "#078b92" },
          },
        ],
        series:
          view === "residual"
            ? colors.map((color, i) => ({
                name: "模态 " + (i + 1),
                type: "line",
                data: activeAnalysis.residual.map((r) => r[i]),
                showSymbol: false,
                lineStyle: { width: 1.5, color },
                markArea:
                  i === 0
                    ? {
                        silent: true,
                        itemStyle: { color: "#078b9209" },
                        label: { show: false },
                        data: [
                          [
                            { xAxis: activeAnalysis.reference.start },
                            { xAxis: activeAnalysis.reference.end },
                          ],
                        ],
                      }
                    : undefined,
              }))
            : [
                {
                  name: "实测频率",
                  type: "line",
                  data: activeAnalysis.frequency.map((r) => r[mode]),
                  showSymbol: false,
                  lineStyle: { width: 2, color: "#078b92" },
                },
                {
                  name: "温度预测",
                  type: "line",
                  data: activeAnalysis.predicted.map((r) => r[mode]),
                  showSymbol: false,
                  lineStyle: { width: 1.5, type: "dashed", color: "#a3b4c2" },
                },
              ],
      }
    : {};
  const correlationOption = activeAnalysis
    ? {
        ...base,
        tooltip: { position: "top" },
        grid: { left: 45, right: 20, top: 20, bottom: 50 },
        xAxis: {
          type: "category",
          data: ["f1", "f2", "f3", "f4"],
          splitArea: { show: true },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        yAxis: {
          type: "category",
          data: ["f1", "f2", "f3", "f4"],
          axisLine: { show: false },
          axisTick: { show: false },
        },
        visualMap: {
          min: -1,
          max: 1,
          calculable: false,
          orient: "horizontal",
          left: "center",
          bottom: 0,
          itemWidth: 9,
          itemHeight: 110,
          inRange: { color: ["#d6e1ef", "#f1f5f8", "#09858e"] },
        },
        series: [
          {
            type: "heatmap",
            data: activeAnalysis.correlation.flatMap((r, i) =>
              r.map((v, j) => [i, j, v]),
            ),
            label: { show: true, fontSize: 11 },
            itemStyle: { borderWidth: 3, borderColor: "#fff" },
          },
        ],
      }
    : {};
  return (
    <div className="shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("workbench");
          }}
        >
          <span className="brand-icon">
            <Activity size={25} />
          </span>
          <span>
            桥安智析<small>BRIDGE INSIGHT</small>
          </span>
        </a>
        <div className="workspace-label">
          监测分析空间 <span>V 1.0</span>
        </div>
        <nav>
          {pages.map((p) => (
            <button
              key={p.id}
              className={page === p.id ? "nav-item active" : "nav-item"}
              onClick={() => navigate(p.id)}
            >
              <p.icon size={18} />
              {p.title}
              {page === p.id && <ChevronRight size={14} />}
            </button>
          ))}
        </nav>
        <div className="sidebar-guide">
          <span className="mini-label">EVIDENCE FIRST</span>
          <ShieldCheck size={26} />
          <strong>每一个判断，都有据可查</strong>
          <p>连接监测数据、分析工具与专业资料，让异常解释更清晰。</p>
          <button onClick={() => navigate("library")}>
            查看方法说明 <ArrowRight size={14} />
          </button>
        </div>
        <div className="sidebar-bottom">
          <div className="avatar">桥</div>
          <div>
            本地研究工作空间<small>数据保存在当前设备</small>
          </div>
          <ShieldCheck size={16} />
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            工作空间 <ChevronRight size={12} />
            <strong>{pages.find((p) => p.id === page)?.title}</strong>
          </div>
          <div className="topbar-right">
            <span className="local-dot" />
            本地服务 <span className="divider" />
            <button
              className="icon-button"
              title="查看使用说明"
              onClick={() => {
                setDocId("method-temperature");
                navigate("library");
              }}
            >
              <HelpCircle size={18} />
            </button>
            <div className="user-avatar">研</div>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                BRIDGE HEALTH INTELLIGENCE /{" "}
                {page === "workbench" ? "OVERVIEW" : page.toUpperCase()}
              </div>
              <h1>
                {pages.find((p) => p.id === page)?.title}
                <span className="heading-dot" />
              </h1>
              <p>
                {page === "workbench"
                  ? "从环境变化中，识别真正值得关注的数据异常。"
                  : page === "assistant"
                    ? "让问题驱动分析，让每一步结论回到证据。"
                    : page === "library"
                      ? "为分析补充专业依据，清楚记录来源与适用边界。"
                      : "把数据、证据与判断整理成一份可复核的报告。"}
              </p>
            </div>
            <div className="heading-actions">
              {page === "workbench" ? (
                <>
                  <button
                    className="button"
                    onClick={() => csvInput.current?.click()}
                    disabled={busy || streaming}
                  >
                    <Upload size={15} />
                    导入监测数据
                  </button>
                  <button
                    className="button primary"
                    disabled={!activeAnalysis || busy || streaming}
                    onClick={createReport}
                  >
                    <FileText size={15} />
                    生成分析报告
                  </button>
                </>
              ) : page === "library" ? (
                <button
                  className="button primary"
                  onClick={() => docInput.current?.click()}
                  disabled={busy}
                >
                  <Plus size={16} />
                  导入专业资料
                </button>
              ) : page === "reports" ? (
                <button
                  className="button primary"
                  disabled={!activeAnalysis || busy || streaming}
                  onClick={createReport}
                >
                  <Plus size={16} />
                  创建当前分析报告
                </button>
              ) : (
                <span
                  className={
                    "badge " + (status?.ai_configured ? "green" : "neutral")
                  }
                >
                  <span className="tiny-dot" />
                  {status?.ai_configured
                    ? status.model + " · 已配置"
                    : "真实模型 · 待配置"}
                </span>
              )}
            </div>
          </div>
          <input
            ref={csvInput}
            type="file"
            accept=".csv"
            hidden
            onChange={(e) => {
              void upload(e.target.files?.[0], "dataset");
              e.target.value = "";
            }}
          />
          <input
            ref={docInput}
            type="file"
            accept=".pdf,.md,.txt"
            hidden
            onChange={(e) => {
              void upload(e.target.files?.[0], "document");
              e.target.value = "";
            }}
          />
          {error && (
            <div className="alert error" role="alert">
              <AlertTriangle size={18} />
              <span>{error}</span>
              <button
                className="icon-button"
                onClick={() => setError("")}
                aria-label="关闭错误"
              >
                <X size={16} />
              </button>
            </div>
          )}
          {page === "workbench" && (
            <>
              <div className="overview-banner">
                <div>
                  <span className="banner-icon">
                    <Activity size={23} />
                  </span>
                  <div>
                    <strong>让温度回归环境，让异常回归证据。</strong>
                    <p>温度补偿 × 多变量异常检测 × 可追溯 AI 分析</p>
                  </div>
                </div>
                <span className="badge">
                  <FlaskConical size={13} />
                  研究演示 / 非工程鉴定
                </span>
                <svg
                  className="bridge-line"
                  viewBox="0 0 420 110"
                  aria-hidden="true"
                >
                  <path d="M0 85H420M0 92H420M90 15V102M330 15V102M90 20Q210 115 330 20M0 70Q45 63 90 20M330 20Q375 63 420 70M120 42V85M150 59V85M180 70V85M210 74V85M240 70V85M270 59V85M300 42V85" />
                </svg>
              </div>
              <section className="card config-card">
                <div className="section-heading">
                  <h2>
                    <Database size={17} />
                    数据与分析配置
                  </h2>
                  <span className="subtle">
                    01 / 选择数据，确认健康参考区间
                  </span>
                </div>
                <div className="config-grid">
                  <label className="field dataset-field">
                    当前数据集
                    <select
                      value={selected}
                      disabled={streaming || busy}
                      onChange={(e) => chooseDataset(e.target.value)}
                    >
                      {datasets.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    参考开始日期
                    <input
                      type="date"
                      value={start}
                      min={selectedData?.start}
                      max={selectedData?.end}
                      onChange={(e) => setStart(e.target.value)}
                    />
                  </label>
                  <label className="field">
                    参考结束日期
                    <input
                      type="date"
                      value={end}
                      min={selectedData?.start}
                      max={selectedData?.end}
                      onChange={(e) => setEnd(e.target.value)}
                    />
                  </label>
                  <button
                    className="button primary run-button"
                    onClick={run}
                    disabled={busy || streaming || !selectedData}
                  >
                    {busy ? (
                      <LoaderCircle className="spin" size={16} />
                    ) : (
                      <Play size={15} />
                    )}
                    运行统计分析
                  </button>
                </div>
                <div className="config-meta">
                  <span
                    className={
                      "badge " + (selectedData?.simulation ? "sand" : "neutral")
                    }
                  >
                    {selectedData?.simulation ? (
                      <FlaskConical size={12} />
                    ) : (
                      <Upload size={12} />
                    )}
                    {selectedData?.simulation ? "模拟数据" : "用户导入"}
                  </span>
                  <span>{selectedData?.samples ?? "—"} 条记录</span>
                  <span>
                    {selectedData?.start} — {selectedData?.end}
                  </span>
                  <span className="meta-spacer" />
                  <a href={"/api/datasets/" + selected + "/csv"}>
                    <ArrowDownToLine size={13} />
                    下载原始 CSV
                  </a>
                </div>
                <p className="field-help">
                  参考区间应由专业记录确认健康，至少 30
                  个样本。调整日期后请重新运行；图表始终对应已完成的分析参数。
                </p>
              </section>
              {!activeAnalysis ? (
                <div className="empty-state card">
                  <div className="empty-icon">
                    <Activity size={32} />
                  </div>
                  <h2>准备好探索这组监测数据了吗？</h2>
                  <p>
                    已提供三个可复现案例。确认参考区间，运行分析后查看环境效应与异常证据。
                  </p>
                  <button
                    className="button primary"
                    onClick={run}
                    disabled={busy || !selectedData}
                  >
                    <Play size={15} />
                    开始分析当前案例
                  </button>
                  <div className="case-grid">
                    {datasets
                      .filter((d) => d.simulation)
                      .map((d, i) => (
                        <button
                          className={
                            selected === d.id ? "case selected" : "case"
                          }
                          key={d.id}
                          onClick={() => chooseDataset(d.id)}
                        >
                          <span>CASE 0{i + 1}</span>
                          <strong>{d.name}</strong>
                          <small>
                            365 天 / 4 阶模态 <ArrowRight size={12} />
                          </small>
                        </button>
                      ))}
                  </div>
                </div>
              ) : (
                <>
                  <div className="stats-grid">
                    <Stat
                      label="监测样本"
                      value={format(activeAnalysis.summary.samples, 0)}
                      unit="条"
                      foot={`${activeAnalysis.dates[0]} 至 ${activeAnalysis.dates.at(-1)}`}
                      icon={<Database size={18} />}
                    />
                    <Stat
                      label="健康参考样本"
                      value={format(activeAnalysis.reference.count, 0)}
                      unit="条"
                      foot={`${activeAnalysis.reference.start} 至 ${activeAnalysis.reference.end}`}
                      icon={<ShieldCheck size={18} />}
                    />
                    <Stat
                      label="监测期异常"
                      value={format(activeAnalysis.summary.anomalies, 0)}
                      unit="条"
                      foot={`在参考期后 ${activeAnalysis.summary.evaluated} 条样本中检出`}
                      warm={activeAnalysis.summary.anomalies > 0}
                      icon={<Activity size={18} />}
                    />
                    <Stat
                      label="连续告警起点"
                      value={activeAnalysis.summary.onset?.slice(5) || "未触发"}
                      unit={activeAnalysis.summary.onset?.slice(0, 4) || ""}
                      foot="连续 3 个监测样本超过经验阈值"
                      icon={<AlertTriangle size={18} />}
                    />
                  </div>
                  <div className="analysis-grid">
                    <section
                      className="card chart-panel wide"
                      id="frequency-chart"
                    >
                      <div className="section-heading">
                        <div>
                          <h2>模态频率与温度补偿</h2>
                          <p>剥离可解释的环境变化，观察剩余偏移</p>
                        </div>
                        <div className="segmented">
                          <button
                            className={view === "residual" ? "selected" : ""}
                            onClick={() => setView("residual")}
                          >
                            补偿后残差
                          </button>
                          <button
                            className={view === "raw" ? "selected" : ""}
                            onClick={() => setView("raw")}
                          >
                            原始与预测
                          </button>
                        </div>
                      </div>
                      {view === "raw" && (
                        <div className="mode-pills">
                          {colors.map((_, i) => (
                            <button
                              key={i}
                              className={mode === i ? "selected" : ""}
                              onClick={() => setMode(i)}
                            >
                              模态 {i + 1}
                            </button>
                          ))}
                        </div>
                      )}
                      <Chart
                        option={frequencyOption}
                        height={300}
                        group="monitoring"
                      />
                      <div className="chart-caption">
                        <span className="tiny-dot" />
                        淡色区域为健康参考段 · 拖动底部滑块可缩放时间范围
                      </div>
                    </section>
                    <section className="insight-card">
                      <span className="mini-label">ANALYSIS COMPANION</span>
                      <div className="ai-orb">
                        <Sparkles size={28} />
                      </div>
                      <h2>
                        异常发生了，
                        <br />
                        然后呢？
                      </h2>
                      <p>
                        结合计算证据与专业资料，继续追问变化的原因和复核方向。
                      </p>
                      <button
                        className="insight-question"
                        onClick={() => {
                          setQuestion(
                            "这段频率下降能否由温度解释？哪些数据支持异常判断？下一步应核查什么？",
                          );
                          navigate("assistant");
                        }}
                      >
                        这段变化能用温度解释吗？
                        <ArrowRight size={16} />
                      </button>
                      <button
                        className="button primary"
                        onClick={() => navigate("assistant")}
                      >
                        进入 AI 分析助手 <ArrowRight size={15} />
                      </button>
                      <div className="insight-status">
                        <span className="tiny-dot" />
                        {status?.ai_configured
                          ? "已配置真实模型接口"
                          : "配置模型密钥后启用真实 AI"}
                      </div>
                    </section>
                    <section className="card chart-panel" id="anomaly-chart">
                      <div className="section-heading">
                        <div>
                          <h2>多变量异常证据</h2>
                          <p>马氏距离平方 / 基准段经验 99.9% 分位</p>
                        </div>
                        <span className="badge sand">
                          阈值 {format(activeAnalysis.summary.threshold)}
                        </span>
                      </div>
                      <Chart
                        option={scoreOption}
                        height={270}
                        group="monitoring"
                      />
                    </section>
                    <section className="card chart-panel">
                      <div className="section-heading">
                        <div>
                          <h2>模态残差关联</h2>
                          <p>全时段相关系数，辅助识别共同变化</p>
                        </div>
                        <Link2 size={17} />
                      </div>
                      <Chart option={correlationOption} height={270} />
                    </section>
                  </div>
                  <section className="card evidence-section">
                    <div className="section-heading">
                      <h2>
                        <ShieldCheck size={17} />
                        分析依据与适用边界
                      </h2>
                      <span className="subtle">02 / 可核查、可复现</span>
                    </div>
                    <div className="evidence-grid">
                      <div>
                        <h3>统计模型</h3>
                        <div className="model-table">
                          <div className="model-row header">
                            <span>模态</span>
                            <span>温度系数 Hz/°C</span>
                            <span>残差标准差 Hz</span>
                          </div>
                          {activeAnalysis.models.map((m) => (
                            <div className="model-row" key={m.mode}>
                              <strong>{m.mode.toUpperCase()}</strong>
                              <span>{m.slope.toFixed(6)}</span>
                              <span>{m.reference_std.toFixed(6)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                      <div>
                        <h3>结果应如何解读</h3>
                        {activeAnalysis.limitations.map((t) => (
                          <p className="limit" key={t}>
                            <Check size={14} />
                            {t}
                          </p>
                        ))}
                        {activeAnalysis.metrics && (
                          <div className="metric-chips">
                            <span>
                              误报率{" "}
                              {percent(
                                activeAnalysis.metrics.false_positive_rate,
                              )}
                            </span>
                            <span>
                              漏报率 {percent(activeAnalysis.metrics.miss_rate)}
                            </span>
                            <span>
                              检测延迟{" "}
                              {activeAnalysis.metrics.detection_delay_days ??
                                "—"}{" "}
                              天
                            </span>
                          </div>
                        )}
                        <small className="subtle">
                          指标只评价参考期之后的已标注样本；不代表真实桥梁性能。
                        </small>
                      </div>
                    </div>
                  </section>
                </>
              )}
            </>
          )}
          {page === "assistant" && (
            <div className="assistant-layout">
              <section className="card conversation">
                <div className="chat-header">
                  <div>
                    <Sparkles size={20} />
                    <strong>桥安分析助手</strong>
                    <span className="badge neutral">工具驱动 · 证据可追溯</span>
                  </div>
                  <button
                    className="text-button"
                    disabled={streaming}
                    onClick={() => {
                      setConversation(null);
                      setTurns([]);
                    }}
                  >
                    <Plus size={14} />
                    新对话
                  </button>
                </div>
                <div className="chat-content">
                  {!activeAnalysis ? (
                    <Empty
                      icon={<Database size={28} />}
                      title="请先完成一次数据分析"
                      text="助手会围绕当前分析调用工具，以避免脱离数据给出结论。"
                      action={
                        <button
                          className="button primary"
                          onClick={() => navigate("workbench")}
                        >
                          前往分析工作台
                        </button>
                      }
                    />
                  ) : turns.length === 0 ? (
                    <div className="chat-welcome">
                      <div className="ai-orb">
                        <Sparkles size={28} />
                      </div>
                      <h2>从一个值得追问的问题开始</h2>
                      <p>
                        当前案例：{selectedData?.name}
                        <br />
                        我会调用分析工具，帮助你核查数据变化。
                      </p>
                      {[
                        "这段频率下降能否由温度解释？哪些数据支持异常判断？",
                        "请比较参考区间与最后 30 天的数据变化。",
                        "如何区分单通道传感器尖峰与多模态持续漂移？",
                      ].map((q) => (
                        <button
                          key={q}
                          className="prompt-card"
                          onClick={() => setQuestion(q)}
                        >
                          {q}
                          <ArrowRight size={16} />
                        </button>
                      ))}
                    </div>
                  ) : (
                    turns.map((turn, i) => (
                      <div className="turn" key={i}>
                        <div className="question-bubble">{turn.question}</div>
                        <div className="answer-heading">
                          <span className="assistant-avatar">
                            <Sparkles size={15} />
                          </span>
                          桥安分析助手
                          <span className="subtle">
                            {turn.status === "complete"
                              ? "分析完成"
                              : turn.status === "error"
                                ? "调用未完成"
                                : turn.status === "cancelled"
                                  ? "已停止"
                                  : turn.status === "limit"
                                    ? "已达轮次上限"
                                    : "正在分析"}
                          </span>
                        </div>
                        {turn.tools.length > 0 && (
                          <div className="tool-list">
                            {turn.tools.map((t, j) => (
                              <details key={j}>
                                <summary>
                                  {t.status === "running" ? (
                                    <LoaderCircle className="spin" size={14} />
                                  ) : t.status === "error" ? (
                                    <AlertTriangle size={14} />
                                  ) : (
                                    <Check size={14} />
                                  )}
                                  {tools[t.name] || t.name}
                                  <span>
                                    {t.status === "running"
                                      ? "处理中"
                                      : t.status === "error"
                                        ? "参数错误"
                                        : "完成"}
                                  </span>
                                </summary>
                                {t.result !== undefined && (
                                  <pre>{JSON.stringify(t.result, null, 2)}</pre>
                                )}
                              </details>
                            ))}
                          </div>
                        )}
                        <div
                          className={
                            "answer-text " +
                            (turn.status === "error" ? "muted" : "")
                          }
                        >
                          {turn.answer || "等待模型返回…"}
                        </div>
                        {turn.citations.length > 0 && (
                          <div className="citation-list">
                            {turn.citations.map((c) => (
                              <button
                                key={c.id}
                                onClick={() => openCitation(c)}
                              >
                                <BookOpen size={13} />[{c.id}] {c.title} ·{" "}
                                {c.section}
                                <ChevronRight size={13} />
                              </button>
                            ))}
                          </div>
                        )}
                        {turn.elapsed !== undefined && (
                          <div className="answer-meta">
                            耗时 {turn.elapsed}s ·{" "}
                            {turn.usage?.total_tokens ?? 0} tokens ·{" "}
                            <button
                              onClick={() => openChart("frequency-chart")}
                            >
                              查看频率证据
                            </button>{" "}
                            ·{" "}
                            <button onClick={() => openChart("anomaly-chart")}>
                              查看异常证据
                            </button>
                          </div>
                        )}
                      </div>
                    ))
                  )}
                  <div ref={chatEnd} />
                </div>
                <div className="chat-compose">
                  {!status?.ai_configured && (
                    <div className="config-notice">
                      <Settings2 size={14} />
                      尚未配置模型密钥。可先使用统计分析；真实 AI 需配置本机
                      .env 并重启。
                    </div>
                  )}
                  {streaming && (
                    <div className="progress">
                      <LoaderCircle className="spin" size={13} />
                      {progress}
                    </div>
                  )}
                  <div className="compose-input">
                    <textarea
                      aria-label="向 AI 提问"
                      placeholder="例如：这段频率下降能否由温度解释？"
                      value={question}
                      maxLength={2000}
                      disabled={!activeAnalysis || streaming}
                      onChange={(e) => setQuestion(e.target.value)}
                      onKeyDown={(e) => {
                        if (
                          e.key === "Enter" &&
                          !e.shiftKey &&
                          !e.nativeEvent.isComposing
                        ) {
                          e.preventDefault();
                          void ask();
                        }
                      }}
                    />
                    {streaming ? (
                      <button
                        className="send-button stop"
                        title="停止生成"
                        onClick={() => abort.current?.abort()}
                      >
                        <Square size={17} />
                      </button>
                    ) : (
                      <button
                        className="send-button"
                        title="发送问题"
                        disabled={!question.trim() || !activeAnalysis}
                        onClick={() => ask()}
                      >
                        <Send size={17} />
                      </button>
                    )}
                  </div>
                  <div className="compose-foot">
                    Enter 发送 · Shift + Enter 换行
                    <span>分析建议需专业复核</span>
                  </div>
                </div>
              </section>
              <aside className="context-column">
                <div className="card context-card">
                  <span className="mini-label">CURRENT CONTEXT</span>
                  <h3>本次分析上下文</h3>
                  <div className="context-data">
                    <Database size={18} />
                    <strong>{selectedData?.name || "尚未选择数据"}</strong>
                  </div>
                  <dl>
                    <dt>数据性质</dt>
                    <dd>
                      {selectedData?.simulation ? "模拟数据" : "用户导入"}
                    </dd>
                    <dt>分析样本</dt>
                    <dd>{activeAnalysis?.summary.samples ?? "—"}</dd>
                    <dt>监测异常</dt>
                    <dd>{activeAnalysis?.summary.anomalies ?? "—"}</dd>
                    <dt>参考区间</dt>
                    <dd>
                      {activeAnalysis?.reference.start ?? "—"}
                      <br />
                      {activeAnalysis?.reference.end}
                    </dd>
                  </dl>
                  <button
                    className="button full"
                    onClick={() => navigate("workbench")}
                  >
                    查看图表证据 <ArrowRight size={14} />
                  </button>
                </div>
                <div className="card context-card">
                  <BookOpen size={20} />
                  <h3>从分析到专业依据</h3>
                  <p>
                    检索结果附带来源与适用范围。无匹配证据时，助手应明确说明信息不足。
                  </p>
                  <button
                    className="text-button"
                    onClick={() => navigate("library")}
                  >
                    浏览专业资料库 <ArrowRight size={14} />
                  </button>
                </div>
                <button
                  className="button primary full"
                  disabled={!activeAnalysis || busy || streaming}
                  onClick={createReport}
                >
                  <FileText size={15} />
                  整理为分析报告
                </button>
              </aside>
            </div>
          )}
          {page === "library" && (
            <>
              <section className="card library-search">
                <Search size={22} />
                <div>
                  <h2>查找支持分析的专业依据</h2>
                  <p>覆盖温度补偿、数据质量与复检思路；每条资料均标明来源。</p>
                </div>
                <div className="search-input">
                  <input
                    aria-label="检索专业资料"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void search();
                    }}
                    placeholder="输入问题或关键词"
                    maxLength={300}
                  />
                  <button
                    className="button primary"
                    onClick={search}
                    disabled={busy || !query.trim()}
                  >
                    {busy ? (
                      <LoaderCircle className="spin" size={15} />
                    ) : (
                      <Search size={15} />
                    )}
                    检索
                  </button>
                </div>
              </section>
              {searchResult && (
                <section className="card search-results">
                  <div className="section-heading">
                    <h2>检索结果 · {searchResult.results.length}</h2>
                    <span className="badge neutral">
                      {searchResult.mode === "hybrid"
                        ? "关键词 + 向量混合检索"
                        : "关键词检索"}
                    </span>
                  </div>
                  {searchResult.warning && (
                    <p className="notice-line">{searchResult.warning}</p>
                  )}
                  {searchResult.results.length === 0 ? (
                    <p className="muted">
                      未找到足够相关的资料。请更换关键词，或导入可信资料。
                    </p>
                  ) : (
                    searchResult.results.map((c) => (
                      <button
                        className="search-hit"
                        key={c.id}
                        onClick={() => openCitation(c)}
                      >
                        <div>
                          <strong>{c.title}</strong>
                          <span>{c.section}</span>
                        </div>
                        <p>{c.text}</p>
                        <small>{c.scope}</small>
                        <ChevronRight size={16} />
                      </button>
                    ))
                  )}
                </section>
              )}
              <div className="section-heading library-label">
                <h2>
                  资料集合 <span className="count">{docs.length}</span>
                </h2>
                <span className="subtle">
                  支持文本型 PDF、Markdown、TXT · 最大 10 MB
                </span>
              </div>
              <div className="document-grid">
                {docs.map((d) => (
                  <button
                    className={
                      "card document-card " + (docId === d.id ? "selected" : "")
                    }
                    key={d.id}
                    onClick={() => setDocId(docId === d.id ? null : d.id)}
                  >
                    <div className="doc-symbol">
                      <BookOpen size={23} />
                    </div>
                    <span className="badge neutral">
                      {d.source.startsWith("https://")
                        ? "公开资料导读"
                        : "方法与流程"}
                    </span>
                    <h3>{d.title}</h3>
                    <p>{d.scope}</p>
                    <div className="doc-footer">
                      <span>{d.chunks.length} 个章节片段</span>
                      <ArrowRight size={16} />
                    </div>
                  </button>
                ))}
              </div>
              {currentDoc && (
                <section className="card document-detail">
                  <div className="section-heading">
                    <h2>{currentDoc.title}</h2>
                    <button
                      className="icon-button"
                      onClick={() => setDocId(null)}
                      aria-label="关闭资料详情"
                    >
                      <X size={18} />
                    </button>
                  </div>
                  <div className="source-box">
                    <strong>来源</strong>
                    {/^https?:\/\//.test(currentDoc.source) ? (
                      <a
                        href={currentDoc.source}
                        target="_blank"
                        rel="noreferrer"
                      >
                        查看原始资料 <ExternalLink size={13} />
                      </a>
                    ) : (
                      currentDoc.source
                    )}
                    <p>{currentDoc.scope}</p>
                  </div>
                  {currentDoc.chunks.map((c, i) => (
                    <article
                      key={i}
                      id={"citation-" + currentDoc.id + ":" + i}
                      className={
                        citationTarget === currentDoc.id + ":" + i
                          ? "highlighted"
                          : ""
                      }
                    >
                      <span className="mini-label">
                        证据片段 {i + 1} / {currentDoc.id}:{i}
                      </span>
                      <h3>{c.section}</h3>
                      <p>{c.text.replace(/^#.+\n/, "")}</p>
                    </article>
                  ))}
                </section>
              )}
            </>
          )}
          {page === "reports" && (
            <div className="reports-layout">
              <section className="card report-list">
                <div className="section-heading">
                  <h2>已保存报告</h2>
                  <span className="count">{reports.length}</span>
                </div>
                {reports.length === 0 ? (
                  <p className="muted">完成分析后即可创建报告。</p>
                ) : (
                  reports.map((r) => (
                    <button
                      key={r.id}
                      className={
                        "report-item " + (r.id === reportId ? "selected" : "")
                      }
                      onClick={() => {
                        setReportId(r.id);
                        setDraft(r.conclusion);
                      }}
                    >
                      <FileText size={20} />
                      <div>
                        <strong>{r.dataset_name}</strong>
                        <small>
                          参考区间 {r.reference.start} — {r.reference.end}
                        </small>
                      </div>
                      <ChevronRight size={14} />
                    </button>
                  ))
                )}
              </section>
              {!selectedReport ? (
                <section className="card report-preview">
                  <Empty
                    icon={<FileText size={30} />}
                    title="让分析有一份完整记录"
                    text="报告保留独立的分析快照。选择已有报告，或从当前分析创建一份新报告。"
                    action={
                      <button
                        className="button primary"
                        disabled={!activeAnalysis || busy || streaming}
                        onClick={createReport}
                      >
                        创建当前分析报告
                      </button>
                    }
                  />
                </section>
              ) : (
                <section className="card report-preview">
                  <div className="report-toolbar">
                    <span className="badge green">
                      <Check size={12} />
                      已保存分析快照
                    </span>
                    <div>
                      <button
                        className="button"
                        onClick={saveReport}
                        disabled={busy || draft === selectedReport.conclusion}
                      >
                        保存修改
                      </button>
                      <a
                        className={
                          "button primary " +
                          (draft !== selectedReport.conclusion
                            ? "disabled"
                            : "")
                        }
                        href={"/api/reports/" + selectedReport.id + "/pdf"}
                        onClick={(e) => {
                          if (draft !== selectedReport.conclusion) {
                            e.preventDefault();
                            notify("请先保存修改，再导出 PDF");
                          }
                        }}
                      >
                        <ArrowDownToLine size={15} />
                        导出 PDF
                      </a>
                    </div>
                  </div>
                  <div className="report-paper">
                    <div className="report-brand">
                      桥安智析 <span>BRIDGE INSIGHT</span>
                    </div>
                    <span className="eyebrow">MONITORING ANALYSIS REPORT</span>
                    <h2>{selectedReport.title}</h2>
                    <p className="report-source">{selectedReport.source}</p>
                    <div className="report-summary">
                      <div>
                        <small>样本数量</small>
                        <strong>{selectedReport.summary.samples}</strong>
                      </div>
                      <div>
                        <small>参考期后异常</small>
                        <strong>{selectedReport.summary.anomalies}</strong>
                      </div>
                      <div>
                        <small>连续告警起点</small>
                        <strong>
                          {selectedReport.summary.onset || "未触发"}
                        </strong>
                      </div>
                    </div>
                    <h3>
                      01 / 分析结论 <span>支持编辑</span>
                    </h3>
                    <textarea
                      className="report-editor"
                      aria-label="编辑报告结论"
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      maxLength={20000}
                    />
                    <h3>02 / 计算证据</h3>
                    <p>
                      健康参考区间：{selectedReport.reference.start} —{" "}
                      {selectedReport.reference.end}，共{" "}
                      {selectedReport.reference.count}{" "}
                      条样本。马氏距离平方阈值为{" "}
                      {selectedReport.summary.threshold.toFixed(4)}。
                    </p>
                    <p className="subtle">
                      分析编号：{selectedReport.analysis_id}
                    </p>
                    <h3>03 / 资料引用</h3>
                    {selectedReport.citations.length ? (
                      selectedReport.citations.map((c) => (
                        <button
                          className="citation-inline"
                          key={c.id}
                          onClick={() => openCitation(c)}
                        >
                          <BookOpen size={14} />
                          {c.title} / {c.section}
                          <ExternalLink size={12} />
                        </button>
                      ))
                    ) : (
                      <p>
                        尚未附加资料引用；当前报告仅依据统计计算。完成 AI
                        资料检索后可重新生成含引用的报告。
                      </p>
                    )}
                    <h3>04 / 复核建议与局限</h3>
                    <p>
                      建议核查采集链路、传感器校准记录与温度覆盖范围，必要时由专业人员组织现场复检。
                    </p>
                    {selectedReport.limitations.map((t) => (
                      <p key={t} className="limit">
                        <Check size={14} />
                        {t}
                      </p>
                    ))}
                    <div className="paper-footer">
                      本报告为研究辅助结果，不构成结构损伤定位或法定安全鉴定。
                    </div>
                  </div>
                </section>
              )}
            </div>
          )}
          <footer className="footer">
            <span>桥安智析 · 让桥梁监测更易理解</span>
            <span>
              <ShieldCheck size={13} />
              研究辅助 · 证据可追溯 · 专业复核
            </span>
          </footer>
        </main>
      </div>
      {toast && (
        <div className="toast" role="status">
          <Check size={17} />
          {toast}
        </div>
      )}
    </div>
  );
}
function Stat({
  label,
  value,
  unit,
  foot,
  icon,
  warm = false,
}: {
  label: string;
  value: string;
  unit: string;
  foot: string;
  icon: React.ReactNode;
  warm?: boolean;
}) {
  return (
    <div className={"card stat " + (warm ? "warm" : "")}>
      <div className="stat-label">
        {label}
        <span>{icon}</span>
      </div>
      <div className="stat-value">
        {value}
        <small>{unit}</small>
      </div>
      <div className="stat-foot">{foot}</div>
    </div>
  );
}
function Empty({
  icon,
  title,
  text,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  text: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <h2>{title}</h2>
      <p>{text}</p>
      {action}
    </div>
  );
}
