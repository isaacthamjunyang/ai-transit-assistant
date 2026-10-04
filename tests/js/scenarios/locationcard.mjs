import { toLive, poll } from "./common.mjs";

// The Location uncertain card says what the server saw in this poll, whatever the phone thinks now.
export default async function (h) {
  const out = {};
  await toLive(h, { permission: "granted" });
  await poll(h);
  out.phone = await h.eval("({accuracy: userAccuracy, ageMs: Date.now() - userLocationTimestamp})");
  const cases = [
    ["age", { data_quality: "location uncertain", location_reason: "age", location_age_s: 95, location_accuracy_m: 22 }],
    ["accuracy", { data_quality: "location uncertain", location_reason: "accuracy", location_age_s: 3, location_accuracy_m: 140 }],
    ["both", { data_quality: "location uncertain", location_reason: "accuracy", location_age_s: 150, location_accuracy_m: 140 }],
    ["neither-uncertain", { data_quality: "location uncertain", location_reason: null, location_age_s: 5, location_accuracy_m: 22 }],
    ["neither-live", { data_quality: "live", location_reason: null, location_age_s: 5, location_accuracy_m: 22 }]
  ];
  out.cards = {};
  for (const [name, fields] of cases) {
    out.cards[name] = await h.eval(`(function () {
      var chance = featuredBus(lastSuccess.buses).probability;
      Object.assign(chance, ${JSON.stringify(fields)});
      syncQuality();
      var card = document.getElementById("location-card");
      return {hidden: card.hidden, body: document.getElementById("location-card-body").textContent,
        title: document.getElementById("location-card-title").textContent};
    })()`);
  }
  return out;
}
