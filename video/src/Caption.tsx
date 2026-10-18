import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { EASE, FADE_FRAMES, PHONE, sec, TIMING } from "./constants";
import { FONT, T } from "./theme";

// The burned-in caption above the phone: at most eight words, plus an optional small second line. It fades in with a small rise and
// leaves with its scene.
export const Caption: React.FC<{ text: string; sub?: string; frames: number }> = ({ text, sub, frames }) => {
  const frame = useCurrentFrame();
  const start = sec(TIMING.captionDelay);
  const progress = interpolate(frame, [start, start + sec(TIMING.captionIn)], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE.in });
  const leave = interpolate(frame, [frames - FADE_FRAMES, frames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div
      style={{
        position: "absolute", left: 80, right: 80, top: PHONE.captionTop, height: PHONE.captionHeight,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center",
        opacity: progress * leave, transform: `translateY(${(1 - progress) * TIMING.captionRise}px)`,
        fontFamily: FONT, color: T["color-ink"],
      }}
    >
      <div style={{ fontSize: 76, lineHeight: 1.12, fontWeight: 800, letterSpacing: -1 }}>{text}</div>
      {sub ? <div style={{ marginTop: 20, fontSize: 40, lineHeight: 1.2, fontWeight: 500, color: T["color-muted"] }}>{sub}</div> : null}
    </div>
  );
};
