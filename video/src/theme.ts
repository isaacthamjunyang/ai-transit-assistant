// The app's own tokens, read from static/theme.css by scripts/read-theme.mjs. The video is dark: the captures are dark.
import data from "./generated/theme.json";

type Tokens = Record<string, string>;

export const T = data.dark as Tokens;
export const FONT = T["font-stack"];

// the background: the app's dark paper into its dark secondary surface
export const BACKGROUND = `linear-gradient(165deg, ${T["color-paper"]} 0%, ${T["color-secondary"]} 100%)`;
