// The multi-track timeline: drag to move (across matching tracks), drag an edge to trim, snap to edges and the
// playhead, click the ruler or an empty lane to seek, Ctrl/Cmd + wheel to zoom. Every change is one op batch.
import React, { useMemo, useRef, useState } from "react";
import { deleteSelected, dispatch, fitTimeline, getState, itemFor, seek, setState, splitAtPlayhead, uploadFiles, useStore, zoomBy } from "../store";
import { mint } from "../ops";
import type { Item, Track as TrackT } from "../types";
import { DragMode } from "./Item";
import { Playhead } from "./Playhead";
import { Ruler } from "./Ruler";
import { canMoveTo, snap, snapPoints } from "./snapping";
import { Track } from "./Track";
import { timecode } from "./zoom";

const HEAD = 168;   // the track names' column, px (name + mute, show, lock)

type Drag = {
  mode: DragMode; ids: string[]; x0: number; orig: Map<string, { from: number; dur: number; track: string; role: string; trimIn?: number }>;
  dx: number; track: string | null; moved: boolean; points: number[];
};

export const Timeline: React.FC = () => {
  const doc = useStore((s) => s.doc);
  const ppf = useStore((s) => s.ppf);
  const selection = useStore((s) => s.selection);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [snapOn, setSnapOn] = useState(true);
  const [dropping, setDropping] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const sel = useMemo(() => new Set(selection), [selection]);

  if (!doc) return <div className="timeline empty">Open a project to see its timeline.</div>;
  const fps = doc.fps;
  const total = Math.max(doc.durationInFrames, ...doc.tracks.flatMap((t) => t.items.map((i) => i.from + i.durationInFrames)), fps * 10);
  const width = Math.ceil(total * ppf + 400);

  // where the dragged items sit right now (the drop is the op)
  const previews = new Map<string, { from: number; dur: number; track: string }>();
  if (drag?.moved) {
    for (const [id, o] of drag.orig) {
      if (drag.mode === "move") previews.set(id, { from: Math.max(0, o.from + drag.dx), dur: o.dur, track: drag.track && drag.ids.length === 1 ? drag.track : o.track });
      else if (drag.mode === "start") previews.set(id, { from: Math.min(o.from + o.dur - 1, Math.max(0, o.from + drag.dx, o.trimIn !== undefined ? o.from - o.trimIn : 0)),
        dur: 0, track: o.track });
      else previews.set(id, { from: o.from, dur: Math.max(1, o.dur + drag.dx), track: o.track });
    }
    if (drag.mode === "start") for (const [id, p] of previews) { const o = drag.orig.get(id)!; p.dur = o.from + o.dur - p.from; }
  }
  // an item moved onto another track draws there
  const ghosts = (t: TrackT): Item[] => {
    if (!drag?.moved || drag.mode !== "move" || drag.ids.length !== 1 || drag.track !== t.id) return [];
    const id = drag.ids[0], o = drag.orig.get(id)!;
    if (o.track === t.id) return [];
    const it = doc.tracks.flatMap((x) => x.items).find((x) => x.id === id);
    return it ? [it] : [];
  };

  const frameAt = (clientX: number) => {
    const el = scroller.current!;
    const r = el.getBoundingClientRect();
    return Math.max(0, (clientX - r.left - HEAD + el.scrollLeft) / ppf);
  };

  const onDown = (e: React.PointerEvent, it: Item, mode: DragMode) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    const multi = e.shiftKey || e.ctrlKey || e.metaKey;
    let ids = selection;
    if (multi) ids = sel.has(it.id) ? selection.filter((x) => x !== it.id) : [...selection, it.id];
    else if (!sel.has(it.id)) ids = [it.id];
    setState({ selection: ids, panel: "inspector" });
    if (multi && !ids.includes(it.id)) return;
    const use = mode === "move" ? ids : [it.id];
    const orig = new Map<string, any>();
    for (const t of doc.tracks) for (const x of t.items) if (use.includes(x.id) && !t.locked)
      orig.set(x.id, { from: x.from, dur: x.durationInFrames, track: t.id, role: t.role, trimIn: x.trimIn });
    if (!orig.size) return;
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    setDrag({ mode, ids: use, x0: e.clientX, orig, dx: 0, track: null, moved: false,
      points: snapPoints(doc, new Set(use), getState().frame) });
  };

  const onMove = (e: React.PointerEvent) => {
    if (!drag) return;
    let dx = Math.round((e.clientX - drag.x0) / ppf);
    if (!drag.moved && Math.abs(e.clientX - drag.x0) < 3) return;
    // snap the edge that moves (for a move: whichever edge of the first item lands nearer)
    const first = drag.orig.get(drag.ids[0])!;
    if (drag.mode === "move") {
      const a = snap(first.from + dx, drag.points, ppf, snapOn), b = snap(first.from + first.dur + dx, drag.points, ppf, snapOn);
      if (a.hit !== null) dx = a.frame - first.from;
      else if (b.hit !== null) dx = b.frame - first.from - first.dur;
    } else {
      const edge = drag.mode === "start" ? first.from : first.from + first.dur;
      const s = snap(edge + dx, drag.points, ppf, snapOn);
      if (s.hit !== null) dx = s.frame - edge;
    }
    // vertical: the lane under the pointer, when it takes this kind of item
    let track = drag.track;
    if (drag.mode === "move" && drag.ids.length === 1) {
      const lane = (document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null)?.closest(".lane") as HTMLElement | null;
      const t = lane ? doc.tracks.find((x) => x.id === lane.dataset.track) : null;
      track = t && !t.locked && canMoveTo(first.role, t.role) ? t.id : drag.track;
    }
    setDrag({ ...drag, dx, track, moved: true });
  };

  const onUp = () => {
    if (!drag) return;
    setDrag(null);
    if (!drag.moved) return;
    const ops = [];
    for (const [id, o] of drag.orig) {
      if (drag.mode === "move") {
        const from = Math.max(0, o.from + drag.dx);
        const track = drag.track && drag.ids.length === 1 && drag.track !== o.track ? drag.track : undefined;
        if (from !== o.from || track) ops.push({ op: "move", id, from, ...(track ? { track } : {}) });
      } else if (drag.mode === "start") {
        const min = o.trimIn !== undefined ? o.from - o.trimIn : 0;
        const to = Math.min(o.from + o.dur - 1, Math.max(0, min, o.from + drag.dx));
        if (to !== o.from) ops.push({ op: "trim", id, edge: "start", to });
      } else {
        const to = Math.max(o.from + 1, o.from + o.dur + drag.dx);
        if (to !== o.from + o.dur) ops.push({ op: "trim", id, edge: "end", to });
      }
    }
    if (ops.length) dispatch(drag.mode === "move" ? (ops.length > 1 ? `Move ${ops.length} items` : "Move") : "Trim", ops);
  };

  const onLane = (e: React.PointerEvent, _t: TrackT) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest(".item")) return;
    if (!(e.shiftKey || e.ctrlKey || e.metaKey)) setState({ selection: [] });
    seek(frameAt(e.clientX));
  };

  const onDrop = (e: React.DragEvent, t: TrackT) => {
    e.preventDefault();
    const frame = Math.round(frameAt(e.clientX));
    const files = Array.from(e.dataTransfer.files ?? []);
    if (files.length) return void uploadFiles(files, { role: t.role, frame });
    const assetId = e.dataTransfer.getData("application/x-ai-asset");
    if (assetId && doc.assets[assetId]) {
      const { track, item } = itemFor(assetId, doc.assets[assetId], fps, frame, t.role);
      return void dispatch("Add to the timeline", [{ op: "add", track: t.locked ? track : track === t.role ? t.id : track, id: mint(), item }]);
    }
    const comp = e.dataTransfer.getData("application/x-ai-component");
    if (comp) window.dispatchEvent(new CustomEvent("ai-editor:add-component", { detail: { id: comp, frame } }));
  };

  const onWheel = (e: React.WheelEvent) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    const el = scroller.current!;
    const f = frameAt(e.clientX);
    const k = e.deltaY < 0 ? 1.2 : 1 / 1.2;
    zoomBy(k);
    requestAnimationFrame(() => { el.scrollLeft = f * getState().ppf - (e.clientX - el.getBoundingClientRect().left - HEAD); });
  };

  return (
    <div className="timeline">
      <div className="tl-bar">
        <button onClick={splitAtPlayhead} title="Split at the playhead (S)">Split</button>
        <button onClick={deleteSelected} disabled={!selection.length} title="Delete (Del)">Delete</button>
        <span className="sep" />
        <button onClick={() => zoomBy(1 / 1.4)} title="Zoom out (-)">−</button>
        <button onClick={() => zoomBy(1.4)} title="Zoom in (+)">+</button>
        <button onClick={() => fitTimeline(scroller.current?.clientWidth ? scroller.current.clientWidth - HEAD : undefined)}>Fit</button>
        <label className="chk"><input type="checkbox" checked={snapOn} onChange={(e) => setSnapOn(e.target.checked)} /> Snap</label>
        <span className="grow" />
        <TimeReadout fps={fps} total={doc.durationInFrames} />
      </div>
      <div className="tl-scroll" ref={scroller} onWheel={onWheel} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}>
        <div className="tl-inner" style={{ width: HEAD + width }}>
          <div className="row ruler-row"><div className="head corner" /><Ruler frames={total} fps={fps} ppf={ppf} width={width} /></div>
          {doc.tracks.map((t) => (
            <Track key={t.id} t={t} assets={doc.assets} ppf={ppf} width={width} selection={sel} previews={previews} ghost={ghosts(t)}
              onDown={onDown} onLane={onLane} onDrop={onDrop} dropping={dropping === t.id} setDropping={setDropping} />
          ))}
          <Playhead offset={HEAD} ppf={ppf} />
        </div>
      </div>
    </div>
  );
};

const TimeReadout: React.FC<{ fps: number; total: number }> = ({ fps, total }) => {
  const frame = useStore((s) => s.frame);
  return <span className="time">{timecode(frame, fps, true)} / {timecode(total, fps)}</span>;
};
