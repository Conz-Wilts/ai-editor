// Calls to the home server (home.py + app_api.py + app_render.py). The page was opened with ?t=<token>, which set
// the cookie every call here carries; POSTs also pass the server's same-origin check.
export class ApiError extends Error {
  constructor(public status: number, public body: any) { super(body?.error || `HTTP ${status}`); }
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { credentials: "same-origin", ...init });
  const text = await r.text();
  let body: any = {};
  try { body = text ? JSON.parse(text) : {}; } catch { body = { error: text.slice(0, 300) }; }
  if (!r.ok) throw new ApiError(r.status, body);
  return body as T;
}

export const get = <T = any>(url: string) => call<T>(url);
export const post = <T = any>(url: string, body: unknown) =>
  call<T>(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

export const q = (params: Record<string, string | number | undefined | null>) =>
  Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&");

/** POST a file as the raw body, with progress (fetch cannot report upload progress). */
export function upload(url: string, file: File, onProgress: (p: number) => void): Promise<any> {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", url);
    x.withCredentials = true;
    x.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    x.onload = () => {
      let body: any = {};
      try { body = JSON.parse(x.responseText || "{}"); } catch { body = { error: x.responseText.slice(0, 300) }; }
      if (x.status >= 200 && x.status < 300) resolve(body);
      else reject(new ApiError(x.status, body));
    };
    x.onerror = () => reject(new ApiError(0, { error: "The upload failed. Is the editor still running?" }));
    x.send(file);
  });
}
