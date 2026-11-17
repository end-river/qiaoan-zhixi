const staleService = "当前服务缺少新版分析接口。请关闭旧的平台窗口，重新双击「启动平台.bat」，再刷新此页。";

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly code?: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const versioned = path.startsWith("/v2/");
  let response: Response;
  try {
    response = await fetch("/api" + path, init);
  } catch (error) {
    if (versioned && error instanceof TypeError) {
      throw new Error("无法连接本机平台。请双击「启动平台.bat」，保持服务窗口开启，然后刷新页面。");
    }
    throw error;
  }
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    let code: string | undefined;
    try {
      const data = await response.json();
      code = typeof data.code === "string" ? data.code : undefined;
      message =
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail);
    } catch {}
    if (versioned && response.status === 404 && (message === "Not Found" || message === "请求失败 (404)")) {
      throw new Error(staleService);
    }
    throw new ApiError(message, response.status, code);
  }
  if (versioned && !response.headers.get("content-type")?.includes("application/json")) {
    throw new Error(staleService);
  }
  return response.json();
}
export const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
