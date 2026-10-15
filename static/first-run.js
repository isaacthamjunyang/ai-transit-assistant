/* First-run explainer flag: whether this phone has seen (or skipped) "How it works". One versioned key in this phone's
   localStorage, validated on every read. Nothing here is sent anywhere, written to a URL or logged, and it makes no
   network call. When storage is unavailable (private mode, blocked) the flag lives in memory for the session and
   storageAvailable() says false, so the card can still be shown once and closed. The page (index.html) draws the card
   and never touches storage. */
(function (root) {
  "use strict";

  var KEY = "bus-catch-first-run-v1";
  var VERSION = 1;
  var memoryDone = false;

  function storage() {
    try {
      return root.localStorage || null;
    } catch (error) {
      return null;
    }
  }

  // Valid only as the exact object this module writes: {"v":1,"done":true}. Anything else counts as "not seen".
  function validStored(raw) {
    if (typeof raw !== "string" || raw.length > 64) {
      return false;
    }
    try {
      var value = JSON.parse(raw);
      return !!value && typeof value === "object" && value.v === VERSION && value.done === true;
    } catch (error) {
      return false;
    }
  }

  function isDone() {
    if (memoryDone) {
      return true;
    }
    var store = storage();
    if (!store) {
      return false;
    }
    try {
      return validStored(store.getItem(KEY));
    } catch (error) {
      return false;
    }
  }

  function markDone() {
    memoryDone = true;
    var store = storage();
    if (!store) {
      return false;
    }
    try {
      store.setItem(KEY, JSON.stringify({ v: VERSION, done: true }));
      return true;
    } catch (error) {
      return false;
    }
  }

  function storageAvailable() {
    var store = storage();
    if (!store) {
      return false;
    }
    try {
      var probe = KEY + "-probe";
      store.setItem(probe, "1");
      store.removeItem(probe);
      return true;
    } catch (error) {
      return false;
    }
  }

  root.FirstRun = { KEY: KEY, VERSION: VERSION, isDone: isDone, markDone: markDone, storageAvailable: storageAvailable };
})(typeof window !== "undefined" ? window : this);
