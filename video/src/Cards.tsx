import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { APP_NAME, APP_URL, DATA_CREDIT, EASE, FADE_FRAMES, GITHUB_URL, HOOK, sec, TIMING } from "./constants";
import { FONT, T } from "./theme";

const fade = (frame: number, start: number, length: number) =>
  interpolate(frame, [start, start + length], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE.in });

const centre: React.CSSProperties = {
  position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
  textAlign: "center", padding: "0 90px", fontFamily: FONT, color: T["color-ink"],
};

const leaving = (frame: number, frames: number) =>
  interpolate(frame, [frames - FADE_FRAMES, frames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

// The opening card: the claim in two sentences, the second one in the app's link colour.
export const HookCard: React.FC<{ frames: number }> = ({ frames }) => {
  const frame = useCurrentFrame();
  const a = fade(frame, 0, sec(TIMING.hookIn));
  const b = fade(frame, sec(TIMING.hookLineGap), sec(TIMING.hookIn));
  return (
    <div style={{ ...centre, opacity: leaving(frame, frames) }}>
      <div style={{ opacity: a, transform: `translateY(${(1 - a) * 24}px)`, fontSize: 84, lineHeight: 1.15, fontWeight: 700, color: T["color-muted"] }}>
        {HOOK.first}
      </div>
      <div style={{ height: 70 }} />
      <div style={{ opacity: b, transform: `translateY(${(1 - b) * 24}px)`, fontSize: 96, lineHeight: 1.12, fontWeight: 800, color: T["color-link"] }}>
        {HOOK.second}
      </div>
    </div>
  );
};

// The closing card: the app name, the two links and the data credit.
export const EndCard: React.FC<{ frames: number }> = ({ frames }) => {
  const frame = useCurrentFrame();
  const step = sec(TIMING.endLineGap);
  const lines = [
    { text: APP_NAME, size: 130, weight: 800, color: T["color-ink"] },
    { text: GITHUB_URL, size: 46, weight: 600, color: T["color-link"] },
    { text: APP_URL, size: 46, weight: 600, color: T["color-link"] },
    { text: DATA_CREDIT, size: 38, weight: 500, color: T["color-muted"] },
  ];
  return (
    <div style={{ ...centre, opacity: leaving(frame, frames) }}>
      {lines.map((line, index) => {
        const p = fade(frame, index * step, sec(TIMING.endIn));
        return (
          <div key={index} style={{ opacity: p, transform: `translateY(${(1 - p) * 20}px)`, fontSize: line.size, fontWeight: line.weight, color: line.color, marginTop: index === 0 ? 0 : index === 3 ? 90 : 34 }}>
            {line.text}
          </div>
        );
      })}
    </div>
  );
};
