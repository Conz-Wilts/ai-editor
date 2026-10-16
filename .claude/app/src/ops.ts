// The op semantics of lib/ai_editor/project_store.py apply_op, in TypeScript, so a drag shows at once and the
// server's answer only confirms it. tests/fixtures/ops-cases.json runs through both (tests/test_ops.mjs and
// tests/check_ops.py) so the two never drift. Forward only: undo lives on the server (project.log.jsonl).
import type { Item, Op, Project, Track } from "./types";

export class OpError extends Error {
  constructor(public kind: "conflict" | "bad", msg: string) { super(msg); }
}
const conflict = (m: string) => new OpError("conflict", m);
const bad = (m: string) => new OpError("bad", m);

const PROJECT_KEYS = ["name", "format", "formats", "designSystem", "width", "height"];
const TRACK_KEYS: Record<string, string> = { muted: "boolean", hidden: "boolean", locked: "boolean", name: "string" };   // updateTrack
const EDITS = ["move", "trim", "split", "update"];
const ROLES: Record<string, string> = { main: "video", broll: "video", generated: "video", cards: "overlay", zooms: "effect",
  captions: "caption", music: "audio", sfx: "audio" };
const B32 = "abcdefghijklmnopqrstuvwxyz234567";

export const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
export const mint = (prefix = "itm") => `${prefix}_` + Array.from({ length: 8 }, () => B32[Math.floor(Math.random() * 32)]).join("");
export const end = (it: Item) => it.from + it.durationInFrames;

export function find(doc: Project, id: string): [Track | null, number, Item | null] {
  for (const t of doc.tracks) {
    const i = t.items.findIndex((it) => it.id === id);
    if (i >= 0) return [t, i, t.items[i]];
  }
  return [null, -1, null];
}

export const track = (doc: Project, ref: string): Track | null =>
  doc.tracks.find((t) => t.id === ref) ?? doc.tracks.find((t) => t.role === ref) ?? null;

export function deriveDuration(doc: Project): number {
  const main = doc.tracks.filter((t) => t.role === "main" && !t.hidden).flatMap((t) => t.items);
  return main.length ? Math.max(...main.map(end)) : doc.durationInFrames ?? 0;
}

function need(doc: Project, id: string): [Track, number, Item] {
  const [t, i, it] = find(doc, id);
  if (!it || !t) throw conflict(`no item ${id}`);
  return [t, i, it];
}
function guard(t: Track, author: string) {
  if (t.locked && author !== "plan") throw bad(`track ${t.name} is locked`);
}
function frame(v: unknown, name: string): number {
  if (typeof v !== "number" || !Number.isInteger(v) || v < 0) throw bad(`${name} must be a frame (a non-negative integer)`);
  return v;
}
function setPath(obj: any, dotted: string, value: unknown, unset = false) {
  const keys = dotted.split(".");
  for (const k of keys.slice(0, -1)) {
    if (typeof obj[k] !== "object" || obj[k] === null || Array.isArray(obj[k])) {
      if (unset) return;
      obj[k] = {};
    }
    obj = obj[k];
  }
  if (unset) delete obj[keys[keys.length - 1]];
  else obj[keys[keys.length - 1]] = value;
}
export function newTrack(role: string, name?: string): Track {
  return { id: mint("trk"), kind: ROLES[role] ?? "video", role, name: name ?? role[0].toUpperCase() + role.slice(1),
    muted: false, hidden: false, locked: false, items: [] };
}

/** Apply one op to doc in place (project_store.apply_op without the inverse). */
export function applyOp(doc: Project, op: Op, author: string) {
  const kind = op.op;
  if (kind === "add") {
    const t = track(doc, op.track ?? "");
    if (!t) throw conflict(`no track ${op.track}`);
    guard(t, author);
    const it: Item = clone(op.item ?? {});
    it.id = op.id ?? it.id ?? mint();
    if (find(doc, it.id)[2]) throw conflict(`${it.id} already exists`);
    if (it.origin === undefined) it.origin = author === "plan" ? "plan" : (author as Item["origin"]);
    if (it.pinned === undefined) it.pinned = author !== "plan";
    if (it.from === undefined) it.from = 0;
    t.items.splice(op.index ?? t.items.length, 0, it);
    return;
  }
  if (kind === "delete") {
    const [t, i] = need(doc, op.id);
    guard(t, author);
    t.items.splice(i, 1);
    return;
  }
  if (kind === "replace") {
    const [t0, i0, cur] = find(doc, op.id);
    if (cur && t0) t0.items.splice(i0, 1);
    const t = track(doc, op.track ?? "");
    if (!t) throw conflict(`no track ${op.track}`);
    t.items.splice(Math.min(op.index ?? t.items.length, t.items.length), 0, clone(op.item));
    return;
  }
  if (EDITS.includes(kind)) {
    const [t, i, it] = need(doc, op.id);
    guard(t, author);
    if (kind === "move") {
      it.from = frame(op.from, "from");
      if (op.track != null && op.track !== t.id && op.track !== t.role) {
        const dest = track(doc, op.track);
        if (!dest) throw conflict(`no track ${op.track}`);
        guard(dest, author);
        t.items.splice(i, 1);
        dest.items.push(it);
      }
    } else if (kind === "trim") {
      const to = frame(op.to, "to"), e = end(it);
      if (op.edge === "start") {
        if (to >= e) throw bad("trim start past the item's end");
        const d = to - it.from;
        if (it.trimIn !== undefined) {
          if (it.trimIn + d < 0) throw bad("trim start before the clip's first frame");
          it.trimIn += d;
        }
        it.from = to;
        it.durationInFrames = e - to;
      } else if (op.edge === "end") {
        if (to <= it.from) throw bad("trim end before the item's start");
        it.durationInFrames = to - it.from;
      } else throw bad("trim edge is start or end");
    } else if (kind === "split") {
      const at = frame(op.at, "at");
      if (!(it.from < at && at < end(it))) throw bad("split inside the item");
      const right: Item = clone(it);
      right.id = op.newId ?? mint();
      if (find(doc, right.id)[2]) throw conflict(`${right.id} already exists`);
      right.from = at;
      right.durationInFrames = end(it) - at;
      if (right.trimIn !== undefined) right.trimIn += at - it.from;
      delete right.sec;
      if (right.anchor) right.anchor = { ...right.anchor, t: Math.round((at / doc.fps) * 1000) / 1000 };
      it.durationInFrames = at - it.from;
      t.items.splice(i + 1, 0, right);
    } else {
      for (const [k, v] of Object.entries(op.set ?? {})) {
        if (["id", "type"].includes(k.split(".")[0])) throw bad(`${k} cannot change`);
        setPath(it, k, clone(v));
      }
      for (const k of op.unset ?? []) setPath(it, k, null, true);
    }
    if (author !== "plan" && it.origin === "plan") it.pinned = true;
    return;
  }
  if (kind === "addTrack") {
    const spec = clone(op.track ?? {});
    const t: Track = { ...newTrack(spec.role ?? "broll", spec.name), ...spec };
    if (!t.items) t.items = [];
    if (spec.id) t.id = spec.id;
    if (doc.tracks.some((x) => x.id === t.id)) throw conflict(`${t.id} already exists`);
    doc.tracks.splice(op.index ?? doc.tracks.length, 0, t);
    return;
  }
  if (kind === "deleteTrack") {
    const i = doc.tracks.findIndex((t) => t.id === op.id);
    if (i < 0) throw conflict(`no track ${op.id}`);
    doc.tracks.splice(i, 1);
    return;
  }
  if (kind === "updateTrack") {
    const t = doc.tracks.find((x) => x.id === op.id);
    if (!t) throw conflict(`no track ${op.id}`);
    const set = op.set;
    if (!set || typeof set !== "object" || !Object.keys(set).length) throw bad("updateTrack needs a set");
    for (const [k, v] of Object.entries(set)) {   // allowed even on a locked track: that is how it unlocks
      if (!(k in TRACK_KEYS)) throw bad(`updateTrack cannot set ${k}`);
      if (typeof v !== TRACK_KEYS[k] || (k === "name" && !(v as string).trim()))
        throw bad(`track ${k} must be ${k === "name" ? "a non-empty string" : "true or false"}`);
      (t as any)[k] = v;
    }
    return;
  }
  if (kind === "setProject") {
    for (const [k, v] of Object.entries(op.set ?? {})) {
      if (!PROJECT_KEYS.includes(k)) throw bad(`setProject cannot set ${k}`);
      (doc as any)[k] = clone(v);
    }
    for (const k of op.unset ?? []) if (PROJECT_KEYS.includes(k)) delete (doc as any)[k];
    return;
  }
  if (kind === "addAsset") {
    const id = op.id ?? op.asset?.id ?? mint("ast");
    if (id in doc.assets) throw conflict(`${id} already exists`);
    const a = clone(op.asset ?? {});
    delete a.id;
    doc.assets[id] = a;
    return;
  }
  if (kind === "deleteAsset") {
    if (!(op.id in doc.assets)) throw conflict(`no asset ${op.id}`);
    if (doc.tracks.some((t) => t.items.some((it) => it.asset === op.id))) throw bad(`${op.id} is on the timeline`);
    delete doc.assets[op.id];
    return;
  }
  throw bad(`unknown op ${JSON.stringify(kind)}`);
}

/** The doc after a whole batch (a copy; doc is untouched), or an OpError. */
export function applyBatch(doc: Project, ops: Op[], author = "user"): Project {
  if (!ops.length) throw bad("ops must be a non-empty list");
  const out = clone(doc);
  for (const op of ops) applyOp(out, op, author);
  out.durationInFrames = deriveDuration(out);
  return out;
}
