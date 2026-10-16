// The selected item's settings: timing, the component's props (a form made from its JSON Schema), its box, a
// clip's fit (cover / contain / follow the speaker). Each change is an "update" op.
import React, { useEffect, useState } from "react";
import { dispatch, reframe, setState, useStore } from "./store";
import { find } from "./ops";
import type { Box, Item, JSONSchema } from "./types";

const ENTRANCES = ["pop", "slide", "fade", "scale", "cut"];

/** A text or number field that commits on Enter or blur, so typing is one edit, not one per key. */
const Field: React.FC<{ value: any; type?: "text" | "number"; step?: number; onCommit: (v: any) => void; wide?: boolean }> = ({ value, type = "text", step, onCommit, wide }) => {
  const [v, setV] = useState(value ?? "");
  useEffect(() => setV(value ?? ""), [value]);
  const commit = () => {
    const out = type === "number" ? (v === "" ? undefined : Number(v)) : v;
    if (out !== value && !(type === "number" && Number.isNaN(out))) onCommit(out);
  };
  return <input className={wide ? "wide" : ""} type={type} step={step} value={v} onChange={(e) => setV(e.target.value)}
    onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); e.stopPropagation(); }} />;
};

/** Fields for a JSON Schema object (strings, numbers, booleans, enums; anything else as JSON). */
export const SchemaForm: React.FC<{ schema: JSONSchema; value: Record<string, any>; onSet: (key: string, v: any) => void }> = ({ schema, value, onSet }) => {
  const props = schema.properties ?? {};
  return (
    <>
      {Object.entries(props).map(([k, s]) => {
        const t = Array.isArray(s.type) ? s.type.find((x) => x !== "null") : s.type;
        const cur = value?.[k] ?? s.default;
        const name = s.title ?? k;
        let input: React.ReactNode;
        if (s.enum) input = <select value={cur ?? ""} onChange={(e) => onSet(k, e.target.value)}>{s.enum.map((o) => <option key={String(o)} value={o}>{String(o)}</option>)}</select>;
        else if (t === "boolean") input = <input type="checkbox" checked={!!cur} onChange={(e) => onSet(k, e.target.checked)} />;
        else if (t === "number" || t === "integer") input = <Field type="number" value={cur} step={t === "integer" ? 1 : 0.1} onCommit={(v) => onSet(k, v)} />;
        else if (t === "string") input = s.format === "color"
          ? <input type="color" value={cur ?? "#ffffff"} onChange={(e) => onSet(k, e.target.value)} />
          : <Field value={cur} wide onCommit={(v) => onSet(k, v)} />;
        else input = <JsonField value={cur} onCommit={(v) => onSet(k, v)} />;
        return <label key={k} className="prop" title={s.description}><span>{name}</span>{input}</label>;
      })}
    </>
  );
};

const JsonField: React.FC<{ value: any; onCommit: (v: any) => void }> = ({ value, onCommit }) => {
  const [v, setV] = useState(JSON.stringify(value ?? null, null, 1));
  const [bad, setBad] = useState(false);
  useEffect(() => setV(JSON.stringify(value ?? null, null, 1)), [value]);
  return <textarea className={bad ? "bad" : ""} value={v} rows={Math.min(8, v.split("\n").length)} onChange={(e) => setV(e.target.value)}
    onKeyDown={(e) => e.stopPropagation()}
    onBlur={() => { try { const p = JSON.parse(v); setBad(false); if (JSON.stringify(p) !== JSON.stringify(value)) onCommit(p); } catch { setBad(true); } }} />;
};

const boxOf = (it: Item): Box | null => {
  const b = it.box as any;
  if (!b) return null;
  return Array.isArray(b) ? { units: "frame", x: b[0], y: b[1], w: b[2], h: b[3] } : b;
};

export const Inspector: React.FC = () => {
  const doc = useStore((s) => s.doc);
  const selection = useStore((s) => s.selection);
  const components = useStore((s) => s.components);
  if (!doc) return null;
  if (!selection.length) {
    return (
      <div className="inspector">
        <p className="hint">Select something on the timeline to change it.</p>
        <p className="hint">Keys: Space play · S split · Del delete · Ctrl+Z undo · Ctrl+Shift+Z redo · +/− zoom · ←/→ step</p>
      </div>
    );
  }
  if (selection.length > 1) return <div className="inspector"><p className="hint">{selection.length} items selected. Drag to move them together.</p></div>;
  const [t, , it] = find(doc, selection[0]);
  if (!it || !t) return null;
  const fps = doc.fps;
  const set = (label: string, s: Record<string, any>) => dispatch(label, [{ op: "update", id: it.id, set: s }]);
  const comp = it.component ? components?.find((c) => c.id === it.component) : undefined;
  const box = boxOf(it);
  return (
    <div className="inspector">
      <div className="ins-title"><b>{it.component ?? it.type}</b><small>{t.name} · made by {it.origin}{it.pinned ? " · kept on re-plan" : ""}</small></div>
      <section>
        <label className="prop"><span>Start (s)</span>
          <Field type="number" step={0.04} value={+(it.from / fps).toFixed(2)} onCommit={(v) => dispatch("Move", [{ op: "move", id: it.id, from: Math.max(0, Math.round(v * fps)) }])} /></label>
        <label className="prop"><span>Length (s)</span>
          <Field type="number" step={0.04} value={+(it.durationInFrames / fps).toFixed(2)}
            onCommit={(v) => dispatch("Trim", [{ op: "trim", id: it.id, edge: "end", to: it.from + Math.max(1, Math.round(v * fps)) }])} /></label>
        {it.trimIn !== undefined ? <label className="prop"><span>Source in (s)</span><input disabled value={(it.trimIn / fps).toFixed(2)} /></label> : null}
      </section>
      {it.type === "video" && t.role === "main" ? (
        <section>
          <label className="prop"><span>Fit</span>
            <select value={it.fit ?? "cover"} onChange={(e) => e.target.value === "reframe" ? reframe(it.id) : set("Fit", { fit: e.target.value })}>
              <option value="cover">Fill the frame</option><option value="contain">Whole picture</option><option value="reframe">Follow the speaker</option>
            </select></label>
          <label className="prop"><span>Volume</span>
            <input type="range" min={0} max={1} step={0.05} value={it.volume ?? 1} onChange={(e) => set("Volume", { volume: Number(e.target.value) })} /></label>
        </section>
      ) : null}
      {it.type === "zoom" ? (
        <section>
          <label className="prop"><span>Scale</span><Field type="number" step={0.02} value={it.props?.scale} onCommit={(v) => set("Zoom", { "props.scale": v })} /></label>
          <label className="prop"><span>Kind</span><select value={it.props?.kind ?? "punch"} onChange={(e) => set("Zoom", { "props.kind": e.target.value })}>
            <option value="punch">Punch</option><option value="push">Push</option></select></label>
        </section>
      ) : null}
      {it.type === "caption" ? (
        <section><label className="prop"><span>Text</span><Field wide value={it.props?.text} onCommit={(v) => set("Caption", { "props.text": v })} /></label></section>
      ) : null}
      {it.type === "card" ? (
        <section>
          <label className="prop"><span>Entrance</span><select value={it.entrance ?? "pop"} onChange={(e) => set("Entrance", { entrance: e.target.value })}>
            {ENTRANCES.map((x) => <option key={x}>{x}</option>)}</select></label>
          {box ? (["x", "y", "w", "h"] as const).map((k) => (
            <label key={k} className="prop"><span>Box {k} {box.units === "safe" ? "(% of safe zone)" : "(% of frame)"}</span>
              <Field type="number" step={1} value={box[k]} onCommit={(v) => set("Box", { [`box.${k}`]: v })} /></label>
          )) : null}
          {comp?.propsSchema?.properties ? (
            <><h4>{comp.name}</h4><SchemaForm schema={comp.propsSchema} value={it.props ?? {}} onSet={(k, v) => set(`${comp.name}: ${k}`, { [`props.${k}`]: v })} /></>
          ) : (
            <label className="prop"><span>Props (JSON)</span><JsonField value={it.props ?? {}} onCommit={(v) => set("Props", { props: v })} /></label>
          )}
        </section>
      ) : null}
      <section className="actions">
        <button onClick={() => dispatch("Delete", [{ op: "delete", id: it.id }]) && setState({ selection: [] })}>Delete</button>
      </section>
    </div>
  );
};
