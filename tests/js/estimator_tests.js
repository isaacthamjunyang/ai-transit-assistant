/* Estimator tests with synthetic signals. They run in headless Edge from tests/test_walk_speed_js.py.
   The result list is written into <pre id="results"> as JSON: [{group, name, ok, detail}]. */
(function () {
  var W = window.WalkSpeed;
  var C = W.CONSTANTS;
  var results = [];
  var pending = [];
  var LAT0 = 1.3;

  function record(group, name, ok, detail) {
    results.push({ group: group, name: name, ok: !!ok, detail: detail || "" });
  }

  function test(group, name, fn) {
    try {
      var out = fn();
      if (out && typeof out.then === "function") {
        pending.push(out.then(function () {
          record(group, name, true);
        }, function (error) {
          record(group, name, false, String(error && error.message ? error.message : error));
        }));
      } else {
        record(group, name, true);
      }
    } catch (error) {
      record(group, name, false, String(error && error.message ? error.message : error));
    }
  }

  function check(condition, message) {
    if (!condition) {
      throw new Error(message || "check failed");
    }
  }

  function near(value, expected, tolerance, label) {
    check(typeof value === "number" && isFinite(value) && Math.abs(value - expected) <= tolerance,
      (label || "value") + " " + value + " not within " + tolerance + " of " + expected);
  }

  // ---------- synthetic signals ----------

  function rng(seed) {
    var s = seed;
    return function () {
      s = (s * 1664525 + 1013904223) % 4294967296;
      return s / 4294967296;
    };
  }

  function gauss(r) {
    return Math.sqrt(-2 * Math.log(r() + 1e-12)) * Math.cos(2 * Math.PI * r());
  }

  /* Steps at f per second: a smooth bump per step, alternate steps scaled by alt (arm swing), noise. */
  function walkSignal(f, alt, seed) {
    var r = rng(seed);
    return function (t) {
      var phase = (t * f) % 1;
      var index = Math.floor(t * f);
      var amp = index % 2 === 0 ? 1 : alt;
      var bump = phase < 0.5 ? Math.pow(Math.sin(Math.PI * phase / 0.5), 2) : 0;
      return 3 * amp * bump + 0.15 * gauss(r);
    };
  }

  function stillSignal(seed) {
    var r = rng(seed);
    return function () {
      return Math.abs(0.03 * gauss(r));
    };
  }

  function shakeSignal(seed) {
    var r = rng(seed);
    var lp = 0;
    return function () {
      lp = 0.8 * lp + 0.2 * gauss(r) * 5;
      return Math.abs(lp);
    };
  }

  function memStorage(initial) {
    var data = {};
    var key;
    for (key in (initial || {})) {
      data[key] = initial[key];
    }
    return {
      data: data,
      getItem: function (k) { return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null; },
      setItem: function (k, v) { data[k] = String(v); },
      removeItem: function (k) { delete data[k]; }
    };
  }

  function brokenStorage() {
    return {
      getItem: function () { throw new Error("blocked"); },
      setItem: function () { throw new Error("quota"); }
    };
  }

  function manualTimers() {
    var now = 0;
    var next = 1;
    var jobs = [];
    return {
      set: function (fn, ms) {
        var id = next++;
        jobs.push({ id: id, at: now + ms, fn: fn });
        return id;
      },
      clear: function (id) {
        jobs = jobs.filter(function (job) { return job.id !== id; });
      },
      advance: function (ms) {
        var end = now + ms;
        for (;;) {
          jobs.sort(function (a, b) { return a.at - b.at; });
          if (!jobs.length || jobs[0].at > end) {
            break;
          }
          var job = jobs.shift();
          now = job.at;
          job.fn();
        }
        now = end;
      },
      count: function () { return jobs.length; }
    };
  }

  function fakeWin(options) {
    var o = options || {};
    var listeners = {};
    var docListeners = {};
    var geo = {
      watches: 0,
      cleared: 0,
      watchPosition: function (success) { geo.watches += 1; geo.success = success; return 7; },
      clearWatch: function () { geo.cleared += 1; }
    };
    var win = {
      listeners: listeners,
      geo: geo,
      document: {
        hidden: false,
        addEventListener: function (type, fn) { (docListeners[type] = docListeners[type] || []).push(fn); },
        removeEventListener: function () {}
      },
      navigator: { geolocation: o.noGeo ? undefined : geo },
      location: { search: o.debug ? "?pace=debug" : "" },
      performance: { timeOrigin: 0 },
      isSecureContext: o.secure !== false,
      addEventListener: function (type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      removeEventListener: function (type, fn) {
        listeners[type] = (listeners[type] || []).filter(function (item) { return item !== fn; });
      },
      fire: function (type, event) {
        (listeners[type] || []).slice().forEach(function (fn) { fn(event); });
      },
      setVisible: function (visible) {
        win.document.hidden = !visible;
        (docListeners.visibilitychange || []).slice().forEach(function (fn) { fn(); });
      },
      count: function (type) { return (listeners[type] || []).length; }
    };
    if (o.motion !== undefined) {
      win.DeviceMotionEvent = o.motion;
    }
    if (o.debug) {
      win.document.createElement = function (tag) { return document.createElement(tag); };
      win.document.getElementById = function (id) { return document.getElementById(id); };
      win.document.body = document.body;
    }
    return win;
  }

  /* A scenario: an estimator on a hand-driven clock. */
  function scenario(options) {
    var o = options || {};
    var S = { t: o.startAt || 0, dist: 0, nextTick: (o.startAt || 0) + 1000 };
    var est = W.createEstimator({
      win: o.win || fakeWin({ motion: function () {} }),
      now: function () { return S.t; },
      storage: o.storage === undefined ? memStorage() : o.storage,
      timers: o.timers || manualTimers(),
      debug: o.debug,
      debugContext: o.debugContext,
      clipboard: o.clipboard
    });
    S.est = est;
    return S;
  }

  /* Advance seconds of simulated time. cfg.motion(tSec) gives the magnitude (or null for no motion events);
     cfg.motionG(tSec) gives an accelerationIncludingGravity vector; cfg.gps(tSec) gives
     {speed (true m/s), report (number or null), acc} or null for no fix. */
  function run(S, seconds, cfg, onTick) {
    var dtMs = 1000 / 60;
    var target = S.t + seconds * 1000;
    while (S.t < target) {
      S.t += dtMs;
      var ts = S.t / 1000;
      if (cfg.motion) {
        S.est.ingestMotion({ t: S.t, acceleration: { x: cfg.motion(ts), y: 0, z: 0 } });
      } else if (cfg.motionG) {
        S.est.ingestMotion({ t: S.t, acceleration: null, accelerationIncludingGravity: cfg.motionG(ts) });
      }
      if (S.t >= S.nextTick) {
        S.nextTick += 1000;
        var g = cfg.gps ? cfg.gps(ts) : null;
        if (g) {
          S.dist += g.speed;
          S.est.ingestFix({
            t: S.t - (g.age || 0) * 1000,
            lat: LAT0 + S.dist / 111195,
            lon: 103.8,
            accuracy: g.acc,
            speed: g.report === undefined ? g.speed : g.report
          });
        }
        S.est.tick(S.t);
        if (onTick) {
          onTick(S.est.snapshot());
        }
      }
    }
    return S.est.snapshot();
  }

  function goodGps(speed, acc) {
    var r = rng(77);
    return function () {
      return { speed: speed, report: speed + 0.02 * gauss(r), acc: acc === undefined ? 8 : acc };
    };
  }

  // ---------- cadence ----------

  [1.4, 1.8, 2.2].forEach(function (f) {
    test("cadence", "steady walking at " + f + " steps/s is within 5% by 15 s", function () {
      var S = scenario();
      var snap = run(S, 15, { motion: walkSignal(f, 1, 11) });
      near(snap.cadence, f, f * 0.05, "cadence");
    });
  });

  test("cadence", "a still phone with sensor noise gives no walking", function () {
    var S = scenario();
    var snap = run(S, 25, { motion: stillSignal(5) });
    check(!snap.walking && snap.cadence === null, "walking " + snap.walking + " cadence " + snap.cadence);
  });

  test("cadence", "a shaken but stationary phone gives no walking", function () {
    var S = scenario();
    var snap = run(S, 25, { motion: shakeSignal(6) });
    check(!snap.walking && snap.cadence === null, "walking " + snap.walking + " cadence " + snap.cadence);
  });

  test("cadence", "arm-swing at half the step rate gives the step rate, not half of it", function () {
    var S = scenario();
    var snap = run(S, 15, { motion: walkSignal(1.8, 0.7, 12) });
    near(snap.cadence, 1.8, 1.8 * 0.05, "cadence");
  });

  test("cadence", "a running rhythm with a GPS speed at the vehicle limit is not walking", function () {
    var S = scenario();
    var snap = run(S, 25, { motion: walkSignal(3.5, 1, 13), gps: function () { return { speed: 3.4, acc: 8 }; } });
    check(!snap.walking && snap.walkingReason === "vehicle" && snap.mode !== "gps", "reason " + snap.walkingReason);
  });

  test("cadence", "the phone's orientation does not matter (gravity removed by low-pass)", function () {
    [[2.0, 4.0, 8.7, 0.5, 0.5, 0.7071], [9.6, 0.5, 1.5, 0.0, 0.7071, 0.7071], [0.0, -9.7, 1.0, 1.0, 0.0, 0.0]].forEach(function (v) {
      var S = scenario();
      var sig = walkSignal(1.8, 1, 14);
      var snap = run(S, 16, {
        motionG: function (t) {
          var m = sig(t);
          return { x: v[0] + v[3] * m, y: v[1] + v[4] * m, z: v[2] + v[5] * m };
        }
      });
      near(snap.cadence, 1.8, 1.8 * 0.05, "cadence");
    });
  });

  test("cadence", "walking is detected only after a regular cadence of about 8 s", function () {
    var S = scenario();
    var early = run(S, 9, { motion: walkSignal(1.8, 1, 15) });
    check(!early.walking, "walking too early at 9 s");
    var later = run(S, 10, { motion: walkSignal(1.8, 1, 16) });
    check(later.walking, "not walking at 19 s: " + later.walkingReason);
  });

  test("cadence", "an irregular step rhythm is not walking", function () {
    var S = scenario();
    var r = rng(3);
    var nextStep = 0;
    var signal = function (t) {
      if (t >= nextStep) {
        nextStep = t + 0.35 + 0.55 * r();
        signal.start = t;
      }
      var age = t - (signal.start || 0);
      return age < 0.2 ? 3 * Math.pow(Math.sin(Math.PI * age / 0.2), 2) : 0;
    };
    var snap = run(S, 30, { motion: signal });
    check(!snap.walking, "an irregular rhythm counted as walking");
  });

  // ---------- gps ----------

  function fix(t, metres, acc, speed) {
    return { t: t, lat: LAT0 + metres / 111195, lon: 103.8, accuracy: acc, speed: speed === undefined ? null : speed };
  }

  test("gps", "a numeric coords.speed on a recent good fix is used", function () {
    var got = W.gpsSpeed([fix(0, 0, 10, 1.3)], 1000);
    near(got.speed, 1.3, 1e-9);
    check(got.derived === false);
  });

  test("gps", "null speed with a long derived displacement gives a speed", function () {
    var got = W.gpsSpeed([fix(0, 0, 8, null), fix(25000, 45, 8, null)], 26000);
    check(got && got.derived === true, "no derived speed");
    near(got.speed, 45 / 25, 0.02, "speed");
  });

  test("gps", "a short displacement gives no GPS speed", function () {
    check(W.gpsSpeed([fix(0, 0, 8, null), fix(25000, 30, 8, null)], 26000) === null);
  });

  test("gps", "a displacement under 4 x the accuracy gives no GPS speed", function () {
    check(W.gpsSpeed([fix(0, 0, 14, null), fix(25000, 50, 14, null)], 26000) === null);
  });

  test("gps", "fixes under 20 s apart derive nothing", function () {
    check(W.gpsSpeed([fix(0, 0, 8, null), fix(15000, 60, 8, null)], 16000) === null);
  });

  test("gps", "poor accuracy is ignored and an old fix gives nothing", function () {
    var S = scenario();
    var heard = [];
    S.est.onFix(function (item) { heard.push(item.accuracy); });
    check(S.est.ingestFix({ t: 0, lat: LAT0, lon: 103.8, accuracy: 31, speed: 1.2 }) === false);
    check(heard.length === 1 && heard[0] === 31, "the page was not told about a poor fix (it stamps the fix age)");
    check(S.est.snapshot().gpsSpeed === null, "a poor fix was used for speed");
    check(W.gpsSpeed([fix(0, 0, 40, 1.2)], 1000) === null, "accuracy 40 m accepted");
    check(W.gpsSpeed([fix(0, 0, 10, 1.2)], 3500) === null, "a 3.5 s old fix gave a speed");
    near(W.gpsSpeed([fix(0, 0, 10, 1.2)], 3000).speed, 1.2, 1e-9);
    near(W.gpsSpeed([fix(0, 0, 10, 1.2)], 3000).age, 3, 1e-9);
  });

  test("gps", "a vehicle speed (8 m/s) is ignored and nothing is learned", function () {
    var S = scenario();
    var snap = run(S, 60, { motion: walkSignal(1.8, 1, 17), gps: function () { return { speed: 8, acc: 8 }; } });
    check(!snap.walking && snap.walkingReason === "vehicle", "walking " + snap.walking);
    check(snap.stepCount === 0 && snap.mode !== "gps", "mode " + snap.mode + " count " + snap.stepCount);
  });

  // ---------- learning ----------

  function recs(over) {
    var o = over || {};
    var out = [];
    for (var i = 0; i < (o.n || 15); i++) {
      out.push({
        t: i * 1000,
        walking: o.walking === undefined ? true : o.walking,
        cadence: o.cadence === undefined ? 1.8 : (typeof o.cadence === "function" ? o.cadence(i) : o.cadence),
        gpsSpeed: o.speed === undefined ? 1.26 : (typeof o.speed === "function" ? o.speed(i) : o.speed),
        gpsAcc: o.acc === undefined ? 8 : o.acc
      });
    }
    return out;
  }

  var FRESH = { length: C.STEP_LEN_PRIOR, count: 0 };

  test("learning", "a good window is accepted, and the first sample is blended with the prior", function () {
    var got = W.learnStep(recs({ speed: 1.62 }), FRESH);
    check(got.accepted, got.reason);
    near(got.sample, 0.9, 1e-9);
    near(got.state.length, 0.7 + 0.2 * (0.9 - 0.7), 1e-9);
    check(got.state.count === 1);
  });

  [
    ["a window with too few records", { n: 10 }, "short"],
    ["a window where one record is not walking", { n: 15, cadence: 1.8, walking: false }, "not walking"],
    ["a window with a missing GPS speed", { speed: null }, "missing"],
    ["an unsteady cadence", { cadence: function (i) { return i % 2 ? 1.5 : 2.2; }, speed: 1.3 }, "cadence not steady"],
    ["an unsteady GPS speed", { speed: function (i) { return i % 2 ? 0.9 : 1.6; } }, "gps not steady"],
    ["a median accuracy above 15 m", { acc: 16 }, "gps accuracy"],
    ["a GPS speed below 0.7 m/s", { cadence: 1.4, speed: 0.6 }, "gps speed range"],
    ["a GPS speed above 2.0 m/s", { cadence: 2.5, speed: 2.1 }, "gps speed range"],
    ["a cadence below 1.3", { cadence: 1.25, speed: 0.9 }, "cadence range"],
    ["a cadence above 2.6", { cadence: 2.7, speed: 1.8 }, "cadence range"],
    ["a step length under 0.35 m", { cadence: 2.5, speed: 0.8 }, "length range"],
    ["a step length over 1.1 m", { cadence: 1.4, speed: 1.6 }, "length range"]
  ].forEach(function (row) {
    test("learning", "rejects " + row[0], function () {
      var base = row[1];
      var window = recs(base);
      if (base.walking === false) {
        window[7].walking = false;
        window = recs({});
        window[7].walking = false;
      }
      if (base.speed === null) {
        window = recs({});
        window[4].gpsSpeed = null;
      }
      var got = W.learnStep(window, FRESH);
      check(!got.accepted && got.reason === row[2], "reason " + got.reason + " wanted " + row[2]);
      check(got.state === FRESH, "state changed on a rejected window");
    });
  });

  test("learning", "rejects a window where GPS speed and cadence x length disagree by more than 0.6 m/s", function () {
    var known = { length: 0.7, count: 5 };
    var got = W.learnStep(recs({ cadence: 2.4, speed: 1.0 }), known);
    check(!got.accepted && got.reason === "disagreement", got.reason);
    var ok = W.learnStep(recs({ cadence: 1.8, speed: 1.3 }), known);
    check(ok.accepted, ok.reason);
  });

  test("learning", "the step length is clamped to 0.45 to 0.95 m", function () {
    var high = W.learnStep(recs({ cadence: 1.4, speed: 1.5 }), { length: 0.94, count: 5 });
    check(high.accepted && high.state.length === C.STEP_LEN_MAX, "high " + high.state.length);
    var low = W.learnStep(recs({ cadence: 2.5, speed: 1.0 }), { length: 0.46, count: 5 });
    check(low.accepted && low.state.length === C.STEP_LEN_MIN, "low " + low.reason + " " + (low.state && low.state.length));
  });

  test("learning", "a good sequence converges to within 5% of the true step length", function () {
    [0.62, 0.8, 0.9].forEach(function (trueLength) {
      var S = scenario();
      var speed = 1.8 * trueLength;
      var snap = run(S, 220, { motion: walkSignal(1.8, 1, 21), gps: goodGps(speed) });
      near(snap.stepLength, trueLength, trueLength * 0.05, "step length for " + trueLength);
      check(snap.stepCount >= 8, "samples " + snap.stepCount);
    });
  });

  // ---------- fusion ----------

  test("fusion", "walking with a usable GPS speed is gps mode", function () {
    var S = scenario();
    var snap = run(S, 25, { motion: walkSignal(1.8, 1, 31), gps: goodGps(1.2) });
    check(snap.mode === "gps" && snap.walking, "mode " + snap.mode);
    near(snap.smoothed, 1.2, 0.05);
    var sent = S.est.pollValue();
    check(sent.source === "gps", "source " + sent.source);
    near(sent.speed, 1.2, 0.05);
  });

  test("fusion", "GPS lost after learning falls to cadence mode within 10% of the true speed", function () {
    var S = scenario();
    var trueSpeed = 1.3;
    run(S, 160, { motion: walkSignal(1.8, 1, 32), gps: goodGps(trueSpeed) });
    var learned = S.est.snapshot();
    check(learned.stepCount >= C.CADENCE_MODE_MIN_SAMPLES, "learned " + learned.stepCount);
    var snap = run(S, 30, { motion: walkSignal(1.8, 1, 33) });
    check(snap.mode === "cadence", "mode " + snap.mode);
    near(snap.smoothed, trueSpeed, trueSpeed * 0.1, "speed");
    check(S.est.pollValue().source === "cadence");
  });

  test("fusion", "cadence mode needs three learning samples", function () {
    var S = scenario();
    var snap = run(S, 30, { motion: walkSignal(1.8, 1, 34) });
    check(snap.walking && snap.mode !== "cadence" && snap.mode !== "gps", "mode " + snap.mode);
  });

  test("fusion", "a short stop holds the speed for under 30 s, then falls back to the remembered pace", function () {
    var S = scenario();
    run(S, 80, { motion: walkSignal(1.8, 1, 35), gps: goodGps(1.2) });
    var walked = S.est.snapshot().smoothed;
    check(S.est.snapshot().remembered !== null, "no remembered pace after 80 s of measured walking");
    var at20 = run(S, 20, { motion: stillSignal(36) });
    check(at20.mode === "hold", "mode at 20 s " + at20.mode);
    near(at20.smoothed, walked, 0.03, "held speed");
    var at40 = run(S, 20, { motion: stillSignal(37) });
    check(at40.mode === "remembered", "mode at 40 s " + at40.mode);
    check(S.est.pollValue().source === "remembered");
  });

  test("fusion", "a short stop with GPS saying 0 does not lower the speed while the cadence window drains", function () {
    var S = scenario();
    run(S, 40, { motion: walkSignal(1.8, 1, 81), gps: goodGps(1.3) });
    var before = S.est.snapshot().smoothed;
    var lowest = before;
    for (var i = 0; i < 20; i++) {
      var snap = run(S, 1, { motion: stillSignal(82 + i), gps: goodGps(0.05) });
      lowest = Math.min(lowest, snap.smoothed);
    }
    check(lowest > before - 0.03, "the speed fell from " + before + " to " + lowest);
    check(S.est.snapshot().mode === "hold", "mode " + S.est.snapshot().mode);
    var again = run(S, 15, { motion: walkSignal(1.8, 1, 83), gps: goodGps(1.3) });
    check(again.walking && again.mode === "gps", "did not resume: " + again.walkingReason);
  });

  test("fusion", "after a short walk with nothing remembered the fallback is no value", function () {
    var S = scenario();
    run(S, 40, { motion: walkSignal(1.8, 1, 38), gps: goodGps(1.2) });
    check(S.est.snapshot().remembered === null, "remembered too early");
    var snap = run(S, 45, { motion: stillSignal(39) });
    check(snap.mode === "none", "mode " + snap.mode);
    check(S.est.pollValue() === null && S.est.queryString() === "", "a value was sent");
  });

  test("fusion", "a remembered pace newer than 30 days is used, an older one is not", function () {
    var fresh = memStorage();
    fresh.setItem(C.PACE_KEY, JSON.stringify({ pace: 0.9, savedAt: -5 * 86400000 }));
    var S = scenario({ storage: fresh });
    S.t = 0;
    var value = S.est.pollValue();
    check(value && value.source === "remembered", "no remembered value");
    near(value.speed, 0.9, 1e-9);
    var old = memStorage();
    old.setItem(C.PACE_KEY, JSON.stringify({ pace: 0.9, savedAt: -31 * 86400000 }));
    check(scenario({ storage: old }).est.pollValue() === null, "an old pace was used");
  });

  test("fusion", "with nothing measured or remembered there is no value (the server default)", function () {
    var S = scenario();
    check(S.est.pollValue() === null && S.est.queryString() === "");
  });

  test("fusion", "the value sent moves by at most 0.15 m/s per poll", function () {
    var storage = memStorage();
    storage.setItem(C.PACE_KEY, JSON.stringify({ pace: 0.8, savedAt: 0 }));
    var S = scenario({ storage: storage });
    check(S.est.pollValue().speed === 0.8);
    run(S, 90, { motion: walkSignal(1.8, 1, 40), gps: goodGps(1.4) });
    var previous = S.est.pollValue().speed;
    var polls = [];
    for (var i = 0; i < 6; i++) {
      S.t += 5000;
      var value = S.est.pollValue().speed;
      polls.push(value);
      check(Math.abs(value - previous) <= C.SLEW_MPS_PER_POLL + 1e-9, "jump " + previous + " to " + value);
      previous = value;
    }
    near(polls[polls.length - 1], 1.4, 0.06, "reaches the speed after several polls");
    var again = S.est.pollValue().speed;
    check(again === previous, "two requests in one poll disagree");
    near(W.slew(1.0, 1.4), 1.15, 1e-9);
    near(W.slew(1.0, 0.6), 0.85, 1e-9);
    near(W.slew(null, 1.4), 1.4, 1e-9);
  });

  test("fusion", "the value is clamped to 0.5 to 1.4 m/s", function () {
    var S = scenario();
    var fast = run(S, 40, { motion: walkSignal(1.8, 1, 41), gps: goodGps(1.9) });
    check(fast.smoothed <= 1.4 + 1e-9, "smoothed " + fast.smoothed);
    check(S.est.pollValue().speed === 1.4);
    var T = scenario();
    var slow = run(T, 40, { motion: walkSignal(1.8, 1, 42), gps: goodGps(0.72) });
    check(slow.smoothed >= 0.5);
    check(W.clampSpeed(0.2) === 0.5 && W.clampSpeed(3) === 1.4 && W.toSendable(1.2345) === 1.23);
  });

  test("fusion", "the speed is smoothed with a 10 s time constant", function () {
    near(W.smooth(1.0, 1.4, 10), 1.0 + 0.4 * (1 - Math.exp(-1)), 1e-9);
    near(W.smooth(null, 1.4, 10), 1.4, 1e-9);
    near(W.smooth(1.0, 1.4, 0), 1.0, 1e-9);
  });

  test("fusion", "the fusion order is first match wins", function () {
    var step = { length: 0.7, count: 5 };
    var base = { nowMs: 100000, lastWalkingAt: null, lastSpeed: null, remembered: null };
    var gps = W.fuse(Object.assign({ walking: true, gps: 1.2, cadence: 1.8, step: step }, base));
    check(gps.mode === "gps" && gps.speed === 1.2);
    var cad = W.fuse(Object.assign({ walking: true, gps: null, cadence: 1.8, step: step }, base));
    check(cad.mode === "cadence"); near(cad.speed, 1.26, 1e-9);
    var held = W.fuse({ walking: false, gps: null, cadence: null, step: step, nowMs: 100000, lastWalkingAt: 75000, lastSpeed: 1.1, remembered: null });
    check(held.mode === "hold" && held.speed === 1.1);
    var lapsed = W.fuse({ walking: false, gps: null, cadence: null, step: step, nowMs: 100000, lastWalkingAt: 69000, lastSpeed: 1.1, remembered: { pace: 0.9, savedAt: 99000 } });
    check(lapsed.mode === "remembered" && lapsed.speed === 0.9);
    var none = W.fuse({ walking: false, gps: null, cadence: null, step: step, nowMs: 100000, lastWalkingAt: null, lastSpeed: null, remembered: null });
    check(none.mode === "none" && none.speed === null);
  });

  function gpsOnly() {
    var S = scenario({ win: fakeWin({ motion: undefined }) });
    return S.est.requestPermission().then(function () { return S; });
  }

  test("fusion", "with no motion sensor the page is GPS-only and steady GPS walking still counts", function () {
    var before = scenario();
    var early = run(before, 20, { gps: goodGps(1.1) });
    check(early.walking && early.walkingSource === "gps" && early.mode === "gps", "GPS alone did not count");
    return gpsOnly().then(function (S) {
      var snap = run(S, 20, { gps: goodGps(1.1) });
      check(snap.walking && snap.mode === "gps", "GPS-only: " + snap.walkingReason + " " + snap.mode);
      return gpsOnly();
    }).then(function (S) {
      check(!run(S, 20, { gps: goodGps(0.2) }).walking, "standing counted as walking");
      return gpsOnly();
    }).then(function (S) {
      check(!run(S, 20, { gps: goodGps(8) }).walking, "a vehicle counted as walking");
    });
  });

  test("fusion", "GPS-only: a steady 1.3 m/s walker counts, never learns, never uses cadence", function () {
    return gpsOnly().then(function (S) {
      var snap = run(S, 60, { motion: walkSignal(1.8, 1, 71), gps: goodGps(1.3) });
      check(snap.walking && snap.mode === "gps", "mode " + snap.mode);
      check(snap.stepCount === 0 && snap.lastLearn !== "ok", "learned without a cadence");
      var sent = S.est.pollValue();
      check(sent.source === "gps" && sent.speed <= 1.4 && sent.speed >= 0.5, "source " + sent.source);
      near(sent.speed, 1.3, 0.05);
    });
  });

  test("fusion", "GPS-only: the upper bound is the vehicle limit and the speed is still clamped", function () {
    return gpsOnly().then(function (S) {
      check(C.VEHICLE_SPEED_MIN === 2.2);
      check(!run(S, 20, { gps: goodGps(2.2) }).walking, "2.2 m/s counted as walking");
      return gpsOnly();
    }).then(function (S) {
      var snap = run(S, 30, { gps: goodGps(2.0) });
      check(snap.walking, "2.0 m/s is a brisk walk");
      check(S.est.pollValue().speed === 1.4, "not clamped to 1.4");
      return gpsOnly();
    }).then(function (S) {
      check(!run(S, 30, { gps: goodGps(1.3, 40) }).walking, "a poor fix was used");
      return gpsOnly();
    }).then(function (S) {
      var flip = 0;
      var snap = run(S, 30, { gps: function () { flip += 1; return { speed: flip % 2 ? 0.8 : 1.9, acc: 8 }; } });
      check(!snap.walking, "an unsteady GPS speed counted as walking");
    });
  });

  test("fusion", "a phone shaken in place at a walking rhythm with GPS speed near 0 is not walking and does not learn", function () {
    var S = scenario();
    var snap = run(S, 60, { motion: walkSignal(1.8, 1, 72), gps: goodGps(0.05) });
    check(!snap.walking && snap.walkingReason === "gps still", "walking " + snap.walking + " " + snap.walkingReason);
    check(snap.stepCount === 0 && snap.mode !== "gps" && snap.mode !== "cadence", "mode " + snap.mode);
    check(S.est.pollValue() === null, "a speed was sent for a shaken phone");
  });

  test("fusion", "a real walk from standstill is detected a few seconds after the GPS speed rises", function () {
    var S = scenario();
    var still = run(S, 20, { motion: walkSignal(1.8, 1, 73), gps: goodGps(0.05) });
    check(!still.walking, "walking while GPS said still");
    var risen = 0;
    for (var i = 0; i < 4; i++) {
      var snap = run(S, 1, { motion: walkSignal(1.8, 1, 74 + i), gps: goodGps(1.3) });
      risen += 1;
      if (snap.walking) {
        break;
      }
    }
    check(S.est.snapshot().walking && risen <= 3, "walking only after " + risen + " s of GPS speed");
  });

  test("fusion", "poor GPS leaves cadence detection unchanged", function () {
    var withPoor = scenario();
    var a = run(withPoor, 25, { motion: walkSignal(1.8, 1, 75), gps: goodGps(0.05, 40) });
    var without = scenario();
    var b = run(without, 25, { motion: walkSignal(1.8, 1, 75) });
    check(a.walking && b.walking, "cadence-only walking not detected: " + a.walkingReason + " / " + b.walkingReason);
    near(a.cadence, b.cadence, 1e-9);
    var stale = scenario();
    run(stale, 12, { motion: walkSignal(1.8, 1, 76), gps: goodGps(0.05) });
    var c = run(stale, 25, { motion: walkSignal(1.8, 1, 77) });
    check(c.walking, "the rule applied after the fix went stale");
  });

  // ---------- persistence ----------

  test("persistence", "the learned step length and the remembered pace survive a restart", function () {
    var storage = memStorage();
    var S = scenario({ storage: storage });
    run(S, 100, { motion: walkSignal(1.8, 1, 51), gps: goodGps(1.3) });
    var first = S.est.snapshot();
    check(first.stepCount >= 3 && first.remembered !== null, "nothing learned");
    var T = scenario({ storage: storage, startAt: S.t + 1000 });
    var second = T.est.snapshot();
    near(second.stepLength, first.stepLength, 1e-9, "step length");
    check(second.stepCount === first.stepCount, "count " + second.stepCount);
    check(second.remembered !== null);
  });

  test("persistence", "storage that throws is harmless", function () {
    var S = scenario({ storage: brokenStorage() });
    var snap = run(S, 100, { motion: walkSignal(1.8, 1, 52), gps: goodGps(1.3) });
    check(snap.stepCount >= 3, "no learning in memory " + snap.stepCount);
    check(S.est.pollValue() !== null);
    var T = scenario({ storage: null });
    var other = run(T, 40, { motion: walkSignal(1.8, 1, 53), gps: goodGps(1.3) });
    check(other.mode === "gps");
  });

  test("persistence", "only the step length and the pace are stored, with no sensor data or positions", function () {
    var storage = memStorage();
    var S = scenario({ storage: storage });
    run(S, 100, { motion: walkSignal(1.8, 1, 54), gps: goodGps(1.3) });
    var keys = Object.keys(storage.data).sort();
    check(keys.join(",") === [C.PACE_KEY, C.STEP_KEY].sort().join(","), "keys " + keys.join(","));
    var step = JSON.parse(storage.data[C.STEP_KEY]);
    var pace = JSON.parse(storage.data[C.PACE_KEY]);
    check(Object.keys(step).sort().join(",") === "count,length,savedAt", Object.keys(step).join(","));
    check(Object.keys(pace).sort().join(",") === "pace,savedAt", Object.keys(pace).join(","));
    var text = JSON.stringify(storage.data);
    check(text.indexOf("lat") === -1 && text.indexOf("lon") === -1 && text.indexOf("1.30") === -1, "a position leaked");
  });

  test("persistence", "garbage and out-of-range stored values are ignored", function () {
    var storage = memStorage();
    storage.setItem(C.STEP_KEY, "{not json");
    storage.setItem(C.PACE_KEY, JSON.stringify({ pace: 9, savedAt: 0 }));
    var S = scenario({ storage: storage });
    var snap = S.est.snapshot();
    check(snap.stepCount === 0 && snap.stepLength === C.STEP_LEN_PRIOR && snap.remembered === null);
    storage.setItem(C.STEP_KEY, JSON.stringify({ length: 5, count: 4, savedAt: 0 }));
    check(scenario({ storage: storage }).est.snapshot().stepCount === 0);
  });

  // ---------- permission and sensor availability ----------

  test("permission", "Android style: no permission call, listening works, events arrive", function () {
    var win = fakeWin({ motion: function () {} });
    var timers = manualTimers();
    var S = scenario({ win: win, timers: timers });
    return S.est.requestPermission().then(function (answer) {
      check(answer === "granted");
      S.est.start();
      check(win.count("devicemotion") === 1 && win.geo.watches === 1, "not listening");
      win.fire("devicemotion", { acceleration: { x: 1, y: 0, z: 0 }, accelerationIncludingGravity: null });
      check(S.est.status().motion === "on");
      timers.advance(5000);
      check(S.est.status().motion === "on", "the timeout fired after an event");
    });
  });

  test("permission", "iOS style: the permission is requested once, inside the call, and granted", function () {
    var asked = 0;
    var Motion = function () {};
    Motion.requestPermission = function () { asked += 1; return Promise.resolve("granted"); };
    var win = fakeWin({ motion: Motion });
    var S = scenario({ win: win });
    var first = S.est.requestPermission();
    check(asked === 1, "not asked synchronously");
    S.est.start();
    return first.then(function (answer) {
      check(answer === "granted" && S.est.requestPermission() === first && asked === 1, "asked again");
      check(win.count("devicemotion") === 1, "listeners " + win.count("devicemotion"));
    });
  });

  test("permission", "denied: GPS-only, the journey keeps working, never asked again", function () {
    var asked = 0;
    var Motion = function () {};
    Motion.requestPermission = function () { asked += 1; return Promise.resolve("denied"); };
    var win = fakeWin({ motion: Motion });
    var S = scenario({ win: win });
    var p = S.est.requestPermission();
    S.est.start();
    return p.then(function (answer) {
      check(answer === "denied" && S.est.status().motion === "off");
      check(win.count("devicemotion") === 0, "still listening after a denial");
      S.est.start();
      S.est.requestPermission();
      check(asked === 1, "asked again");
      var snap = run(S, 20, { gps: goodGps(1.1) });
      check(snap.mode === "gps", "GPS-only mode " + snap.mode);
      check(S.est.pollValue() !== null);
    });
  });

  test("permission", "a rejected permission request counts as denied and does not throw", function () {
    var Motion = function () {};
    Motion.requestPermission = function () { return Promise.reject(new Error("no")); };
    var S = scenario({ win: fakeWin({ motion: Motion }) });
    return S.est.requestPermission().then(function (answer) {
      check(answer === "denied");
    });
  });

  test("permission", "unavailable (no DeviceMotionEvent) and an insecure context are GPS-only", function () {
    var a = scenario({ win: fakeWin({ motion: undefined }) });
    var b = scenario({ win: fakeWin({ motion: function () {}, secure: false }) });
    return Promise.all([a.est.requestPermission(), b.est.requestPermission()]).then(function (answers) {
      check(answers[0] === "unavailable" && answers[1] === "unavailable", answers.join());
      a.est.start();
      check(a.est.status().motion === "off" && a.est.isRunning(), "journey blocked");
    });
  });

  test("permission", "no motion event within 3 s means the sensor is unavailable", function () {
    var timers = manualTimers();
    var win = fakeWin({ motion: function () {} });
    var S = scenario({ win: win, timers: timers });
    return S.est.requestPermission().then(function () {
      S.est.start();
      timers.advance(2900);
      check(S.est.status().motion === "unknown", "off too early");
      timers.advance(200);
      check(S.est.status().motion === "off", "not off after 3 s");
      var snap = run(S, 20, { gps: goodGps(1.1) });
      check(snap.mode === "gps", "GPS-only after no event " + snap.mode);
      win.fire("devicemotion", { acceleration: { x: 1, y: 0, z: 0 } });
      check(S.est.status().motion === "on", "a late event did not turn it back on");
    });
  });

  test("permission", "an event with no data (desktop) does not count as a sensor", function () {
    var timers = manualTimers();
    var win = fakeWin({ motion: function () {} });
    var S = scenario({ win: win, timers: timers });
    return S.est.requestPermission().then(function () {
      S.est.start();
      win.fire("devicemotion", { acceleration: { x: null, y: null, z: null }, accelerationIncludingGravity: { x: null, y: null, z: null } });
      timers.advance(3100);
      check(S.est.status().motion === "off");
    });
  });

  // ---------- lifecycle (estimator level) ----------

  test("lifecycle", "nothing runs until start, and stop detaches the sensors and the watch", function () {
    var win = fakeWin({ motion: function () {} });
    var S = scenario({ win: win });
    check(win.count("devicemotion") === 0 && win.geo.watches === 0 && !S.est.isRunning(), "running before start");
    S.est.start();
    check(win.count("devicemotion") === 1 && win.geo.watches === 1 && S.est.isRunning());
    S.est.start();
    check(win.count("devicemotion") === 1 && win.geo.watches === 1, "a second start doubled the listeners");
    S.est.stop("yes");
    check(win.count("devicemotion") === 0 && win.geo.cleared === 1 && !S.est.isRunning(), "still running after stop");
    check(S.est.status().stopReason === "yes");
  });

  test("lifecycle", "a hidden page stops everything and a visible page resumes it", function () {
    var win = fakeWin({ motion: function () {} });
    var S = scenario({ win: win });
    S.est.start();
    win.setVisible(false);
    check(!S.est.isRunning() && win.count("devicemotion") === 0 && win.geo.cleared === 1, "ran while hidden");
    win.setVisible(true);
    check(S.est.isRunning() && win.count("devicemotion") === 1 && win.geo.watches === 2, "did not resume");
    S.est.stop("end");
    win.setVisible(false);
    win.setVisible(true);
    check(!S.est.isRunning(), "resumed after a stop");
  });

  test("lifecycle", "two near-stop polls in a row latch the estimator off for the leg", function () {
    var win = fakeWin({ motion: function () {} });
    var S = scenario({ win: win });
    S.est.start();
    check(S.est.noteNearStop(true) === false && S.est.isRunning());
    check(S.est.noteNearStop(false) === false);
    check(S.est.noteNearStop(true) === false);
    check(S.est.noteNearStop(true) === true && !S.est.isRunning(), "not latched");
    S.est.start();
    check(S.est.noteNearStop(false) === true, "the latch released on a far fix");
    S.est.resetLeg();
    check(S.est.isLatched() === false);
  });

  test("lifecycle", "the last smoothed speed keeps being sent after a stop, and a restart keeps what was learned", function () {
    var win = fakeWin({ motion: function () {} });
    var S = scenario({ win: win });
    S.est.start();
    run(S, 100, { motion: walkSignal(1.8, 1, 61), gps: goodGps(1.1) });
    var learned = S.est.snapshot().stepCount;
    S.est.stop("near stop");
    S.t += 10000;
    var one = S.est.pollValue().speed;
    S.t += 60000;
    var two = S.est.pollValue().speed;
    check(one === two && S.est.snapshot().frozen, "the frozen value moved");
    near(one, 1.1, 0.05);
    S.est.start();
    check(S.est.snapshot().stepCount === learned && win.geo.watches === 2);
  });

  test("lifecycle", "a stop saves the remembered pace after at least 60 s of measured walking", function () {
    var storage = memStorage();
    var S = scenario({ storage: storage });
    run(S, 50, { motion: walkSignal(1.8, 1, 62), gps: goodGps(1.1) });
    S.est.stop("yes");
    check(storage.getItem(C.PACE_KEY) === null, "saved after under 60 s");
    var T = scenario({ storage: storage });
    run(T, 80, { motion: walkSignal(1.8, 1, 63), gps: goodGps(1.1) });
    T.est.stop("yes");
    near(JSON.parse(storage.getItem(C.PACE_KEY)).pace, 1.1, 0.05);
  });

  // ---------- readout ----------

  test("readout", "the debug readout exists only when asked for", function () {
    var off = W.createEstimator({ now: function () { return 0; }, storage: null, debug: false, timers: manualTimers() });
    off.tick(1000);
    check(document.getElementById("pace-debug") === null, "readout without the flag");
    var on = W.createEstimator({ now: function () { return 1000; }, storage: null, debug: true, timers: manualTimers() });
    on.tick(1000);
    var box = document.getElementById("pace-debug");
    check(box && /mode /.test(box.textContent) && box.className === "pace-debug", "no readout");
  });


  // ---------- hand-held walking, GPS alone, fresh fixes ----------

  /* A weak, noisy step rhythm with an arm swing at half the step rate and about 10% jitter in each step. */
  function handheldSignal(seed, base) {
    var r = rng(seed);
    var f0 = base || 1.8;
    var phase = 0;
    var last = null;
    var freq = f0;
    var index = -1;
    return function (t) {
      var dt = last === null ? 0 : t - last;
      last = t;
      phase += freq * dt;
      if (Math.floor(phase) !== index) {
        index = Math.floor(phase);
        freq = f0 * Math.min(1.25, Math.max(0.75, 1 + 0.1 * gauss(r)));
      }
      var frac = phase - Math.floor(phase);
      var amp = index % 2 === 0 ? 0.9 : 0.5;
      var bump = frac < 0.5 ? Math.pow(Math.sin(Math.PI * frac / 0.5), 2) : 0;
      return 1.1 * amp * bump + 0.45 * Math.abs(gauss(r)) * 0.6;
    };
  }

  function irregularSignal(seed) {
    var r = rng(seed);
    var nextStep = 0;
    var start = 0;
    return function (t) {
      if (t >= nextStep) {
        nextStep = t + 0.35 + 0.55 * r();
        start = t;
      }
      var age = t - start;
      return age < 0.2 ? 3 * Math.pow(Math.sin(Math.PI * age / 0.2), 2) : 0;
    };
  }

  /* GPS at 1 Hz with 15 to 25 m accuracy; the reported speed is noisy. */
  function slowGps(speed, report) {
    var r = rng(91);
    return function () {
      return { speed: speed, report: report === undefined ? speed + 0.08 * gauss(r) : report, acc: 15 + 10 * r() };
    };
  }

  test("handheld", "hand-held walking with slow, poor GPS: walking is detected and the speed used is the GPS speed", function () {
    var S = scenario();
    var snap = run(S, 30, { motion: handheldSignal(31), gps: slowGps(1.3) });
    check(snap.walking && snap.mode === "gps", "walking " + snap.walking + " " + snap.walkingReason + " mode " + snap.mode);
    near(snap.smoothed, 1.3, 0.12, "speed used");
  });

  test("handheld", "GPS alone establishes walking while the cadence is irregular", function () {
    var S = scenario();
    var snap = run(S, 30, { motion: irregularSignal(32), gps: slowGps(1.3) });
    check(snap.cadence === null, "the irregular rhythm gave a cadence");
    check(snap.walking && snap.walkingSource === "gps" && snap.mode === "gps", snap.walkingReason + " " + snap.mode);
    near(snap.smoothed, 1.3, 0.12, "speed used");
    check(snap.stepCount === 0, "learned from an irregular cadence");
  });

  test("handheld", "GPS alone establishes walking when the motion sensor shows nothing", function () {
    var S = scenario();
    var snap = run(S, 30, { motion: stillSignal(33), gps: slowGps(1.2) });
    check(snap.walking && snap.walkingSource === "gps" && snap.mode === "gps", snap.walkingReason + " " + snap.mode);
  });

  test("handheld", "cadence mode still needs learned samples", function () {
    var S = scenario();
    var snap = run(S, 30, { motion: walkSignal(1.8, 1, 34) });
    check(snap.walking && snap.walkingSource === "cadence", "walking " + snap.walking + " " + snap.walkingReason);
    check(snap.mode !== "cadence", "cadence mode with no learned step length");
    var learned = scenario({ storage: memStorage({ "bus-catch-step-length": JSON.stringify({ length: 0.7, count: 3, savedAt: 0 }) }) });
    var snap2 = run(learned, 30, { motion: walkSignal(1.8, 1, 35) });
    check(snap2.mode === "cadence", "mode " + snap2.mode);
    near(snap2.smoothed, 1.8 * 0.7, 0.1, "speed used");
  });

  test("handheld", "standing is not walking", function () {
    var S = scenario();
    var snap = run(S, 30, { motion: stillSignal(36), gps: slowGps(0, 0.05) });
    check(!snap.walking && snap.mode !== "gps", "walking " + snap.walking);
    var T = scenario();
    var snap2 = run(T, 30, { motion: stillSignal(37) });
    check(!snap2.walking, "standing with no GPS counted as walking");
  });

  test("handheld", "a vehicle speed is not walking", function () {
    var S = scenario();
    var snap = run(S, 30, { motion: handheldSignal(38), gps: slowGps(4.0) });
    check(!snap.walking && snap.walkingReason === "vehicle" && snap.mode !== "gps", snap.walkingReason + " " + snap.mode);
    var T = scenario();
    var snap2 = run(T, 30, { motion: irregularSignal(39), gps: slowGps(4.0) });
    check(!snap2.walking, "a vehicle on irregular motion counted as walking");
  });

  test("handheld", "a shaken phone with a GPS speed near 0 is not walking", function () {
    var S = scenario();
    var snap = run(S, 30, { motion: shakeSignal(40), gps: slowGps(0, 0.04) });
    check(!snap.walking && snap.mode !== "gps", "walking " + snap.walking);
    var T = scenario();
    var snap2 = run(T, 30, { motion: walkSignal(1.8, 1, 41), gps: slowGps(0, 0.04) });
    check(!snap2.walking && snap2.walkingReason === "gps still", snap2.walkingReason);
  });

  test("handheld", "a cached fix gives no speed", function () {
    var S = scenario();
    S.t = 20000;
    check(S.est.ingestFix({ t: 12000, lat: LAT0, lon: 103.8, accuracy: 10, speed: 1.3 }) === false, "an 8 s old fix was kept");
    S.est.tick(S.t);
    check(S.est.snapshot().gpsSpeed === null && S.est.snapshot().ignoredStale === 1, "a cached fix gave a speed");
    check(S.est.ingestFix({ t: 16000, lat: LAT0, lon: 103.8, accuracy: 10, speed: 1.3 }) === true, "a 4 s old fix was dropped");
    S.est.tick(S.t);
    check(S.est.snapshot().gpsSpeed === null, "a 4 s old fix gave a speed");
    S.est.ingestFix({ t: 19500, lat: LAT0, lon: 103.8, accuracy: 10, speed: 1.3 });
    S.est.tick(S.t);
    near(S.est.snapshot().gpsSpeed, 1.3, 1e-9, "a fresh fix");
    check(W.gpsSpeed([fix(0, 0, 10, 1.3)], 3100) === null, "a speed was reused after 3 s");
  });

  test("handheld", "a speed of 0 from a stale fix never counts as gps still, a fresh 0 does", function () {
    var stale = scenario();
    var snap = run(stale, 30, {
      motion: walkSignal(1.8, 1, 42),
      gps: function () { return { speed: 0, report: 0, acc: 10, age: 4 }; }
    });
    check(snap.gpsSpeed === null, "a stale speed was used");
    check(snap.walkingReason !== "gps still", "a stale 0 counted as still");
    var fresh = scenario();
    var snap2 = run(fresh, 30, { motion: walkSignal(1.8, 1, 43), gps: function () { return { speed: 0, report: 0, acc: 10 }; } });
    check(!snap2.walking && snap2.walkingReason === "gps still", "a fresh 0 did not count as still: " + snap2.walkingReason);
  });

  test("handheld", "the gps-only gate details are reported", function () {
    var S = scenario();
    var snap = run(S, 14, { motion: irregularSignal(44), gps: slowGps(1.3) });
    var g = snap.gpsOnly;
    check(g.reason === "ok" && g.inRange >= 7 && g.outRange === 0 && g.nulls === 0 && g.cv < C.STEADY_CV_MAX, JSON.stringify(g));
    var T = scenario();
    var n = 0;
    var snap2 = run(T, 14, { motion: irregularSignal(45), gps: function () { n += 1; var v = n % 2 ? 0.4 : 1.3; return { speed: v, report: v, acc: 10 }; } });
    check(snap2.gpsOnly.reason === "slow" && snap2.gpsOnly.outRange > 0 && !snap2.walking, JSON.stringify(snap2.gpsOnly));
  });

  // ---------- iOS: event time stamps, event.interval, null acceleration, watch time stamps ----------

  test("handheld", "events delivered in a burst keep their own spacing and event.interval is ignored", function () {
    var win = fakeWin({ motion: function () {} });
    var S = scenario({ win: win });
    S.est.start();
    var sig = walkSignal(1.8, 1, 46);
    for (var second = 1; second <= 14; second++) {
      var base = (second - 1) * 1000;
      for (var i = 0; i < 60; i++) {
        var at = base + i * (1000 / 60);
        S.t = second * 1000;  // the handler runs late and all at once
        win.fire("devicemotion", {
          acceleration: { x: sig(at / 1000), y: 0, z: 0 },
          accelerationIncludingGravity: null,
          interval: 5000,
          timeStamp: at + 1000 / 60
        });
      }
      S.est.tick(S.t);
    }
    near(S.est.snapshot().cadence, 1.8, 0.1, "cadence");
    S.est.stop("test");
  });

  test("handheld", "a null or partly null linear acceleration falls back to gravity removed", function () {
    [{ x: null, y: null, z: null }, { x: 0.2, y: null, z: 0.1 }, null].forEach(function (lin) {
      var win = fakeWin({ motion: function () {} });
      var S = scenario({ win: win });
      S.est.start();
      var sig = walkSignal(1.8, 1, 47);
      for (var second = 1; second <= 14; second++) {
        for (var i = 0; i < 60; i++) {
          var at = (second - 1) * 1000 + i * (1000 / 60);
          S.t = at + 1000 / 60;
          win.fire("devicemotion", {
            acceleration: lin,
            accelerationIncludingGravity: { x: 9.5 + sig(at / 1000), y: 0.3, z: 2.0 },
            timeStamp: S.t
          });
        }
        S.est.tick(second * 1000);
      }
      near(S.est.snapshot().cadence, 1.8, 0.1, "cadence");
      S.est.stop("test");
    });
  });

  test("handheld", "a watch fix is stamped with the position time, not the callback time", function () {
    var win = fakeWin({ motion: function () {} });
    var S = scenario({ win: win });
    S.t = 30000;
    S.est.start();
    win.geo.success({ coords: { latitude: LAT0, longitude: 103.8, accuracy: 10, speed: 1.2 }, timestamp: 21000 });
    S.est.tick(S.t);
    check(S.est.snapshot().gpsSpeed === null && S.est.snapshot().ignoredStale === 1, "a cached position was used");
    win.geo.success({ coords: { latitude: LAT0, longitude: 103.8, accuracy: 10, speed: 1.2 }, timestamp: 29200 });
    S.est.tick(S.t);
    near(S.est.snapshot().gpsSpeed, 1.2, 1e-9);
    near(S.est.snapshot().speedFixAge, 0.8, 1e-6, "age of the fix that supplied the speed");
    S.est.stop("test");
  });

  // ---------- the debug bar, the reasons and the trace ----------

  function dbg(options) {
    var o = options || {};
    o.win = fakeWin({ motion: function () {}, debug: true });
    o.debug = true;
    return scenario(o);
  }

  test("readout", "the bar is one line, shows mode, speed used and one reason, and a tap opens the panel", function () {
    var S = dbg();
    var root = document.getElementById("pace-debug");
    var bar = root.querySelector(".pace-debug__bar");
    check(bar && bar.tagName === "BUTTON" && /^mode none .* used - m\/s .* journey not started$/.test(bar.textContent), bar && bar.textContent);
    check(root.className === "pace-debug" && root.querySelector(".pace-debug__panel").hidden, "the panel was open");
    bar.click();
    check(root.className === "pace-debug is-open" && !root.querySelector(".pace-debug__panel").hidden, "the tap did not open it");
    bar.click();
    check(root.querySelector(".pace-debug__panel").hidden, "the second tap did not close it");
    check(!!root.querySelector(".pace-debug__area") && root.querySelectorAll(".pace-debug__button").length === 3, "buttons");
  });

  test("readout", "each reason shows in the bar", function () {
    var seen = {};
    var S = dbg();
    S.est.start();
    S.est.tick(S.t + 1000);
    seen.noEvents = S.est.debugWhy();
    var T = dbg();
    T.est.start();
    run(T, 3, { motion: walkSignal(1.8, 1, 51) });
    seen.short = T.est.debugWhy();
    var U = dbg();
    U.est.start();
    run(U, 30, { motion: irregularSignal(52) });
    seen.irregular = U.est.debugWhy();
    var V = dbg();
    V.est.start();
    run(V, 30, { motion: walkSignal(1.8, 1, 53), gps: slowGps(0, 0) });
    seen.still = V.est.debugWhy();
    var X = dbg();
    X.est.start();
    run(X, 30, { motion: walkSignal(1.8, 1, 54), gps: slowGps(4) });
    seen.vehicle = X.est.debugWhy();
    var Y = dbg();
    Y.est.start();
    run(Y, 30, { motion: walkSignal(1.8, 1, 55), gps: slowGps(1.3) });
    seen.ok = Y.est.debugWhy();
    var Z = dbg();
    Z.est.start();
    run(Z, 30, { motion: walkSignal(1.8, 1, 56) });
    seen.noGps = Z.est.debugWhy();
    var N = dbg();
    N.est.start();
    N.est.noteNearStop(true);
    N.est.noteNearStop(true);
    seen.near = N.est.debugWhy();
    var D = dbg({ debugContext: function () { return { demo: true }; } });
    seen.demo = D.est.debugWhy();
    var P = dbg();
    P.est.start();
    return P.est.requestPermission().then(function () {
      seen.granted = P.est.debugWhy();
      var Q = scenario({ win: fakeWin({ motion: { requestPermission: function () { return Promise.resolve("denied"); } }, debug: true }), debug: true });
      Q.est.start();
      return Q.est.requestPermission().then(function () {
        seen.denied = Q.est.debugWhy();
        var want = {
          noEvents: "no motion events", short: "short window", irregular: "irregular cadence", still: "gps still",
          vehicle: "not walking", ok: "ok", noGps: "no GPS speed", near: "near stop (estimator off)",
          demo: "demo mode", granted: "no motion events", denied: "no motion permission"
        };
        Object.keys(want).forEach(function (key) {
          check(seen[key] === want[key], key + ": " + seen[key]);
        });
      });
    });
  });

  test("readout", "a trace of 90 rows has the listed columns and no position", function () {
    var S = dbg();
    S.est.start();
    S.est.traceStart();
    run(S, 100, { motion: handheldSignal(57), gps: slowGps(1.3) });
    var all = S.est.traceText().split("\n");
    check(/^# RUN_REJECT_RATIO=1\.3 GPS_ONLY_CV_MAX=0\.2 LEARN_MIN_VALID_CADENCE=10 AUTOCORR_MIN=0\.3 MOTION_RMS_MIN=0\.4 STEADY_CV_MAX=0\.15$/.test(all[0]), "constants line: " + all[0]);
    var lines = all.slice(1);
    var head = lines[0].split(",");
    ["t", "cadence", "score", "cad_cv", "rms", "gps", "gps_kind", "gps_acc", "fix_age", "speed_fix_age", "walking",
      "reason", "used", "null_cad", "go_n", "go_in", "go_out", "go_cv", "go_fail", "step", "n", "learn",
      "best_in_range_f", "best_in_range_score", "best_overall_f", "best_overall_score", "best_low_f",
      "best_low_score", "cad_pick_reason", "smoothed"].forEach(function (name) {
      check(head.indexOf(name) !== -1, "missing column " + name);
    });
    check(lines.length === 91, "rows " + (lines.length - 1));
    lines.slice(1).forEach(function (line, i) {
      var cells = line.split(",");
      check(cells.length === head.length, "row " + i + " has " + cells.length + " cells");
      check(Number(cells[0]) === i, "row " + i + " starts at " + cells[0]);
    });
    check(lines[60].split(",")[head.indexOf("gps_kind")] === "reported", "gps kind");
    check(/trace ready: 90 rows/.test(document.getElementById("pace-debug").textContent), "status");
    S.est.stop("test");
  });

  test("readout", "copy uses the clipboard and falls back to a visible text area", function () {
    var written = [];
    var S = dbg({ clipboard: { writeText: function (text) { written.push(text); return Promise.resolve(); } } });
    S.est.start();
    S.est.traceStart();
    run(S, 5, { motion: walkSignal(1.8, 1, 58), gps: slowGps(1.3) });
    return S.est.copyTrace().then(function (how) {
      check(how === "copied" && written.length === 1 && written[0] === S.est.traceText(), "clipboard " + how);
      check(S.est.debugArea().hidden, "area shown after a copy");
      var T = dbg({ clipboard: { writeText: function () { return Promise.reject(new Error("blocked")); } } });
      T.est.start();
      T.est.traceStart();
      run(T, 5, { motion: walkSignal(1.8, 1, 59), gps: slowGps(1.3) });
      return T.est.copyTrace().then(function (how2) {
        var area = T.est.debugArea();
        check(how2 === "shown" && !area.hidden && area.value === T.est.traceText(), "fallback " + how2);
        var U = dbg({ clipboard: null });
        U.est.traceStart();
        return U.est.copyTrace().then(function (how3) {
          check(how3 === "empty", "an empty trace was copied " + how3);
        });
      });
    });
  });


  // ---------- the cadence octave rule, learning gate, GPS-only steadiness, clearing, raw capture ----------

  /* A step rhythm at f0 plus a second harmonic of relative size h, 10% jitter per cycle, noise. */
  function harmonicSignal(f0, h, seed) {
    var r = rng(seed);
    var phase = 0;
    var last = null;
    var freq = f0;
    var idx = -1;
    return function (t) {
      var dt = last === null ? 0 : t - last;
      last = t;
      phase += freq * dt;
      if (Math.floor(phase) !== idx) {
        idx = Math.floor(phase);
        freq = f0 * Math.min(1.25, Math.max(0.75, 1 + 0.1 * gauss(r)));
      }
      // a constant offset keeps the magnitude positive, so the harness's |x| does not rectify the rhythm
      return 3 + h + Math.cos(2 * Math.PI * phase) + h * Math.cos(4 * Math.PI * phase) + 0.3 * gauss(r);
    };
  }

  /* Equal steps at f (a running-like rhythm), optional jitter. */
  function periodicSignal(f, jitter, seed) {
    var r = rng(seed);
    var phase = 0;
    var last = null;
    var freq = f;
    var idx = -1;
    return function (t) {
      var dt = last === null ? 0 : t - last;
      last = t;
      phase += freq * dt;
      if (jitter && Math.floor(phase) !== idx) {
        idx = Math.floor(phase);
        freq = f * Math.min(1.25, Math.max(0.75, 1 + jitter * gauss(r)));
      }
      var p = phase % 1;
      return 3 * (p < 0.5 ? Math.pow(Math.sin(Math.PI * p / 0.5), 2) : 0) + 0.15 * gauss(r);
    };
  }

  /* Seconds of a signal after the 10 s warm-up: how many give the true cadence, how many are not valid. */
  function share(make, seeds, truth, withGps) {
    var out = { total: 0, good: 0, invalid: 0, highValid: 0 };
    seeds.forEach(function (seed) {
      var S = scenario();
      run(S, 40, { motion: make(seed), gps: withGps }, function (snap) {
        if (S.t < 10500) {
          return;
        }
        out.total += 1;
        if (snap.cadence === null) {
          out.invalid += 1;
        } else {
          if (Math.abs(snap.cadence - truth) <= truth * 0.06) {
            out.good += 1;
          }
          if (snap.cadence > C.CADENCE_MAX) {
            out.highValid += 1;
          }
        }
      });
    });
    return out;
  }

  [0.8, 1.0, 1.2].forEach(function (h) {
    test("octave", "a 1.9 steps/s rhythm with a second harmonic of " + h + " times the fundamental gives 1.9", function () {
      var out = share(function (seed) { return harmonicSignal(1.9, h, seed); }, [61, 62, 63], 1.9);
      check(out.good >= 0.9 * out.total, out.good + " of " + out.total);
    });
  });

  test("octave", "with a second harmonic of 2.0 times the fundamental at least 90% of seconds give 1.9", function () {
    var out = share(function (seed) { return harmonicSignal(1.9, 2.0, seed); }, [64, 65, 66], 1.9);
    check(out.good >= 0.9 * out.total, out.good + " of " + out.total);
  });

  test("octave", "with a second harmonic of 3.0 times the fundamental 3.8 is never valid and 60% give 1.9", function () {
    var out = share(function (seed) { return harmonicSignal(1.9, 3.0, seed); }, [67, 68, 69], 1.9);
    check(out.highValid === 0, "a valid cadence above 2.8");
    check(out.good >= 0.6 * out.total, out.good + " of " + out.total);
  });

  test("octave", "a 3.2 steps/s running rhythm with jitter: 40% of seconds are not valid and none is above 2.8", function () {
    var out = share(function (seed) { return periodicSignal(3.2, 0.1, seed); }, [71, 72, 73], 1.6);
    check(out.highValid === 0, "a valid cadence above 2.8");
    check(out.invalid >= 0.4 * out.total, "only " + out.invalid + " of " + out.total + " not valid");
  });

  test("octave", "running with a GPS speed at or above 2.2 m/s is not walking", function () {
    [2.2, 3.5].forEach(function (speed) {
      var S = scenario();
      var snap = run(S, 30, { motion: periodicSignal(3.2, 0.1, 74), gps: function () { return { speed: speed, acc: 8 }; } });
      check(!snap.walking && snap.walkingReason === "vehicle" && snap.mode !== "gps" && snap.mode !== "cadence",
        speed + ": " + snap.walkingReason + " " + snap.mode);
    });
  });

  test("octave", "a half-rate arm swing does not give 0.95", function () {
    var seen = [];
    var S = scenario();
    run(S, 30, { motion: walkSignal(1.9, 0.5, 75) }, function (snap) {
      if (snap.cadence !== null) {
        seen.push(snap.cadence);
      }
    });
    check(seen.length > 10, "no valid cadence at all");
    seen.forEach(function (value) { check(Math.abs(value - 0.95) > 0.2 && Math.abs(value - 1.9) <= 0.1, "cadence " + value); });
  });

  /* 8 s of a jittered periodic rhythm, as samples at 50 Hz. */
  function periodicSamples(f, jitter, seed) {
    var g = periodicSignal(f, jitter, seed);
    var out = [];
    for (var i = 0; i < 400; i++) {
      out.push(g(i / 50));
    }
    return out;
  }

  test("octave", "a fast peak just above 1.3 times the in-range score is rejected, just below is accepted", function () {
    var above = null;
    var below = null;
    for (var seed = 1; seed <= 600 && (above === null || below === null); seed++) {
      var e = W.estimateCadence(periodicSamples(3.2, 0.1, seed), 50);
      if (e.fastScore === null || e.chosenScore === null || e.chosenScore < C.AUTOCORR_MIN) {
        continue;
      }
      var ratio = e.fastScore / e.chosenScore;
      if (ratio >= C.RUN_REJECT_RATIO && ratio < C.RUN_REJECT_RATIO + 0.1 && above === null) {
        above = { e: e, ratio: ratio };
      } else if (ratio < C.RUN_REJECT_RATIO && ratio >= C.RUN_REJECT_RATIO - 0.1 && below === null) {
        below = { e: e, ratio: ratio };
      }
    }
    check(above !== null && below !== null, "no windows near the limit");
    check(!above.e.valid && above.e.reason === "fast" && above.e.pick === "reject_ratio" && above.e.cadence > C.CADENCE_MAX,
      "above " + above.ratio + ": " + above.e.reason + " " + above.e.pick);
    check(below.e.valid && below.e.cadence > 1.5 && below.e.cadence < 1.7, "below " + below.ratio + ": " + below.e.reason);
  });

  test("octave", "DOCUMENTED LIMITATION: a perfectly periodic 3.2 steps/s rhythm with no GPS can read as about 1.6, and the speed stays capped", function () {
    [0.95, 0.7].forEach(function (length) {
      var storage = memStorage({ "bus-catch-step-length": JSON.stringify({ length: length, count: 3, savedAt: 0 }) });
      var S = scenario({ storage: storage });
      var valid = 0;
      var top = 0;
      var snap = run(S, 40, { motion: periodicSignal(3.2, 0, 76) }, function (sn) {
        if (sn.cadence !== null) {
          valid += 1;
          check(sn.cadence > 1.5 && sn.cadence < 1.7, "cadence " + sn.cadence);
        }
        if (sn.smoothed !== null) {
          top = Math.max(top, sn.smoothed);
          check(sn.smoothed <= C.SPEED_MAX + 1e-9, "speed " + sn.smoothed);
          check(sn.smoothed <= 1.7 * sn.stepLength + 1e-9, "speed above cadence x step length");
        }
      });
      check(valid > 10, "the limitation did not show: " + valid);
      check(snap.mode === "cadence" && top > 0, "mode " + snap.mode);
    });
  });

  test("octave", "the constants have the agreed values", function () {
    check(C.RUN_REJECT_RATIO === 1.3 && C.GPS_ONLY_CV_MAX === 0.2 && C.LEARN_MIN_VALID_CADENCE === 10, "values");
    check(C.STEADY_CV_MAX === 0.15 && C.AUTOCORR_MIN === 0.3 && C.CADENCE_MAX === 2.8, "unchanged values");
  });

  function gpsRecs(speeds) {
    return speeds.map(function (v, i) { return { t: i * 1000, gpsSpeed: v }; });
  }

  test("octave", "GPS-only steadiness: a ramp-up and CV 0.15 to 0.19 pass, a noisy 0.25 fails", function () {
    var ramp = W.detectWalkingGpsOnly(gpsRecs([0.8, 0.95, 1.1, 1.2, 1.25, 1.3, 1.3, 1.3, 1.3]), 8000);
    check(ramp.walking && ramp.cv > 0.08 && ramp.cv < 0.2, "ramp " + ramp.reason + " " + ramp.cv);
    var edge = W.detectWalkingGpsOnly(gpsRecs([1.02, 1.38, 1.02, 1.38, 1.02, 1.38, 1.02, 1.38, 1.02]), 8000);
    check(edge.walking && edge.cv >= C.STEADY_CV_MAX && edge.cv < C.GPS_ONLY_CV_MAX, "edge " + edge.reason + " " + edge.cv);
    var noisy = W.detectWalkingGpsOnly(gpsRecs([0.9, 1.5, 0.9, 1.5, 0.9, 1.5, 0.9, 1.5, 0.9]), 8000);
    check(!noisy.walking && noisy.reason === "irregular" && noisy.cv > 0.2, "noisy " + noisy.reason + " " + noisy.cv);
  });

  test("octave", "the cadence rule still uses STEADY_CV_MAX (0.15), not the GPS-only limit", function () {
    var rows = [];
    for (var i = 0; i < 9; i++) {
      rows.push({ t: i * 1000, cadence: i % 2 ? 2.2 : 1.6, gpsSpeed: null });  // CV about 0.16
    }
    var verdict = W.detectWalking(rows, null, 8000);
    check(!verdict.walking && verdict.reason === "irregular" && verdict.cv > 0.15 && verdict.cv < 0.2, verdict.reason + " " + verdict.cv);
  });

  // ---- the learning gate: enough valid-cadence seconds

  test("learning", "a window with 11 valid seconds and 3 doubled (null) ones learns", function () {
    var window14 = recs({ n: 14, cadence: function (i) { return i === 2 || i === 6 || i === 10 ? null : 1.8; } });
    var valid = window14.filter(function (r) { return r.cadence !== null; }).length;
    var out = W.learnStep(window14, { length: 0.7, count: 0 });
    check(valid === 11 && out.accepted, valid + " valid, " + out.reason);
  });

  test("learning", "9 valid seconds do not learn", function () {
    var out = W.learnStep(recs({ n: 14, cadence: function (i) { return i < 9 ? 1.8 : null; } }), { length: 0.7, count: 0 });
    check(!out.accepted && out.reason === "few valid cadence", out.reason);
  });

  test("learning", "10 valid seconds learn, with the median and CV over the valid ones only", function () {
    var out = W.learnStep(recs({ n: 14, cadence: function (i) { return i < 10 ? 1.8 : null; } }), { length: 0.7, count: 0 });
    check(out.accepted, out.reason);
    var unsteady = W.learnStep(recs({ n: 14, cadence: function (i) { return i < 10 ? (i % 2 ? 2.4 : 1.6) : null; } }), { length: 0.7, count: 0 });
    check(!unsteady.accepted && unsteady.reason === "cadence not steady", unsteady.reason);
  });

  test("learning", "a vehicle second or a not-walking second blocks learning", function () {
    var vehicle = W.learnStep(recs({ n: 14, speed: function (i) { return i === 6 ? 3.0 : 1.26; } }), { length: 0.7, count: 0 });
    check(!vehicle.accepted, "a vehicle second learned");
    var notWalking = recs({ n: 14 });
    notWalking[5].walking = false;
    var out = W.learnStep(notWalking, { length: 0.7, count: 0 });
    check(!out.accepted && out.reason === "not walking", out.reason);
    var missingGps = W.learnStep(recs({ n: 14, speed: function (i) { return i === 3 ? null : 1.26; } }), { length: 0.7, count: 0 });
    check(!missingGps.accepted && missingGps.reason === "missing", missingGps.reason);
  });

  test("learning", "the estimator learns from a walk with doubled seconds in between", function () {
    var S = scenario();
    var n = 0;
    run(S, 60, {
      motion: harmonicSignal(1.9, 2.0, 77),
      gps: function () { return { speed: 1.2, report: 1.2 + 0.01 * ((n++ % 3) - 1), acc: 8 }; }
    });
    check(S.est.snapshot().stepCount >= 1, "no step sample learned: " + S.est.snapshot().lastLearn);
  });

  // ---- the stale speed is cleared on a new journey, not on a pause

  test("lifecycle", "a new Start journey tap clears the smoothed value, the hold and the slew state", function () {
    var S = scenario();
    run(S, 30, { motion: walkSignal(1.8, 1, 78), gps: goodGps(1.2) });
    check(S.est.snapshot().smoothed !== null && S.est.pollValue() !== null, "no speed to clear");
    S.est.stop("yes");
    S.est.resetLeg();
    S.est.start();
    var snap = S.est.snapshot();
    check(snap.smoothed === null && snap.mode === "none" && snap.sent === null, "kept " + snap.smoothed + " " + snap.mode);
    check(S.est.pollValue() === null, "a stale speed was sent");
    S.est.tick(S.t + 1000);
    check(S.est.snapshot().smoothed === null && S.est.pollValue() === null, "a stale speed came back through the hold");
    S.est.stop("test");
  });

  test("lifecycle", "a pause and a resume keep the smoothed speed", function () {
    var S = scenario();
    run(S, 30, { motion: walkSignal(1.8, 1, 79), gps: goodGps(1.2) });
    var before = S.est.snapshot().smoothed;
    S.est.stop("paused");
    S.est.start();
    check(S.est.snapshot().smoothed === before && before !== null, "the speed was cleared by a resume");
    S.est.stop("test");
  });

  test("lifecycle", "with a remembered pace loaded a new journey uses it with source remembered", function () {
    var storage = memStorage({ "bus-catch-pace": JSON.stringify({ pace: 1.0, savedAt: 0 }) });
    var S = scenario({ storage: storage });
    run(S, 30, { motion: walkSignal(1.8, 1, 80), gps: goodGps(1.3) });
    S.est.stop("yes");
    S.est.resetLeg();
    S.est.start();
    check(S.est.snapshot().smoothed === null, "kept the smoothed speed");
    var sent = S.est.pollValue();
    check(sent && sent.source === "remembered" && Math.abs(sent.speed - 1.0) < 1e-9, JSON.stringify(sent));
    S.est.stop("test");
  });

  // ---- the diagnostics, the stride-rate peak and the raw capture

  test("handheld", "used in the trace is what a poll would send, or a dash", function () {
    var S = dbg();
    S.est.start();
    S.est.traceStart();
    run(S, 3, { motion: stillSignal(81) });
    var rows = S.est.traceText().split("\n").slice(2);
    var head = S.est.traceText().split("\n")[1].split(",");
    var used = head.indexOf("used");
    rows.forEach(function (row) { check(row.split(",")[used] === "-", "used " + row.split(",")[used]); });
    check(head[head.length - 1] === "smoothed" && head[head.length - 2] === "used_src", "columns");
    S.est.stop("test");
  });

  test("handheld", "a stride-rate peak below 1.2 is visible in the diagnostics but never accepted", function () {
    function pocket(seed) {
      var r = rng(seed);
      var ph = 0;
      var fr = 1.9;
      var idx = -1;
      return function (t) {
        if (pocket.last === undefined) { pocket.last = t; }
        ph += fr * (t - pocket.last);
        pocket.last = t;
        if (Math.floor(ph) !== idx) {
          idx = Math.floor(ph);
          fr = 1.9 * Math.min(1.25, Math.max(0.75, 1 + 0.1 * gauss(r)));
        }
        var f = ph - Math.floor(ph);
        var amp = idx % 2 === 0 ? 1 : 0.3;
        var bump = f < 0.5 ? Math.pow(Math.sin(Math.PI * f / 0.5), 2) : 0;
        return 3 * amp * bump + 2 * (1 + Math.cos(Math.PI * ph)) + 0.5 * Math.abs(gauss(r));
      };
    }
    var seen = { low: 0, total: 0, accepted: 0 };
    var S = scenario();
    run(S, 30, { motion: pocket(82) }, function (snap) {
      if (S.t < 10500) {
        return;
      }
      seen.total += 1;
      var d = snap.cadenceDiag;
      if (d.bestLowF !== null && d.bestLowF > 0.8 && d.bestLowF < 1.1 && d.bestLowScore > 0.3) {
        seen.low += 1;
      }
      if (snap.cadence !== null) {
        seen.accepted += 1;
        check(snap.cadence >= C.CADENCE_MIN, "accepted below the range");
      }
    });
    check(seen.low >= 0.7 * seen.total, "the stride peak was visible in " + seen.low + " of " + seen.total);
  });

  test("readout", "one record tap also captures raw motion at 25 Hz, 25 values a line, in memory only", function () {
    var S = dbg();
    S.est.start();
    S.est.traceStart();
    run(S, 100, { motion: handheldSignal(83), gps: slowGps(1.3) });
    var lines = S.est.rawText().split("\n");
    check(lines[0] === "hz=25", "first line " + lines[0]);
    var values = lines.slice(1).join(",").split(",");
    check(values.length === 2250, "values " + values.length);
    check(lines.length === 91 && lines.slice(1).every(function (l) { return l.split(",").length === 25; }), "lines " + lines.length);
    check(values.every(function (v) { return /^-?\d+\.\d\d$/.test(v); }), "format");
    check(!/[a-zA-Z]/.test(lines.slice(1).join("")), "not numbers only");
    // the values follow the signal: a walking magnitude is not flat
    var nums = values.map(Number);
    var lo = Math.min.apply(null, nums);
    var hi = Math.max.apply(null, nums);
    check(hi - lo > 0.5, "flat series");
    check(/raw 2250 values/.test(document.getElementById("pace-debug").textContent), "status");
    S.est.stop("test");
  });

  test("readout", "Copy raw motion uses the clipboard and falls back to the text area", function () {
    var written = [];
    var S = dbg({ clipboard: { writeText: function (text) { written.push(text); return Promise.resolve(); } } });
    S.est.start();
    S.est.traceStart();
    run(S, 12, { motion: handheldSignal(84), gps: slowGps(1.3) });
    return S.est.copyRaw().then(function (how) {
      check(how === "copied" && written.length === 1 && written[0] === S.est.rawText(), "clipboard " + how);
      var T = dbg({ clipboard: null });
      T.est.start();
      T.est.traceStart();
      run(T, 12, { motion: handheldSignal(85), gps: slowGps(1.3) });
      return T.est.copyRaw().then(function (how2) {
        var area = T.est.debugArea();
        check(how2 === "shown" && !area.hidden && area.value === T.est.rawText(), "fallback " + how2);
        var U = dbg({ clipboard: null });
        return U.est.copyRaw().then(function (how3) { check(how3 === "empty", "empty raw " + how3); });
      });
    });
  });

  // ---------- done ----------

  Promise.all(pending).then(function () {
    var out = document.getElementById("results");
    out.textContent = JSON.stringify(results);
    document.documentElement.setAttribute("data-done", "1");
  });
})();
