export type Channel = { name: string; type: string; unit: string };
export type Dataset = {
  id: string; name: string; sheet: string | null; source: string; simulation: boolean;
  channels: Channel[]; original_id: string; start: string; end: string;
  samples: number; interval: number | null; regular: boolean; invalid_times: number;
};
export type Rule = {
  channel: string; unit: string; upper: number | null; lower: number | null;
  rate: number | null; duration: number; source: string;
};
export type Params = {
  channels?: string[]; start?: string; end?: string; start_b?: string; end_b?: string;
  window?: number; interval_seconds?: number; period_seconds?: number; cutoff_hz?: number;
  duplicate?: string; outliers?: string; fill_seconds?: number; coefficient?: string;
  max_lag?: number; threshold?: number; steps?: number; rule?: Rule;
};
export type Step = { method: string; label: string; parameters: Params };
export type Version = {
  id: string; label: string; parent_id: string | null; steps: Step[];
  temporary?: boolean; range?: [string, string];
};
export type Recipe = { id: string; name: string; steps: Step[]; channels: Channel[] };
export type Cell = string | number | null;
export type Row = Record<string, Cell>;
export type DetailKey = "rows" | "issues" | "events" | "backtest" | "forecast";
export type Series = {
  name: string; unit: string; group: string; kind: "time" | "lag" | "frequency";
  style: string; points: [string | number, number | null][];
};
export type ResultMeta = {
  id: string; dataset_id: string; version_id: string; created_version_id: string | null;
  method: string; title: string; summary: string; range: [string, string];
  parameters: Params; steps: Step[]; notes: string[];
  temporary?: boolean; snapshot?: boolean;
};
export type Result = ResultMeta & Record<DetailKey, Row[]> & {
  counts: Record<"rows" | "issues" | "events", number>;
  series: Series[];
  heatmap: { bins: string[]; channels: string[]; cells: [number, number, number][]; correlation?: boolean } | null;
  limits: { name: string; value: number; unit: string }[];
};
export type Citation = { id: string; title: string; source: string; text: string; section: string };
export type ObservationInterval = {
  start: string; end: string; interval_seconds: number; duration_seconds: number; samples: number;
};
export type ScanResult = {
  total_candidates: number;
  intervals: ObservationInterval[];
  diagnostics: {
    scanned_rows: number; missing_rows: number; duplicate_rows: number; cadence_breaks: number; longest_samples: number;
    reasons: string[]; requires_original: boolean;
  };
};
export type ObservationScanAction = {
  version_id: string; method: string; parameters: Params; result: ScanResult | null;
};
export type Tool = {
  name: string; status: string;
  result?: {
    error?: string; analysis_id?: string; unavailable?: boolean; deleted?: boolean;
    observation_scan?: ObservationScanAction;
  };
};
export type Turn = { question: string; answer: string; status: string; tools: Tool[]; citations: Citation[] };
export type Conversation = { id: string; version_id: string; context: Params; turns: Turn[] };
export type Report = { id: string; title: string; analysis_id: string; conclusion: string; citations: Citation[] };
export type Preview = { columns: string[]; time_column: string; rows: (string | null)[][] };
export type Upload = { token: string; name: string; sheets: string[] };
export type RawPage = { columns: string[]; rows: Cell[][]; total: number; offset: number; issue?: Row; selected_row?: number | null };
export const prettyTime = (value: string) => value.replace("T", " ").replace(/\.000$/, "");
export const show = (value: Cell | undefined) =>
  value === null || value === undefined || value === "" ? "—"
  : typeof value === "number" ? new Intl.NumberFormat("zh-CN", { maximumSignificantDigits: 7 }).format(value)
  : prettyTime(value);

