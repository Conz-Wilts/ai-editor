// Render: pick formats and where (this computer, GitHub Actions on the editor's repo with the media encrypted,
// or Modal). It queues a job on the home server (POST /job type=render); Claude exports the timeline
// (project.py export) and renders each format (edit.py render), reporting progress here.
import React, { useEffect, useState } from "react";
import { render, useStore } from "./store";

const TARGETS: [string, string, string][] = [
  ["laptop", "This computer", "Free. Often fastest for a short video."],
  ["github", "GitHub Actions", "Free on the public repo. Footage and the result are encrypted."],
  ["modal", "Modal", "Pay as you go, many machines at once."],
];

export const RenderPanel: React.FC = () => {
  const doc = useStore((s) => s.doc);
  const edit = useStore((s) => s.edit);
  const formats = useStore((s) => s.formats);
  const jobs = useStore((s) => s.jobs);
  const listening = useStore((s) => s.listening);
  const [pick, setPick] = useState<string[]>([]);
  const [target, setTarget] = useState("laptop");
  useEffect(() => { if (doc?.format) setPick((p) => (p.length ? p : [doc.format!])); }, [doc?.format]);
  if (!doc) return null;
  const mine = jobs.filter((j) => (j.type === "render" || j.type === "ask") && j.args?.edit === edit).slice(-6).reverse();
  const toggle = (id: string) => setPick((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  return (
    <div className="render">
      <h4>Formats</h4>
      <div className="fmts">
        {Object.entries(formats).map(([id, f]) => (
          <label key={id} className="chk"><input type="checkbox" checked={pick.includes(id)} onChange={() => toggle(id)} />
            {f.label} <small>{f.width}×{f.height}</small></label>
        ))}
      </div>
      <h4>Where</h4>
      {TARGETS.map(([id, name, why]) => (
        <label key={id} className="radio"><input type="radio" name="target" checked={target === id} onChange={() => setTarget(id)} />
          <span><b>{name}</b><small>{why}</small></span></label>
      ))}
      <button className="primary big" disabled={!pick.length} onClick={() => render(pick, target)}>
        Render {pick.length > 1 ? `${pick.length} formats` : ""}
      </button>
      {!listening ? <p className="hint">No Claude is connected right now; one opens in a Terminal window for the render.</p> : null}
      {mine.length ? <h4>Jobs</h4> : null}
      {mine.map((j) => {
        const last = (j.steps ?? [])[(j.steps ?? []).length - 1];
        return (
          <div key={j.id} className={`job s-${j.state}`}>
            <b>{j.type === "render" ? `Render ${(j.args.formats ?? []).join(", ") || ""} on ${j.args.target}` : `Ask: ${j.args.text}`}</b>
            <small>{j.state}{last ? ` · ${last.step ?? ""}${last.detail ? ` (${last.detail})` : ""}` : ""}</small>
            {typeof last?.progress === "number" && j.state !== "done" ? <div className="bar"><div style={{ width: `${last.progress * 100}%` }} /></div> : null}
            {j.result && typeof j.result === "object" && Object.keys(j.result).length
              ? <small className="res">{j.result.message ?? j.result.video ?? JSON.stringify(j.result).slice(0, 160)}</small> : null}
          </div>
        );
      })}
    </div>
  );
};
