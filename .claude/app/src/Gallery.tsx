// Motion-graphics components (GET /api/components: the built-ins and the user's own <library>/components/):
// drag one onto the timeline, or Add puts it at the playhead on the cards track.
import React, { useEffect, useState } from "react";
import { dispatch, getState, useStore } from "./store";
import { mint } from "./ops";
import type { ComponentInfo, JSONSchema } from "./types";

const defaults = (s?: JSONSchema) =>
  Object.fromEntries(Object.entries(s?.properties ?? {}).filter(([, p]) => p.default !== undefined).map(([k, p]) => [k, p.default]));

/** Put component c on the cards track at frame (the playhead by default). */
export function addComponent(c: ComponentInfo, frame = getState().frame) {
  const doc = getState().doc;
  if (!doc) return;
  dispatch(`Add ${c.name}`, [{ op: "add", track: "cards", id: mint(), item: {
    type: "card", component: c.id, props: defaults(c.propsSchema), from: Math.round(frame),
    durationInFrames: Math.round((c.defaultDurationS ?? 3) * doc.fps), entrance: c.entrance ?? "pop", layout: "box",
    box: { units: "safe", x: 5, y: 5, w: 90, h: 35 } } }]);
}

const Thumb: React.FC<{ id: string }> = ({ id }) => {
  const [tries, setTries] = useState(0);
  const [ok, setOk] = useState(true);
  useEffect(() => {   // 202 while the still renders: look again a little later
    if (ok || tries > 6) return;
    const t = setTimeout(() => { setOk(true); setTries(tries + 1); }, 4000);
    return () => clearTimeout(t);
  }, [ok, tries]);
  return ok ? <img src={`/api/components/preview?id=${encodeURIComponent(id)}&n=${tries}`} alt="" onError={() => setOk(false)} />
    : <div className="thumb-wait">…</div>;
};

export const Gallery: React.FC = () => {
  const components = useStore((s) => s.components);
  const format = useStore((s) => s.formats[s.doc?.format ?? ""]?.aspect);
  const [filter, setFilter] = useState("");
  if (components === null) return <div className="gallery"><p className="hint">The component library is not available on this editor yet.</p></div>;
  const f = filter.toLowerCase();
  const list = components.filter((c) => !f || c.name.toLowerCase().includes(f) || c.id.includes(f) || (c.tags ?? []).some((t) => t.includes(f)));
  return (
    <div className="gallery">
      <input className="search" placeholder="Search components" value={filter} onChange={(e) => setFilter(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
      <div className="cards">
        {list.map((c) => {
          const fits = !format || !c.aspects?.length || c.aspects.includes(format);
          return (
            <div key={c.id} className={`comp${fits ? "" : " off"}`} draggable title={`${c.name}${fits ? "" : ` (made for ${c.aspects?.join(", ")})`}\nDrag onto the timeline`}
              onDragStart={(e) => { e.dataTransfer.setData("application/x-ai-component", c.id); e.dataTransfer.effectAllowed = "copy"; }}>
              <Thumb id={c.id} />
              <div className="meta"><b>{c.name}</b><small>{c.kind}{c.tags?.length ? ` · ${c.tags.slice(0, 2).join(", ")}` : ""}</small></div>
              <button onClick={() => addComponent(c)}>Add</button>
            </div>
          );
        })}
        {!list.length ? <p className="hint">No component matches.</p> : null}
      </div>
    </div>
  );
};
