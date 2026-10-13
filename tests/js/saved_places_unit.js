// Runs static/saved-places.js in a fresh sandbox per case with a fake localStorage (no browser, no network) and prints
// the results as JSON. Used by tests/test_saved_places.py.
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SOURCE = fs.readFileSync(path.join(__dirname, "..", "..", "static", "saved-places.js"), "utf8");
const KEY = "bus-catch-saved-places-v1";

function memoryStorage(initial, options) {
  const data = Object.assign({}, initial || {});
  const calls = { set: 0, get: 0 };
  return {
    data, calls,
    getItem(key) { calls.get += 1; return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null; },
    setItem(key, value) {
      calls.set += 1;
      if (options && options.failWrites) { throw new Error("QuotaExceededError"); }
      data[key] = String(value);
    },
    removeItem(key) { delete data[key]; }
  };
}

function load(storage, throwing) {
  const sandbox = { module: { exports: {} }, Date, JSON, Array, Object, Math, isFinite, String, Number };
  if (throwing) {
    Object.defineProperty(sandbox, "localStorage", { get() { throw new Error("SecurityError"); } });
  } else if (storage) {
    sandbox.localStorage = storage;
  }
  vm.runInNewContext(SOURCE, sandbox);
  return { api: sandbox.module.exports, sandbox };
}

const NUS = { name: "Uni", address: "21 Lower Kent Ridge Road", latitude: 1.29667, longitude: 103.77639 };
const out = {};

// add, trim, order
{
  const store = memoryStorage();
  const { api } = load(store);
  const first = api.add(Object.assign({}, NUS, { name: "  Uni   " }));
  const second = api.add({ name: "Shops", address: "Orchard", latitude: 1.30421, longitude: 103.83197 });
  out.add = { first: first.ok, stored: first.stored, second: second.ok, names: api.list().map((p) => p.name),
              raw: JSON.parse(store.data[KEY]), max: api.MAX, nameMax: api.NAME_MAX };
}
// empty, too long, duplicate (same point, different name), full
{
  const { api } = load(memoryStorage());
  out.errors = {
    empty: api.add(Object.assign({}, NUS, { name: "   " })),
    tooLong: api.add(Object.assign({}, NUS, { name: "x".repeat(25) })),
    exactly24: api.add(Object.assign({}, NUS, { name: "y".repeat(24) })).ok,
    duplicate: api.add(Object.assign({}, NUS, { name: "Other name" })),
    invalid: api.add({ name: "Nowhere", address: "", latitude: "1.3", longitude: 103.8 })
  };
  for (let i = 0; i < 4; i += 1) {
    api.add({ name: "P" + i, address: "", latitude: 1.31 + i * 0.01, longitude: 103.81 });
  }
  out.errors.full = api.add({ name: "Sixth", address: "", latitude: 1.4, longitude: 103.9 });
  out.errors.count = api.list().length;
}
// rename and remove
{
  const { api } = load(memoryStorage());
  const id = api.add(NUS).place.id;
  out.edit = { renamed: api.rename(id, "  Campus ").ok, name: api.list()[0].name,
               empty: api.rename(id, " ").error, long: api.rename(id, "z".repeat(30)).error,
               missing: api.rename("nope", "Name").error };
  out.remove = { removed: api.remove(id).ok, left: api.list().length, again: api.remove(id).error };
}
// malformed storage: dropped on read, capped at five, never throws
{
  const places = [
    { id: "a", name: "Good", address: "x", latitude: 1.3, longitude: 103.8 },
    { id: "b", name: "", address: "x", latitude: 1.3, longitude: 103.8 },
    { id: "c", name: "No point", address: "x" },
    { id: "d", name: "Far", address: "x", latitude: 999, longitude: 103.8 },
    { id: "e", name: "w".repeat(40), address: "x", latitude: 1.31, longitude: 103.81 },
    "junk", null, 7,
    { id: "g", name: "Two", address: "y", latitude: 1.32, longitude: 103.82 },
    { id: "g", name: "Same id", address: "y", latitude: 1.33, longitude: 103.83 },
    { id: "h", name: "Repeat point", address: "y", latitude: 1.32, longitude: 103.82 },
    { id: "i", name: "Four", address: "y", latitude: 1.34, longitude: 103.84 },
    { id: "j", name: "Five", address: "y", latitude: 1.35, longitude: 103.85 },
    { id: "k", name: "Six", address: "y", latitude: 1.36, longitude: 103.86 },
    { id: "l", name: "Seven", address: "y", latitude: 1.37, longitude: 103.87 }
  ];
  const cases = {
    mixed: JSON.stringify({ v: 1, places }),
    wrongVersion: JSON.stringify({ v: 2, places }),
    notJson: "{not json",
    notObject: "42",
    noList: JSON.stringify({ v: 1 }),
    nullText: "null"
  };
  out.malformed = {};
  Object.keys(cases).forEach((name) => {
    const { api } = load(memoryStorage({ [KEY]: cases[name] }));
    out.malformed[name] = api.list().map((p) => p.name);
  });
  const { api } = load(memoryStorage({ [KEY]: cases.mixed }));
  out.malformed.ids = api.list().map((p) => p.id);
}
// storage that throws on access (private mode): the feature works in memory and says it cannot keep the list
{
  const { api } = load(null, true);
  const before = api.storageAvailable();
  const added = api.add(NUS);
  out.unavailable = { before, ok: added.ok, stored: added.stored, names: api.list().map((p) => p.name),
                      after: api.storageAvailable(), renamed: api.rename(added.place.id, "Campus").ok,
                      renamedName: api.list()[0].name };
}
// storage that refuses writes (quota): the session copy wins and a read does not bring back the old list
{
  const store = memoryStorage({}, { failWrites: true });
  const { api } = load(store);
  const added = api.add(NUS);
  out.quota = { ok: added.ok, stored: added.stored, names: api.list().map((p) => p.name), after: api.storageAvailable() };
}
// no localStorage at all
{
  const { api } = load(null, false);
  out.missing = { ok: api.add(NUS).ok, names: api.list().map((p) => p.name), available: api.storageAvailable() };
}
// the file itself: no network, no URL, no logging
out.source = {
  fetch: /\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|Image\s*\(|location|console\./.test(SOURCE),
  sessionStorage: /sessionStorage|indexedDB|document\.cookie/.test(SOURCE),
  usesKey: SOURCE.split(KEY).length - 1
};
console.log(JSON.stringify(out));
