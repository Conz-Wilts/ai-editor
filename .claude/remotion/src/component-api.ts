// What a user's own component (<library>/components/<id>/index.tsx) may import, as "../../component-api":
// gen-registry.mjs copies it to src/user-components/<id>/index.tsx, two folders below this file. Its default export
// is a React.FC<TP>: p (its props, checked against component.json's propsSchema), w and h (the card box in px),
// look (the design system's colours and fonts), m (the motion personality), fonts, dur (seconds up), id.
export type { TP } from "./Templates";
export type { Look, Fonts } from "./look";
export type { Motion } from "./motion";
export { textCase, shadowOf } from "./look";
export { useTl, landAt, dropIn, punch, exitUp, camera } from "./motion";
