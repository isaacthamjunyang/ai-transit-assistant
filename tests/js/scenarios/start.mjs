import { openHome, planOverview, state, toLive } from "./common.mjs";

export default async function (h) {
  const out = {};
  await openHome(h, { permission: h.config.permission || "granted" });
  out.afterLoad = await h.eval(state);
  out.permissionCallsOnLoad = await h.eval("__motion.permission.calls");
  await planOverview(h);
  out.onOverview = await h.eval(state);
  out.permissionCallsOnOverview = await h.eval("__motion.permission.calls");
  out.requestsBeforeStart = await h.eval("__requests.slice()");
  await h.eval("document.getElementById('start-journey').click(); true");
  await h.until("monitoringActive === true", 10000, "polling");
  await h.sleep(500);
  out.afterTap = await h.eval(state);
  out.permission = await h.eval("({calls: __motion.permission.calls, duringClick: __motion.permission.duringClick})");
  out.geoCalls = await h.eval("__geo.state.getCalls");
  return out;
}
