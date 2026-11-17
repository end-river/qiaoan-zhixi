import { useEffect, useState } from "react";
import { post } from "./api";
import { monitorApi } from "./monitorApi";
import { Dialog, labels, root } from "./MonitorForms";
import { prettyTime, show, type ObservationInterval, type Params, type ScanResult } from "./monitorTypes";
import { toMinutes } from "./monitorUnits";

export function IntervalDialog({
  datasetId, versionId, versionLabel, method, parameters, initialResult, close, choose, resample, scanOriginal,
}: {
  datasetId: string; versionId: string; versionLabel: string; method?: string; parameters: Params;
  initialResult?: ScanResult;
  close: () => void;
  choose: (interval: ObservationInterval) => void;
  resample: (scope: Pick<Params, "start" | "end">) => void;
  scanOriginal: () => void;
}) {
  const [full, setFull] = useState(false);
  const [result, setResult] = useState(initialResult);
  const [error, setError] = useState("");
  const hasWindow = !!(parameters.start || parameters.end);

  useEffect(() => {
    if (!full && initialResult) {
      setResult(initialResult);
      setError("");
      return;
    }
    const controller = new AbortController();
    setResult(undefined);
    setError("");
    monitorApi<ScanResult>(root + "/datasets/" + datasetId + "/observation-intervals", {
      ...post({
        version_id: versionId,
        method,
        parameters: full ? { ...parameters, start: null, end: null } : parameters,
      }),
      signal: controller.signal,
    }).then((found) => {
      if (!controller.signal.aborted) setResult(found);
    }).catch((failure: Error) => {
      if (!controller.signal.aborted) setError(failure.message);
    });
    return () => controller.abort();
  }, [datasetId, versionId, method, parameters, full, initialResult]);

  const diagnostic = result?.diagnostics;
  return <Dialog title="扫描连续观测区间" close={close} wide>
    <div className="mw-interval-heading">
      <div><strong>{versionLabel}{method ? " · " + labels[method] : ""}</strong>
        <p className="mw-help">{parameters.channels?.join("、")}</p></div>
      {hasWindow && <label className="mw-field horizontal">扫描范围<select value={full ? "all" : "selected"}
        onChange={(event) => { setResult(undefined); setFull(event.target.value === "all"); }}>
        <option value="selected">所选时段</option><option value="all">全版本</option>
      </select></label>}
    </div>
    {hasWindow && !full && <p className="mw-help">{parameters.start ? prettyTime(parameters.start) : "数据起点"}
      {" ～ "}{parameters.end ? prettyTime(parameters.end) : "数据终点"}</p>}
    {!result && !error && <p className="mw-help" role="status">正在扫描观测区间…</p>}
    {error && <p className="mw-error" role="alert">{error}</p>}
    {result && diagnostic && <div>
      <p className="mw-help">扫描 {show(diagnostic.scanned_rows)} 行 · 最长连续段 {show(diagnostic.longest_samples)} 个样本 ·
        {" "}缺测 {show(diagnostic.missing_rows)} 行 · 重复时间 {show(diagnostic.duplicate_rows)} 行 ·
        {" "}间隔变化 {show(diagnostic.cadence_breaks)} 处</p>
      {result.intervals.length > 0 ? <>
        <p className="mw-help" role="status">找到 {show(result.total_candidates)} 个可用区间
          {result.total_candidates > result.intervals.length && `，显示样本数最多的 ${result.intervals.length} 个`}</p>
        <ul className="mw-interval-list">{result.intervals.map((item) =>
          <li key={item.start + item.end}>
            <div><strong>{prettyTime(item.start)} ～ {prettyTime(item.end)}</strong>
              <p className="mw-help">间隔 {show(toMinutes(item.interval_seconds))} 分钟 ·
                {" "}持续 {show(toMinutes(item.duration_seconds))} 分钟 · {show(item.samples)} 个样本</p></div>
            <button className="mw-button primary" onClick={() => choose(item)}>使用此区间</button>
          </li>)}</ul>
      </> : <>
        <div className="mw-summary" role="status"><strong>没有可用区间</strong>
          {diagnostic.reasons.map((reason) => <p key={reason}>{reason}</p>)}</div>
        <div className="mw-dialog-actions">
          {diagnostic.requires_original
            ? <button className="mw-button primary" onClick={scanOriginal}>扫描原始版本</button>
            : method !== "forecast" && diagnostic.scanned_rows > 0 && <button className="mw-button primary"
              onClick={() => resample(full ? {} : { start: parameters.start, end: parameters.end })}>去重采样</button>}
        </div>
      </>}
    </div>}
  </Dialog>;
}
