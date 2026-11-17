import { useState } from "react";
import { ArrowDownToLine, ArrowRight, ChevronLeft, ChevronRight, Database, FileText, LineChart, Save } from "lucide-react";
import { downloadCsv, monitorApi as api } from "./monitorApi";
import { root } from "./MonitorForms";
import { ResultCharts } from "./MonitorCharts";
import { analysisRowInMinutes, forecastSummaryInMinutes, isDurationParameter, toMinutes, toSeconds } from "./monitorUnits";
import { prettyTime, show, type Citation, type Dataset, type DetailKey, type RawPage, type Result, type Row, type Rule, type Version } from "./monitorTypes";

const base = "/api" + root;
const detailNames: Record<DetailKey, string> = {
  rows: "统计与指标", issues: "质量问题", events: "事件", backtest: "历史回测", forecast: "未来预测",
};
const parameterNames: Record<string, string> = {
  channels: "测点", start: "开始", end: "结束", start_b: "对照开始", end_b: "对照结束",
  window: "窗口采样点数", threshold: "偏离倍数", duplicate: "重复处理", outliers: "异常处理",
  fill_seconds: "填补间隔上限（分钟）", interval_seconds: "重采样间隔（分钟）", coefficient: "相关系数",
  max_lag: "最大滞后样本数", cutoff_hz: "截止频率（Hz）", period_seconds: "分解周期（分钟）",
  steps: "预测步数", rule: "用户限值规则",
};
const methodParameters: Record<string, string[]> = {
  compare: ["start_b", "end_b"], rolling: ["window"], anomaly: ["window", "threshold"],
  clean: ["window", "threshold", "duplicate", "outliers", "fill_seconds"],
  resample: ["interval_seconds", "fill_seconds"], correlation: ["coefficient"], lag: ["max_lag"],
  moving: ["window"], savgol: ["window"], filter: ["cutoff_hz"], stl: ["period_seconds"],
  forecast: ["steps", "rule"], limits: ["rule"],
};

function Table({ rows, locate, selected }: { rows: Row[]; locate?: (row: Row) => void; selected?: number }) {
  if (!rows.length) return <p className="mw-help">当前没有明细。</p>;
  const columns = [...new Set(rows.flatMap(Object.keys))];
  return <div className="mw-tablewrap" tabIndex={0}><table>
    <thead><tr>{columns.map((key) => <th key={key}>{key}</th>)}{locate && <th>定位</th>}</tr></thead>
    <tbody>{rows.map((row, i) => <tr key={i} className={row.原表行 === selected ? "mw-row-focus" : ""}>
      {columns.map((key) => <td key={key}>{show(row[key])}</td>)}
      {locate && <td><button type="button" className="mw-link" onClick={() => locate(row)}>查看</button></td>}
    </tr>)}</tbody>
  </table></div>;
}

function Pager({ total, offset, move }: { total: number; offset: number; move: (next: number) => void }) {
  if (!total) return null;
  return <div className="mw-pager">
    <button disabled={!offset} aria-label="上一页" className="mw-icon" onClick={() => move(Math.max(0, offset - 100))}><ChevronLeft size={16} /></button>
    <span>{offset + 1}–{Math.min(total, offset + 100)} / {total}</span>
    <button disabled={total <= offset + 100} aria-label="下一页" className="mw-icon" onClick={() => move(offset + 100)}><ChevronRight size={16} /></button>
  </div>;
}

type WorkflowActions = {
  item: Version; output: boolean;
  use: () => void; save: () => void; discard: () => void; download: () => void;
  scan?: () => void;
};

export function ResultPane({ dataset, result, version, citations, workflow, blocked, onError, trend, report }: {
  dataset: Dataset; result?: Result; version: string; citations: Citation[]; blocked: boolean;
  workflow?: WorkflowActions;
  onError: (message: string) => void; trend: () => void; report: () => void;
}) {
  const [tab, setTab] = useState("charts");
  const [focus, setFocus] = useState<Row | null>(null);
  const [view, setView] = useState<"both" | "input" | "output" | "backtest">("both");
  const [detail, setDetail] = useState<DetailKey>(result?.events.length ? "events" : "rows");
  const [detailPage, setDetailPage] = useState<{ rows: Row[]; total: number; offset: number }>();
  const [raw, setRaw] = useState<RawPage>();
  const [origin, setOrigin] = useState(version);
  const [selected, setSelected] = useState<number>();
  const [recordBusy, setRecordBusy] = useState(false);
  const datasetPath = "/datasets/" + dataset.id;
  const path = "/analyses/" + result?.id;
  const detailsTotal = result ? detailPage?.total ?? (detail in result.counts
    ? result.counts[detail as keyof typeof result.counts] : result[detail].length) : 0;
  const count = detailPage?.offset ?? 0;

  async function loadDetails(kind: DetailKey, offset = 0) {
    if (!result) return;
    setDetail(kind); setDetailPage(undefined);
    if (!offset) return;
    try { setDetailPage(await api(root + path + "/details/" + kind + "?offset=" + offset)); }
    catch (e) { onError((e as Error).message); }
  }
  async function loadRaw(offset = 0, source = version, row?: number, time?: string) {
    setTab("source"); setOrigin(source); setSelected(row); setRecordBusy(true);
    const query = new URLSearchParams({ version_id: source, offset: String(offset) });
    if (row !== undefined) query.set("row", String(row));
    if (time !== undefined) query.set("time", time);
    try { setRaw(await api<RawPage>(root + datasetPath + "/records?" + query.toString())); }
    catch (e) { onError((e as Error).message); }
    finally { setRecordBusy(false); }
  }
  function locate(row: Row) {
    if (detail === "issues") {
      if (typeof row.row === "number") void loadRaw(0, dataset.original_id, row.row);
      else if (typeof row.time === "string") void loadRaw(0, version, undefined, row.time);
    } else {
      setFocus(row); setView("both"); setTab("charts");
    }
  }
  function point(time: string, channel: string) {
    if (result?.snapshot) return;
    const bins = result?.heatmap?.bins ?? [];
    const next = bins[bins.indexOf(time) + 1];
    const hit = result?.issues.find((r) => r.channel === channel && typeof r.time === "string" &&
      r.time >= time && (!next || r.time < next));
    void loadRaw(0, hit ? dataset.original_id : result?.version_id ?? version,
      typeof hit?.row === "number" ? hit.row : undefined, time);
  }
  function csv(endpoint: string, filename: string) {
    void downloadCsv(root + endpoint, filename).catch((e: Error) => onError(e.message));
  }
  const showsProcessing = ["clean", "resample", "moving", "savgol", "detrend", "filter"].includes(result?.method ?? "");
  const rangeShown = result && workflow?.item.range?.every((time, index) => time === result.range[index]);
  const summary = result?.method === "forecast" ? forecastSummaryInMinutes(result.summary) : result?.summary;

  return <section className="mw-result" aria-label="分析结果">
    <div className="mw-section-title"><h2><LineChart size={17} />{result?.title ?? "分析结果"}</h2>
      {result && <button className="mw-button" disabled={blocked} onClick={report}><FileText size={15} />保存报告</button>}</div>
    {workflow && <section className="mw-workflow" aria-label={workflow.output ? "处理输出" : "分析输入"}>
      <div className="mw-workflow-heading">
        <Database size={17} aria-hidden="true" />
        <div><h3>{workflow.output ? "处理输出" : "分析输入"} · {workflow.item.label}</h3>
          {workflow.item.range && <small>{workflow.item.range.map(prettyTime).join(" ～ ")}</small>}</div>
        <span className={"mw-version-status" + (workflow.item.temporary ? " temporary" : "")}>
          {workflow.item.temporary ? "临时数据 · 未保存" : "已保存"}
        </span>
      </div>
      <div className="mw-workflow-actions">
        <button className="mw-button primary" disabled={blocked} onClick={workflow.use}>继续分析<ArrowRight size={15} /></button>
        {workflow.scan && <button className="mw-button" disabled={blocked} onClick={workflow.scan}>扫描新版本</button>}
        {workflow.item.temporary && <button className="mw-button" disabled={blocked} onClick={workflow.save}>
          <Save size={15} />保存为数据版本</button>}
        <button className="mw-button" disabled={blocked} onClick={workflow.download}><ArrowDownToLine size={15} />下载数据 CSV</button>
        {workflow.item.temporary && <button className="mw-link" disabled={blocked} onClick={workflow.discard}>放弃临时结果</button>}
      </div>
    </section>}
    {result?.snapshot && <p className="mw-snapshot">报告快照 · 可查看图表、明细和分析依据</p>}
    <div className="mw-result-tabs" aria-label="结果视图">
      {[["charts", "图表"], ["details", "分析明细"], ["source", "数据记录"], ["basis", "分析依据"]].map(([k, label]) =>
        <button key={k} className={tab === k ? "active" : ""} disabled={(!result && (k === "details" || k === "basis")) || (result?.snapshot && k === "source")}
          onClick={() => k === "source" ? void loadRaw() : setTab(k)}>{label}</button>)}</div>
    <div className="mw-result-body">
      {tab === "charts" && (!result ? <div className="mw-inset-empty"><LineChart size={31} />
        <h3>选择一个分析任务</h3><p>在这里查看曲线、分析明细和计算依据。</p>
        <button className="mw-button" disabled={blocked} onClick={trend}><LineChart size={16} />查看测点曲线</button></div> : <>
        <div className="mw-chart-toolbar">
          <div className="mw-summary"><p>{summary}</p>
            {!rangeShown && <small>{prettyTime(result.range[0])} ～ {prettyTime(result.range[1])}</small>}</div>
          <div className="mw-result-actions">
            {showsProcessing && <label className="mw-field horizontal">曲线<select value={view}
              onChange={(e) => setView(e.target.value as typeof view)}><option value="both">处理前后对照</option>
              <option value="input">输入曲线</option><option value="output">处理结果</option></select></label>}
            {!!result.backtest.length && <label className="mw-field horizontal">视图<select value={view}
              onChange={(e) => setView(e.target.value as typeof view)}><option value="both">未来预测</option>
              <option value="backtest">历史回测</option></select></label>}
            <button className="mw-button" onClick={() => csv(path + "/csv", "分析结果.csv")}><ArrowDownToLine size={15} />结果 CSV</button>
          </div>
        </div>
        <ResultCharts result={result} focus={focus} resultView={view} onQualityPoint={point} />
        {result.events.length > 0 && <div className="mw-event-strip"><h3>{result.counts.events} 个事件</h3>
          {result.events.slice(0, 5).map((r, i) => <button key={i} className={focus === r ? "active" : ""}
            onClick={() => setFocus(focus === r ? null : r)}><span>{show(r.测点)} · {show(r.开始)}</span><small>{show(r.触发依据)}</small></button>)}
          <button className="mw-link" onClick={() => { void loadDetails("events"); setTab("details"); }}>查看全部事件</button></div>}
      </>)}
      {tab === "details" && result && <>
        <div className="mw-result-actions"><label className="mw-field horizontal">明细类别<select value={detail}
          onChange={(e) => void loadDetails(e.target.value as DetailKey)}>
          {(Object.keys(detailNames) as DetailKey[]).filter((key) => key === "rows" || result[key].length > 0)
            .map((key) => <option key={key} value={key}>{detailNames[key]}</option>)}</select></label>
          <button className="mw-button" onClick={() => csv(path + "/csv?kind=" + detail, detailNames[detail] + ".csv")}>
            <ArrowDownToLine size={15} />导出此类明细</button></div>
        <Table rows={(detailPage?.rows ?? result[detail]).map(analysisRowInMinutes)}
          locate={!result.snapshot && (detail === "events" || detail === "issues") ? locate : undefined} />
        <Pager total={detailsTotal} offset={count} move={(next) => void loadDetails(detail, next)} />
      </>}
      {tab === "source" && <>
        <div className="mw-result-actions"><a className="mw-button" href={base + datasetPath + "/original"}><ArrowDownToLine size={15} />原始文件</a>
          <button className="mw-button" onClick={() => csv(datasetPath + "/versions/" + origin + "/csv", "数据记录.csv")}>
            <ArrowDownToLine size={15} />所示版本 CSV</button>
          {origin !== version && <button className="mw-button" disabled={recordBusy} onClick={() => void loadRaw()}>回到当前版本</button>}</div>
        {recordBusy && <p className="mw-help" role="status">正在读取数据记录…</p>}
        {raw?.issue && <div className="mw-summary">原表第 {show(raw.issue.row)} 行 · {show(raw.issue.kind)} · {show(raw.issue.value)}</div>}
        {raw && <><Table rows={raw.rows.map((row) => Object.fromEntries(raw.columns.map((c, i) => [c, row[i]])))}
          selected={selected ?? raw.selected_row ?? undefined} />
          <Pager total={raw.total} offset={raw.offset} move={(offset) => void loadRaw(offset, origin)} /></>}
      </>}
      {tab === "basis" && result && <div className="mw-basis">
        <p>{summary}</p>{result.notes.map((note) => <p key={note}>{note}</p>)}
        <details open><summary>方法与参数</summary><dl>
          <dt>方法</dt><dd>{result.title}</dd><dt>数据版本</dt><dd>{result.version_id}</dd>
          {Object.entries(result.parameters).filter(([key]) =>
            ["channels", "start", "end", ...(methodParameters[result.method] ?? [])].includes(key))
            .map(([key, value]) => <Parameter key={key} name={key} value={value} />)}
        </dl></details>
        <details><summary>处理步骤（{result.steps.length}）</summary>
          {result.steps.length ? <ol>{result.steps.map((step, i) => <li key={i}>{step.label}<dl>
            {Object.entries(step.parameters).filter(([key]) => ["channels", ...(methodParameters[step.method] ?? [])].includes(key))
              .map(([key, value]) => <Parameter key={key} name={key} value={value} />)}
          </dl></li>)}</ol> : <p>本次计算直接使用所选数据。</p>}
        </details>
        {!!citations.length && <details open><summary>引用资料</summary>{citations.map((c) =>
          <article key={c.id}><h3>{c.title} · {c.section}</h3><p>{c.text}</p><p>{c.source}</p></article>)}</details>}
      </div>}
    </div>
  </section>;
}

function Parameter({ name, value }: { name: string; value: unknown }) {
  const options: Record<string, string> = { keep: "保留", first: "首条", mean: "取均值", mark: "仅标记", exclude: "置为空值" };
  let formatted: string;
  if (Array.isArray(value)) formatted = value.join("、");
  else if (name === "rule" && value) {
    const r = value as Rule;
    formatted = [r.channel, "上下限 " + show(r.lower) + " ~ " + show(r.upper) + " " + r.unit,
      "变化速率 " + show(r.rate === null ? null : toSeconds(r.rate)) + " " + r.unit + "/分钟",
      "持续 " + show(toMinutes(r.duration)) + " 分钟", "依据 " + r.source].join(" · ");
  } else if (typeof value === "number" && isDurationParameter(name)) {
    formatted = show(toMinutes(value));
  } else formatted = options[String(value)] ?? show(value as string | number | null);
  return <><dt>{parameterNames[name] ?? name}</dt><dd>{formatted}</dd></>;
}

