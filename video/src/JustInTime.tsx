import React from "react";
import { AbsoluteFill, Audio, interpolate, Sequence, staticFile, useCurrentFrame } from "remotion";
import { Caption } from "./Caption";
import { EndCard, HookCard } from "./Cards";
import audio from "./generated/audio.json";
import { AUDIO_FADE_IN, AUDIO_FADE_OUT, AUDIO_VOLUME, FADE_FRAMES, FPS, sec, timeline, TOTAL_FRAMES } from "./constants";
import { Phone } from "./Phone";
import { BACKGROUND } from "./theme";

// One item of the timeline with a fade in at its start and a fade out at its end (neighbours overlap by FADE_FRAMES, so they cross-fade).
const Faded: React.FC<{ frames: number; first?: boolean; last?: boolean; children: React.ReactNode }> = ({ frames, first, last, children }) => {
  const frame = useCurrentFrame();
  const inn = first ? 1 : interpolate(frame, [0, FADE_FRAMES], [0, 1], { extrapolateRight: "clamp" });
  const out = last ? 1 : interpolate(frame, [frames - FADE_FRAMES, frames], [1, 0], { extrapolateLeft: "clamp" });
  return <AbsoluteFill style={{ opacity: Math.min(inn, out) }}>{children}</AbsoluteFill>;
};

// 1 s fade in, 2 s fade out at the end of the video, otherwise AUDIO_VOLUME.
const musicVolume = (frame: number) =>
  AUDIO_VOLUME *
  Math.min(
    interpolate(frame, [0, sec(AUDIO_FADE_IN)], [0, 1], { extrapolateRight: "clamp" }),
    interpolate(frame, [TOTAL_FRAMES - sec(AUDIO_FADE_OUT), TOTAL_FRAMES], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
  );

// The track, trimmed to the video or repeated end to end when it is shorter. Each copy sits in its own Sequence, so the volume
// envelope is worked out from the frame of the whole video (the copy's own frame plus where the copy starts).
const Music: React.FC<{ file: string; seconds: number }> = ({ file, seconds }) => {
  const length = Math.max(1, Math.round(seconds * FPS));
  const copies = Math.ceil(TOTAL_FRAMES / length);
  return (
    <>
      {Array.from({ length: copies }, (_, k) => (
        <Sequence key={k} from={k * length} durationInFrames={Math.min(length, TOTAL_FRAMES - k * length)} layout="none">
          <Audio src={staticFile(file)} volume={(frame) => musicVolume(k * length + frame)} />
        </Sequence>
      ))}
    </>
  );
};

export const JustInTime: React.FC = () => {
  const { items } = timeline();
  return (
    <AbsoluteFill style={{ background: BACKGROUND }}>
      {audio.file ? <Music file={audio.file} seconds={audio.seconds} /> : null}
      {items.map((item, index) => (
        <Sequence key={index} from={item.from} durationInFrames={item.frames} layout="none">
          <Faded frames={item.frames} first={index === 0} last={index === items.length - 1}>
            {item.kind === "hook" ? <HookCard frames={item.frames} /> : null}
            {item.kind === "end" ? <EndCard frames={item.frames} /> : null}
            {item.kind === "scene" && item.scene ? (
              <>
                <Phone scene={item.scene} />
                <Caption text={item.scene.caption} sub={item.scene.sub} frames={item.frames} />
              </>
            ) : null}
          </Faded>
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
