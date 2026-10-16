// One block on a track. Drag the body to move it, an edge to trim it; Timeline.tsx owns the drag.
import React from "react";
import type { Asset, Item as ItemT } from "../types";

export type DragMode = "move" | "start" | "end";

const base = (s?: string) => (s ? s.split("/").pop() ?? s : "");

export function label(it: ItemT, assets: Record<string, Asset>): string {
  const a = it.asset ? assets[it.asset] : undefined;
  switch (it.type) {
    case "zoom": return `Zoom ${it.props?.scale ? `${Number(it.props.scale).toFixed(2)}x` : ""} ${it.props?.kind ?? ""}`.trim();
    case "caption": return String(it.props?.text ?? (it.props?.words ?? []).map((w: any) => w.text ?? w.word).join(" ") ?? "Caption");
    case "card": return [it.component ?? base(it.src) ?? "Card", it.anchor?.word ? `"${it.anchor.word}"` : ""].filter(Boolean).join(" ");
    default: return a?.name ?? base(a?.src ?? it.src) ?? it.type;
  }
}

export const ItemView: React.FC<{
  it: ItemT; assets: Record<string, Asset>; ppf: number; selected: boolean; preview?: { from: number; dur: number };
  onDown: (e: React.PointerEvent, it: ItemT, mode: DragMode) => void; locked: boolean;
}> = ({ it, assets, ppf, selected, preview, onDown, locked }) => {
  const from = preview?.from ?? it.from, dur = preview?.dur ?? it.durationInFrames;
  const w = Math.max(3, dur * ppf);
  const edge = w > 18 ? 6 : 3;
  const cls = ["item", `t-${it.type}`, selected ? "sel" : "", it.origin === "claude" ? "by-claude" : "", it.pinned ? "pinned" : "",
    preview ? "dragging" : ""].filter(Boolean).join(" ");
  const tip = `${label(it, assets)}\n${(it.from / 30).toFixed(2)}s, ${it.durationInFrames} frames${it.origin !== "user" ? `\nmade by ${it.origin}` : ""}`;
  return (
    <div className={cls} style={{ left: from * ppf, width: w }} title={tip} data-id={it.id}
      onPointerDown={(e) => !locked && onDown(e, it, "move")}>
      {!locked ? <b className="edge l" style={{ width: edge }} onPointerDown={(e) => { e.stopPropagation(); onDown(e, it, "start"); }} /> : null}
      <span>{w > 24 ? label(it, assets) : ""}</span>
      {it.fit === "reframe" ? <em className="badge">follow</em> : null}
      {!locked ? <b className="edge r" style={{ width: edge }} onPointerDown={(e) => { e.stopPropagation(); onDown(e, it, "end"); }} /> : null}
    </div>
  );
};
