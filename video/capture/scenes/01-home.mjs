import { openHome } from "./common.mjs";

// 01 Home: choose a saved place, then an arrive-by chip.
export default async function (h) {
  await openHome(h);
  await h.still("01-before");
  const clip = await h.record("01-home", async () => {
    await h.sleep(500);
    await h.tapText("#quick-picks button", "School");
    await h.sleep(500);
    await h.tap("#arrive-by-field");
    await h.sleep(300);
    await h.tap("#arrive-60");
    await h.sleep(900);
  });
  await h.still("01-after");
  return clip;
}
