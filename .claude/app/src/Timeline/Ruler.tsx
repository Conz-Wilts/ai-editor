// The time ruler: click or drag on it to move the playhead.
import React from "react";
import { seek } from "../store";
import { tickStep, timecode } from "./zoom";

export const Ruler: React.FC<{ frames: number; fps: number; ppf: number; width: number }> = ({ frames, fps, ppf, width }) => {
  const { major, minor } = tickStep(ppf, fps);
  const ticks: React.ReactNode[] = [];
  const last = Math.max(frames, Math.ceil(width / ppf));
  for (let f = 0; f <= last; f += minor) {
    const isMajor = f % major === 0;
    ticks.push(
      <div key={f} className={isMajor ? "tick major" : "tick"} style={{ left: f * ppf }}>
        {isMajor ? <span>{timecode(f, fps, major < fps)}</span> : null}
      </div>,
    );
  }
  const at = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    seek((e.clientX - r.left) / ppf);
  };
  return (
    <div className="ruler" style={{ width }}
      onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); at(e); }}
      onPointerMove={(e) => { if (e.buttons & 1) at(e); }}>
      {ticks}
    </div>
  );
};
