// One track: its name on the left, its items on the lane. Files, bin assets and gallery components drop here.
import React from "react";
import type { Asset, Item, Track as TrackT } from "../types";
import { dispatch } from "../store";
import { DragMode, ItemView } from "./Item";

export const HEIGHT: Record<string, number> = { main: 58, broll: 42, generated: 42, cards: 38, zooms: 26, captions: 30, music: 30, sfx: 26 };
const ICON: Record<string, string> = { main: "▶", broll: "▣", generated: "✦", cards: "◧", zooms: "⤢", captions: "T", music: "♪", sfx: "∿" };
const SOUNDS = new Set(["main", "broll", "generated", "music", "sfx"]);   // tracks with audio: these get a mute button

// mute / show / lock: one updateTrack op each, undoable like any edit (allowed on a locked track, so it can unlock)
const toggle = (t: TrackT, key: "muted" | "hidden" | "locked", label: string) => (e: React.MouseEvent) => {
  e.stopPropagation();
  dispatch(`${t[key] ? "Un" : ""}${label} ${t.name}`, [{ op: "updateTrack", id: t.id, set: { [key]: !t[key] } }]);
};

export const Track: React.FC<{
  t: TrackT; assets: Record<string, Asset>; ppf: number; width: number; selection: Set<string>;
  previews: Map<string, { from: number; dur: number; track: string }>; ghost: Item[];
  onDown: (e: React.PointerEvent, it: Item, mode: DragMode) => void;
  onLane: (e: React.PointerEvent, t: TrackT) => void;
  onDrop: (e: React.DragEvent, t: TrackT) => void; dropping: boolean; setDropping: (id: string | null) => void;
}> = ({ t, assets, ppf, width, selection, previews, ghost, onDown, onLane, onDrop, dropping, setDropping }) => {
  const h = HEIGHT[t.role] ?? 36;
  const items = t.items.filter((it) => !previews.has(it.id) || previews.get(it.id)!.track === t.id).concat(ghost);
  return (
    <div className={`row r-${t.role}${dropping ? " drop" : ""}${t.hidden ? " hid" : ""}${t.muted ? " muted" : ""}`} style={{ height: h }}>
      <div className="head" title={`${t.name} (${t.role})${t.locked ? ", locked" : ""}${t.hidden ? ", hidden" : ""}${t.muted ? ", muted" : ""}`}>
        <i>{ICON[t.role] ?? "•"}</i><span>{t.name}</span>
        <span className="tbtns">
          {SOUNDS.has(t.role) ? <button className={t.muted ? "on" : ""} aria-pressed={!!t.muted} title={t.muted ? "Unmute" : "Mute"}
            onPointerDown={(e) => e.stopPropagation()} onClick={toggle(t, "muted", "Mute")}>{t.muted ? "🔇" : "🔊"}</button> : null}
          {t.role !== "main" ? <button className={t.hidden ? "on" : ""} aria-pressed={!!t.hidden} title={t.hidden ? "Show track" : "Hide track"}
            onPointerDown={(e) => e.stopPropagation()} onClick={toggle(t, "hidden", "Hide")}>{t.hidden ? "◌" : "◉"}</button> : null}
          <button className={t.locked ? "on" : ""} aria-pressed={!!t.locked} title={t.locked ? "Unlock" : "Lock"}
            onPointerDown={(e) => e.stopPropagation()} onClick={toggle(t, "locked", "Lock")}>{t.locked ? "🔒" : "🔓"}</button>
        </span>
      </div>
      <div className="lane" style={{ width }} data-track={t.id}
        onPointerDown={(e) => onLane(e, t)}
        onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setDropping(t.id); }}
        onDragLeave={() => setDropping(null)}
        onDrop={(e) => { setDropping(null); onDrop(e, t); }}>
        {items.map((it) => (
          <ItemView key={it.id} it={it} assets={assets} ppf={ppf} selected={selection.has(it.id)} locked={t.locked}
            preview={previews.get(it.id)} onDown={onDown} />
        ))}
      </div>
    </div>
  );
};
