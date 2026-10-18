import React from "react";
import { Composition } from "remotion";
import { FPS, HEIGHT, TOTAL_FRAMES, WIDTH } from "./constants";
import { JustInTime } from "./JustInTime";

export const Root: React.FC = () => (
  <Composition id="JustInTime" component={JustInTime} durationInFrames={TOTAL_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
);
