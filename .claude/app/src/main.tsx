// ai-editor: the app. Media bin on the left, the edit playing in the middle, the inspector / components / render
// on the right, the timeline along the bottom. Claude edits the same project (project.py apply) and its changes
// arrive as toasts; "Ask Claude" sends it a request about this edit.
import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { AssetBin } from "./AssetBin";
import { ChangeToasts } from "./ChangeToasts";
import { FormatBar } from "./FormatBar";
import { Gallery, addComponent } from "./Gallery";
import { Inspector } from "./Inspector";
import { Preview } from "./Preview";
import { RenderPanel } from "./RenderPanel";
import { Timeline } from "./Timeline/Timeline";
import { timecode } from "./Timeline/zoom";
import * as store from "./store";
import {
  ask, boot, deleteSelected, getState, newProject, openProject, redo, seek, setState, splitAtPlayhead, undo,
  uploadFiles, useStore, zoomBy,
} from "./store";

const NewProject: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const formats = useStore((s) => s.formats);
  const [name, setName] = useState("");
  const [fmt, setFmt] = useState("youtube");
  return (
    <div className="modal" onClick={onClose}>
      <form className="dialog" onClick={(e) => e.stopPropagation()} onSubmit={(e) => { e.preventDefault(); newProject(name, fmt); onClose(); }}>
        <h3>New project</h3>
        <label><span>Name</span><input autoFocus value={name} placeholder="My video" onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.stopPropagation()} /></label>
        <label><span>Format</span>
          <div className="fmtpick">
            {Object.entries(formats).filter(([id]) => ["youtube", "shorts", "tiktok", "reels", "ig-4x5", "square", "youtube-4k", "vertical"].includes(id))
              .map(([id, f]) => (
                <button type="button" key={id} className={fmt === id ? "on" : ""} onClick={() => setFmt(id)}>
                  <i style={{ aspectRatio: `${f.width}/${f.height}` }} /><b>{f.label}</b><small>{f.width}×{f.height}</small>
                </button>
              ))}
          </div>
        </label>
        <div className="row-end"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Create</button></div>
      </form>
    </div>
  );
};

const Header: React.FC = () => {
  const projects = useStore((s) => s.projects);
  const edit = useStore((s) => s.edit);
  const doc = useStore((s) => s.doc);
  const listening = useStore((s) => s.listening);
  const [making, setMaking] = useState(false);
  return (
    <header>
      <b className="logo">ai-editor</b>
      <select className="proj" value={edit ?? ""} onChange={(e) => (e.target.value === "+" ? setMaking(true) : openProject(e.target.value))}>
        {!edit ? <option value="">Open a project…</option> : null}
        {projects.map((p) => <option key={p.edit} value={p.edit}>{p.name}</option>)}
        <option value="+">+ New project…</option>
      </select>
      <button onClick={() => setMaking(true)}>New</button>
      <span className="sep" />
      <button onClick={() => undo()} disabled={!doc} title="Undo (Ctrl+Z)">↶</button>
      <button onClick={() => redo()} disabled={!doc} title="Redo (Ctrl+Shift+Z)">↷</button>
      <span className="sep" />
      <FormatBar />
      <span className="grow" />
      <span className={`claude ${listening ? "on" : ""}`} title={listening ? "A Claude is connected and takes jobs from here" : "No Claude listening; one opens when you render or ask"}>
        <i /> Claude {listening ? "connected" : "idle"}
      </span>
      <a className="home" href="/" title="Styles, setup and your videos (the home page)">Home</a>
      {making ? <NewProject onClose={() => setMaking(false)} /> : null}
    </header>
  );
};

const Transport: React.FC = () => {
  const playing = useStore((s) => s.playing);
  const frame = useStore((s) => s.frame);
  const fps = useStore((s) => s.doc?.fps ?? 30);
  const dur = useStore((s) => s.plan?.durationInFrames ?? 0);
  const [text, setText] = useState("");
  return (
    <div className="transport">
      <button onClick={() => seek(0)} title="Start (Home)">⏮</button>
      <button className="play" onClick={() => window.dispatchEvent(new Event("ai-editor:toggle"))} title="Play / pause (Space)">{playing ? "❚❚" : "▶"}</button>
      <span className="time">{timecode(frame, fps, true)} / {timecode(dur, fps)}</span>
      <form className="ask" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { ask(text.trim()); setText(""); } }}>
        <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.stopPropagation()}
          placeholder="Ask Claude: “add a zoom when I say launch”, “tighten the pauses”, “a lower third with my name”…" />
        <button className="primary" disabled={!text.trim()}>Ask</button>
      </form>
    </div>
  );
};

const Side: React.FC = () => {
  const panel = useStore((s) => s.panel);
  return (
    <aside className="side">
      <nav className="tabs">
        {(["inspector", "gallery", "render"] as const).map((p) => (
          <button key={p} className={panel === p ? "on" : ""} onClick={() => setState({ panel: p })}>
            {p === "inspector" ? "Inspector" : p === "gallery" ? "Components" : "Render"}
          </button>
        ))}
      </nav>
      <div className="side-body">{panel === "inspector" ? <Inspector /> : panel === "gallery" ? <Gallery /> : <RenderPanel />}</div>
    </aside>
  );
};

const App: React.FC = () => {
  const doc = useStore((s) => s.doc);
  const error = useStore((s) => s.error);
  const projects = useStore((s) => s.projects);
  const [making, setMaking] = useState(false);
  useEffect(() => { boot(); }, []);

  // keys: space, S, Del, undo/redo, zoom, arrows (never while typing)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)) return;
      const mod = e.ctrlKey || e.metaKey, s = getState(), fps = s.doc?.fps ?? 30;
      if (e.code === "Space") { e.preventDefault(); window.dispatchEvent(new Event("ai-editor:toggle")); }
      else if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); (e.shiftKey ? redo : undo)(); }
      else if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); }
      else if (!mod && e.key.toLowerCase() === "s") splitAtPlayhead();
      else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); deleteSelected(); }
      else if (e.key === "+" || e.key === "=") zoomBy(1.4);
      else if (e.key === "-" || e.key === "_") zoomBy(1 / 1.4);
      else if (e.key === "ArrowLeft") { e.preventDefault(); seek(s.frame - (e.shiftKey ? fps : 1)); }
      else if (e.key === "ArrowRight") { e.preventDefault(); seek(s.frame + (e.shiftKey ? fps : 1)); }
      else if (e.key === "Home") seek(0);
      else if (e.key === "End") seek((s.plan?.durationInFrames ?? 1) - 1);
      else if (e.key === "Escape") setState({ selection: [] });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // a component dropped on the timeline (Timeline.tsx) lands at that frame
  useEffect(() => {
    const onAdd = (e: Event) => {
      const { id, frame } = (e as CustomEvent).detail;
      const c = getState().components?.find((x) => x.id === id);
      if (c) addComponent(c, frame);
    };
    window.addEventListener("ai-editor:add-component", onAdd);
    return () => window.removeEventListener("ai-editor:add-component", onAdd);
  }, []);

  // files dropped anywhere else go to the bin
  useEffect(() => {
    const over = (e: DragEvent) => { if (e.dataTransfer?.types.includes("Files")) e.preventDefault(); };
    const drop = (e: DragEvent) => {
      if (!e.dataTransfer?.files.length || (e.target as HTMLElement).closest?.(".lane, .bin")) return;
      e.preventDefault();
      uploadFiles(Array.from(e.dataTransfer.files));
    };
    window.addEventListener("dragover", over);
    window.addEventListener("drop", drop);
    return () => { window.removeEventListener("dragover", over); window.removeEventListener("drop", drop); };
  }, []);

  if (!doc) {
    return (
      <div className="app start">
        <Header />
        <main className="welcome">
          <h1>Edit a video</h1>
          <p>Start a project, drop your clips in, and cut on the timeline. Claude can do any step for you: ask it in plain words.</p>
          <div className="row-c"><button className="primary big" onClick={() => setMaking(true)}>New project</button></div>
          {projects.length ? <><h3>Or open one</h3><div className="projlist">
            {projects.map((p) => <button key={p.edit} onClick={() => openProject(p.edit)}><b>{p.name}</b><small>{p.project ? `edited · rev ${p.rev}` : "from Claude's plan"}</small></button>)}
          </div></> : null}
          {error ? <p className="err">{error}</p> : null}
        </main>
        {making ? <NewProject onClose={() => setMaking(false)} /> : null}
        <ChangeToasts />
      </div>
    );
  }
  return (
    <div className="app">
      <Header />
      <AssetBin />
      <section className="center"><Preview /><Transport /></section>
      <Side />
      <Timeline />
      <ChangeToasts />
    </div>
  );
};

createRoot(document.getElementById("root")!).render(<App />);
// for the smoke test (tests/test_app.mjs) and the console: the store, read and driven like the UI drives it
(window as any).__aiEditor = store;
