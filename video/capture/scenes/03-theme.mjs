import { openHome } from "./common.mjs";

// 03 Theme: open the menu, Appearance, Light, then Dark again.
export default async function (h) {
  await openHome(h);
  const clip = await h.record("03-theme", async () => {
    await h.sleep(500);
    await h.tap("#menu-open");
    await h.sleep(500);
    await h.tap("#appearance-toggle");
    await h.sleep(500);
    await h.tap("#theme-light");
    await h.sleep(1700);
    await h.tap("#theme-dark");
    await h.sleep(1500);
    await h.tap("#menu-open");
    await h.sleep(700);
  });
  return { clip };
}
