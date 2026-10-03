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
      watchPosition: function () { geo.watches += 1; return 7; },
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
      location: { search: "" },
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
      timers: o.timers || manualTimers()
    });
    S.est = est;
    return S;
  }

  /* Advance seconds of simulated time. cfg.motion(tSec) gives the magnitude (or null for no motion events);
     cfg.motionG(tSec) gives an accelerationIncludingGravity vector; cfg.gps(tSec) gives
     {speed (true m/s), report (number or null), acc} or null for no fix. */
  function run(S, seconds, cfg) {
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
            t: S.t,
            lat: LAT0 + S.dist / 111195,
            lon: 103.8,
            accuracy: g.acc,
            speed: g.report === undefined ? g.speed : g.report
          });
        }
        S.est.tick(S.t);
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

  test("cadence", "a signal at 3.5 Hz (running) is rejected", function () {
    var S = scenario();
    var snap = run(S, 25, { motion: walkSignal(3.5, 1, 13) });
    check(!snap.walking && snap.cadence === null && snap.cadenceReason === "fast", "reason " + snap.cadenceReason);
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
    check(W.gpsSpeed([fix(0, 0, 10, 1.2)], 11000) === null, "an 11 s old fix accepted");
    near(W.gpsSpeed([fix(0, 0, 10, 1.2)], 10000).speed, 1.2, 1e-9);
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
    check(!run(before, 20, { gps: goodGps(1.1) }).walking, "GPS alone counted before the sensor was declared off");
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

  // ---------- done ----------

  Promise.all(pending).then(function () {
    var out = document.getElementById("results");
    out.textContent = JSON.stringify(results);
    document.documentElement.setAttribute("data-done", "1");
  });
})();
