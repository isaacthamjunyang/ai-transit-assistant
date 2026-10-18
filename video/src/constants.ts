// Every number that decides when something happens, how long it lasts and how it eases lives here and nowhere else.
import { Easing } from "remotion";

export const FPS = 30;
export const WIDTH = 1080;
export const HEIGHT = 1920;

export const sec = (seconds: number) => Math.round(seconds * FPS);

// ---- easing ---------------------------------------------------------------------------------------------------------------------
export const EASE = {
  // gentle, no overshoot, no bounce: nothing flashes or snaps
  in: Easing.bezier(0.22, 0.61, 0.36, 1),
  out: Easing.bezier(0.4, 0, 0.6, 1),
  slide: Easing.bezier(0.16, 1, 0.3, 1),
};

// ---- timing (seconds unless the name says frames) -------------------------------------------------------------------------------
export const TIMING = {
  hook: 3.6, // the opening card
  end: 4.0, // the closing card
  fade: 0.4, // the cross-fade between two neighbours (they overlap by this much)
  captionIn: 0.45, // the caption's fade and rise
  captionRise: 22, // pixels the caption rises while it fades in
  captionDelay: 0.12, // the caption starts this long after its scene
  hookLineGap: 1.0, // the second sentence of the hook card arrives this long after the first
  hookIn: 0.7,
  endIn: 0.7,
  endLineGap: 0.35,
};

// ---- the things you will want to edit -------------------------------------------------------------------------------------------------
export const APP_NAME = "Just-In-Time";
export const GITHUB_URL = "{GITHUB_URL}"; // replace with the repository link before rendering for LinkedIn
export const APP_URL = "{APP_URL}"; // replace with the live app link
export const DATA_CREDIT = "Data: LTA DataMall, OneMap";
export const SAMPLE_NOTE = "Captured from the real app with sample data"; // small line under the phone: the places and stops are made up
export const HOOK = {
  first: "Google Maps tells you how to get there.",
  second: "Just-In-Time tells you whether you'll catch it.",
};

// Music: put a royalty-free track at video/assets/music.mp3 (nothing is downloaded or bundled). It is looped or trimmed to the video.
// Without the file the render is muted. scripts/prepare.mjs records whether it exists in src/generated/audio.json.
export const AUDIO_VOLUME = 0.35;
export const AUDIO_FADE_IN = 1; // seconds
export const AUDIO_FADE_OUT = 2; // seconds

// ---- the phone ------------------------------------------------------------------------------------------------------------------
export const PHONE = {
  width: 600, // the screen is 390 x 844 CSS px, so its height follows
  bezel: 14,
  radius: 70,
  top: 480, // distance from the top of the video to the top of the phone
  noteGap: 34, // between the phone and the sample-data note
  captionTop: 150,
  captionHeight: 280,
};

// ---- the scenes -----------------------------------------------------------------------------------------------------------------------
// clip: the capture in video/assets/; from: where in the clip to start (s); show: how long the scene is on screen (s);
// rate: playback speed (the captures are real time; > 1 skips the waiting). caption: eight words at most.
export type Scene = { id: string; clip: string; caption: string; sub?: string; from: number; show: number; rate: number };

export const SCENES: Scene[] = [
  { id: "01", clip: "01-home.webm", caption: "Pick a saved place and arrival time", from: 0.4, show: 4.0, rate: 1.3 },
  { id: "02", clip: "02-stops.webm", caption: "We plan it, or route to a stop you pick", from: 0.3, show: 4.8, rate: 1.9 },
  { id: "03", clip: "03-theme.webm", caption: "Light or dark, your choice", from: 0.5, show: 3.6, rate: 2.1 },
  { id: "04", clip: "04-overview.webm", caption: "Pick a priority, see time, transfers, walking", from: 0.2, show: 4.4, rate: 2.0 },
  { id: "05", clip: "05-arrivals.webm", caption: "Live bus times and seats", from: 0.4, show: 5.0, rate: 1.5 },
  { id: "06", clip: "06-mrt.webm", caption: "Scheduled MRT times", from: 0.4, show: 4.6, rate: 1.5 },
  { id: "07", clip: "07-pagea.webm", caption: "Leave-by from your own walking speed", from: 0.5, show: 13.0, rate: 1.1 },
  { id: "08", clip: "08-walk.webm", caption: "Track your walk to the stop", from: 1.4, show: 6.5, rate: 1.7 },
  { id: "09", clip: "09-getoff.webm", caption: "Get-off alert as you near your stop", sub: "Works while the app is open", from: 0.6, show: 4.4, rate: 2.2 },
  { id: "10", clip: "10-pagec.webm", caption: "Missed it? Instant alternatives", from: 0.4, show: 3.8, rate: 1.65 },
  { id: "11", clip: "11-nomode.webm", caption: "No transit? Open a ride app", from: 0.4, show: 3.6, rate: 2.2 },
  { id: "12", clip: "12-alert.webm", caption: "Warned of train disruptions", from: 0.4, show: 3.6, rate: 2.1 },
];

// ---- the timeline, worked out from the numbers above -----------------------------------------------------------------------------
const overlap = sec(TIMING.fade);
export type Placed = { kind: "hook" | "scene" | "end"; scene?: Scene; from: number; frames: number };

export function timeline(): { items: Placed[]; total: number } {
  const items: Placed[] = [];
  let cursor = 0;
  const add = (kind: Placed["kind"], seconds: number, scene?: Scene) => {
    const frames = sec(seconds);
    items.push({ kind, scene, from: cursor, frames });
    cursor += frames - overlap;
  };
  add("hook", TIMING.hook);
  SCENES.forEach((scene) => add("scene", scene.show, scene));
  add("end", TIMING.end);
  const last = items[items.length - 1];
  return { items, total: last.from + last.frames };
}

export const TOTAL_FRAMES = timeline().total;
export const FADE_FRAMES = overlap;
