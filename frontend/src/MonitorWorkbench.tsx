import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, ArrowDownToLine, ArrowRight, BarChart3, CircleHelp, Database, FileText,
  History, LineChart, ListChecks, Plus, Send, SlidersHorizontal,
  ScanLine, Square, Trash2, TriangleAlert, Upload, Waves,
} from "lucide-react";
import { ApiError, post } from "./api";
import { downloadCsv, monitorApi as api, monitorFetch, readWorkspace, storeWorkspace } from "./monitorApi";
import { Dialog, ImportDialog, RecipeDialog, ToolDialog, labels, primaryMethods, root } from "./MonitorForms";
import { IntervalDialog } from "./MonitorIntervals";
import { ResultPane } from "./MonitorResult";
import { forecastSummaryInMinutes, minuteBoundary, minuteInput, toMinutes } from "./monitorUnits";
import { prettyTime, show, type Conversation, type Dataset, type Params, type Recipe, type Report,
  type ObservationInterval, type ObservationScanAction, type Result, type ResultMeta,
  type Rule, type ScanResult, type Tool, type Turn, type Version } from "./monitorTypes";
import "./monitor.css";

const entries = [
  ["quality", "检查数据", "缺测、重复与采样", ListChecks],
  ["trend", "查看规律", "趋势、统计与比较", LineChart],
  ["anomaly", "查找异常", "尖峰、偏移与波动", Activity],
  ["forecast", "预测趋势", "短期预测与回测", BarChart3],
  ["limits", "检查超限", "按自设限值检查", TriangleAlert],
] as const;
const prompts = ["检查当前测点有没有缺测或重复时间", "画出当前所选测点的趋势图", "找出变化明显的时段"];
const tools = [
  ["数据整理", "clean", "resample", "compare", "change", "rolling", "correlation", "lag"],
  ["信号分析", "moving", "savgol", "detrend", "filter", "fft", "welch", "stl"],
];
type Page = "work" | "history" | "reports";
type Discarded = { version_id: string; discarded_versions: string[]; discarded_analyses: string[] };
type ReportLabel = Pick<Report, "id" | "title" | "conclusion">;
type Deletion =
  | { kind: "analysis"; item: ResultMeta; reports: ReportLabel[] }
  | { kind: "report"; item: Report };
type Deleted = { report_ids: string[]; analysis_ids: string[] };
type RetryTool = { method: string; params: Params; saveRule: boolean };
type ScanContext = {
  versionId: string; channels: string[]; start?: string; end?: string; retry?: RetryTool; initialResult?: ScanResult;
};
type ToolDraft = { target: ScanContext; initial?: Params; saveRule?: boolean };
type Health = {
  service: string; api_version: number; workspace_drafts: boolean; record_deletion: boolean; ai_configured: boolean;
  observation_intervals: boolean;
  chat_observation_intervals: boolean;
};
const assistantImage = new URL("./assets/ai-assistant.webp", import.meta.url).href;
const deepseekExample = [
  "AI_API_KEY=你的DeepSeek密钥",
  "AI_BASE_URL=https://api.deepseek.com",
  "AI_MODEL=deepseek-flash",
].join("\n");
const describe = (e: unknown) => {
  const msg = (e as Error).message || "操作失败";
  try {
    const fields = JSON.parse(msg);
    if (Array.isArray(fields)) return fields.map((f) => f.loc?.slice(1).join(".") + " · " + f.msg).join("；");
  } catch { /* Plain service message. */ }
  return msg;
};
const base = "/api" + root;
function dateInput(value?: string, end = false) {
  if (!value) return "";
  return value.length === 10 ? value + (end ? "T23:59:59.999" : "T00:00") : value.replace(" ", "T");
}

function datasetLabel(dataset: Dataset) {
  const title = dataset.sheet ? dataset.sheet + " · " + dataset.name : dataset.name;
  return title + (dataset.simulation ? "（模拟）" : "");
}

export default function MonitorWorkbench() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [dataset, setDataset] = useState<Dataset>();
  const [versions, setVersions] = useState<Version[]>([]);
  const [version, setVersion] = useState("");
  const [channels, setChannels] = useState<string[]>([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [ai, setAi] = useState<boolean>();
  const [aiVerified, setAiVerified] = useState(false);
  const [service, setService] = useState<"checking" | "ready" | "offline">("checking");
  const [serviceError, setServiceError] = useState("");
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const [page, setPage] = useState<Page>("work");
  const [mobile, setMobile] = useState<"chat" | "result">("result");
  const [result, setResult] = useState<Result>();
  const [history, setHistory] = useState<ResultMeta[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversation, setConversation] = useState<string>();
  const [question, setQuestion] = useState("");
  const [running, setRunning] = useState("");
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [modal, setModal] = useState("");
  const [scan, setScan] = useState<ScanContext>();
  const [failedScan, setFailedScan] = useState<ScanContext>();
  const [toolDraft, setToolDraft] = useState<ToolDraft>();
  const [resampledRetry, setResampledRetry] = useState<{ versionId: string; retry: RetryTool }>();
  const [drawer, setDrawer] = useState(false);
  const [rules, setRules] = useState<Rule[]>([]);
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [conclusion, setConclusion] = useState("");
  const [reportBusy, setReportBusy] = useState(false);
  const [checkingAi, setCheckingAi] = useState(false);
  const [aiMessage, setAiMessage] = useState("");
  const [versionLabel, setVersionLabel] = useState("");
  const [versionError, setVersionError] = useState("");
  const [deletion, setDeletion] = useState<Deletion>();
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const log = useRef<HTMLDivElement>(null);
  const controls = useRef<HTMLSelectElement>(null);
  const dsId = dataset?.id;
  const blocked = !!running;
  const scanParams = useMemo<Params | undefined>(() => scan && ({
    ...scan.retry?.params, channels: scan.channels, start: scan.start, end: scan.end,
  }), [scan]);

  function select(d?: Dataset) {
    setDataset(d);
    setVersion(d?.original_id ?? "");
    setChannels(d?.channels.map((c) => c.name) ?? []);
    setStart(""); setEnd(""); setResult(undefined); setError(""); setPage("work"); setMobile("result");
    setVersions([]); setRules([]); setTurns([]); setQuestion(""); setConversation(undefined); setDrawer(false);
    setScan(undefined); setFailedScan(undefined); setToolDraft(undefined); setResampledRetry(undefined);
    if (d) localStorage.setItem("mw-dataset", d.id);
    else localStorage.removeItem("mw-dataset");
  }
  useEffect(() => {
    const stop = new AbortController();
    setService("checking");
    setServiceError("");
    const config = { signal: stop.signal };
    api<Health>(root + "/health", config).then(async (status) => {
      if (status.service !== "bridge-insight" || status.api_version !== 2 ||
          !status.workspace_drafts || !status.record_deletion ||
          !status.observation_intervals || !status.chat_observation_intervals) {
        throw new Error("当前服务与界面版本不匹配，请关闭旧窗口并重新启动平台。");
      }
      const items = await api<Dataset[]>(root + "/datasets", config);
      if (stop.signal.aborted) return;
      setAi(status.ai_configured);
      setAiVerified(false);
      setDatasets(items);
      const saved = readWorkspace();
      const lastId = saved?.dataset ?? localStorage.getItem("mw-dataset");
      const last = items.find((d) => d.id === lastId);
      if (last) {
        select(last);
        if (saved?.dataset === last.id) {
          const [items, previous] = await Promise.all([
            api<Version[]>(root + "/datasets/" + last.id + "/versions", config),
            saved.result ? api<Result>(root + "/analyses/" + saved.result, config).catch(() => undefined) : undefined,
          ]);
          if (stop.signal.aborted) return;
          setVersions(items);
          if (items.some((item) => item.id === saved.version)) {
            setVersion(saved.version);
            setChannels(saved.channels);
            setStart(saved.start);
            setEnd(saved.end);
          }
          if (previous?.dataset_id === last.id) setResult(previous);
          else if (saved.result) setToast("此前的临时结果已结束");
        }
      }
      setService("ready");
    }).catch((e) => {
      if (stop.signal.aborted) return;
      setServiceError(describe(e));
      setService("offline");
    });
    return () => stop.abort();
  }, [connectionAttempt]);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (!dsId || service !== "ready") return;
    const stop = new AbortController();
    const config = { signal: stop.signal };
    Promise.all([
      api<Version[]>(root + "/datasets/" + dsId + "/versions", config),
      api<{ rule: Rule }[]>(root + "/datasets/" + dsId + "/rules", config),
      api<Conversation[]>(root + "/conversations?dataset_id=" + dsId, config),
    ]).then(([available, savedRules, [last]]) => {
      if (stop.signal.aborted) return;
      setVersions(available);
      setRules(savedRules.map((item) => item.rule));
      if (last) { setConversation(last.id); setTurns(last.turns); }
    }).catch((e) => { if (!stop.signal.aborted) setError(describe(e)); });
    return () => stop.abort();
  }, [dsId, service]);
  useEffect(() => {
    if (service !== "ready") return;
    storeWorkspace(dsId ? { dataset: dsId, version, result: result?.id, channels, start, end } : undefined);
  }, [service, dsId, version, result?.id, channels, start, end]);
  useEffect(() => {
    if (page === "history") api<ResultMeta[]>(root + "/analyses").then(setHistory).catch((e) => setError(describe(e)));
    if (page === "reports") api<Report[]>(root + "/reports").then(setReports).catch((e) => setError(describe(e)));
  }, [page]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 4200);
    return () => window.clearTimeout(timer);
  }, [toast]);
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [turns, mobile]);

  function openAi() {
    setAiMessage("");
    setModal("ai");
  }

  async function checkAi() {
    setCheckingAi(true);
    setAiMessage("");
    try {
      const status = await api<{ ai_configured: boolean }>(root + "/health");
      setAi(status.ai_configured);
      setAiVerified(false);
      if (status.ai_configured) {
        setAiMessage("已读取密钥。关闭窗口后，选一个数据集发送消息验证连接。");
      } else {
        setAiMessage("还没有读到密钥。请在项目目录的 .env 文件中保存 AI_API_KEY。");
      }
    } catch (e) {
      setAiMessage(describe(e));
    } finally {
      setCheckingAi(false);
    }
  }

  async function operate(label: string, action: (signal: AbortSignal) => Promise<void>) {
    if (controller.current) return;
    const stop = new AbortController();
    controller.current = stop;
    setError(""); setFailedScan(undefined); setRunning(label);
    try { await action(stop.signal); }
    catch (e) { if (!stop.signal.aborted) setError(describe(e)); }
    finally { controller.current = null; setRunning(""); }
  }
  async function exhibit(item: Result, signal: AbortSignal, fromChat = false) {
    const target = datasets.find((d) => d.id === item.dataset_id);
    if (!target) throw new Error("分析的数据集无法加载");
    const available = await api<Version[]>(root + "/datasets/" + item.dataset_id + "/versions", { signal });
    if (signal.aborted) return;
    if (target.id !== dsId) select(target);
    setVersions(available);
    setPage("work");
    setResult(item);
    setMobile(fromChat && !item.created_version_id ? "chat" : "result");
    if (item.snapshot) return;
    const input = available.find((v) => v.id === item.version_id);
    setVersion(input?.id ?? target.original_id);
    if (input) {
      if (item.parameters.channels?.length) setChannels(item.parameters.channels);
      setStart(dateInput(item.parameters.start));
      setEnd(dateInput(item.parameters.end, true));
    } else {
      setChannels(target.channels.map((c) => c.name));
      setStart("");
      setEnd("");
    }
  }
  function currentScope(): ScanContext {
    return { versionId: version, channels, start: start || undefined, end: end || undefined };
  }

  function run(method: string, params: Params = {}, saveRule = false, target = currentScope()) {
    if (!dataset || blocked) return;
    const selected = params.channels ?? target.channels;
    if (!selected.length) { setError("请至少选择一个测点"); return; }
    setModal(""); setDrawer(false); setToolDraft(undefined);
    void operate(labels[method], async (signal) => {
      const parameters = { start: target.start, end: target.end, ...params, channels: selected };
      let item: Result;
      try {
        item = await api<Result>(root + "/analyses", {
          ...post({ dataset_id: dsId, version_id: target.versionId, method, parameters }), signal,
        });
      } catch (e) {
        if (e instanceof ApiError && e.code === "observation_interval_required") {
          setFailedScan({
            versionId: target.versionId, channels: selected, start: parameters.start, end: parameters.end,
            retry: { method, params, saveRule },
          });
        }
        throw e;
      }
      await exhibit(item, signal);
      if (method === "resample" && item.created_version_id) {
        setResampledRetry(target.retry ? {
          versionId: item.created_version_id,
          retry: { ...target.retry, params: { ...target.retry.params, channels: target.channels } },
        } : undefined);
      }
      if (params.rule && saveRule) {
        await api(root + "/datasets/" + dsId + "/rules", { ...post(params.rule), signal });
        setRules((all) => [...all, params.rule!]);
      }
    });
  }
  function openTool(method: string) {
    setToolDraft(undefined);
    if (["quality", "trend", "change", "detrend", "fft", "welch"].includes(method)) run(method);
    else setModal("tool:" + method);
  }

  function openScan(context = currentScope()) {
    setDrawer(false);
    setScan(context);
  }

  function openChatScan(action: ObservationScanAction) {
    const { channels: selected, start, end, ...params } = action.parameters;
    openScan({
      versionId: action.version_id,
      channels: selected ?? channels,
      start,
      end,
      retry: { method: action.method, params, saveRule: false },
      initialResult: action.result ?? undefined,
    });
  }

  function chooseInterval(interval: ObservationInterval) {
    if (!scan) return;
    const target = { ...scan, start: interval.start, end: interval.end };
    setVersion(target.versionId);
    setChannels(target.channels);
    setStart(interval.start);
    setEnd(interval.end);
    setScan(undefined);
    setFailedScan(undefined);
    setError("");
    if (target.retry) {
      setToolDraft({ target, initial: target.retry.params, saveRule: target.retry.saveRule });
      setModal("tool:" + target.retry.method);
    } else {
      setToast("已选用观测区间");
    }
  }

  function resampleScan(scope: Pick<Params, "start" | "end">) {
    if (!scan) return;
    setToolDraft({ target: { ...scan, start: scope.start, end: scope.end } });
    setScan(undefined);
    setModal("tool:resample");
  }
  function ask(value = question) {
    if (!dataset || !value.trim() || !ai || blocked) return;
    if (!channels.length) { setError("请至少选择一个测点"); return; }
    void operate("正在处理问题", async (signal) => {
      setMobile("chat"); setQuestion("");
      setTurns((items) => [...items, { question: value.trim(), answer: "", tools: [], citations: [], status: "running" }]);
      let done = false;
      let awaiting: ObservationScanAction | undefined;
      const update = (change: (t: Turn) => Turn) => setTurns((items) => [...items.slice(0, -1), change(items[items.length - 1])]);
      try {
        const response = await monitorFetch(root + "/chat", { ...post({
          dataset_id: dsId, version_id: version, conversation_id: conversation, question: value.trim(),
          context: { channels, start: start || null, end: end || null },
        }), signal });
        if (!response.ok) throw new Error((await response.json()).detail ?? "对话请求失败");
        const reader = response.body?.getReader();
        if (!reader) throw new Error("对话响应为空");
        const decoder = new TextDecoder();
        let pending = "";
        while (!signal.aborted) {
          const chunk = await reader.read();
          pending += decoder.decode(chunk.value, { stream: !chunk.done });
          const blocks = pending.split(/\r?\n\r?\n/);
          pending = blocks.pop() ?? "";
          for (const block of blocks) {
            const event = block.match(/^event: (.+)$/m)?.[1].trim();
            const payload = block.match(/^data: (.+)$/m)?.[1];
            if (!payload || signal.aborted) continue;
            const data = JSON.parse(payload);
            if (event === "conversation") setConversation(data.id);
            if (event === "status") setRunning(data.text);
            if (event === "token") update((t) => ({ ...t, answer: t.answer + data.text }));
            if (event === "tool") {
              const tool = data as Tool;
              if (tool.status === "awaiting_interval") awaiting = tool.result?.observation_scan;
              update((t) => ({ ...t, tools: [...t.tools.filter((x) => x.status !== "running"), tool] }));
            }
            if (event === "citations") update((t) => ({ ...t, citations: data.items }));
            if (event === "analysis") {
              const item = await api<Result>(root + "/analyses/" + data.id, { signal });
              await exhibit(item, signal, true);
              setToast("分析结果已更新");
            }
            if (event === "error") setError(data.message);
            if (event === "done") {
              done = true;
              setAiVerified(data.status === "complete" || data.status === "awaiting_interval");
              update((t) => ({ ...t, status: data.status }));
              if (data.status === "awaiting_interval" && awaiting) openChatScan(awaiting);
            }
          }
          if (chunk.done) break;
        }
      } finally {
        if (!done) {
          if (!signal.aborted) setAiVerified(false);
          update((t) => ({ ...t, status: signal.aborted ? "cancelled" : "error" }));
        }
      }
    });
  }
  function openAnalysis(id: string) {
    void operate("正在读取分析", async (signal) => {
      await exhibit(await api<Result>(root + "/analyses/" + id, { signal }), signal);
    });
  }

  const demo = datasets.find((d) => d.simulation);
  const available = versions.some((v) => v.id === dataset?.original_id) ? versions : [
    ...(dataset ? [{ id: dataset.original_id, label: "原始数据", parent_id: null, steps: [] }] : []), ...versions,
  ];
  const current = available.find((v) => v.id === version);
  const resultVersion = result?.snapshot ? undefined : available.find((v) =>
    v.id === (result?.created_version_id ?? result?.version_id ?? version));
  const workflowVersion = resultVersion && (result?.created_version_id || resultVersion.parent_id)
    ? resultVersion : undefined;
  const versionPath = workflowVersion
    ? root + "/datasets/" + dsId + "/versions/" + workflowVersion.id : "";
  const cites = result ? [...new Map(turns.flatMap((t) => t.tools.some((x) => x.result?.analysis_id === result.id)
    ? t.citations : []).map((c) => [c.id, c])).values()] : [];

  function continueWith(item: Version) {
    setVersion(item.id);
    if (result?.parameters.channels?.length) setChannels(result.parameters.channels);
    if (result?.created_version_id === item.id) {
      setStart("");
      setEnd("");
    }
    setError("");
    setToast("已选用「" + item.label + "」作为输入，请选择下一步操作");
    controls.current?.focus();
  }

  function saveData() {
    if (!workflowVersion || !versionLabel.trim()) {
      setVersionError("请输入数据版本名称");
      return;
    }
    setVersionError("");
    void operate("正在保存数据版本", async () => {
      let item: Version;
      try {
        item = await api<Version>(versionPath + "/save", post({ label: versionLabel.trim() }));
      } catch (e) {
        setVersionError(describe(e));
        return;
      }
      setVersions((all) => all.map((v) => v.id === item.id ? item : v));
      setModal("");
      setToast("已保存数据版本「" + item.label + "」");
      const refreshed = await api<Version[]>(root + "/datasets/" + dsId + "/versions");
      setVersions(refreshed);
      if (!refreshed.some((v) => v.id === version)) {
        setVersion(item.id);
        setStart("");
        setEnd("");
      }
    });
  }

  function discardData() {
    setVersionError("");
    void operate("正在放弃临时结果", async () => {
      try {
        const discarded = await api<Discarded>(versionPath, { method: "DELETE" });
        setVersions((all) => all.filter((v) => !discarded.discarded_versions.includes(v.id)));
        invalidateLinks(discarded.discarded_analyses);
        setVersion(discarded.version_id);
        setResult(undefined);
        setStart("");
        setEnd("");
        setModal("");
        setToast("已放弃临时结果，回到上一步输入");
      } catch (e) {
        setVersionError(describe(e));
      }
    });
  }

  function invalidateLinks(ids: string[], deleted = false) {
    if (!ids.length) return;
    const removed = new Set(ids);
    setTurns((all) => all.map((turn) => ({
      ...turn,
      tools: turn.tools.map((tool) => tool.result?.analysis_id && removed.has(tool.result.analysis_id)
        ? { ...tool, result: { unavailable: true, deleted } } : tool),
    })));
  }

  function deletionPreview(id: string, signal?: AbortSignal) {
    return api<{ reports: ReportLabel[] }>(root + "/analyses/" + id + "/deletion-preview", { signal });
  }

  function confirmAnalysisDeletion(item: ResultMeta) {
    void operate("正在核对关联报告", async (signal) => {
      const preview = await deletionPreview(item.id, signal);
      setDeleteError("");
      setDeletion({ kind: "analysis", item, reports: preview.reports });
    });
  }

  async function deleteRecord() {
    if (!deletion || deleteBusy) return;
    const target = deletion;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      const response = await api<Deleted>(
        root + (target.kind === "analysis" ? "/analyses/" : "/reports/") + target.item.id,
        target.kind === "analysis"
          ? { ...post({ report_ids: target.reports.map((item) => item.id) }), method: "DELETE" }
          : { method: "DELETE" },
      );
      const analyses = new Set(response.analysis_ids);
      const reports = new Set(response.report_ids);
      setHistory((all) => all.filter((item) => !analyses.has(item.id)));
      setReports((all) => all.filter((item) => !reports.has(item.id)));
      setResult((item) => item && analyses.has(item.id) ? undefined : item);
      invalidateLinks(response.analysis_ids, true);
      setDeletion(undefined);
      setToast(target.kind === "report" ? "已删除报告"
        : reports.size ? "已删除分析和 " + reports.size + " 份关联报告" : "已删除分析");
    } catch (e) {
      if (target.kind === "analysis" && e instanceof ApiError && e.status === 409) {
        try {
          const preview = await deletionPreview(target.item.id);
          setDeletion({ ...target, reports: preview.reports });
        } catch (refreshError) {
          setDeleteError(describe(refreshError));
          return;
        }
      }
      setDeleteError(describe(e));
    } finally {
      setDeleteBusy(false);
    }
  }

  return <div className="mw">
    <header className="mw-top">
      <a className="mw-brand" href="/"><span><Waves size={22} /></span><div><strong>桥安智析</strong><small>桥梁监测数据分析</small></div></a>
      <nav aria-label="主导航">
        {([["work", "分析工作台", Activity], ["history", "分析历史", History], ["reports", "报告", FileText]] as const)
          .map(([key, title, Icon]) => <button disabled={blocked} key={key} className={page === key ? "active" : ""}
            onClick={() => { setPage(key); setDrawer(false); }}><Icon size={17} />{title}</button>)}
      </nav>
      <div className="mw-top-right">
        {service === "ready"
          ? <button className="mw-button" onClick={openAi}>配置 AI</button>
          : <span className="mw-status"><i />{service === "checking" ? "正在连接" : "服务未连接"}</span>}
        <button className="mw-button mw-icon" title="使用说明" aria-label="使用说明" onClick={() => setModal("help")}><CircleHelp size={18} /></button>
      </div>
    </header>
    <main className="mw-main">
      {serviceError && <div className="mw-error mw-banner" role="alert">
        <TriangleAlert size={16} /><span>{serviceError}</span>
        <button className="mw-link" onClick={() => setConnectionAttempt((n) => n + 1)}>重新连接</button></div>}
      {error && <div className="mw-error mw-banner" role="alert"><TriangleAlert size={16} /><span>{error}</span>
        <div className="mw-inline">
          {failedScan && page === "work" && <button className="mw-button" disabled={blocked}
            onClick={() => openScan(failedScan)}>扫描区间</button>}
          <button className="mw-link" onClick={() => { setError(""); setFailedScan(undefined); }}>关闭</button>
        </div></div>}
      {running && <div role="status" className="mw-progress"><span><i />{running}</span>
        <button className="mw-button" onClick={() => { controller.current?.abort(); setToast("已取消当前操作"); }}><Square size={13} />取消</button></div>}
      {page === "work" && <>
        <section className="mw-dataset">
          <div className="mw-dataset-top">
            <div className="mw-dataset-name"><Database size={21} /><div><h1>{dataset?.name ?? "监测数据工作台"}</h1>
              <p>{dataset ? (dataset.simulation ? "模拟数据" : "用户上传") + (dataset.sheet ? " · " + dataset.sheet : "")
                : "从一份时间序列表格开始"}</p></div></div>
            <div className="mw-inline">
              <select aria-label="选择数据集" value={dsId ?? ""} disabled={blocked}
                onChange={(e) => select(datasets.find((d) => d.id === e.target.value))}>
                <option value="">选择数据集</option>
                {datasets.map((d) => <option key={d.id} value={d.id}>{datasetLabel(d)}</option>)}
              </select>
              <button className="mw-button primary" disabled={blocked || service !== "ready"} onClick={() => setModal("import")}><Upload size={16} />导入数据</button>
            </div>
          </div>
          {dataset && <div className="mw-dataset-meta">
            <span><strong>{show(dataset.samples)}</strong> 行</span><span><strong>{dataset.channels.length}</strong> 个测点</span>
            <span>{prettyTime(dataset.start)} ～ {prettyTime(dataset.end)}</span>
            <span>{dataset.interval ? "常见间隔 " + show(toMinutes(dataset.interval)) + " 分钟" : "采样间隔待确认"}</span>
            {dataset.invalid_times > 0 && <button className="mw-link" disabled={blocked} onClick={() => run("quality")}>
              {dataset.invalid_times} 行无效时间</button>}
          </div>}
        </section>
        {!dataset ? <section className="mw-empty">
          <div className="mw-empty-art" aria-hidden="true"><LineChart size={46} strokeWidth={1.4} /></div>
          <h2>上传监测数据，开始分析</h2><p>支持挠度、应变、位移、温度和倾角。表格包含一列时间和一个或多个测点。</p>
          <div className="mw-inline"><button className="mw-button primary" disabled={service !== "ready"} onClick={() => setModal("import")}><Plus size={16} />导入 CSV 或 Excel</button>
            {demo && <button className="mw-button" onClick={() => { select(demo); }}>试用挠度示例<ArrowRight size={15} /></button>}</div>
          {service === "ready" && <a className="mw-link" href={base + "/import-template.csv"}>下载 CSV 模板</a>}
          <div className="mw-example"><span>时间</span><span>跨中 A（mm）</span><span>跨中 B（mm）</span>
            <code>2025-10-01 09:00</code><code>2.46</code><code>1.82</code></div>
        </section> : <>
          <section className="mw-controls" aria-label="分析范围">
            <label className="mw-field horizontal">数据版本<select aria-label="数据版本" ref={controls} value={version} disabled={blocked} onChange={(e) => {
              setVersion(e.target.value); setResult(undefined);
            }}>{available.map((v, i) => <option key={v.id} value={v.id}>{v.label}{v.temporary ? "（临时）" : ""}
              {v.parent_id ? " · " + (available.length - i - 1) : ""}</option>)}</select></label>
            <details className="mw-select"><summary>{channels.length === dataset.channels.length ? "全部测点" : channels.length + " 个测点"}</summary>
              <div>{dataset.channels.map((c) => <label className="mw-check" key={c.name}><input type="checkbox" disabled={blocked}
                checked={channels.includes(c.name)} onChange={() => setChannels((a) => a.includes(c.name)
                  ? a.filter((name) => name !== c.name) : [...a, c.name])} />{c.name}<small>{c.unit || c.type}</small></label>)}</div></details>
            <label className="mw-field horizontal">开始<input type="datetime-local" step="60" value={minuteInput(start)}
              disabled={blocked} onChange={(e) => setStart(minuteBoundary(e.target.value))} /></label>
            <label className="mw-field horizontal">结束<input type="datetime-local" step="60" value={minuteInput(end)}
              disabled={blocked} onChange={(e) => setEnd(minuteBoundary(e.target.value, true))} /></label>
            {(start || end) && <button className="mw-link" disabled={blocked} onClick={() => { setStart(""); setEnd(""); }}>全时段</button>}
            <button className="mw-button" disabled={blocked || !channels.length} onClick={() => openScan()}>
              <ScanLine size={16} />扫描区间</button>
            <button className="mw-button mw-tools-toggle" aria-expanded={drawer} disabled={blocked} onClick={() => setDrawer(!drawer)}>
              <SlidersHorizontal size={16} />专业工具</button>
          </section>
          <section className="mw-tasks" aria-label="常用分析">{entries.map(([key, title, description, Icon]) =>
            <button className={result?.method === key ? "active" : ""} disabled={blocked} key={key} onClick={() => openTool(key)}>
              <span className="mw-task-icon"><Icon size={19} /></span><span><strong>{title}</strong><small>{description}</small></span>
            </button>)}</section>
          <div className="mw-mobile-tabs"><button className={mobile === "chat" ? "active" : ""} onClick={() => setMobile("chat")}>对话</button>
            <button className={mobile === "result" ? "active" : ""} onClick={() => setMobile("result")}>结果{result ? " · 可查看" : ""}</button></div>
          <div className={"mw-work show-" + mobile}>
            <section className="mw-chat" aria-label="AI 分析助手">
              <div className="mw-section-title mw-assistant-heading">
                <div className="mw-assistant-identity">
                  <img src={assistantImage} alt="" width={54} height={54} />
                  <div><h2>AI 分析助手</h2>
                    <span className={"mw-status" + (aiVerified ? " online" : "")}><i />
                      {aiVerified ? "对话已验证" : ai ? "已读取密钥" : "待配置"}</span></div>
                </div>
                {turns.length > 0 && <button className="mw-icon" disabled={blocked} title="新对话" aria-label="新对话"
                  onClick={() => { setTurns([]); setConversation(undefined); }}><Plus size={18} /></button>}</div>
              <div className="mw-chat-log" ref={log} aria-live="polite">
                {!turns.length && <div className="mw-chat-intro"><h3>想了解这份数据的什么？</h3>
                  <p>可以指定测点、时段和分析方法。</p>{prompts.map((p) => <button className="mw-prompt" disabled={!ai || blocked}
                    key={p} onClick={() => ask(p)}>{p}<ArrowRight size={13} /></button>)}</div>}
                {turns.map((t, i) => <div className="mw-turn" key={i}><p className="mw-question">{t.question}</p>
                  <div className="mw-turn-inner">{t.tools.filter((x) => x.name !== "dataset_overview").map((x, j) =>
                    <div className="mw-tool-status" key={j}><span>{x.status === "awaiting_interval"
                      ? (labels[x.result?.observation_scan?.method ?? ""] ?? "分析") + " · "
                        + (x.result?.observation_scan?.result ? "已自动扫描区间" : "需要扫描区间")
                      : x.status === "error" ? x.result?.error ?? "工具执行失败"
                      : x.status === "running" ? "正在调用工具" : x.result?.deleted ? "结果已删除"
                      : x.result?.unavailable ? "临时结果已结束" : "工具已完成"}</span>
                      {x.result?.analysis_id && <button className="mw-link" disabled={blocked} onClick={() => openAnalysis(x.result!.analysis_id!)}>查看结果</button>}
                      {x.result?.observation_scan && (available.some((item) => item.id === x.result?.observation_scan?.version_id)
                        ? <button className="mw-link" disabled={blocked} onClick={() => openChatScan(x.result!.observation_scan!)}>查看扫描结果</button>
                        : <span>数据版本已不可用</span>)}</div>)}
                    {t.answer && <p className="mw-answer">{t.answer}</p>}
                    {t.status === "running" && !t.answer && <p className="mw-help">正在处理…</p>}
                    {t.status === "cancelled" && <p className="mw-help">已取消</p>}
                    {t.status === "error" && <button className="mw-link" disabled={blocked} onClick={() => ask(t.question)}>重试此问题</button>}
                  </div></div>)}
              </div>
              <form className="mw-compose" onSubmit={(e) => { e.preventDefault(); ask(); }}>
                {!ai && <p className="mw-help"><button type="button" className="mw-link" onClick={openAi}>配置 AI</button> 后可提问。任务按钮可直接计算。</p>}
                <textarea aria-label="分析问题" placeholder="例如：比较两个测点近一周的挠度" rows={2} maxLength={2000}
                  value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); ask(); }
                  }} />
                <div><span>Enter 发送</span><button className="mw-button primary" disabled={!ai || blocked || !question.trim()}><Send size={15} />发送</button></div>
              </form>
            </section>
            <ResultPane key={result?.id ?? dataset.id + version} dataset={dataset} result={result}
              version={result?.created_version_id ?? result?.version_id ?? version} citations={cites}
              workflow={workflowVersion && {
                item: workflowVersion, output: result?.created_version_id === workflowVersion.id,
                use: () => continueWith(workflowVersion),
                scan: result?.created_version_id === workflowVersion.id ? () => {
                  const retry = resampledRetry?.versionId === workflowVersion.id ? resampledRetry.retry : undefined;
                  openScan({ versionId: workflowVersion.id, channels: retry?.params.channels ?? result.parameters.channels ?? channels, retry });
                } : undefined,
                save: () => { setVersionLabel(workflowVersion.label); setVersionError(""); setModal("save-data"); },
                discard: () => { setVersionError(""); setModal("discard-data"); },
                download: () => void operate("正在下载数据", (signal) =>
                  downloadCsv(versionPath + "/csv", workflowVersion.label + ".csv", signal)),
              }}
              blocked={blocked} onError={setError} trend={() => run("trend")} report={() => {
                setConclusion(result?.summary ?? ""); setModal("report");
              }} />
          </div>
        </>}
      </>}
      {page === "history" && <section className="mw-collection">
        <div className="mw-section-title"><h1><History size={22} />分析历史</h1></div>
        {!history.length && <p className="mw-collection-empty">完成一次分析后，可以在这里重新查看结果。</p>}
        {history.map((item) => <article className="mw-list-row" key={item.id}><div><h3>{item.title}</h3>
          <p>{datasets.find((d) => d.id === item.dataset_id)?.name} · {
            item.method === "forecast" ? forecastSummaryInMinutes(item.summary) : item.summary}</p></div>
          <div className="mw-inline">
            <button disabled={blocked} className="mw-button" onClick={() => openAnalysis(item.id)}>查看结果<ArrowRight size={15} /></button>
            <button className="mw-button mw-danger" disabled={blocked} onClick={() => confirmAnalysisDeletion(item)}>
              <Trash2 size={15} />删除</button>
          </div></article>)}
      </section>}
      {page === "reports" && <section className="mw-collection">
        <div className="mw-section-title"><h1><FileText size={22} />报告</h1></div>
        {!reports.length && <p className="mw-collection-empty">保存分析报告后，可在此下载。</p>}
        {reports.map((item) => <article className="mw-list-row" key={item.id}><div><h3>{item.title}</h3><p>{item.conclusion}</p></div>
          <div className="mw-inline"><button className="mw-button" disabled={blocked} onClick={() => openAnalysis(item.analysis_id)}>打开分析</button>
            <a className="mw-button" href={base + "/reports/" + item.id + "/pdf"}><ArrowDownToLine size={15} />PDF</a>
            <button className="mw-button mw-danger" disabled={blocked} onClick={() => {
              setDeleteError(""); setDeletion({ kind: "report", item });
            }}><Trash2 size={15} />删除</button></div></article>)}
      </section>}
    </main>
    {drawer && dataset && <aside className="mw-drawer" aria-label="专业工具">
      <div className="mw-section-title"><h2><SlidersHorizontal size={17} />专业工具</h2><button className="mw-link" onClick={() => setDrawer(false)}>关闭</button></div>
      {tools.map(([group, ...methods]) => <section key={group}><h3>{group}</h3>{methods.filter((m) => !primaryMethods.includes(m))
        .map((m) => <button key={m} onClick={() => openTool(m)} disabled={blocked}>{labels[m]}<ArrowRight size={14} /></button>)}</section>)}
      <section><h3>处理记录</h3><button disabled={blocked} onClick={() => {
        api<Recipe[]>(root + "/recipes").then((items) => { setRecipes(items); setModal("recipes"); })
          .catch((e) => setError(describe(e)));
      }}>保存或复用步骤<ArrowRight size={14} /></button></section>
    </aside>}
    {toast && <div className="mw-toast" role="status">{toast}</div>}
    {deletion && <Dialog title={deletion.kind === "analysis" ? "删除分析记录" : "删除报告"}
      close={() => { if (!deleteBusy) setDeletion(undefined); }}>
      <p>删除「{deletion.kind === "analysis"
        ? [datasets.find((item) => item.id === deletion.item.dataset_id)?.name, deletion.item.title]
          .filter(Boolean).join(" · ") : deletion.item.title}」？此操作无法撤销。</p>
      {deletion.kind === "report" && <p className="mw-help">{deletion.item.conclusion.slice(0, 120)}</p>}
      {deletion.kind === "analysis" && deletion.reports.length > 0 && <div className="mw-delete-impact">
        <p>以下 {deletion.reports.length} 份关联报告将一并删除。</p>
        <ul>{deletion.reports.map((item) => <li key={item.id}>{item.title}
          {item.conclusion && <small>{item.conclusion}</small>}</li>)}</ul>
      </div>}
      {deleteError && <p className="mw-error" role="alert">{deleteError}</p>}
      <div className="mw-dialog-actions">
        <button className="mw-button" disabled={deleteBusy} onClick={() => setDeletion(undefined)}>取消</button>
        <button className="mw-button mw-danger" disabled={deleteBusy} onClick={() => void deleteRecord()}>
          {deleteBusy ? "正在删除…" : "确认删除"}
        </button>
      </div>
    </Dialog>}
    {modal === "import" && <ImportDialog close={() => setModal("")} onImport={(item) => {
      setDatasets((items) => [item, ...items]); select(item); setModal(""); setToast("已导入 " + datasetLabel(item));
    }} />}
    {modal.startsWith("tool:") && dataset && <ToolDialog key={modal} method={modal.slice(5)} dataset={dataset}
      selected={toolDraft?.target.channels ?? channels} rules={rules} initial={toolDraft?.initial}
      initialSave={toolDraft?.saveRule} close={() => { setModal(""); setToolDraft(undefined); }}
      onRun={(params, save) => run(modal.slice(5), params, save, toolDraft?.target)} />}
    {scan && scanParams && dataset && <IntervalDialog datasetId={dataset.id} versionId={scan.versionId}
      versionLabel={available.find((item) => item.id === scan.versionId)?.label ?? "数据版本"}
      method={scan.retry?.method} parameters={scanParams} initialResult={scan.initialResult} close={() => setScan(undefined)}
      choose={chooseInterval} resample={resampleScan}
      scanOriginal={() => setScan({ ...scan, versionId: dataset.original_id, initialResult: undefined })} />}
    {modal === "recipes" && dataset && <RecipeDialog dataset={dataset} recipes={recipes} canSave={!!current?.steps.length} close={() => setModal("")}
      save={(name) => {
        api<Recipe>(root + "/recipes", post({ version_id: version, name })).then((item) => {
          setRecipes((items) => [item, ...items]); setToast("已保存处理步骤"); setModal("");
        }).catch((e) => { setModal(""); setError(describe(e)); });
      }} apply={(id, mapping) => {
        setModal(""); setDrawer(false);
        void operate("正在应用处理步骤", async (signal) => {
          const item = await api<Result>(root + "/recipes/" + id + "/apply", { ...post({ dataset_id: dsId, version_id: version, mapping }), signal });
          await exhibit(item, signal);
        });
      }} />}
    {modal === "save-data" && workflowVersion && <Dialog title="保存为数据版本" close={() => { if (!blocked) setModal(""); }}>
      <form onSubmit={(e) => { e.preventDefault(); saveData(); }}>
        <label className="mw-field">版本名称<input required maxLength={100} value={versionLabel}
          onChange={(e) => setVersionLabel(e.target.value)} disabled={blocked} /></label>
        {versionError && <p className="mw-error" role="alert">{versionError}</p>}
        <div className="mw-dialog-actions"><button className="mw-button primary" disabled={blocked}>保存数据版本</button></div>
      </form>
    </Dialog>}
    {modal === "discard-data" && workflowVersion && <Dialog title="放弃临时结果" close={() => { if (!blocked) setModal(""); }}>
      <p>将回到上一步输入，并清除依赖「{workflowVersion.label}」的未保存结果。</p>
      {versionError && <p className="mw-error" role="alert">{versionError}</p>}
      <div className="mw-dialog-actions">
        <button className="mw-button" disabled={blocked} onClick={() => setModal("")}>保留</button>
        <button className="mw-button mw-danger" disabled={blocked} onClick={discardData}>放弃临时结果</button>
      </div>
    </Dialog>}
    {modal === "report" && result && <Dialog title="保存分析报告" close={() => setModal("")}>
      <form onSubmit={async (e) => {
        e.preventDefault(); setReportBusy(true);
        try {
          const item = await api<Report>(root + "/reports", post({ analysis_id: result.id, conclusion, conversation_id: conversation }));
          setReports((all) => [item, ...all]); setPage("reports"); setToast("已保存报告");
        } catch (err) { setError(describe(err)); }
        finally { setReportBusy(false); setModal(""); }
      }}>
        <p className="mw-help">报告包含图表、参数与处理步骤。</p>
        <label className="mw-field">结论<textarea rows={6} maxLength={20000} value={conclusion} onChange={(e) => setConclusion(e.target.value)} /></label>
        <div className="mw-dialog-actions"><button className="mw-button primary" disabled={reportBusy}>保存报告</button></div>
      </form>
    </Dialog>}
    {modal === "ai" && <Dialog title="配置 AI 对话" close={() => setModal("")}>
      <ol className="mw-help-list">
        <li>在项目目录双击 <code>配置AI.bat</code>，用记事本打开本机配置。</li>
        <li>使用 DeepSeek 官方密钥时，填写下面三项并保存。使用默认的百炼时，填写密钥即可。</li>
        <li>点击「检查配置」，然后在助手中发送消息验证连接。</li>
      </ol>
      <pre className="mw-ai-config"><code>{deepseekExample}</code></pre>
      <p className="mw-help">密钥保存在本机 .env 文件里。</p>
      <p className="mw-help" role="status">{aiMessage || (aiVerified ? "已成功完成一次对话。"
        : ai ? "已读取密钥。选一个数据集发消息验证连接。" : "尚未读取密钥。")}</p>
      <div className="mw-dialog-actions"><button className="mw-button primary" disabled={checkingAi}
        onClick={() => void checkAi()}>{checkingAi ? "正在检查…" : "检查配置"}</button></div>
    </Dialog>}
    {modal === "help" && <Dialog title="使用说明" close={() => setModal("")}>
      <ol className="mw-help-list"><li>导入 CSV 或 XLSX，确认时间、测点和单位。</li>
        <li>按测点和时段选择任务，也可以在对话中提问。</li><li>在图表、明细与分析依据中核对结果，按需下载。</li></ol>
      <p className="mw-help">对话会向已配置的服务发送问题、字段和计算摘要。上传文件保存在本机。</p>
    </Dialog>}
  </div>;
}

