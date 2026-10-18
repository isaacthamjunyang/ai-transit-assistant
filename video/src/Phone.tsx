import React from "react";
import { OffthreadVideo, staticFile } from "remotion";
import { FPS, PHONE, SAMPLE_NOTE, Scene } from "./constants";
import { FONT, T } from "./theme";

// A plain phone frame (the app's own line and card colours) around one capture. The capture is 1170 x 2532 (390 x 844 CSS px at 3x).
const SCREEN_W = PHONE.width;
const SCREEN_H = Math.round((PHONE.width * 844) / 390);

export const Phone: React.FC<{ scene: Scene }> = ({ scene }) => (
  <>
    <div
      style={{
        position: "absolute", left: (1080 - SCREEN_W) / 2 - PHONE.bezel, top: PHONE.top - PHONE.bezel,
        width: SCREEN_W + PHONE.bezel * 2, height: SCREEN_H + PHONE.bezel * 2, borderRadius: PHONE.radius + PHONE.bezel,
        background: T["color-line"], boxShadow: "0 40px 90px rgb(0 0 0 / 0.5)", border: `2px solid ${T["color-muted"]}`, boxSizing: "border-box",
      }}
    />
    <div
      style={{
        position: "absolute", left: (1080 - SCREEN_W) / 2, top: PHONE.top, width: SCREEN_W, height: SCREEN_H, borderRadius: PHONE.radius,
        overflow: "hidden", background: T["color-paper"],
      }}
    >
      <OffthreadVideo
        src={staticFile(scene.clip)}
        startFrom={Math.round(scene.from * FPS)}
        playbackRate={scene.rate}
        muted
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
    </div>
    <div
      style={{
        position: "absolute", left: 0, right: 0, top: PHONE.top + SCREEN_H + PHONE.bezel + PHONE.noteGap, textAlign: "center",
        fontFamily: FONT, fontSize: 28, color: T["color-muted"],
      }}
    >
      {SAMPLE_NOTE}
    </div>
  </>
);
