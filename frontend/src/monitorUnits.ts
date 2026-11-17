import { show, type Row } from "./monitorTypes";

const secondsPerMinute = 60;

export function toMinutes(seconds: number) {
  return seconds / secondsPerMinute;
}

export function toSeconds(minutes: number) {
  return minutes * secondsPerMinute;
}

export function minuteInput(value?: string) {
  return value?.replace(" ", "T").slice(0, 16) ?? "";
}

export function minuteBoundary(value: string, end = false) {
  return value ? minuteInput(value) + (end ? ":59.999" : ":00") : "";
}

export function isDurationParameter(key: string) {
  return key === "fill_seconds" || key === "interval_seconds" || key === "period_seconds";
}

const durationColumns: Record<string, string> = {
  常见间隔秒: "常见间隔（分钟）",
  持续秒数: "持续时长（分钟）",
  时滞秒: "时滞（分钟）",
  周期秒: "周期（分钟）",
  对应周期秒: "对应周期（分钟）",
};

export function analysisRowInMinutes(row: Row): Row {
  return Object.fromEntries(Object.entries(row).map(([key, value]) => {
    const label = durationColumns[key];
    return label ? [label, typeof value === "number" ? toMinutes(value) : value] : [key, value];
  }));
}

export function forecastSummaryInMinutes(summary: string) {
  return summary.replace(/(预测 \d+ 步（)([\d.e+-]+) (天|小时|分钟|秒)）/u,
    (original, prefix: string, amount: string, unit: "天" | "小时" | "分钟" | "秒") => {
      const minutes = Number(amount) * { 天: 1440, 小时: 60, 分钟: 1, 秒: 1 / 60 }[unit];
      return Number.isFinite(minutes) ? prefix + show(minutes) + " 分钟）" : original;
    });
}
