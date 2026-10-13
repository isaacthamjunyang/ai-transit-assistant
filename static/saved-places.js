/* Saved places: up to five places the user named, kept in this phone's localStorage only (one versioned key).
   A place is a name, an address and a point. Nothing here is sent anywhere, written to a URL, logged or stored
   elsewhere, and it makes no network call. Every read is validated: a malformed entry is dropped and the list is cut to
   five. When storage is unavailable (private mode, blocked) the places live in memory for the session and
   storageAvailable() says false. The page (index.html) draws the row and the panels and never touches storage. */
(function (root) {
  "use strict";

  var KEY = "bus-catch-saved-places-v1";
  var VERSION = 1;
  var MAX = 5;
  var NAME_MAX = 24;
  var ADDRESS_MAX = 200;
  var memory = [];
  var counter = 0;
  var lastWriteOk = true;

  function storage() {
    try {
      return root.localStorage || null;
    } catch (error) {
      return null;
    }
  }

  function finite(value) {
    return typeof value === "number" && isFinite(value);
  }

  function cleanName(value) {
    return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
  }

  // The same point to about a metre: the key a duplicate is judged by.
  function pointKey(latitude, longitude) {
    return latitude.toFixed(5) + "," + longitude.toFixed(5);
  }

  function validEntry(entry) {
    if (!entry || typeof entry !== "object") {
      return null;
    }
    var name = cleanName(entry.name);
    var address = typeof entry.address === "string" ? entry.address.trim() : "";
    if (!name || name.length > NAME_MAX || address.length > ADDRESS_MAX) {
      return null;
    }
    if (!finite(entry.latitude) || !finite(entry.longitude)
      || Math.abs(entry.latitude) > 90 || Math.abs(entry.longitude) > 180) {
      return null;
    }
    var id = typeof entry.id === "string" && /^[A-Za-z0-9_-]{1,40}$/.test(entry.id) ? entry.id : null;
    return { id: id, name: name, address: address, latitude: entry.latitude, longitude: entry.longitude };
  }

  function newId() {
    counter += 1;
    return "p" + Date.now().toString(36) + counter.toString(36);
  }

  // Keep valid entries in order, give each an id, drop a repeat of the same point, cap at five.
  function clean(list) {
    var out = [];
    var seen = {};
    var ids = {};
    (Array.isArray(list) ? list : []).forEach(function (raw) {
      var entry = validEntry(raw);
      if (!entry || out.length >= MAX) {
        return;
      }
      var key = pointKey(entry.latitude, entry.longitude);
      if (seen[key]) {
        return;
      }
      if (!entry.id || ids[entry.id]) {
        entry.id = newId();
      }
      seen[key] = true;
      ids[entry.id] = true;
      out.push(entry);
    });
    return out;
  }

  function read() {
    var store = storage();
    if (!store || !lastWriteOk) {  // after a failed write the session copy is the truth
      return memory.slice();
    }
    var text;
    try {
      text = store.getItem(KEY);
    } catch (error) {
      return memory.slice();  // storage cannot be read: the session copy
    }
    if (text === null || text === undefined) {
      return [];
    }
    try {
      var data = JSON.parse(text);
      if (!data || data.v !== VERSION || !Array.isArray(data.places)) {
        return [];
      }
      return clean(data.places);
    } catch (error) {
      return [];  // not JSON: nothing is trusted
    }
  }

  function write(list) {
    memory = list.slice();
    var store = storage();
    if (!store) {
      lastWriteOk = false;
      return false;
    }
    try {
      store.setItem(KEY, JSON.stringify({ v: VERSION, places: list }));
      lastWriteOk = true;
      return true;
    } catch (error) {
      lastWriteOk = false;
      return false;
    }
  }

  function copy(entry) {
    return { id: entry.id, name: entry.name, address: entry.address, latitude: entry.latitude, longitude: entry.longitude };
  }

  var api = {
    KEY: KEY,
    MAX: MAX,
    NAME_MAX: NAME_MAX,

    // The saved places, oldest first (most recent last).
    list: function () {
      return read().map(copy);
    },

    // place: { name, address, latitude, longitude }. Returns { ok: true, stored } or { ok: false, error } where error is
    // "name" (empty), "long" (over 24 characters), "invalid" (no usable point), "duplicate" or "full".
    add: function (place) {
      var name = cleanName(place && place.name);
      if (!name) {
        return { ok: false, error: "name" };
      }
      if (name.length > NAME_MAX) {
        return { ok: false, error: "long" };
      }
      var entry = validEntry({
        name: name, address: place.address, latitude: place.latitude, longitude: place.longitude
      });
      if (!entry) {
        return { ok: false, error: "invalid" };
      }
      var list = read();
      if (list.length >= MAX) {
        return { ok: false, error: "full" };
      }
      var key = pointKey(entry.latitude, entry.longitude);
      if (list.some(function (item) { return pointKey(item.latitude, item.longitude) === key; })) {
        return { ok: false, error: "duplicate" };
      }
      entry.id = newId();
      list.push(entry);
      return { ok: true, stored: write(list), place: copy(entry) };
    },

    rename: function (id, name) {
      var next = cleanName(name);
      if (!next) {
        return { ok: false, error: "name" };
      }
      if (next.length > NAME_MAX) {
        return { ok: false, error: "long" };
      }
      var list = read();
      var found = list.filter(function (item) { return item.id === id; })[0];
      if (!found) {
        return { ok: false, error: "missing" };
      }
      found.name = next;
      return { ok: true, stored: write(list) };
    },

    remove: function (id) {
      var list = read();
      var kept = list.filter(function (item) { return item.id !== id; });
      if (kept.length === list.length) {
        return { ok: false, error: "missing" };
      }
      return { ok: true, stored: write(kept) };
    },

    // False when this phone cannot keep the list (private mode, blocked storage): it then lasts for the session only.
    storageAvailable: function () {
      var store = storage();
      if (!store) {
        return false;
      }
      return lastWriteOk;
    }
  };

  root.SavedPlaces = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
