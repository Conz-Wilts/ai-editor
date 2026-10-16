// project.json (lib/ai_editor/project_schema.py): the one timeline the app and Claude both edit.
export type Box = { units: "frame" | "safe"; x: number; y: number; w: number; h: number };
export type Item = {
  id: string;
  type: "video" | "image" | "audio" | "caption" | "card" | "zoom" | "generated";
  from: number;
  durationInFrames: number;
  trimIn?: number;
  asset?: string;
  src?: string;
  component?: string;
  props?: Record<string, any>;
  box?: Box | [number, number, number, number];
  boxByFormat?: Record<string, Box>;
  entrance?: string;
  layout?: string;
  lane?: string;
  anchor?: { word: string; t: number };
  origin: "plan" | "user" | "claude";
  pinned: boolean;
  fit?: "cover" | "contain" | "reframe";
  reframe?: { f: number; cx: number; cy: number }[];
  volume?: number;
  sec?: { start?: number; end?: number };
  extra?: Record<string, any>;
  [k: string]: any;
};
export type Track = {
  id: string; kind: string; role: string; name: string; muted: boolean; hidden: boolean; locked: boolean;
  props?: Record<string, any>; items: Item[];
};
export type Asset = {
  kind: "video" | "image" | "audio"; src: string; width?: number; height?: number; fps?: number;
  durationInFrames?: number; duration?: number; hasAudio?: boolean; origin: string; name?: string; [k: string]: any;
};
export type Project = {
  schema: string; id: string; name: string; rev: number; fps: number; width: number; height: number;
  durationInFrames: number; format?: string | null; formats?: string[]; designSystem?: string | null;
  assets: Record<string, Asset>; tracks: Track[]; planExtras?: Record<string, any>; source?: Record<string, any>;
};
export type Op = Record<string, any> & { op: string };
export type Batch = { baseRev?: number; author?: "user" | "claude" | "plan"; label?: string; propose?: boolean; ops: Op[] };
export type Proposal = { id: string; label?: string; author?: string; ops: Op[]; [k: string]: any };
export type LogEntry = { rev: number; author: string; label: string; ops: Op[]; ts: number; undoOf?: number; redoOf?: number };
export type ComponentInfo = {
  id: string; name: string; kind: string; aspects?: string[]; defaultDurationS?: number; entrance?: string;
  propsSchema?: JSONSchema; tags?: string[]; preview?: string;
};
export type DesignSystem = { id: string; name: string; source?: string; swatch?: { ground?: string; ink?: string; accent?: string }; font?: string };
export type JSONSchema = {
  type?: string | string[]; title?: string; description?: string; enum?: any[]; default?: any; properties?: Record<string, JSONSchema>;
  items?: JSONSchema; minimum?: number; maximum?: number; format?: string; required?: string[];
};
export type FormatSpec = { label: string; aspect: string; width: number; height: number; platforms?: string[] };
