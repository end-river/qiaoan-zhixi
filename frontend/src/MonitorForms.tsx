import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { FileSpreadsheet, UploadCloud, X } from "lucide-react";
import { api, post } from "./api";
import { isDurationParameter, minuteBoundary, minuteInput, toMinutes, toSeconds } from "./monitorUnits";
import { show, type Channel, type Dataset, type Params, type Preview, type Recipe, type Rule, type Upload } from "./monitorTypes";

export const root = "/v2";
const types = ["挠度", "应变", "位移", "温度", "倾角", "其他"];
const defaultUnits: Record<string, string> = { "挠度": "mm", "位移": "mm", "温度": "°C", "倾角": "°", "应变": "με" };

export function Dialog({ title, children, close, wide = false }: {
  title: string; children: ReactNode; close: () => void; wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement;
    dialog?.showModal();
    return () => {
      dialog?.close();
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);
  return <dialog ref={ref} className={wide ? "mw-dialog wide" : "mw-dialog"}
    aria-labelledby="mw-dialog-title" onCancel={(e) => { e.preventDefault(); close(); }}>
    <div className="mw-dialog-heading"><h2 id="mw-dialog-title">{title}</h2>
      <button title="关闭" aria-label="关闭" className="mw-icon" onClick={close}><X size={19} /></button></div>
    <div className="mw-dialog-body">{children}</div>
  </dialog>;
}

function channelGuess(name: string): Channel {
  const match = types.find((item) => name.includes(item)) ?? "其他";
  const unit = name.match(/[(（](mm|cm|m|µε|με|°C|℃|°|Hz)[)）]/)?.[1] ?? defaultUnits[match] ?? "";
  return { name, type: match, unit };
}

export function ImportDialog({ close, onImport }: { close: () => void; onImport: (data: Dataset) => void }) {
  const [upload, setUpload] = useState<Upload>();
  const [sheet, setSheet] = useState("");
  const [preview, setPreview] = useState<Preview>();
  const [time, setTime] = useState("");
  const [channels, setChannels] = useState<Channel[]>([]);
  const [excluded, setExcluded] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!upload || (upload.sheets.length && !sheet)) return;
    const abort = new AbortController();
    const path = root + "/uploads/" + upload.token + (sheet ? "?sheet=" + encodeURIComponent(sheet) : "");
    setPreview(undefined);
    setBusy(true);
    setError("");
    api<Preview>(path, { signal: abort.signal }).then((data) => {
      setPreview(data);
      setTime(data.time_column);
      setChannels(data.columns.map(channelGuess));
      setExcluded(data.columns.filter((name, index) => name !== data.time_column &&
        !data.rows.some((row) => row[index]?.trim() && Number.isFinite(Number(row[index])))));
    }).catch((err: Error) => { if (!abort.signal.aborted) setError(err.message); })
      .finally(() => { if (!abort.signal.aborted) setBusy(false); });
    return () => abort.abort();
  }, [upload, sheet]);

  async function read(file?: File) {
    if (!file) return;
    if (!/\.(csv|xlsx)$/i.test(file.name)) {
      setError("请选择 .csv 或 .xlsx 文件。旧版 .xls 请先另存为 .xlsx。");
      return;
    }
    if (!file.size || file.size > 20 * 1024 * 1024) {
      setError("请选择不超过 20 MB 的非空文件。");
      return;
    }
    setBusy(true);
    setError("");
    setPreview(undefined);
    setUpload(undefined);
    try {
      const form = new FormData();
      form.append("file", file);
      const item = await api<Upload>(root + "/uploads", { method: "POST", body: form });
      setSheet(item.sheets[0] ?? "");
      setUpload(item);
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  const active = channels.filter((c) => c.name !== time && !excluded.includes(c.name));
  async function confirm(e: FormEvent) {
    e.preventDefault();
    if (!upload || busy || !active.length) return;
    setBusy(true);
    setError("");
    try {
      const dataset = await api<Dataset>(root + "/uploads/" + upload.token + "/confirm",
        post({ sheet: sheet || null, time_column: time, channels: active }));
      onImport(dataset);
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  return <Dialog title="导入监测数据" close={close} wide>
    <input ref={input} type="file" accept=".csv,.xlsx,.xls" hidden
      onChange={(e) => { void read(e.target.files?.[0]); e.target.value = ""; }} />
    <button type="button" className="mw-drop" disabled={busy}
      onClick={() => input.current?.click()} onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); if (!busy) void read(e.dataTransfer.files[0]); }}>
      {upload ? <FileSpreadsheet size={25} /> : <UploadCloud size={28} />}
      <strong>{upload ? upload.name : "点此选择或拖入文件"}</strong>
      <span>{upload ? "点击更换文件" : "CSV、XLSX · 单文件 20 MB · 第一行为列名"}</span>
    </button>
    <p className="mw-help">第 1 行填写唯一列名，下面每行是一次观测。时间示例 2025-10-01 09:00:00.001，测点列填数值，缺测可留空。</p>
    <a className="mw-link" href={"/api" + root + "/import-template.csv"}>下载 CSV 模板</a>
    {upload?.sheets.length ? <label className="mw-field">工作表<select value={sheet}
      onChange={(e) => setSheet(e.target.value)}>{upload.sheets.map((name) => <option key={name}>{name}</option>)}</select></label> : null}
    {busy && <p className="mw-help" role="status">正在读取或导入表格…</p>}
    {error && <p className="mw-error" role="alert">{error}</p>}
    {preview && <form onSubmit={(e) => void confirm(e)}>
      <h3>确认列和单位</h3>
      <p className="mw-help">请选择一列日期时间，其余每列对应一个测点。时间保留到毫秒。</p>
      <label className="mw-field">时间列<select value={time} onChange={(e) => setTime(e.target.value)}>
        {preview.columns.map((name) => <option key={name}>{name}</option>)}</select></label>
      <div className="mw-map">
        {channels.filter((c) => c.name !== time).map((col) => {
          const checked = !excluded.includes(col.name);
          const edit = (patch: Partial<Channel>) => setChannels((items) => items.map((c) => c.name === col.name ? { ...c, ...patch } : c));
          return <div className="mw-map-row" key={col.name}>
            <label className="mw-check"><input type="checkbox" checked={checked} onChange={() =>
              setExcluded((items) => checked ? [...items, col.name] : items.filter((x) => x !== col.name))} />{col.name}</label>
            <select aria-label={col.name + "类型"} value={col.type} disabled={!checked} onChange={(e) =>
              edit({ type: e.target.value, unit: defaultUnits[e.target.value] ?? "" })}>
              {types.map((type) => <option key={type}>{type}</option>)}</select>
            <input aria-label={col.name + "单位"} placeholder="单位" maxLength={30} value={col.unit} disabled={!checked}
              onChange={(e) => edit({ unit: e.target.value })} />
          </div>;
        })}
      </div>
      <div className="mw-tablewrap"><table><thead><tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>{preview.rows.slice(0, 6).map((row, i) => <tr key={i}>{row.map((v, j) => <td key={j}>{show(v)}</td>)}</tr>)}</tbody></table></div>
      <div className="mw-dialog-actions"><span className="mw-help">已选择 {active.length} 个测点（需选择 1–32 个）</span>
        <button className="mw-button primary" disabled={busy || !active.length || active.length > 32}>确认导入</button></div>
    </form>}
  </Dialog>;
}

type Input = { key: keyof Params; label: string; value?: string; min?: number; max?: number; required?: boolean };
const fields: Record<string, Input[]> = {
  compare: [{ key: "start_b", label: "对比时段开始", required: true }, { key: "end_b", label: "对比时段结束", required: true }],
  change: [],
  rolling: [{ key: "window", label: "窗口（采样点）", value: "12", min: 3, max: 1001 }],
  lag: [{ key: "max_lag", label: "最大滞后（采样点）", value: "24", min: 1, max: 250 }],
  clean: [{ key: "fill_seconds", label: "允许填补的最大间隔（分钟）", value: "0", min: 0 }],
  resample: [{ key: "interval_seconds", label: "重采样间隔（分钟）", min: 1, required: true },
    { key: "fill_seconds", label: "允许填补的最大间隔（分钟）", value: "0", min: 0 }],
  moving: [{ key: "window", label: "窗口（采样点）", value: "9", min: 3, max: 1001 }],
  savgol: [{ key: "window", label: "窗口（奇数采样点）", value: "9", min: 3, max: 1001 }],
  filter: [{ key: "cutoff_hz", label: "截止频率（Hz）", min: .0000000001, required: true }],
  stl: [{ key: "period_seconds", label: "周期（分钟，例如一天 1440）", min: 1, required: true }],
  anomaly: [{ key: "window", label: "参考窗口（采样点）", value: "12", min: 3, max: 1001 },
    { key: "threshold", label: "偏离倍数", value: "4", min: .1, max: 50 }],
  forecast: [{ key: "steps", label: "预测步数（留空自动）", min: 1, max: 24 }],
};

export const labels: Record<string, string> = {
  quality: "数据质量检查", trend: "趋势与描述统计", compare: "两个时段对比",
  change: "变化量与变化速率", rolling: "滚动统计", correlation: "测点相关",
  lag: "互相关时滞", clean: "清洗与插值", resample: "重采样",
  moving: "移动平均", savgol: "Savitzky–Golay 平滑", detrend: "线性去趋势",
  filter: "Butterworth 低通", fft: "FFT 幅度谱", welch: "Welch 功率谱",
  stl: "STL 趋势与周期分解", anomaly: "异常事件识别", forecast: "短期趋势预测", limits: "超限检查",
};
export const primaryMethods = ["quality", "trend", "anomaly", "forecast", "limits"];

function rateInput(rate: number | null) {
  return rate === null ? "" : String(Number(toSeconds(rate).toPrecision(12)));
}

export function ToolDialog({ method, dataset, selected, rules, initial, initialSave, close, onRun }: {
  method: string; dataset: Dataset; selected: string[]; rules: Rule[]; close: () => void;
  initial?: Params; initialSave?: boolean;
  onRun: (params: Params, saveRule: boolean) => void;
}) {
  const [params, setParams] = useState<Params>(() => {
    const defaults = Object.fromEntries((fields[method] ?? []).filter((f) => f.value !== undefined)
      .map((f) => [f.key, Number(f.value)]));
    const { rule, start, end, ...rest } = initial ?? {};
    return { ...defaults, ...rest };
  });
  const [channels, setChannels] = useState(selected.length ? selected : dataset.channels.map((c) => c.name));
  const [single, setSingle] = useState(channels[0]);
  const channel = dataset.channels.find((c) => c.name === single)!;
  const [limit, setLimit] = useState(() => {
    const rule = initial?.rule;
    return rule ? { upper: String(rule.upper ?? ""), lower: String(rule.lower ?? ""),
      rate: rateInput(rule.rate), duration: String(toMinutes(rule.duration)), source: rule.source }
      : { upper: "", lower: "", rate: "", duration: "0", source: "" };
  });
  const [ruleIndex, setRuleIndex] = useState("");
  const [useRule, setUseRule] = useState(method === "limits" || !!initial?.rule);
  const [saveRule, setSaveRule] = useState(!!initialSave);
  const [error, setError] = useState("");
  const one = method === "limits" || method === "forecast";
  const priorRule = ruleIndex === "" ? initial?.rule : rules[Number(ruleIndex)];
  const reuseDuration = priorRule && limit.duration === String(toMinutes(priorRule.duration));
  const reuseRate = priorRule && limit.rate === rateInput(priorRule.rate);
  const update = (key: keyof Params, value: string | number | undefined) => setParams((p) => ({ ...p, [key]: value }));
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!one && !channels.length) return setError("请至少选一个测点");
    if (method === "lag" && channels.length !== 2) return setError("时滞分析需选择两个测点");
    let rule: Rule | undefined;
    if (useRule) {
      const num = (key: "upper" | "lower" | "rate") => limit[key] === "" ? null : Number(limit[key]);
      if (![limit.upper, limit.lower, limit.rate].some(Boolean)) return setError("请至少填写一项规则条件");
      const rate = num("rate");
      if (rate !== null && rate <= 0) return setError("变化速率上限须大于 0");
      rule = { channel: single, unit: channel.unit, upper: num("upper"), lower: num("lower"),
        rate: reuseRate ? priorRule.rate : rate === null ? null : toMinutes(rate),
        duration: reuseDuration ? priorRule.duration : toSeconds(Number(limit.duration || "0")),
        source: limit.source.trim() };
    }
    onRun({ ...params, channels: one ? [single] : channels, ...(rule ? { rule } : {}) }, saveRule && !!rule);
  }
  return <Dialog title={labels[method] ?? method} close={close}><form onSubmit={submit}>
    {one ? <label className="mw-field">测点<select value={single} onChange={(e) => {
      setSingle(e.target.value);
      setRuleIndex("");
    }}>{dataset.channels.map((c) => <option key={c.name}>{c.name}</option>)}</select></label>
      : <fieldset className="mw-fieldset"><legend>测点</legend><div className="mw-channel-list">
        {dataset.channels.map((c) => <label key={c.name} className="mw-check"><input type="checkbox"
          checked={channels.includes(c.name)} onChange={() => setChannels((arr) => arr.includes(c.name)
            ? arr.filter((name) => name !== c.name) : [...arr, c.name])} />{c.name}</label>)}
      </div></fieldset>}
    {(fields[method] ?? []).map((f) => {
      const current = params[f.key] as string | number | undefined;
      if (f.key === "start_b" || f.key === "end_b") {
        return <label className="mw-field" key={f.key}>{f.label}
          <input type="datetime-local" step="60" required={f.required} value={minuteInput(current as string | undefined)}
            onChange={(e) => update(f.key, minuteBoundary(e.target.value, f.key === "end_b") || undefined)} />
        </label>;
      }
      const duration = isDurationParameter(f.key);
      const integer = duration || f.key === "window" || f.key === "steps" || f.key === "max_lag";
      return <label className="mw-field" key={f.key}>{f.label}
        <input type="number" min={f.min} max={f.max} step={integer ? 1 : "any"} required={f.required}
          value={duration && typeof current === "number" ? toMinutes(current) : current ?? ""}
          onChange={(e) => {
            const number = e.target.valueAsNumber;
            update(f.key, Number.isNaN(number) ? undefined : duration ? toSeconds(number) : number);
          }} />
      </label>;
    })}
    {method === "clean" && <>
      <label className="mw-field">重复时间<select value={params.duplicate ?? "keep"} onChange={(e) => update("duplicate", e.target.value)}>
        <option value="keep">保持原样</option><option value="first">保留首条</option><option value="mean">对同一时间取平均</option></select></label>
      <label className="mw-field">异常值<select value={params.outliers ?? "keep"} onChange={(e) => update("outliers", e.target.value)}>
        <option value="keep">保持原样</option><option value="mark">仅标记</option><option value="exclude">置为空值</option></select></label>
      <p className="mw-help">插值间隔设为 0 时不补值。处理后可以保存数据或继续分析。</p>
    </>}
    {method === "resample" && <p className="mw-help">每个时间箱取均值。空时间箱保留为空，可选择补短缺口。</p>}
    {method === "correlation" && <label className="mw-field">系数<select value={params.coefficient ?? "pearson"}
      onChange={(e) => update("coefficient", e.target.value)}><option value="pearson">Pearson</option><option value="spearman">Spearman</option></select></label>}
    {method === "forecast" && <>
      <p className="mw-help">使用原始版本连续等间隔区段，至少 60 个有效采样点。{
        dataset.interval ? "常见采样间隔为 " + show(toMinutes(dataset.interval)) + " 分钟。" : ""}</p>
      <label className="mw-check"><input type="checkbox" checked={useRule} onChange={(e) => setUseRule(e.target.checked)} />同时检查预测值是否可能越限</label>
    </>}
    {useRule && <fieldset className="mw-fieldset"><legend>用户限值 · {channel.unit || "单位未注明"}</legend>
      {rules.some((r) => r.channel === single) && <label className="mw-field">复用已保存规则<select value={ruleIndex}
        onChange={(e) => {
          setRuleIndex(e.target.value);
          const r = e.target.value === "" ? undefined : rules[Number(e.target.value)];
          if (r) setLimit({ upper: String(r.upper ?? ""), lower: String(r.lower ?? ""), rate: rateInput(r.rate),
            duration: String(toMinutes(r.duration)), source: r.source });
        }}>
        <option value="">选择规则</option>{rules.map((r, i) => r.channel === single &&
          <option value={i} key={i}>{r.source} · {r.lower ?? "—"} ~ {r.upper ?? "—"}</option>)}
      </select></label>}
      <div className="mw-field-grid">
        {([["lower", "下限"], ["upper", "上限"], ["rate", `变化速率上限（${channel.unit || "测点单位"}/分钟）`],
          ["duration", "最短持续时间（分钟）"]] as const)
          .map(([key, title]) => <label className="mw-field" key={key}>{title}
            <input type="number" step={key === "duration" && !reuseDuration ? 1 : "any"}
              min={key === "duration" ? 0 : key === "rate" ? 0 : undefined}
              value={limit[key]} onChange={(e) => setLimit((old) => ({ ...old, [key]: e.target.value }))} /></label>)}
      </div>
      <label className="mw-field">限值来源<input required maxLength={200} value={limit.source} placeholder="例如项目监测方案中的测点限值"
        onChange={(e) => setLimit((old) => ({ ...old, source: e.target.value }))} /></label>
      <label className="mw-check"><input type="checkbox" checked={saveRule} onChange={(e) => setSaveRule(e.target.checked)} />保存此规则</label>
    </fieldset>}
    {error && <p className="mw-error" role="alert">{error}</p>}
    <div className="mw-dialog-actions"><button type="button" className="mw-button" onClick={close}>返回</button>
      <button className="mw-button primary">运行分析</button></div>
  </form></Dialog>;
}

export function RecipeDialog({ dataset, recipes, canSave, close, save, apply }: {
  dataset: Dataset; recipes: Recipe[]; canSave: boolean; close: () => void;
  save: (name: string) => void; apply: (id: string, mapping: Record<string, string>) => void;
}) {
  const [name, setName] = useState("");
  const [selected, setSelected] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const recipe = recipes.find((item) => item.id === selected);
  const fields = [...new Set(recipe?.steps.flatMap((s) => s.parameters.channels ?? []) ?? [])];
  return <Dialog title="复用处理步骤" close={close}>
    {canSave && <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) save(name.trim()); }}>
      <label className="mw-field">保存当前数据版本的处理步骤<input required maxLength={100} value={name}
        onChange={(e) => setName(e.target.value)} placeholder="例如 挠度数据小时汇总" /></label>
      <button className="mw-button">保存步骤</button></form>}
    <form onSubmit={(e) => { e.preventDefault(); if (recipe) apply(recipe.id, mapping); }}>
      <label className="mw-field">选择已有步骤<select value={selected} onChange={(e) => { setSelected(e.target.value); setMapping({}); }}>
        <option value="">请选择</option>{recipes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      {fields.map((name) => {
        const from = recipe?.channels.find((c) => c.name === name);
        return <label key={name} className="mw-field">{name}（{from?.type} · {from?.unit || "无单位"}）
          <select required value={mapping[name] ?? ""} onChange={(e) => setMapping((m) => ({ ...m, [name]: e.target.value }))}>
            <option value="">确认目标测点</option>
            {dataset.channels.filter((c) => c.type === from?.type && c.unit === from?.unit)
              .map((c) => <option key={c.name}>{c.name}</option>)}
          </select></label>;
      })}
      <div className="mw-dialog-actions"><button className="mw-button primary" disabled={!recipe}>应用到当前数据版本</button></div>
    </form>
  </Dialog>;
}

