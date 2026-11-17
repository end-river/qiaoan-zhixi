import { useMemo, useState } from "react";
import type { ECharts } from "echarts/core";
import { Download } from "lucide-react";
import { Chart } from "./Chart";
import { toMinutes, toSeconds } from "./monitorUnits";
import { prettyTime, show, type Result, type Row, type Series } from "./monitorTypes";

const palette = ["#244f87", "#087d74", "#a56a23", "#79539b", "#51687d", "#a34f55"];
const zoom = [{ type: "inside", filterMode: "none" }, { type: "slider", height: 15, bottom: 8, filterMode: "none", brushSelect: true }];
const axisColor = "#617187";
const gridLine = { lineStyle: { color: "#e7edf5" } };

function Figure({ title, option, group, height = 285, onClick }: {
  title: string; option: Record<string, unknown>; group?: string; height?: number; onClick?: (index: number) => void;
}) {
  const [instance, setInstance] = useState<ECharts>();
  return <section className="mw-figure">
    <div className="mw-figure-title">
      <h3>{title}</h3>
      <button type="button" className="mw-icon" title="下载图表 PNG" aria-label={"下载 " + title + " PNG"}
        onClick={() => {
          if (!instance || instance.isDisposed()) return;
          const a = document.createElement("a");
          a.href = instance.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#fff" });
          a.download = title.replace(/[\\/:*?"<>|]/g, "-") + ".png";
          a.click();
        }}><Download size={15} /></button>
    </div>
    <Chart option={option} height={height} label={title} group={group} onReady={setInstance} onClick={onClick} />
  </section>;
}

export function ResultCharts({ result, focus, onQualityPoint, resultView }: {
  result: Result; focus: Row | null; onQualityPoint: (time: string, channel: string) => void;
  resultView: "both" | "input" | "output" | "backtest";
}) {
  const groups = useMemo(() => {
    const map = new Map<string, Series[]>();
    for (const source of result.series) {
      let item = source;
      if (source.kind === "lag") {
        item = { ...source, points: source.points.map(([x, y]) => [toMinutes(Number(x)), y]) };
      } else if (result.method === "change" && source.name.endsWith(" · 变化速率") && source.unit.endsWith("/s")) {
        const unit = source.unit.slice(0, -2) + "/分钟";
        item = { ...source, unit, group: source.group === source.unit ? unit : source.group,
          points: source.points.map(([x, y]) => [x, y === null ? null : toSeconds(y)]) };
      }
      if (resultView === "input" && item.style !== "reference") continue;
      if (resultView === "output" && item.style === "reference") continue;
      const key = item.kind + ":" + item.group;
      map.set(key, [...(map.get(key) ?? []), item]);
    }
    if (resultView === "backtest" && result.backtest.length) {
      const unit = result.series[0]?.unit ?? "";
      map.clear();
      map.set("time:回测", ["实测", "回测预测"].map((name) => ({
        name, unit, group: "历史回测", kind: "time", style: name === "实测" ? "line" : "forecast",
        points: result.backtest.map((row) => [String(row.时间), Number(row[name])]),
      })));
    }
    return [...map.values()];
  }, [result, resultView]);
  return <div className="mw-figures">
    {result.heatmap && <Heat result={result} onQualityPoint={onQualityPoint} />}
    {groups.map((group) => <Signal key={group[0].kind + group[0].group} result={result} lines={group}
      focus={resultView === "backtest" ? null : focus} backtest={resultView === "backtest"} />)}
  </div>;
}

function Heat({ result, onQualityPoint }: { result: Result; onQualityPoint: (time: string, channel: string) => void }) {
  const heat = result.heatmap!;
  const max = heat.correlation ? 1 : heat.cells.reduce((m, c) => Math.max(m, c[2]), 1);
  const option = {
    animation: false, grid: { left: 20, right: 20, top: 15, bottom: 60, containLabel: true },
    tooltip: { confine: true, formatter: (e: { dataIndex: number }) => {
      const [i, j, value] = heat.cells[e.dataIndex];
      return [heat.channels[j], prettyTime(heat.bins[i]), show(value)].join("\n");
    }, renderMode: "richText" },
    xAxis: { type: "category", data: heat.bins.map(prettyTime), axisLabel: { color: axisColor, rotate: 28, width: 90, overflow: "truncate" } },
    yAxis: { type: "category", data: heat.channels, axisLabel: { color: axisColor, width: 106, overflow: "truncate" } },
    visualMap: { min: heat.correlation ? -1 : 0, max, orient: "horizontal", bottom: 4, left: "center",
      inRange: { color: heat.correlation ? ["#9e5d33", "#f4f7fb", "#3269b2"] : ["#ecf4fe", "#3269b2"] } },
    series: [{ type: "heatmap", data: heat.cells, itemStyle: { borderWidth: 1, borderColor: "#fff" } }],
  };
  return <Figure title={heat.correlation ? "测点相关系数" : "数据质量 · 测点 × 时间区间"} option={option}
    height={Math.max(235, Math.min(570, 135 + heat.channels.length * 19))}
    onClick={(idx) => {
      const cell = heat.cells[idx];
      if (cell && !heat.correlation) onQualityPoint(heat.bins[cell[0]], heat.channels[cell[1]]);
    }} />;
}

function Signal({ lines, result, focus, backtest }: { lines: Series[]; result: Result; focus: Row | null; backtest: boolean }) {
  const primary = lines[0];
  const time = primary.kind === "time";
  const lower = lines.find((s) => s.style === "lower");
  const upper = lines.find((s) => s.style === "upper");
  // ECharts stacks positive and negative series separately by default. "all"
  // makes the upper area start exactly at the signed lower bound.
  const bounds = lower && upper ? [
    { type: "line", data: lower.points, stack: "interval", stackStrategy: "all", lineStyle: { opacity: 0 }, showSymbol: false, silent: true, tooltip: { show: false } },
    { type: "line", name: "95% 预测区间", stack: "interval", stackStrategy: "all", showSymbol: false, silent: true,
      lineStyle: { opacity: 0 }, areaStyle: { color: "#d5e5f9", opacity: .78 }, tooltip: { show: false },
      data: upper.points.map(([t, y], i) => [t, (y ?? 0) - (lower.points[i][1] ?? 0)]) },
  ] : [];
  const target = typeof focus?.开始 === "string" ? focus : null;
  const at = target ? new Date(String(target.开始)).getTime() : NaN;
  const until = target ? new Date(String(target.结束)).getTime() : NaN;
  const dates = time ? lines.flatMap((s) => s.points.length ? [s.points[0][0], s.points[s.points.length - 1][0]] : [])
    .map((t) => new Date(String(t)).getTime()) : [];
  const span = dates.length ? Math.max(...dates) - Math.min(...dates) : 0;
  const pad = span * .04;
  const forecastRange = lower && lower.points.length ? [
    new Date(String(lower.points[0][0])).getTime(), new Date(String(lower.points[lower.points.length - 1][0])).getTime(),
  ] : null;
  const matchUnit = (l: { unit: string }) => l.unit === primary.unit;
  const option = {
    color: palette, animation: false,
    grid: { left: 18, right: 23, top: 43, bottom: 55, containLabel: true },
    tooltip: { trigger: "axis", confine: true, renderMode: "richText" },
    legend: { type: "scroll", top: 0, left: 8, right: 8, textStyle: { color: axisColor },
      data: lines.filter((s) => !["upper", "lower"].includes(s.style)).map((s) => s.name) },
    xAxis: { type: time ? "time" : "value", name: time ? "" : primary.kind === "frequency" ? "Hz" : "分钟",
      nameLocation: "middle", nameGap: 29, axisLabel: { color: axisColor }, splitLine: gridLine },
    yAxis: { type: "value", scale: true, name: primary.unit, axisLabel: { color: axisColor }, splitLine: gridLine },
    dataZoom: zoom.map((item) => ({ ...item,
      ...(time && span && Number.isFinite(at) ? { startValue: Math.max(Math.min(...dates), at - pad),
        endValue: Math.min(Math.max(...dates), until + pad) } : forecastRange && span
        ? { startValue: Math.max(Math.min(...dates), forecastRange[0] - Math.max(span * .1, (forecastRange[1] - forecastRange[0]) * 4)),
          endValue: Math.max(...dates) } : {}),
    })),
    series: [...bounds, ...lines.filter((s) => !["upper", "lower"].includes(s.style)).map((s, i) => {
      const eventAreas = time && !backtest ? result.events.filter((e) => lines.some((l) => l.name === e.测点))
        .filter((e) => e.开始 !== e.结束)
        .map((e) => [{ xAxis: e.开始 }, { xAxis: e.结束 }]) : [];
      const eventMarkers = time && !backtest ? result.events.filter((e) => e.开始 === e.结束 &&
        lines.some((l) => l.name === e.测点)).map((e) => ({ xAxis: e.开始, name: e.触发依据 })) : [];
      return {
        name: s.name, type: "line", showSymbol: s.points.length < 2, connectNulls: false,
        data: s.style === "forecast" && !backtest && primary.points.length
          ? [primary.points[primary.points.length - 1], ...s.points] : s.points,
        ...(s.style === "reference" ? { itemStyle: { color: "#8795a5" }, lineStyle: { type: "dashed", width: 1.2 } }
          : s.style === "forecast" ? { lineStyle: { type: "dashed", width: 2 } } : { lineStyle: { width: 1.6 } }),
        ...(i === 0 ? {
          markLine: { symbol: "none", lineStyle: { color: "#986629", type: "dashed" }, label: { position: "insideEndTop" },
            data: [...(backtest ? [] : result.limits.filter(matchUnit).map((l) => ({ name: l.name, yAxis: l.value }))), ...eventMarkers] },
          markArea: { silent: true, itemStyle: { color: "#f4d9b3", opacity: .54 }, data: eventAreas },
        } : {}),
      };
    })],
  };
  const title = bounds.length ? primary.group + " · 实测、预测与 95% 预测区间"
    : primary.group === primary.unit ? (primary.kind === "frequency" ? "频谱" : primary.kind === "lag" ? "互相关" : "时序") + " · " + primary.unit
    : primary.group;
  return <Figure title={title} option={option} group={time ? result.id + "-time" : undefined} />;
}

