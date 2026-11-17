import { api } from "./api";

const sessionKey = "mw-workspace-session";
const stateKey = "mw-workspace-state";

type WorkspaceState = {
  dataset: string;
  version: string;
  result?: string;
  channels: string[];
  start: string;
  end: string;
};

let session: string | undefined;

function requestOptions(init?: RequestInit): RequestInit {
  if (!session) {
    session = sessionStorage.getItem(sessionKey) ?? crypto.randomUUID().replaceAll("-", "");
    sessionStorage.setItem(sessionKey, session);
  }
  const headers = new Headers(init?.headers);
  headers.set("X-Workbench-Session", session);
  return { ...init, headers };
}

export function readWorkspace(): WorkspaceState | undefined {
  try {
    const value = sessionStorage.getItem(stateKey);
    return value ? JSON.parse(value) : undefined;
  } catch {
    return undefined;
  }
}

export function storeWorkspace(state?: WorkspaceState) {
  if (state) sessionStorage.setItem(stateKey, JSON.stringify(state));
  else sessionStorage.removeItem(stateKey);
}

export function monitorApi<T>(path: string, init?: RequestInit): Promise<T> {
  return api<T>(path, requestOptions(init));
}

export function monitorFetch(path: string, init?: RequestInit) {
  return fetch("/api" + path, requestOptions(init));
}

export async function downloadCsv(path: string, filename: string, signal?: AbortSignal) {
  const response = await monitorFetch(path, { signal });
  if (!response.ok) {
    const detail = await response.json().catch(() => undefined);
    throw new Error(typeof detail?.detail === "string" ? detail.detail : "无法下载数据 CSV");
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
