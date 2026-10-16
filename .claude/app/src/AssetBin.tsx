// The project's media: drop files here (or anywhere on the window) to upload them into the edit; drag one onto
// a track, or double-click it to add it at the playhead.
import React, { useRef, useState } from "react";
import { dispatch, getState, itemFor, uploadFiles, useStore } from "./store";
import { mint } from "./ops";
import type { Asset } from "./types";

const KIND_ICON: Record<string, string> = { video: "▶", image: "▣", audio: "♪" };
const dur = (a: Asset) => (a.duration ? `${Math.floor(a.duration / 60)}:${String(Math.round(a.duration % 60)).padStart(2, "0")}` : "");

export const AssetBin: React.FC = () => {
  const doc = useStore((s) => s.doc);
  const uploads = useStore((s) => s.uploads);
  const pick = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  if (!doc) return <aside className="bin" />;
  const used = new Set(doc.tracks.flatMap((t) => t.items.map((i) => i.asset)).filter(Boolean));
  const assets = Object.entries(doc.assets);
  const add = (id: string, a: Asset) => {
    const { track, item } = itemFor(id, a, doc.fps, getState().frame);
    dispatch(`Add ${a.name ?? a.src}`, [{ op: "add", track, id: mint(), item }]);
  };
  return (
    <aside className={`bin${over ? " over" : ""}`}
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); uploadFiles(Array.from(e.dataTransfer.files)); }}>
      <div className="panel-head">
        <b>Media</b><span className="grow" />
        <button onClick={() => pick.current?.click()}>Import</button>
        <input ref={pick} type="file" multiple hidden accept="video/*,image/*,audio/*"
          onChange={(e) => { uploadFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
      </div>
      <div className="bin-list">
        {uploads.map((u) => (
          <div key={u.id} className={`asset up${u.error ? " err" : ""}`}>
            <i>⇪</i><div><b>{u.name}</b><small>{u.error ?? `${Math.round(u.pct * 100)}%`}</small>
              {!u.error ? <div className="bar"><div style={{ width: `${u.pct * 100}%` }} /></div> : null}</div>
          </div>
        ))}
        {assets.map(([id, a]) => (
          <div key={id} className={`asset k-${a.kind}`} draggable title={`${a.src}\nDouble-click: add at the playhead`}
            onDragStart={(e) => { e.dataTransfer.setData("application/x-ai-asset", id); e.dataTransfer.effectAllowed = "copy"; }}
            onDoubleClick={() => add(id, a)}>
            <i>{KIND_ICON[a.kind] ?? "•"}</i>
            <div><b>{a.name ?? a.src.split("/").pop()}</b>
              <small>{[a.kind, a.width ? `${a.width}×${a.height}` : "", dur(a), a.origin === "generated" ? "generated" : "", used.has(id) ? "" : "unused"]
                .filter(Boolean).join(" · ")}</small></div>
          </div>
        ))}
        {!assets.length && !uploads.length ? (
          <div className="hint">Drop videos, pictures or music here.<br />The first video goes straight onto the timeline.</div>
        ) : null}
      </div>
    </aside>
  );
};
