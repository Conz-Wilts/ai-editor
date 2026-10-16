// The app's state and every action that changes the project. Edits are op batches: applied here at once
// (ops.ts, the same rules as project_store.py), then sent to POST /api/commands; the server's doc replaces ours.
// A long-poll on /api/events brings in what Claude (or another tab) changed, shown as toasts with Undo.
import { useSyncExternalStore } from "react";
import { ApiError, get, post, q, upload } from "./api";
import { OpError, applyBatch, clone, find, mint } from "./ops";
import type { Asset, ComponentInfo, DesignSystem, FormatSpec, Item, LogEntry, Op, Project, Proposal, Track } from "./types";

export type Toast = { id: number; text: string; kind: "info" | "error" | "claude"; undoAuthor?: string; proposal?: Proposal };
export type Upload = { id: string; name: string; pct: number; error?: string };
export type ProjectRow = { edit: string; name: string; project: boolean; rev: number };
export type Job = { id: string; type: string; state: string; args: Record<string, any>; steps?: any[]; result?: any; at?: number };

export type State = {
  projects: ProjectRow[];
  edit: string | null;        // the edit folder's path
  doc: Project | null;
  plan: any | null;           // the Player's props: project_convert.to_plan(doc)
  planRev: number;
  proposals: Proposal[];
  formats: Record<string, FormatSpec>;
  components: ComponentInfo[] | null;   // null: the server has no component library yet
  systems: DesignSystem[] | null;
  selection: string[];
  frame: number;
  seek: number;               // bumped to make the Player jump to `frame`
  playing: boolean;
  ppf: number;                // timeline pixels per frame
  showSafe: boolean;
  uploads: Upload[];
  toasts: Toast[];
  jobs: Job[];
  listening: boolean;
  error: string | null;
  panel: "inspector" | "gallery" | "render";
};

let state: State = {
  projects: [], edit: null, doc: null, plan: null, planRev: -1, proposals: [], formats: {}, components: null, systems: null,
  selection: [], frame: 0, seek: 0, playing: false, ppf: 2, showSafe: false, uploads: [], toasts: [], jobs: [],
  listening: false, error: null, panel: "inspector",
};
const subs = new Set<() => void>();
export const getState = () => state;
export function setState(p: Partial<State> | ((s: State) => Partial<State>)) {
  state = { ...state, ...(typeof p === "function" ? p(state) : p) };
  subs.forEach((f) => f());
}
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };
export function useStore<T>(sel: (s: State) => T): T {
  return useSyncExternalStore(subscribe, () => sel(state));
}

// ---------------------------------------------------------------- toasts
let toastId = 0;
export function toast(text: string, kind: Toast["kind"] = "info", extra: Partial<Toast> = {}) {
  const t = { id: ++toastId, text, kind, ...extra };
  setState((s) => ({ toasts: [...s.toasts.slice(-4), t] }));
  if (!extra.proposal) setTimeout(() => dismiss(t.id), kind === "info" ? 6000 : 15000);   // Claude's: long enough to undo
}
export const dismiss = (id: number) => setState((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

// ---------------------------------------------------------------- loading
const editRef = () => state.edit ?? "";
const editName = () => (state.edit ?? "").split(/[\\/]/).pop() ?? "";

export async function boot() {
  try {
    const f = await get<{ formats: Record<string, FormatSpec> }>("/api/formats");
    setState({ formats: f.formats ?? {} });
  } catch { /* the format bar shows the project's own size */ }
  get<{ components: ComponentInfo[] }>("/api/components").then((r) => setState({ components: r.components ?? [] }), () => {});
  get<{ systems: DesignSystem[] }>("/api/design-systems").then((r) => setState({ systems: r.systems ?? [] }), () => {});
  pollState();
  await loadProjects();
  const want = new URLSearchParams(location.search).get("edit") || localStorage.getItem("ai-editor:edit");
  const row = state.projects.find((p) => p.edit === want || p.name === want);
  if (row) await openProject(row.edit);
}

export async function loadProjects() {
  try {
    const r = await get<{ projects: ProjectRow[] }>("/api/projects");
    setState({ projects: r.projects.sort((a, b) => a.name.localeCompare(b.name)) });
  } catch (e) {
    setState({ error: message(e) });
  }
}

let generation = 0;
export async function openProject(edit: string) {
  const gen = ++generation;
  try {
    const r = await get<{ doc: Project; proposals: Proposal[] }>(`/api/project?${q({ edit })}`);
    if (gen !== generation) return;
    const name = edit.split(/[\\/]/).pop() ?? "";
    (window as any).remotion_staticBase = `/api/media/${encodeURIComponent(name)}`;
    setState({ edit, doc: r.doc, proposals: r.proposals ?? [], selection: [], frame: 0, seek: state.seek + 1, plan: null, planRev: -1, error: null });
    try { localStorage.setItem("ai-editor:edit", edit); } catch { /* private window */ }
    const u = new URL(location.href);
    u.searchParams.set("edit", name);
    history.replaceState(null, "", u.toString());
    fitTimeline();
    await loadPlan();
    events(gen);
  } catch (e) {
    setState({ error: `Could not open it: ${message(e)}` });
  }
}

let planTimer: ReturnType<typeof setTimeout> | null = null;
export function loadPlan(delay = 0): Promise<void> {
  if (planTimer) clearTimeout(planTimer);
  return new Promise((resolve) => {
    planTimer = setTimeout(async () => {
      const ed = state.edit;
      if (!ed) return resolve();
      try {
        const r = await get<{ rev: number; plan: any }>(`/api/plan?${q({ edit: ed, format: state.doc?.format ?? "" })}`);
        if (state.edit === ed) setState({ plan: r.plan, planRev: r.rev });
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 404)) toast(`The preview could not update: ${message(e)}`, "error");
      }
      resolve();
    }, delay);
  });
}

async function reloadDoc() {
  if (!state.edit) return;
  const r = await get<{ doc: Project; proposals: Proposal[] }>(`/api/project?${q({ edit: state.edit })}`);
  setState((s) => ({ doc: r.doc, proposals: r.proposals ?? [], selection: s.selection.filter((id) => find(r.doc, id)[2]) }));
  loadPlan(50);
}

// ---------------------------------------------------------------- edits
const ownRevs = new Set<number>();
let queue: Promise<unknown> = Promise.resolve();

/** Apply ops now, then on the server (one batch at a time, in order). False when the ops are refused. */
export function dispatch(label: string, ops: Op[]): boolean {
  const doc = state.doc;
  if (!doc || !ops.length) return false;
  let next: Project;
  try {
    next = applyBatch(doc, ops, "user");
  } catch (e) {
    toast(e instanceof OpError ? e.message : message(e), "error");
    return false;
  }
  setState({ doc: next });
  const ed = state.edit;
  queue = queue.then(async () => {
    try {
      const r = await post<{ rev: number; doc: Project }>(`/api/commands?${q({ edit: ed })}`,
        { baseRev: doc.rev, author: "user", label, ops });
      ownRevs.add(r.rev);
      if (state.edit === ed && (!state.doc || r.rev >= state.doc.rev)) setState({ doc: r.doc });
      loadPlan(30);
    } catch (e) {
      toast(e instanceof ApiError && e.status === 409 ? "The project changed meanwhile, so that edit was undone. Try it again."
        : `That edit did not save: ${message(e)}`, "error");
      await reloadDoc().catch(() => {});
    }
  });
  return true;
}

export async function undo(author = "user") {
  try {
    const r = await post<{ rev: number; doc: Project | null; nothing?: boolean }>(`/api/undo?${q({ edit: editRef() })}`, { author });
    if (r.nothing) return toast("Nothing to undo.");
    if (r.doc) { ownRevs.add(r.rev); setState({ doc: r.doc }); }
    loadPlan();
  } catch (e) { toast(`Undo failed: ${message(e)}`, "error"); }
}

export async function redo(author = "user") {
  try {
    const r = await post<{ rev: number; doc: Project | null; nothing?: boolean }>(`/api/redo?${q({ edit: editRef() })}`, { author });
    if (r.nothing) return toast("Nothing to redo.");
    if (r.doc) { ownRevs.add(r.rev); setState({ doc: r.doc }); }
    loadPlan();
  } catch (e) { toast(`Redo failed: ${message(e)}`, "error"); }
}

export async function proposal(id: string, accept: boolean) {
  try {
    if (accept) {
      const r = await post<{ rev: number; doc: Project }>(`/api/proposal/accept?${q({ edit: editRef() })}`, { id });
      ownRevs.add(r.rev);
      setState({ doc: r.doc });
      loadPlan();
    } else {
      await post(`/api/proposal/reject?${q({ edit: editRef() })}`, { id });
    }
    setState((s) => ({ proposals: s.proposals.filter((p) => p.id !== id), toasts: s.toasts.filter((t) => t.proposal?.id !== id) }));
  } catch (e) { toast(message(e), "error"); }
}

// Claude's (and other tabs') changes, as they land
async function events(gen: number) {
  while (gen === generation && state.edit) {
    const doc = state.doc;
    try {
      const r = await get<{ rev: number; entries: LogEntry[]; proposals: Proposal[] }>(`/api/events?${q({
        edit: state.edit, since: doc?.rev ?? -1, wait: 25, proposals: state.proposals.map((p) => p.id).join(",") })}`);
      if (gen !== generation) return;
      const fresh = r.entries.filter((e) => !ownRevs.has(e.rev));
      for (const e of fresh) {
        if (e.author === "claude") toast(`Claude: ${e.label}`, "claude", { undoAuthor: "claude" });
        else if (e.author === "plan") toast(`Updated from the plan (${e.label})`);
      }
      const known = new Set(state.proposals.map((p) => p.id));
      for (const p of r.proposals) if (!known.has(p.id)) toast(`Claude suggests: ${p.label ?? "a change"}`, "claude", { proposal: p });
      setState({ proposals: r.proposals });
      if (r.rev > (state.doc?.rev ?? -1)) await reloadDoc();
    } catch {
      await new Promise((ok) => setTimeout(ok, 3000));   // the server restarted (live reload): try again
    }
  }
}

// the home server's state: jobs (render, ask) and whether a Claude listens
async function pollState() {
  for (;;) {
    try {
      const s = await get<{ jobs: Job[]; listening: boolean }>("/state");
      setState({ jobs: s.jobs ?? [], listening: !!s.listening });
    } catch { /* restarting */ }
    await new Promise((ok) => setTimeout(ok, 2500));
  }
}

// ---------------------------------------------------------------- projects, media
export async function newProject(name: string, format: string) {
  try {
    const r = await post<{ edit: string }>("/api/new", { name, format });
    await loadProjects();
    await openProject(r.edit);
  } catch (e) { toast(`Could not make it: ${message(e)}`, "error"); }
}

export const framesOf = (a: Asset, fps: number) =>
  Math.max(1, Math.round(a.duration ? a.duration * fps : a.durationInFrames && a.fps ? (a.durationInFrames / a.fps) * fps : 3 * fps));

/** The track an asset goes on by default, and the item it becomes there. */
export function itemFor(assetId: string, a: Asset, fps: number, from: number, role?: string): { track: string; item: Partial<Item> } {
  const dur = framesOf(a, fps);
  if (a.kind === "audio") return { track: role && ["music", "sfx"].includes(role) ? role : "music",
    item: { type: "audio", asset: assetId, src: a.src, from, durationInFrames: dur, trimIn: 0 } };
  if (a.kind === "image") return { track: role && ["broll", "generated", "cards"].includes(role) ? role : "broll",
    item: role === "cards" ? { type: "card", src: a.src, from, durationInFrames: dur, layout: "box", entrance: "pop",
      box: { units: "safe", x: 10, y: 10, w: 80, h: 40 } }
      : { type: "image", asset: assetId, src: a.src, from, durationInFrames: dur } };
  return { track: role && ["main", "broll", "generated"].includes(role) ? role : "main",
    item: { type: role === "generated" ? "generated" : "video", asset: assetId, src: a.src, from, durationInFrames: dur, trimIn: 0 } };
}

const endOf = (t: Track | undefined) => Math.max(0, ...(t?.items ?? []).map((i) => i.from + i.durationInFrames));

/** Upload dropped files into the edit; each becomes an asset, and (dropped on a track, or the first video of an
 *  empty project) an item at the drop point. */
export async function uploadFiles(files: File[], at?: { role?: string; frame?: number }) {
  if (!state.edit) return toast("Open or make a project first.", "error");
  for (const file of files) {
    const id = mint("up");
    setState((s) => ({ uploads: [...s.uploads, { id, name: file.name, pct: 0 }] }));
    try {
      const r = await upload(`/api/upload?${q({ edit: state.edit, name: file.name })}`, file,
        (pct) => setState((s) => ({ uploads: s.uploads.map((u) => (u.id === id ? { ...u, pct } : u)) })));
      const asset: Asset = r.asset;
      const aid = mint("ast");
      const doc = state.doc!;
      const ops: Op[] = [{ op: "addAsset", id: aid, asset }];
      const mainT = doc.tracks.find((t) => t.role === "main");
      const auto = !at && asset.kind === "video" && !(mainT?.items.length);
      if (at || auto) {
        const role = at?.role ?? "main";
        const from = at?.frame ?? endOf(doc.tracks.find((t) => t.role === role));
        const { track, item } = itemFor(aid, asset, doc.fps, from, role);
        ops.push({ op: "add", track, id: mint(), item });
      }
      dispatch(`Add ${asset.name ?? file.name}`, ops);
      if (auto) fitTimeline();   // the first clip: show all of it
      setState((s) => ({ uploads: s.uploads.filter((u) => u.id !== id) }));
      if (r.proxy) toast(`${file.name} is big, so a lighter copy is being made for the preview. The render uses the original.`);
    } catch (e) {
      setState((s) => ({ uploads: s.uploads.map((u) => (u.id === id ? { ...u, error: message(e) } : u)) }));
    }
  }
}

export async function reframe(id: string) {
  try {
    const r = await post<{ rev: number; doc: Project }>("/api/reframe", { edit: state.edit, id });
    ownRevs.add(r.rev);
    setState({ doc: r.doc });
    loadPlan();
    toast("The clip now follows the speaker.");
  } catch (e) { toast(message(e), "error"); }
}

// ---------------------------------------------------------------- Claude jobs
export async function render(formats: string[], target: string) {
  try {
    await post("/job", { type: "render", edit: state.edit, formats, target });
    toast(state.listening ? "Claude is rendering it." : "Render queued. A Claude window opens to run it.");
  } catch (e) { toast(`Could not start the render: ${message(e)}`, "error"); }
}

export async function ask(text: string) {
  try {
    await post("/job", { type: "ask", edit: state.edit, text, at: state.doc ? state.frame / state.doc.fps : 0 });
    toast("Sent to Claude. Its changes show up here as it makes them.");
  } catch (e) { toast(`Could not send it: ${message(e)}`, "error"); }
}

// ---------------------------------------------------------------- the playhead and the view
export function seek(frame: number) {
  const max = Math.max(0, (state.plan?.durationInFrames ?? state.doc?.durationInFrames ?? 1) - 1);
  setState((s) => ({ frame: Math.max(0, Math.min(max, Math.round(frame))), seek: s.seek + 1 }));
}
export function fitTimeline(width = Math.max(400, window.innerWidth - 200)) {
  const d = state.doc?.durationInFrames || 30 * 30;
  setState({ ppf: Math.max(0.05, Math.min(12, width / (d * 1.05))) });
}
export const zoomBy = (k: number) => setState((s) => ({ ppf: Math.max(0.02, Math.min(24, s.ppf * k)) }));

// ---------------------------------------------------------------- editing helpers the UI uses
export function selectedItems(): Item[] {
  const doc = state.doc;
  return doc ? state.selection.map((id) => find(doc, id)[2]).filter((x): x is Item => !!x) : [];
}

export function splitAtPlayhead() {
  const doc = state.doc;
  if (!doc) return;
  const f = state.frame;
  let targets = selectedItems();
  if (!targets.length) targets = doc.tracks.find((t) => t.role === "main")?.items ?? [];
  const ops = targets.filter((it) => it.from < f && f < it.from + it.durationInFrames).map((it) => ({ op: "split", id: it.id, at: f, newId: mint() }));
  if (!ops.length) return toast("Put the playhead inside a clip to split it.");
  dispatch(ops.length > 1 ? `Split ${ops.length} items` : "Split", ops);
}

export function deleteSelected() {
  const ids = state.selection;
  if (!ids.length) return;
  if (dispatch(ids.length > 1 ? `Delete ${ids.length} items` : "Delete", ids.map((id) => ({ op: "delete", id })))) setState({ selection: [] });
}

export function setFormat(id: string) {
  const f = state.formats[id];
  if (!f || !state.doc) return;
  const formats = Array.from(new Set([...(state.doc.formats ?? []), id]));
  if (dispatch(`Format: ${f.label}`, [{ op: "setProject", set: { format: id, width: f.width, height: f.height, formats } }])) loadPlan(40);
}

export const cloneDoc = () => (state.doc ? clone(state.doc) : null);
