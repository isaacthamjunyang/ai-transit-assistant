/* Injected before the page's own scripts in the browser tests. It fakes the location API and the motion
   permission, counts the devicemotion listeners, and can play a synthetic walk into the real page. */
(function () {
  var CONFIG = __CONFIG__;
  try {
    var preset = CONFIG.storage || {};
    for (var key in preset) { window.localStorage.setItem(key, preset[key]); }
  } catch (e) { /* storage blocked */ }
  var watchers = {};
  var nextId = 1;
  var geoState = { current: CONFIG.position || null, getCalls: 0, watchCalls: 0, clearCalls: 0, mode: "ok", options: [], watchOptions: [] };

  function position(o) {
    return {
      coords: {
        latitude: o.lat, longitude: o.lon, accuracy: o.acc,
        speed: o.speed === undefined ? null : o.speed, heading: o.heading === undefined ? null : o.heading, altitude: null, altitudeAccuracy: null
      },
      timestamp: o.t === undefined ? Date.now() : o.t
    };
  }

  var geo = {
    getCurrentPosition: function (ok, err, options) {
      geoState.getCalls += 1;
      geoState.options.push({ maximumAge: options && options.maximumAge, timeout: options && options.timeout });
      var o = geoState.current;
      if (geoState.mode === "hang") {
        return;  // never answers: the page has to go ahead on its own timer
      }
      setTimeout(function () {
        if (geoState.mode === "fail") {
          if (err) { err({ code: 3 }); }
        } else if (o && !CONFIG.noGeo) {
          ok(position(o));
        } else if (err) {
          err({ code: 1 });
        }
      }, 0);
    },
    watchPosition: function (ok, err, options) {
      geoState.watchCalls += 1;
      geoState.watchOptions.push(options || null);
      var id = nextId++;
      watchers[id] = ok;
      return id;
    },
    clearWatch: function (id) {
      geoState.clearCalls += 1;
      delete watchers[id];
    }
  };
  Object.defineProperty(navigator, "geolocation", { value: geo, configurable: true });

  window.__geo = {
    state: geoState,
    set: function (o) { geoState.current = o; },
    setMode: function (mode) { geoState.mode = mode; },
    push: function (o) {
      geoState.current = o;
      Object.keys(watchers).forEach(function (id) { watchers[id](position(o)); });
    },
    watching: function () { return Object.keys(watchers).length; }
  };

  // devicemotion listeners, counted
  var motionHandlers = [];
  var realAdd = window.addEventListener;
  var realRemove = window.removeEventListener;
  var delivered = 0;
  window.addEventListener = function (type, fn, opts) {
    if (type === "devicemotion") {
      motionHandlers.push(fn);
      var wrapped = fn;
      fn = function (event) { delivered += 1; return wrapped.call(this, event); };
      fn.__orig = wrapped;
      motionHandlers[motionHandlers.length - 1] = fn;
    }
    return realAdd.call(window, type, fn, opts);
  };
  window.removeEventListener = function (type, fn, opts) {
    if (type === "devicemotion") {
      for (var i = 0; i < motionHandlers.length; i++) {
        if (motionHandlers[i] === fn || motionHandlers[i].__orig === fn) {
          var found = motionHandlers.splice(i, 1)[0];
          return realRemove.call(window, type, found, opts);
        }
      }
    }
    return realRemove.call(window, type, fn, opts);
  };

  var permission = { calls: 0, answer: CONFIG.permission || "none", duringClick: [] };
  if (permission.answer !== "none" && permission.answer !== "missing") {
    window.DeviceMotionEvent.requestPermission = function () {
      permission.calls += 1;
      permission.duringClick.push(!!window.__inClick);
      return Promise.resolve(permission.answer);
    };
  }
  if (permission.answer === "missing") {
    try { delete window.DeviceMotionEvent; } catch (e) { window.DeviceMotionEvent = undefined; }
  }
  document.addEventListener("click", function () {
    window.__inClick = true;
    setTimeout(function () { window.__inClick = false; }, 0);
  }, true);

  // A synthetic walk, in real time: motion events at about 60 Hz and one fix per second.
  var seed = 7;
  function rnd() { seed = (seed * 1664525 + 1013904223) % 4294967296; return seed / 4294967296; }
  function gauss() { return Math.sqrt(-2 * Math.log(rnd() + 1e-12)) * Math.cos(2 * Math.PI * rnd()); }
  var sim = { timer: null, fixTimer: null, cadence: 1.8, alt: 1, gps: true, gpsSpeed: 1.3, gpsAcc: 8, mode: "walk",
              pos: CONFIG.position || { lat: 1.3, lon: 103.8, acc: 8 }, started: 0, events: 0, lp: 0 };

  function magnitude(t) {
    if (sim.mode === "still") { return Math.abs(0.03 * gauss()); }
    if (sim.mode === "shake") { sim.lp = 0.8 * sim.lp + 0.2 * gauss() * 5; return Math.abs(sim.lp); }
    var phase = (t * sim.cadence) % 1;
    var amp = Math.floor(t * sim.cadence) % 2 === 0 ? 1 : sim.alt;
    var bump = phase < 0.5 ? Math.pow(Math.sin(Math.PI * phase / 0.5), 2) : 0;
    return 3 * amp * bump + 0.15 * gauss();
  }

  window.__sim = {
    config: sim,
    start: function (o) {
      for (var k in (o || {})) { sim[k] = o[k]; }
      window.__sim.stop();
      sim.started = performance.now();
      sim.timer = setInterval(function () {
        var t = (performance.now() - sim.started) / 1000;
        var m = magnitude(t);
        sim.events += 1;
        window.dispatchEvent(new DeviceMotionEvent("devicemotion", {
          acceleration: { x: m, y: 0, z: 0 },
          accelerationIncludingGravity: { x: m, y: 0, z: 9.8 },
          interval: 16
        }));
      }, 1000 / 60);
      if (sim.gps) {
        sim.fixTimer = setInterval(function () {
          if (sim.gps) {
            window.__geo.push({ lat: sim.pos.lat, lon: sim.pos.lon, acc: sim.gpsAcc, speed: sim.gpsSpeed });
          }
        }, 1000);
      }
    },
    set: function (o) { for (var k in o) { sim[k] = o[k]; } },
    stop: function () {
      if (sim.timer) { clearInterval(sim.timer); sim.timer = null; }
      if (sim.fixTimer) { clearInterval(sim.fixTimer); sim.fixTimer = null; }
    },
    events: function () { return sim.events; }
  };

  window.__motion = {
    listeners: function () { return motionHandlers.length; },
    delivered: function () { return delivered; },
    permission: permission,
    fire: function (m) {
      window.dispatchEvent(new DeviceMotionEvent("devicemotion", {
        acceleration: { x: m, y: 0, z: 0 }, accelerationIncludingGravity: { x: m, y: 0, z: 9.8 }, interval: 16
      }));
    }
  };

  // a page that can be hidden and shown
  var hidden = false;
  Object.defineProperty(document, "hidden", { get: function () { return hidden; }, configurable: true });
  window.__setHidden = function (value) {
    hidden = !!value;
    document.dispatchEvent(new Event("visibilitychange"));
  };

  // every request the page makes to the app, recorded
  var requests = [];
  var realFetch = window.fetch;
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : input.url;
    requests.push(url);
    return realFetch.call(window, input, init);
  };
  window.__requests = requests;
})();
