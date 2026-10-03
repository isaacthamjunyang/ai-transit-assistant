import { openHome, planOverview, state } from "./common.mjs";

export default async function (h) {
  const out = {};
  await openHome(h, { permission: "granted" });
  await planOverview(h);
  await h.eval("showDemoChrome(true); true");
  await h.eval("document.getElementById('start-journey').click(); true");
  await h.until("monitoringActive === true", 10000, "polling");
  await h.sleep(500);
  out.state = await h.eval(state);
  out.permission = await h.eval("__motion.permission.calls");
  out.query = await h.eval("walkSpeedQuery()");
  return out;
}
