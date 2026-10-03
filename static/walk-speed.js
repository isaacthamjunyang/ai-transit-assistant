/* Walking-speed estimator. Pure functions first, then a thin browser layer.

   This is the only file that may use localStorage (index.html must not). It keeps the learned step
   length and a remembered pace, and nothing else: no raw sensor data, no positions, no times of
   positions. Motion data never leaves the phone. The page sends only the speed number.

   Foreground only. The sensors and the location watch run only between "Start journey" and the
   moment the page stops them (see createEstimator). Nothing here runs in the background. */
(function (root) {
  "use strict";

  /* ===================== TUNABLE CONSTANTS (starting guesses) ===================== */
  var CONSTANTS = {
    CADENCE_MIN: 1.2,            // steps per second
    CADENCE_MAX: 2.8,            // steps per second
    WINDOW_S: 8,                 // sliding cadence window
    AUTOCORR_MIN: 0.3,           // smallest normalised autocorrelation score that counts
    GPS_ACC_MAX_USE: 30,         // metres: a fix with worse accuracy is ignored
    GPS_ACC_MAX_LEARN: 15,       // metres: median accuracy needed to learn
    GPS_FIX_MAX_AGE_S: 10,       // seconds: older fixes give no GPS speed
    LEARN_SPEED_MIN: 0.7,        // m/s
    LEARN_SPEED_MAX: 2.0,        // m/s
    VEHICLE_SPEED_MIN: 2.2,      // m/s: at or above this the user is not walking
    STEADY_CV_MAX: 0.15,         // coefficient of variation limit for "steady"
    LEARN_MIN_STEADY_S: 15,      // seconds of steady walking per learning sample
    LEARN_ALPHA: 0.2,            // exponential average weight for the step length
    STEP_LEN_PRIOR: 0.70,        // metres
    STEP_LEN_MIN: 0.45,          // metres
    STEP_LEN_MAX: 0.95,          // metres
    CADENCE_MODE_MIN_SAMPLES: 3, // learning samples before cadence x step length is used
    HOLD_STANDING_S: 30,         // seconds a short stop keeps the last speed
    SMOOTH_TAU_S: 10,            // seconds, exponential filter on the speed
    SLEW_MPS_PER_POLL: 0.15,     // largest change in the value sent between polls
    REMEMBER_MIN_WALK_S: 60,     // seconds of measured walking before the pace is remembered
    REMEMBER_MAX_AGE_DAYS: 30,   // days a remembered pace stays usable

    /* Implied by the brief (named here so nothing is buried in the code). */
    SPEED_MIN: 0.5,              // m/s, the same clamp as the server
    SPEED_MAX: 1.4,              // m/s, the top of a normal walk
    LEARN_CADENCE_MIN: 1.3,      // steps per second, learning gate
    LEARN_CADENCE_MAX: 2.6,      // steps per second, learning gate
    LEARN_L_MIN: 0.35,           // metres, a learning sample outside this is rejected
    LEARN_L_MAX: 1.1,            // metres
    LEARN_DISAGREE_MPS: 0.6,     // GPS speed versus cadence x step length
    LEARN_MIN_RECORDS: 13,       // one-per-second records needed inside the 15 s window
    GPS_DERIVE_MIN_S: 20,        // seconds between two fixes to derive a speed
    GPS_DERIVE_MIN_M: 40,        // metres of net displacement to derive a speed
    GPS_DERIVE_ACC_FACTOR: 4,    // ... and at least this many times the accuracy
    PEAK_RATIO: 0.8,             // shortest lag with at least this share of the best score wins
    RUN_CADENCE_MAX: 4.5,        // search lags up to this rate so running is seen, then rejected
    REGULAR_S: 8,                // seconds of valid, regular cadence before "walking detected"
    REGULAR_MIN_READINGS: 7,     // one-per-second readings needed inside that span
    MIN_WINDOW_S: 6,             // least data before a cadence is estimated
    GPS_WALK_MIN_MPS: 0.3,       // m/s: with a good fix, walking needs a GPS speed of at least this ...
    GPS_STILL_REJECT_S: 5,       // ... unless it has been under it for less than this many seconds in a row
    GPS_ONLY_WALK_MIN: 0.7,      // m/s: with no motion sensor, steady GPS speed from here to the vehicle limit is walking
    MOTION_RMS_MIN: 0.4,         // m/s^2: below this the phone is still
    MOTION_STALE_S: 2,           // no motion sample this long means no cadence
    RESAMPLE_HZ: 50,             // uniform rate for the autocorrelation
    BUFFER_S: 10,                // seconds of motion samples kept in memory
    GRAVITY_TAU_S: 0.5,          // low-pass time constant when gravity must be removed
    MOTION_TIMEOUT_MS: 3000,     // no motion event this long after start: sensor unavailable
    TICK_MS: 1000,               // the fusion runs about once per second
    SLEW_MIN_INTERVAL_MS: 2000,  // one slew step at most per this interval (one step per poll)
    REMEMBER_SAVE_EVERY_S: 30,   // how often the remembered pace may be rewritten
    STEP_KEY: "bus-catch-step-length",
    PACE_KEY: "bus-catch-pace"
  };

  /* ================================ pure functions ================================ */

  function isNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  function clamp(value, low, high) {
    return Math.min(high, Math.max(low, value));
  }

  function mean(values) {
    if (!values.length) {
      return NaN;
    }
    var sum = 0;
    for (var i = 0; i < values.length; i++) {
      sum += values[i];
    }
    return sum / values.length;
  }

  function median(values) {
    if (!values.length) {
      return NaN;
    }
    var sorted = values.slice().sort(function (a, b) { return a - b; });
    var mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }

  /* Coefficient of variation: population standard deviation over the mean. */
  function cv(values) {
    if (values.length < 2) {
      return Infinity;
    }
    var m = mean(values);
    if (!(m > 0)) {
      return Infinity;
    }
    var sum = 0;
    for (var i = 0; i < values.length; i++) {
      sum += (values[i] - m) * (values[i] - m);
    }
    return Math.sqrt(sum / values.length) / m;
  }

  /* Acceleration magnitude without gravity. Uses the linear acceleration when the browser gives it,
     otherwise low-passes accelerationIncludingGravity and subtracts that. The magnitude does not
     depend on how the phone is held. state is {init, gx, gy, gz, t}. Returns a number or null. */
  function motionMagnitude(sample, state, constants) {
    var C = constants || CONSTANTS;
    var lin = sample && sample.acceleration;
    if (lin && isNumber(lin.x) && isNumber(lin.y) && isNumber(lin.z)) {
      return Math.sqrt(lin.x * lin.x + lin.y * lin.y + lin.z * lin.z);
    }
    var g = sample && sample.accelerationIncludingGravity;
    if (!g || !isNumber(g.x) || !isNumber(g.y) || !isNumber(g.z)) {
      return null;
    }
    var t = isNumber(sample.t) ? sample.t : 0;
    if (!state.init) {
      state.init = true;
      state.gx = g.x;
      state.gy = g.y;
      state.gz = g.z;
      state.t = t;
      return 0;
    }
    var dt = Math.max(0.001, Math.min(1, (t - state.t) / 1000));
    var alpha = dt / (C.GRAVITY_TAU_S + dt);
    state.gx += alpha * (g.x - state.gx);
    state.gy += alpha * (g.y - state.gy);
    state.gz += alpha * (g.z - state.gz);
    state.t = t;
    var dx = g.x - state.gx;
    var dy = g.y - state.gy;
    var dz = g.z - state.gz;
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
  }

  /* Linear resample of (times in ms, values) onto a uniform grid of hz between t0 and t1. */
  function resample(times, values, t0, t1, hz) {
    var out = [];
    var step = 1000 / hz;
    var j = 0;
    for (var t = t0; t <= t1 + 1e-6; t += step) {
      while (j < times.length - 2 && times[j + 1] < t) {
        j++;
      }
      var ta = times[j];
      var tb = times[j + 1];
      if (tb === undefined) {
        out.push(values[j]);
      } else if (tb === ta) {
        out.push(values[j]);
      } else {
        var f = clamp((t - ta) / (tb - ta), 0, 1);
        out.push(values[j] + f * (values[j + 1] - values[j]));
      }
    }
    return out;
  }

  /* Normalised autocorrelation at a lag: the mean product over the overlap divided by the mean power,
     so a perfectly periodic signal scores near 1 at its period whatever the window length. */
  function autocorr(x, lag, power) {
    var n = x.length - lag;
    if (n <= 0 || !(power > 0)) {
      return 0;
    }
    var sum = 0;
    for (var i = 0; i < n; i++) {
      sum += x[i] * x[i + lag];
    }
    return (sum / n) / power;
  }

  /* Cadence (steps per second) from a uniformly sampled magnitude signal at fs hertz.
     Returns {valid, cadence, score, reason}. Peaks are not counted. The dominant period comes from the
     autocorrelation, taking the shortest lag whose score is at least PEAK_RATIO of the best, so an
     arm-swing at half the step rate is not mistaken for the cadence. Valid only at AUTOCORR_MIN or more
     and inside CADENCE_MIN to CADENCE_MAX. A faster rhythm (running) is rejected. */
  function estimateCadence(samples, fs, constants) {
    var C = constants || CONSTANTS;
    var n = samples.length;
    if (n < C.MIN_WINDOW_S * fs * 0.9) {
      return { valid: false, cadence: null, score: 0, reason: "short" };
    }
    var m = mean(samples);
    var x = new Array(n);
    var energy = 0;
    for (var i = 0; i < n; i++) {
      x[i] = samples[i] - m;
      energy += x[i] * x[i];
    }
    var power = energy / n;
    if (Math.sqrt(power) < C.MOTION_RMS_MIN) {
      return { valid: false, cadence: null, score: 0, reason: "still" };
    }
    var lagMin = Math.max(2, Math.floor(fs / C.RUN_CADENCE_MAX));
    var lagMax = Math.min(n - 2, Math.ceil(fs / C.CADENCE_MIN) + 1);
    var r = {};
    for (var lag = lagMin - 1; lag <= lagMax + 1; lag++) {
      r[lag] = autocorr(x, lag, power);
    }
    var peaks = [];
    var best = 0;
    for (lag = lagMin; lag <= lagMax; lag++) {
      if (r[lag] > 0 && r[lag] >= r[lag - 1] && r[lag] > r[lag + 1]) {
        peaks.push(lag);
        if (r[lag] > best) {
          best = r[lag];
        }
      }
    }
    if (!peaks.length || best < C.AUTOCORR_MIN) {
      return { valid: false, cadence: null, score: Math.max(0, best), reason: "weak" };
    }
    var chosen = peaks[0];
    for (var k = 0; k < peaks.length; k++) {
      if (r[peaks[k]] >= C.PEAK_RATIO * best) {
        chosen = peaks[k];
        break;
      }
    }
    var a = r[chosen - 1];
    var b = r[chosen];
    var c = r[chosen + 1];
    var denom = a - 2 * b + c;
    var shift = denom < 0 ? clamp(0.5 * (a - c) / denom, -0.5, 0.5) : 0;
    var frequency = fs / (chosen + shift);
    var score = r[chosen];
    if (score < C.AUTOCORR_MIN) {
      return { valid: false, cadence: null, score: score, reason: "weak" };
    }
    if (frequency > C.CADENCE_MAX) {
      return { valid: false, cadence: frequency, score: score, reason: "fast" };
    }
    if (frequency < C.CADENCE_MIN) {
      return { valid: false, cadence: frequency, score: score, reason: "slow" };
    }
    return { valid: true, cadence: frequency, score: score, reason: "ok" };
  }

  function haversineMetres(lat1, lon1, lat2, lon2) {
    var radius = 6371000;
    var p1 = lat1 * Math.PI / 180;
    var p2 = lat2 * Math.PI / 180;
    var dLat = (lat2 - lat1) * Math.PI / 180;
    var dLon = (lon2 - lon1) * Math.PI / 180;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(p1) * Math.cos(p2) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return radius * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
  }

  /* A fix is usable when its accuracy is at most GPS_ACC_MAX_USE. nowMs is the clock. */
  function fixUsable(fix, nowMs, constants) {
    var C = constants || CONSTANTS;
    if (!fix || !isNumber(fix.lat) || !isNumber(fix.lon) || !isNumber(fix.t) || !isNumber(fix.accuracy)) {
      return false;
    }
    return fix.accuracy <= C.GPS_ACC_MAX_USE && (nowMs - fix.t) / 1000 <= C.GPS_FIX_MAX_AGE_S;
  }

  /* GPS speed from the accepted fixes (oldest first). Uses coords.speed when it is a number on a fix
     that is recent enough. Otherwise derives a speed from two fixes at least GPS_DERIVE_MIN_S apart, only
     when the net displacement is at least max(GPS_DERIVE_MIN_M, GPS_DERIVE_ACC_FACTOR x accuracy).
     Returns {speed, accuracy, derived} or null when there is no GPS speed. */
  function gpsSpeed(fixes, nowMs, constants) {
    var C = constants || CONSTANTS;
    if (!fixes.length) {
      return null;
    }
    var last = fixes[fixes.length - 1];
    if (!fixUsable(last, nowMs, C)) {
      return null;
    }
    if (isNumber(last.speed) && last.speed >= 0) {
      return { speed: last.speed, accuracy: last.accuracy, derived: false };
    }
    for (var i = fixes.length - 2; i >= 0; i--) {
      var older = fixes[i];
      var dt = (last.t - older.t) / 1000;
      if (dt < C.GPS_DERIVE_MIN_S) {
        continue;
      }
      var metres = haversineMetres(older.lat, older.lon, last.lat, last.lon);
      var need = Math.max(C.GPS_DERIVE_MIN_M, C.GPS_DERIVE_ACC_FACTOR * Math.max(older.accuracy, last.accuracy));
      if (metres < need) {
        return null;
      }
      return { speed: metres / dt, accuracy: Math.max(older.accuracy, last.accuracy), derived: true };
    }
    return null;
  }

  /* "Walking detected": a valid cadence that has been regular (coefficient of variation under
     STEADY_CV_MAX) for REGULAR_S seconds, and, when there is a GPS speed, one below VEHICLE_SPEED_MIN.
     recs are the one-per-second records {t, cadence (number or null)}, oldest first. */
  function detectWalking(recs, gps, nowMs, constants) {
    var C = constants || CONSTANTS;
    if (gps && isNumber(gps.speed) && gps.speed >= C.VEHICLE_SPEED_MIN) {
      return { walking: false, reason: "vehicle", cv: null };
    }
    // A good fix whose speed has stayed under GPS_WALK_MIN_MPS for GPS_STILL_REJECT_S seconds in a row means
    // the phone is not moving: a shake at a walking rhythm is not walking. No usable fix, no rule.
    var stillSince = null;
    for (var k = recs.length - 1; k >= 0; k--) {
      if (isNumber(recs[k].gpsSpeed) && recs[k].gpsSpeed < C.GPS_WALK_MIN_MPS) {
        stillSince = recs[k].t;
      } else {
        break;
      }
    }
    if (stillSince !== null && nowMs - stillSince >= C.GPS_STILL_REJECT_S * 1000) {
      return { walking: false, reason: "gps still", cv: null };
    }
    var from = nowMs - (C.REGULAR_S + 0.5) * 1000;
    var recent = [];
    for (var i = 0; i < recs.length; i++) {
      if (recs[i].t >= from) {
        recent.push(recs[i]);
      }
    }
    if (recent.length < C.REGULAR_MIN_READINGS) {
      return { walking: false, reason: "short", cv: null };
    }
    var cadences = [];
    for (var j = 0; j < recent.length; j++) {
      if (!isNumber(recent[j].cadence)) {
        return { walking: false, reason: "irregular", cv: null };
      }
      cadences.push(recent[j].cadence);
    }
    var variation = cv(cadences);
    if (!(variation < C.STEADY_CV_MAX)) {
      return { walking: false, reason: "irregular", cv: variation };
    }
    return { walking: true, reason: "ok", cv: variation };
  }

  /* With no motion sensor (permission denied, unavailable or no event) the page is GPS-only. Walking is then
     a steady GPS speed, from GPS_ONLY_WALK_MIN up to VEHICLE_SPEED_MIN, over REGULAR_S seconds. */
  function detectWalkingGpsOnly(recs, nowMs, constants) {
    var C = constants || CONSTANTS;
    var from = nowMs - (C.REGULAR_S + 0.5) * 1000;
    var speeds = [];
    for (var i = 0; i < recs.length; i++) {
      if (recs[i].t >= from) {
        if (!isNumber(recs[i].gpsSpeed)) {
          return { walking: false, reason: "no gps", cv: null };
        }
        speeds.push(recs[i].gpsSpeed);
      }
    }
    if (speeds.length < C.REGULAR_MIN_READINGS) {
      return { walking: false, reason: "short", cv: null };
    }
    for (var j = 0; j < speeds.length; j++) {
      if (speeds[j] < C.GPS_ONLY_WALK_MIN) {
        return { walking: false, reason: "slow", cv: null };
      }
      if (speeds[j] >= C.VEHICLE_SPEED_MIN) {
        return { walking: false, reason: "vehicle", cv: null };
      }
    }
    var variation = cv(speeds);
    if (!(variation < C.STEADY_CV_MAX)) {
      return { walking: false, reason: "irregular", cv: variation };
    }
    return { walking: true, reason: "ok", cv: variation };
  }

  /* One step-length learning sample from the last LEARN_MIN_STEADY_S seconds of one-per-second records
     {t, walking, cadence, gpsSpeed, gpsAcc}. state is {length, count}. Returns
     {accepted, reason, sample, state}. Every gate rejects its own bad window. */
  function learnStep(recs, state, constants) {
    var C = constants || CONSTANTS;
    var fail = function (reason) {
      return { accepted: false, reason: reason, sample: null, state: state };
    };
    if (recs.length < C.LEARN_MIN_RECORDS) {
      return fail("short");
    }
    var cadences = [];
    var speeds = [];
    var accuracies = [];
    for (var i = 0; i < recs.length; i++) {
      var rec = recs[i];
      if (!rec.walking) {
        return fail("not walking");
      }
      if (!isNumber(rec.cadence) || !isNumber(rec.gpsSpeed) || !isNumber(rec.gpsAcc)) {
        return fail("missing");
      }
      cadences.push(rec.cadence);
      speeds.push(rec.gpsSpeed);
      accuracies.push(rec.gpsAcc);
    }
    if (!(cv(cadences) <= C.STEADY_CV_MAX)) {
      return fail("cadence not steady");
    }
    if (!(cv(speeds) <= C.STEADY_CV_MAX)) {
      return fail("gps not steady");
    }
    if (!(median(accuracies) <= C.GPS_ACC_MAX_LEARN)) {
      return fail("gps accuracy");
    }
    for (var s = 0; s < speeds.length; s++) {
      if (speeds[s] < C.LEARN_SPEED_MIN || speeds[s] > C.LEARN_SPEED_MAX) {
        return fail("gps speed range");
      }
    }
    var cadence = mean(cadences);
    var speed = mean(speeds);
    if (cadence < C.LEARN_CADENCE_MIN || cadence > C.LEARN_CADENCE_MAX) {
      return fail("cadence range");
    }
    var sample = speed / cadence;
    if (sample < C.LEARN_L_MIN || sample > C.LEARN_L_MAX) {
      return fail("length range");
    }
    if (state.count > 0 && Math.abs(speed - cadence * state.length) > C.LEARN_DISAGREE_MPS) {
      return fail("disagreement");
    }
    var base = state.count > 0 ? state.length : C.STEP_LEN_PRIOR;
    var next = clamp(base + C.LEARN_ALPHA * (sample - base), C.STEP_LEN_MIN, C.STEP_LEN_MAX);
    return {
      accepted: true,
      reason: "ok",
      sample: sample,
      state: { length: next, count: state.count + 1 }
    };
  }

  /* The fusion, first match wins. in: {walking, gps (speed or null), cadence (or null), step {length,
     count}, nowMs, lastWalkingAt (or null), lastSpeed (or null), lastMode, remembered {pace, savedAt} or
     null}. Returns {speed, mode}: mode is "gps", "cadence", "hold", "remembered" or "none". */
  function fuse(input, constants) {
    var C = constants || CONSTANTS;
    // A GPS speed under GPS_WALK_MIN_MPS is a stop, not a walking speed. While the 8 s cadence window still
    // says "walking" it must not pull the speed down, so neither GPS nor the stale cadence is used: the
    // last speed is held.
    var stopped = isNumber(input.gps) && input.gps < C.GPS_WALK_MIN_MPS;
    if (input.walking && isNumber(input.gps) && !stopped) {
      return { speed: input.gps, mode: "gps" };
    }
    if (input.walking && !stopped && isNumber(input.cadence) && input.step && input.step.count >= C.CADENCE_MODE_MIN_SAMPLES) {
      return { speed: input.cadence * input.step.length, mode: "cadence" };
    }
    if (input.lastWalkingAt !== null && isNumber(input.lastSpeed) &&
        (input.nowMs - input.lastWalkingAt) / 1000 <= C.HOLD_STANDING_S) {
      return { speed: input.lastSpeed, mode: "hold" };
    }
    if (input.remembered && isNumber(input.remembered.pace) &&
        (input.nowMs - input.remembered.savedAt) / 86400000 <= C.REMEMBER_MAX_AGE_DAYS) {
      return { speed: input.remembered.pace, mode: "remembered" };
    }
    return { speed: null, mode: "none" };
  }

  /* Exponential filter with time constant SMOOTH_TAU_S. */
  function smooth(previous, target, dtSeconds, constants) {
    var C = constants || CONSTANTS;
    if (!isNumber(previous)) {
      return target;
    }
    var alpha = 1 - Math.exp(-Math.max(0, dtSeconds) / C.SMOOTH_TAU_S);
    return previous + (target - previous) * alpha;
  }

  /* The value sent with a poll moves from the last one sent by at most SLEW_MPS_PER_POLL. */
  function slew(previousSent, target, constants) {
    var C = constants || CONSTANTS;
    if (!isNumber(previousSent)) {
      return target;
    }
    return previousSent + clamp(target - previousSent, -C.SLEW_MPS_PER_POLL, C.SLEW_MPS_PER_POLL);
  }

  function clampSpeed(value, constants) {
    var C = constants || CONSTANTS;
    return clamp(value, C.SPEED_MIN, C.SPEED_MAX);
  }

  /* The request value for a speed: two decimals, clamped. */
  function toSendable(value, constants) {
    return Math.round(clampSpeed(value, constants) * 100) / 100;
  }

  /* ----- storage (every call guarded; a failure is never an error) ----- */

  function readJson(storage, key) {
    try {
      var text = storage.getItem(key);
      return text ? JSON.parse(text) : null;
    } catch (error) {
      return null;
    }
  }

  function writeJson(storage, key, value) {
    try {
      storage.setItem(key, JSON.stringify(value));
      return true;
    } catch (error) {
      return false;
    }
  }

  function loadStep(storage, constants) {
    var C = constants || CONSTANTS;
    var saved = storage ? readJson(storage, C.STEP_KEY) : null;
    if (saved && isNumber(saved.length) && isNumber(saved.count) && saved.count >= 1 &&
        saved.length >= C.STEP_LEN_MIN && saved.length <= C.STEP_LEN_MAX) {
      return { length: saved.length, count: Math.min(Math.floor(saved.count), 100000) };
    }
    return { length: C.STEP_LEN_PRIOR, count: 0 };
  }

  function saveStep(storage, step, nowMs, constants) {
    var C = constants || CONSTANTS;
    return storage ? writeJson(storage, C.STEP_KEY, { length: step.length, count: step.count, savedAt: nowMs }) : false;
  }

  function loadRemembered(storage, nowMs, constants) {
    var C = constants || CONSTANTS;
    var saved = storage ? readJson(storage, C.PACE_KEY) : null;
    if (saved && isNumber(saved.pace) && isNumber(saved.savedAt) &&
        saved.pace >= C.SPEED_MIN && saved.pace <= C.SPEED_MAX &&
        (nowMs - saved.savedAt) / 86400000 <= C.REMEMBER_MAX_AGE_DAYS && nowMs >= saved.savedAt) {
      return { pace: saved.pace, savedAt: saved.savedAt };
    }
    return null;
  }

  function saveRemembered(storage, pace, nowMs, constants) {
    var C = constants || CONSTANTS;
    return storage ? writeJson(storage, C.PACE_KEY, { pace: toSendable(pace, C), savedAt: nowMs }) : false;
  }

  /* ============================ thin browser layer ============================ */

  function defaultStorage(win) {
    try {
      return win && win.localStorage ? win.localStorage : null;
    } catch (error) {
      return null;
    }
  }

  /* createEstimator(options). options: win, nav, now (function), storage, constants, onStatus, onFix,
     debug (boolean). It owns the sensors and the one location watch. The page decides when to start and
     stop it. Every public method is safe to call at any time. */
  function createEstimator(options) {
    var opts = options || {};
    var win = opts.win || (typeof window !== "undefined" ? window : null);
    var nav = opts.nav || (win ? win.navigator : null);
    var C = opts.constants || CONSTANTS;
    var clock = opts.now || function () { return Date.now(); };
    var storage = opts.storage !== undefined ? opts.storage : defaultStorage(win);
    var timers = opts.timers || {
      set: function (fn, ms) { return win.setTimeout(fn, ms); },
      clear: function (id) { win.clearTimeout(id); }
    };

    var est = {
      wanted: false,        // started by the page and not stopped by it
      attached: false,      // listeners and the watch are on right now
      hidden: false,
      permission: "unknown",
      permissionAsked: false,
      permissionPromise: null,
      motion: "unknown",    // unknown, on, off
      motionSeen: false,
      motionTimer: null,
      tickTimer: null,
      watchId: null,
      stopReason: "",
      nearCount: 0,
      latched: false,
      gravity: { init: false },
      times: [],
      values: [],
      lastMotionAt: null,
      cadence: { valid: false, cadence: null, score: 0, reason: "short" },
      fixes: [],
      gps: null,
      recs: [],
      step: loadStep(storage, C),
      lastLearnAt: -Infinity,
      lastLearn: "",
      remembered: loadRemembered(storage, clock(), C),
      smoothed: null,
      mode: "none",
      lastMeasuredMode: null,
      lastWalkingAt: null,
      lastSpeed: null,
      lastTickAt: null,
      walking: false,
      walkingReason: "",
      measuredWalkS: 0,
      lastRememberAt: -Infinity,
      sent: null,
      sentAt: -Infinity,
      sentSource: null,
      frozen: false,
      motionHandlerCalls: 0,
      listeners: { fix: [], status: [] }
    };
    if (typeof opts.onStatus === "function") {
      est.listeners.status.push(opts.onStatus);
    }
    if (typeof opts.onFix === "function") {
      est.listeners.fix.push(opts.onFix);
    }

    function notifyStatus() {
      for (var i = 0; i < est.listeners.status.length; i++) {
        try {
          est.listeners.status[i](api.status());
        } catch (error) {
          /* a listener must never break the estimator */
        }
      }
    }

    function setMotion(state) {
      if (est.motion !== state) {
        est.motion = state;
        notifyStatus();
      }
    }

    /* ----- inputs ----- */

    function ingestMotion(sample) {
      est.motionHandlerCalls += 1;
      var t = isNumber(sample.t) ? sample.t : clock();
      var magnitude = motionMagnitude({
        acceleration: sample.acceleration,
        accelerationIncludingGravity: sample.accelerationIncludingGravity,
        t: t
      }, est.gravity, C);
      if (magnitude === null) {
        return false;
      }
      if (!est.motionSeen) {
        est.motionSeen = true;
        if (est.motionTimer !== null) {
          timers.clear(est.motionTimer);
          est.motionTimer = null;
        }
        setMotion("on");
      }
      est.lastMotionAt = t;
      est.times.push(t);
      est.values.push(magnitude);
      var cutoff = t - C.BUFFER_S * 1000;
      var drop = 0;
      while (drop < est.times.length - 2 && est.times[drop] < cutoff) {
        drop++;
      }
      if (drop > 32) {
        est.times.splice(0, drop);
        est.values.splice(0, drop);
      }
      return true;
    }

    function ingestFix(fix) {
      var nowMs = clock();
      var item = {
        t: isNumber(fix.t) ? fix.t : nowMs,
        lat: fix.lat,
        lon: fix.lon,
        accuracy: fix.accuracy,
        speed: isNumber(fix.speed) ? fix.speed : null
      };
      if (!isNumber(item.lat) || !isNumber(item.lon) || !isNumber(item.accuracy)) {
        return false;
      }
      // Every watch success goes to the page, which may use it as a newer fix and so refresh the fix age.
      for (var i = 0; i < est.listeners.fix.length; i++) {
        try {
          est.listeners.fix[i](item);
        } catch (error) {
          /* a listener must never break the estimator */
        }
      }
      // Only a fix good enough for speed (accuracy at most GPS_ACC_MAX_USE) is kept for the estimator.
      if (item.accuracy > C.GPS_ACC_MAX_USE) {
        return false;
      }
      est.fixes.push(item);
      var cutoff = item.t - 90000;
      while (est.fixes.length > 2 && est.fixes[0].t < cutoff) {
        est.fixes.shift();
      }
      return true;
    }

    function windowSamples(nowMs) {
      var n = est.times.length;
      if (n < 3 || est.lastMotionAt === null || (nowMs - est.lastMotionAt) / 1000 > C.MOTION_STALE_S) {
        return null;
      }
      var t1 = est.times[n - 1];
      var t0 = Math.max(est.times[0], t1 - C.WINDOW_S * 1000);
      if ((t1 - t0) / 1000 < C.MIN_WINDOW_S) {
        return null;
      }
      var from = 0;
      while (from < n - 2 && est.times[from + 1] <= t0) {
        from++;
      }
      return resample(est.times.slice(from), est.values.slice(from), t0, t1, C.RESAMPLE_HZ);
    }

    /* ----- the once-a-second evaluation ----- */

    function tick(nowArg) {
      var nowMs = isNumber(nowArg) ? nowArg : clock();
      var dt = est.lastTickAt === null ? 0 : (nowMs - est.lastTickAt) / 1000;
      est.lastTickAt = nowMs;

      var samples = windowSamples(nowMs);
      est.cadence = samples
        ? estimateCadence(samples, C.RESAMPLE_HZ, C)
        : { valid: false, cadence: null, score: 0, reason: est.lastMotionAt === null ? "none" : "stale" };
      est.gps = gpsSpeed(est.fixes, nowMs, C);

      est.recs.push({
        t: nowMs,
        walking: false,
        cadence: est.cadence.valid ? est.cadence.cadence : null,
        gpsSpeed: est.gps ? est.gps.speed : null,
        gpsAcc: est.gps ? est.gps.accuracy : null
      });
      while (est.recs.length > 40) {
        est.recs.shift();
      }
      var motionDead = est.motion === "off" || est.permission === "denied" || est.permission === "unavailable";
      var verdict = motionDead
        ? detectWalkingGpsOnly(est.recs, nowMs, C)
        : detectWalking(est.recs, est.gps, nowMs, C);
      est.walking = verdict.walking;
      est.walkingReason = verdict.reason;
      est.recs[est.recs.length - 1].walking = verdict.walking;
      if (verdict.walking) {
        est.lastWalkingAt = nowMs;
      }

      if (!motionDead) {
        learn(nowMs);
      }

      var fused = fuse({
        walking: est.walking,
        gps: est.gps ? est.gps.speed : null,
        cadence: est.cadence.valid && !motionDead ? est.cadence.cadence : null,
        step: est.step,
        nowMs: nowMs,
        lastWalkingAt: est.lastWalkingAt,
        lastSpeed: est.lastSpeed,
        remembered: est.remembered
      }, C);
      est.mode = fused.mode;
      if (fused.speed !== null) {
        var target = clampSpeed(fused.speed, C);
        est.smoothed = smooth(est.smoothed, target, dt, C);
        if (fused.mode === "gps" || fused.mode === "cadence") {
          est.lastSpeed = est.smoothed;
          est.lastMeasuredMode = fused.mode;
          est.measuredWalkS += dt;
          maybeRemember(nowMs);
        }
      }
      renderDebug();
      return api.snapshot();
    }

    function learn(nowMs) {
      var from = Math.max(nowMs - C.LEARN_MIN_STEADY_S * 1000, est.lastLearnAt);
      var window = [];
      for (var i = 0; i < est.recs.length; i++) {
        if (est.recs[i].t > from) {
          window.push(est.recs[i]);
        }
      }
      var result = learnStep(window, est.step, C);
      est.lastLearn = result.reason;
      if (result.accepted) {
        est.step = result.state;
        est.lastLearnAt = nowMs;
        saveStep(storage, est.step, nowMs, C);
      }
    }

    function maybeRemember(nowMs) {
      if (est.measuredWalkS < C.REMEMBER_MIN_WALK_S || est.smoothed === null) {
        return;
      }
      if ((nowMs - est.lastRememberAt) / 1000 < C.REMEMBER_SAVE_EVERY_S) {
        return;
      }
      est.lastRememberAt = nowMs;
      est.remembered = { pace: toSendable(est.smoothed, C), savedAt: nowMs };
      saveRemembered(storage, est.smoothed, nowMs, C);
    }

    /* ----- attach and detach (sensors and the one location watch) ----- */

    function onMotionEvent(event) {
      ingestMotion({
        t: clock(),
        acceleration: event.acceleration,
        accelerationIncludingGravity: event.accelerationIncludingGravity
      });
    }

    function onWatchFix(position) {
      var coords = position && position.coords;
      if (!coords) {
        return;
      }
      ingestFix({
        t: clock(),
        lat: coords.latitude,
        lon: coords.longitude,
        accuracy: coords.accuracy,
        speed: coords.speed
      });
    }

    function onWatchError() {
      return;
    }

    function attach() {
      if (est.attached || !est.wanted || est.hidden) {
        return;
      }
      est.attached = true;
      est.gravity = { init: false };
      est.times = [];
      est.values = [];
      est.lastMotionAt = null;
      est.recs = [];
      est.fixes = [];
      est.lastTickAt = null;
      if (est.permission !== "denied" && est.permission !== "unavailable" && win) {
        win.addEventListener("devicemotion", onMotionEvent);
        if (!est.motionSeen && est.motionTimer === null) {
          est.motionTimer = timers.set(function () {
            est.motionTimer = null;
            if (!est.motionSeen) {
              setMotion("off");
            }
          }, C.MOTION_TIMEOUT_MS);
        }
      }
      if (nav && nav.geolocation && typeof nav.geolocation.watchPosition === "function") {
        try {
          est.watchId = nav.geolocation.watchPosition(onWatchFix, onWatchError, { enableHighAccuracy: true, maximumAge: 0 });
        } catch (error) {
          est.watchId = null;
        }
      }
      est.tickTimer = timers.set(function loop() {
        tick();
        if (est.attached) {
          est.tickTimer = timers.set(loop, C.TICK_MS);
        }
      }, C.TICK_MS);
    }

    function detach() {
      if (!est.attached) {
        return;
      }
      est.attached = false;
      if (win) {
        win.removeEventListener("devicemotion", onMotionEvent);
      }
      if (est.motionTimer !== null) {
        timers.clear(est.motionTimer);
        est.motionTimer = null;
      }
      if (est.tickTimer !== null) {
        timers.clear(est.tickTimer);
        est.tickTimer = null;
      }
      if (est.watchId !== null && nav && nav.geolocation && typeof nav.geolocation.clearWatch === "function") {
        try {
          nav.geolocation.clearWatch(est.watchId);
        } catch (error) {
          /* nothing to do */
        }
      }
      est.watchId = null;
    }

    function onVisibility() {
      var hidden = !!(win && win.document && win.document.hidden);
      est.hidden = hidden;
      if (hidden) {
        detach();
      } else if (est.wanted) {
        attach();
      }
    }

    var visibilityBound = false;
    function bindVisibility() {
      if (!visibilityBound && win && win.document && typeof win.document.addEventListener === "function") {
        win.document.addEventListener("visibilitychange", onVisibility);
        visibilityBound = true;
      }
    }

    /* ----- debug readout (only with ?pace=debug) ----- */

    var debugBox = null;
    function debugWanted() {
      if (opts.debug === true) {
        return true;
      }
      try {
        return !!(win && /[?&]pace=debug(&|$)/.test(win.location.search));
      } catch (error) {
        return false;
      }
    }

    function renderDebug() {
      if (!debugWanted() || !win || !win.document) {
        return;
      }
      if (debugBox === null) {
        debugBox = win.document.createElement("pre");
        debugBox.className = "pace-debug";
        debugBox.setAttribute("aria-hidden", "true");
        debugBox.id = "pace-debug";
        win.document.body.appendChild(debugBox);
      }
      var s = api.snapshot();
      var f = function (value, digits) {
        return isNumber(value) ? value.toFixed(digits) : "-";
      };
      debugBox.textContent = [
        "mode " + s.mode + (s.walking ? " (walking)" : " (" + s.walkingReason + ")"),
        "cadence " + f(s.cadence, 2) + " score " + f(s.cadenceScore, 2),
        "gps " + f(s.gpsSpeed, 2) + " m/s acc " + f(s.gpsAccuracy, 0) + " m",
        "step " + f(s.stepLength, 2) + " m n=" + s.stepCount + " learn: " + s.lastLearn,
        "used " + f(s.sent, 2) + " m/s " + (s.sentSource || "none") + " smooth " + f(s.smoothed, 2),
        "motion " + s.motion + " events " + s.motionHandlerCalls
      ].join("\n");
    }

    /* ================================ public API ================================ */

    var api = {
      /* Ask for the motion permission. On iOS this must run inside the tap that starts the journey.
         It asks once per page session and never again after a denial. Never blocks the journey. */
      requestPermission: function () {
        if (est.permissionPromise) {
          return est.permissionPromise;
        }
        var Motion = win ? win.DeviceMotionEvent : undefined;
        var result;
        if (!Motion || (win && win.isSecureContext === false)) {
          est.permission = "unavailable";
          result = Promise.resolve("unavailable");
        } else if (typeof Motion.requestPermission === "function") {
          est.permissionAsked = true;
          try {
            result = Promise.resolve(Motion.requestPermission()).then(function (answer) {
              est.permission = answer === "granted" ? "granted" : "denied";
              return est.permission;
            }, function () {
              est.permission = "denied";
              return "denied";
            });
          } catch (error) {
            est.permission = "denied";
            result = Promise.resolve("denied");
          }
        } else {
          est.permission = "granted";
          result = Promise.resolve("granted");
        }
        est.permissionPromise = result.then(function (answer) {
          if (answer !== "granted") {
            setMotion("off");
            if (est.attached && win) {
              win.removeEventListener("devicemotion", onMotionEvent);
            }
          } else if (est.attached && win) {
            win.removeEventListener("devicemotion", onMotionEvent);
            win.addEventListener("devicemotion", onMotionEvent);
          }
          notifyStatus();
          return answer;
        });
        return est.permissionPromise;
      },

      /* Start the sensors and the location watch. Safe to call again (a new journey keeps the learned
         values and the last smoothed speed). Does nothing while the page is hidden until it is shown. */
      start: function () {
        est.wanted = true;
        est.frozen = false;
        est.stopReason = "";
        bindVisibility();
        est.hidden = !!(win && win.document && win.document.hidden);
        attach();
        notifyStatus();
      },

      /* Stop everything. The last smoothed speed stays and is still sent, frozen, with each poll. */
      stop: function (reason) {
        est.wanted = false;
        est.stopReason = reason || "stopped";
        est.frozen = true;
        detach();
        if (est.measuredWalkS >= C.REMEMBER_MIN_WALK_S && est.smoothed !== null) {
          est.remembered = { pace: toSendable(est.smoothed, C), savedAt: clock() };
          saveRemembered(storage, est.smoothed, clock(), C);
        }
        notifyStatus();
      },

      /* The near-stop latch. Two polls in a row with near_stop true stop the estimator for the rest of
         the leg. Returns true once latched. A poll that says false resets the count (until latched). */
      noteNearStop: function (near) {
        if (est.latched) {
          return true;
        }
        est.nearCount = near === true ? est.nearCount + 1 : 0;
        if (est.nearCount >= 2) {
          est.latched = true;
          api.stop("near stop");
        }
        return est.latched;
      },

      /* A new leg or a new journey: clear the latch. */
      resetLeg: function () {
        est.latched = false;
        est.nearCount = 0;
      },

      /* False when this browser has no motion sensor API or is not in a secure context. */
      motionSupported: function () {
        return !!(win && win.DeviceMotionEvent && win.isSecureContext !== false);
      },

      isLatched: function () {
        return est.latched;
      },

      isRunning: function () {
        return est.attached;
      },

      isWanted: function () {
        return est.wanted;
      },

      /* The value for a request: {speed, source} or null when there is none (the server then uses
         its default). Moves from the last value sent by at most SLEW_MPS_PER_POLL, one step per
         SLEW_MIN_INTERVAL_MS so several requests in one poll agree. */
      pollValue: function () {
        var nowMs = clock();
        var source;
        var target;
        if (est.smoothed !== null && (est.mode !== "none" || est.frozen)) {
          target = est.smoothed;
          source = est.lastMeasuredMode === "cadence" ? "cadence" : "gps";
          if (est.mode === "remembered") {
            source = "remembered";
          }
        } else if (est.remembered && (nowMs - est.remembered.savedAt) / 86400000 <= C.REMEMBER_MAX_AGE_DAYS) {
          target = est.remembered.pace;
          source = "remembered";
        } else {
          return null;
        }
        if (est.sent === null) {
          est.sent = toSendable(target, C);
          est.sentAt = nowMs;
        } else if (nowMs - est.sentAt >= C.SLEW_MIN_INTERVAL_MS) {
          est.sent = toSendable(slew(est.sent, clampSpeed(target, C), C), C);
          est.sentAt = nowMs;
        }
        est.sentSource = source;
        return { speed: est.sent, source: source };
      },

      /* "&walk_speed=1.23&walk_speed_source=gps", or "" when there is no value. */
      queryString: function () {
        var value = api.pollValue();
        if (value === null) {
          return "";
        }
        return "&walk_speed=" + encodeURIComponent(value.speed) + "&walk_speed_source=" + encodeURIComponent(value.source);
      },

      onFix: function (listener) {
        est.listeners.fix.push(listener);
      },

      onStatus: function (listener) {
        est.listeners.status.push(listener);
      },

      status: function () {
        return {
          running: est.attached,
          wanted: est.wanted,
          latched: est.latched,
          motion: est.motion,
          permission: est.permission,
          stopReason: est.stopReason
        };
      },

      snapshot: function () {
        return {
          mode: est.mode,
          walking: est.walking,
          walkingReason: est.walkingReason,
          cadence: est.cadence.valid ? est.cadence.cadence : null,
          cadenceRaw: est.cadence.cadence,
          cadenceScore: est.cadence.score,
          cadenceReason: est.cadence.reason,
          gpsSpeed: est.gps ? est.gps.speed : null,
          gpsAccuracy: est.gps ? est.gps.accuracy : null,
          stepLength: est.step.length,
          stepCount: est.step.count,
          lastLearn: est.lastLearn,
          smoothed: est.smoothed,
          sent: est.sent,
          sentSource: est.sentSource,
          remembered: est.remembered ? est.remembered.pace : null,
          measuredWalkS: est.measuredWalkS,
          motion: est.motion,
          motionHandlerCalls: est.motionHandlerCalls,
          running: est.attached,
          frozen: est.frozen
        };
      },

      /* Test hooks: feed synthetic input and step the clock by hand. */
      ingestMotion: ingestMotion,
      ingestFix: ingestFix,
      tick: tick
    };

    bindVisibility();
    return api;
  }

  var exported = {
    CONSTANTS: CONSTANTS,
    mean: mean,
    median: median,
    cv: cv,
    motionMagnitude: motionMagnitude,
    resample: resample,
    estimateCadence: estimateCadence,
    haversineMetres: haversineMetres,
    fixUsable: fixUsable,
    gpsSpeed: gpsSpeed,
    detectWalking: detectWalking,
    detectWalkingGpsOnly: detectWalkingGpsOnly,
    learnStep: learnStep,
    fuse: fuse,
    smooth: smooth,
    slew: slew,
    clampSpeed: clampSpeed,
    toSendable: toSendable,
    loadStep: loadStep,
    saveStep: saveStep,
    loadRemembered: loadRemembered,
    saveRemembered: saveRemembered,
    createEstimator: createEstimator
  };

  root.WalkSpeed = exported;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = exported;
  }
})(typeof window !== "undefined" ? window : this);
