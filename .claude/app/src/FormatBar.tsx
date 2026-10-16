// The frame: which format the project is cut for (formats.json: YouTube, Shorts, TikTok, Reels, 4:5, 1:1...),
// the platform's safe zone over the preview, and the design system its graphics use.
import React from "react";
import { dispatch, loadPlan, setFormat, setState, useStore } from "./store";

export const FormatBar: React.FC = () => {
  const doc = useStore((s) => s.doc);
  const formats = useStore((s) => s.formats);
  const showSafe = useStore((s) => s.showSafe);
  const systems = useStore((s) => s.systems);
  if (!doc) return null;
  const ids = Object.keys(formats);
  const sys = systems?.find((x) => x.id === doc.designSystem);
  return (
    <div className="formatbar">
      <label title="The frame this project is cut for. Render can make other formats from it.">
        <span>Format</span>
        <select value={doc.format ?? ""} onChange={(e) => setFormat(e.target.value)}>
          {!doc.format || !formats[doc.format] ? <option value="">{doc.width}×{doc.height}</option> : null}
          {ids.map((id) => <option key={id} value={id}>{formats[id].label}</option>)}
        </select>
      </label>
      <label className="chk" title="The platform's buttons and captions cover what is outside it">
        <input type="checkbox" checked={showSafe} onChange={(e) => setState({ showSafe: e.target.checked })} /> Safe zone
      </label>
      {systems ? (
        <label title="Colours, type and motion for the graphics (design systems)">
          <span>Design</span>
          {sys?.swatch ? <i className="swatch">{[sys.swatch.ground, sys.swatch.ink, sys.swatch.accent].map((c, i) => <b key={i} style={{ background: c }} />)}</i> : null}
          <select value={doc.designSystem ?? ""} onChange={(e) => {
            if (dispatch("Design system", [{ op: "setProject", set: { designSystem: e.target.value || null } }])) loadPlan(40);
          }}>
            <option value="">The style's own look</option>
            {systems.map((s) => <option key={s.id} value={s.id}>{s.name}{s.source === "user" ? " (yours)" : ""}</option>)}
          </select>
        </label>
      ) : null}
    </div>
  );
};
