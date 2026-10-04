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
    GPS_SPEED_MAX_AGE_S: 3,      // seconds: a fix older than this gives no GPS speed (a speed is never reused)
    GPS_WATCH_STALE_S: 5,        // seconds: a watch fix already this old on delivery is a cached position: ignored
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
    RUN_CADENCE_MAX: 4.5,        // search up to this rate so a faster peak can reject the second;
                                 // running is not reliably recognised from motion alone (GPS decides)
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
    RUN_REJECT_RATIO: 1.3,       // a peak above CADENCE_MAX this many times the in-range score rejects the second
    GPS_ONLY_CV_MAX: 0.30,       // coefficient of variation limit for walking established by GPS speed alone
    GPS_ONLY_LOW_ALLOWED: 1,     // readings below GPS_ONLY_WALK_MIN tolerated in the GPS-only window
    VEHICLE_CONFIRM_READINGS: 2, // consecutive readings at or above VEHICLE_SPEED_MIN before the veto applies
    STRIDE_MIN_HZ: 0.6,          // stride rhythm range (one leg cycle = two steps): lowest rate accepted
    STRIDE_MAX_HZ: 1.4,          // ... and highest
    STRIDE_MIN_SCORE: 0.5,       // smallest autocorrelation score of a stride peak that gives a cadence
    LEARN_MIN_VALID_CADENCE: 10, // valid-cadence seconds needed in a learning window (cadence median and CV use them)
    DIAG_CADENCE_MIN: 0.6,       // debug only: the diagnostic autocorrelation search goes down to this rate
    RAW_HZ: 25,                  // debug only: rate of the raw motion capture
    TRACE_SECONDS: 90,           // debug only: length of a recorded trace and of the raw capture
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
     Returns {valid, cadence, score, reason, rms, pick, ...diagnostics}. Peaks are not counted. The pick is made
     inside the walking range [CADENCE_MIN, CADENCE_MAX] first: the shortest lag whose score is at least PEAK_RATIO
     of the best in-range score, so an arm-swing at half the step rate is not mistaken for the cadence and a second
     harmonic above CADENCE_MAX cannot take over. A peak above CADENCE_MAX only rejects the second: when its score is
     at least RUN_REJECT_RATIO times the chosen in-range score the cadence is not valid (reason "fast"). Valid only
     at AUTOCORR_MIN or more. The diagnostic fields (best in range, best overall, best below the range, down to
     DIAG_CADENCE_MIN) are for the debug trace; nothing below CADENCE_MIN is ever accepted. */
  function estimateCadence(samples, fs, constants) {
    var C = constants || CONSTANTS;
    var n = samples.length;
    var diag = {
      bestInF: null, bestInScore: null, bestOverallF: null, bestOverallScore: null,
      bestLowF: null, bestLowScore: null, fastScore: null, chosenScore: null, pick: ""
    };
    var finish = function (result, pick) {
      diag.pick = pick;
      for (var key in diag) {
        result[key] = diag[key];
      }
      return result;
    };
    if (n < C.MIN_WINDOW_S * fs * 0.9) {
      return finish({ valid: false, cadence: null, score: 0, reason: "short", rms: null }, "short");
    }
    var m = mean(samples);
    var x = new Array(n);
    var energy = 0;
    for (var i = 0; i < n; i++) {
      x[i] = samples[i] - m;
      energy += x[i] * x[i];
    }
    var power = energy / n;
    var rms = Math.sqrt(power);
    if (rms < C.MOTION_RMS_MIN) {
      return finish({ valid: false, cadence: null, score: 0, reason: "still", rms: rms }, "still");
    }
    var lagMin = Math.max(2, Math.floor(fs / C.RUN_CADENCE_MAX));
    var lagMax = Math.min(n - 2, Math.ceil(fs / C.CADENCE_MIN) + 1);
    var inMin = Math.max(lagMin, Math.ceil(fs / C.CADENCE_MAX));
    var lagDiag = Math.max(lagMax, Math.min(n - 2, Math.floor(fs / Math.min(C.DIAG_CADENCE_MIN, C.STRIDE_MIN_HZ))));
    var strideLagMin = Math.max(lagMin, Math.ceil(fs / C.STRIDE_MAX_HZ));
    var strideLagMax = Math.min(n - 2, Math.floor(fs / C.STRIDE_MIN_HZ));
    var r = {};
    for (var lag = lagMin - 1; lag <= lagDiag + 1; lag++) {
      r[lag] = autocorr(x, lag, power);
    }
    var freqAt = function (at) {
      var a = r[at - 1];
      var b = r[at];
      var c = r[at + 1];
      var denom = a - 2 * b + c;
      var shift = denom < 0 ? clamp(0.5 * (a - c) / denom, -0.5, 0.5) : 0;
      return fs / (at + shift);
    };
    var inPeaks = [];
    var inBest = 0;
    var inBestLag = 0;
    var fastBest = 0;
    var fastLag = 0;
    var lowBest = 0;
    var lowLag = 0;
    var allBest = 0;
    var allLag = 0;
    var strideBest = 0;
    var strideLag = 0;
    for (lag = lagMin; lag <= lagDiag; lag++) {
      if (!(r[lag] > 0 && r[lag] >= r[lag - 1] && r[lag] > r[lag + 1])) {
        continue;
      }
      if (lag >= strideLagMin && lag <= strideLagMax && r[lag] > strideBest) {
        strideBest = r[lag];
        strideLag = lag;
      }
      if (r[lag] > allBest) {
        allBest = r[lag];
        allLag = lag;
      }
      if (lag < inMin) {
        if (r[lag] > fastBest) {
          fastBest = r[lag];
          fastLag = lag;
        }
      } else if (lag <= lagMax) {
        inPeaks.push(lag);
        if (r[lag] > inBest) {
          inBest = r[lag];
          inBestLag = lag;
        }
      } else if (r[lag] > lowBest) {
        lowBest = r[lag];
        lowLag = lag;
      }
    }
    if (inBestLag) {
      diag.bestInF = freqAt(inBestLag);
      diag.bestInScore = inBest;
    }
    if (allLag) {
      diag.bestOverallF = freqAt(allLag);
      diag.bestOverallScore = allBest;
    }
    if (lowLag) {
      diag.bestLowF = freqAt(lowLag);
      diag.bestLowScore = lowBest;
    }
    if (fastLag) {
      diag.fastScore = fastBest;
    }
    var fastFreq = fastLag ? freqAt(fastLag) : null;
    // With no valid in-range pick, a stride-rhythm peak (one leg cycle, 0.6 to 1.4 per second) gives the cadence as
    // twice its rate. It never overrides a valid in-range pick, and a fast peak at RUN_REJECT_RATIO times its score
    // or more still rejects the second. Peaks below STRIDE_MIN_HZ are never accepted.
    var tryStride = function () {
      if (!strideLag || strideBest < C.STRIDE_MIN_SCORE) {
        return null;
      }
      var doubled = 2 * freqAt(strideLag);
      if (fastLag && fastBest >= C.RUN_REJECT_RATIO * strideBest) {
        diag.chosenScore = strideBest;
        return finish({ valid: false, cadence: fastFreq, score: fastBest, reason: "fast", rms: rms }, "reject_ratio");
      }
      if (doubled < C.CADENCE_MIN || doubled > C.CADENCE_MAX) {
        return null;
      }
      diag.chosenScore = strideBest;
      return finish({ valid: true, cadence: doubled, score: strideBest, reason: "ok", rms: rms }, "stride_doubled");
    };
    if (!inPeaks.length || inBest < C.AUTOCORR_MIN) {
      var strided = tryStride();
      if (strided !== null) {
        return strided;
      }
      if (fastBest >= C.AUTOCORR_MIN) {
        return finish({ valid: false, cadence: fastFreq, score: fastBest, reason: "fast", rms: rms }, "fast_only");
      }
      return finish({ valid: false, cadence: null, score: Math.max(0, inBest), reason: "weak", rms: rms },
        inPeaks.length ? "weak_in_range" : "no_in_range_peak");
    }
    var chosen = inPeaks[0];
    for (var k = 0; k < inPeaks.length; k++) {
      if (r[inPeaks[k]] >= C.PEAK_RATIO * inBest) {
        chosen = inPeaks[k];
        break;
      }
    }
    var frequency = freqAt(chosen);
    var score = r[chosen];
    diag.chosenScore = score;
    if (score < C.AUTOCORR_MIN) {
      var strided2 = tryStride();
      if (strided2 !== null) {
        return strided2;
      }
      return finish({ valid: false, cadence: null, score: score, reason: "weak", rms: rms }, "weak_chosen");
    }
    if (fastLag && fastBest >= C.RUN_REJECT_RATIO * score) {
      return finish({ valid: false, cadence: fastFreq, score: fastBest, reason: "fast", rms: rms }, "reject_ratio");
    }
    if (frequency > C.CADENCE_MAX) {
      return finish({ valid: false, cadence: frequency, score: score, reason: "fast", rms: rms }, "above_range");
    }
    if (frequency < C.CADENCE_MIN) {
      return finish({ valid: false, cadence: frequency, score: score, reason: "slow", rms: rms }, "below_range");
    }
    return finish({ valid: true, cadence: frequency, score: score, reason: "ok", rms: rms },
      fastLag ? "ok_fast_below_ratio" : "ok");
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

  /* A fix is usable for speed when its accuracy is at most GPS_ACC_MAX_USE. Its age is limited by
     GPS_SPEED_MAX_AGE_S in gpsSpeed. */
  function fixUsable(fix, nowMs, constants) {
    var C = constants || CONSTANTS;
    if (!fix || !isNumber(fix.lat) || !isNumber(fix.lon) || !isNumber(fix.t) || !isNumber(fix.accuracy)) {
      return false;
    }
    return fix.accuracy <= C.GPS_ACC_MAX_USE;
  }

  /* GPS speed from the accepted fixes (oldest first). Only a fix at most GPS_SPEED_MAX_AGE_S old gives a speed,
     so the speed of an old fix is never reused. Uses coords.speed when it is a number. Otherwise derives a speed
     from two fixes at least GPS_DERIVE_MIN_S apart, only when the net displacement is at least
     max(GPS_DERIVE_MIN_M, GPS_DERIVE_ACC_FACTOR x accuracy). Returns {speed, accuracy, derived, age} (age in
     seconds of the fix that supplied the speed) or null when there is no GPS speed. */
  function gpsSpeed(fixes, nowMs, constants) {
    var C = constants || CONSTANTS;
    if (!fixes.length) {
      return null;
    }
    var last = fixes[fixes.length - 1];
    if (!fixUsable(last, nowMs, C)) {
      return null;
    }
    var age = Math.max(0, (nowMs - last.t) / 1000);
    if (age > C.GPS_SPEED_MAX_AGE_S) {
      return null;
    }
    if (isNumber(last.speed) && last.speed >= 0) {
      return { speed: last.speed, accuracy: last.accuracy, derived: false, age: age };
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
      return { speed: metres / dt, accuracy: Math.max(older.accuracy, last.accuracy), derived: true, age: age };
    }
    return null;
  }

  /* "Walking detected": a valid cadence that has been regular (coefficient of variation under
     STEADY_CV_MAX) for REGULAR_S seconds, and, when there is a GPS speed, one below VEHICLE_SPEED_MIN.
     recs are the one-per-second records {t, cadence (number or null)}, oldest first. */
  function detectWalking(recs, gps, nowMs, constants) {
    var C = constants || CONSTANTS;
    // The veto needs VEHICLE_CONFIRM_READINGS consecutive readings at or above the limit: one isolated reading
    // (or the newest one, still pending) does not veto. A real vehicle is therefore vetoed one second later.
    var highRun = 0;
    for (var h = recs.length - 1; h >= 0; h--) {
      if (isNumber(recs[h].gpsSpeed) && recs[h].gpsSpeed >= C.VEHICLE_SPEED_MIN) {
        highRun += 1;
      } else {
        break;
      }
    }
    if (highRun === 0 && gps && isNumber(gps.speed) && gps.speed >= C.VEHICLE_SPEED_MIN &&
        recs.length && recs[recs.length - 1].gpsSpeed === undefined) {
      highRun = 1;  // callers that pass only the live reading
    }
    if (highRun >= C.VEHICLE_CONFIRM_READINGS) {
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

  /* Steady GPS speed from GPS_ONLY_WALK_MIN up to VEHICLE_SPEED_MIN over REGULAR_S seconds is walking. This is
     used when there is no motion sensor (permission denied, unavailable or no event) and also when the sensor is
     present but the cadence is irregular or missing. Tolerances: one reading below GPS_ONLY_WALK_MIN is allowed
     in the window; a reading at or above VEHICLE_SPEED_MIN with neighbours below it (or the newest, still pending)
     is an outlier and is left out of the count and the CV; VEHICLE_CONFIRM_READINGS in a row is a vehicle.
     Returns {walking, reason, cv, n, nulls, inRange, outRange, outliers}: the readings in the window, those with
     no GPS speed, those in range, those out of range (low or confirmed vehicle), the outliers, and the failed
     condition as the reason ("no gps", "short", "slow", "vehicle", "irregular" or "ok"). */
  function detectWalkingGpsOnly(recs, nowMs, constants) {
    var C = constants || CONSTANTS;
    var from = nowMs - (C.REGULAR_S + 0.5) * 1000;
    var speeds = [];
    var n = 0;
    var nulls = 0;
    var low = 0;
    var vehicle = 0;
    var outliers = 0;
    var isHigh = function (index) {
      return index >= 0 && index < recs.length && isNumber(recs[index].gpsSpeed) &&
        recs[index].gpsSpeed >= C.VEHICLE_SPEED_MIN;
    };
    for (var i = 0; i < recs.length; i++) {
      if (!(recs[i].t >= from)) {
        continue;
      }
      n += 1;
      var speed = recs[i].gpsSpeed;
      if (!isNumber(speed)) {
        nulls += 1;
        continue;
      }
      if (speed >= C.VEHICLE_SPEED_MIN) {
        if (isHigh(i - 1) || isHigh(i + 1)) {
          vehicle += 1;
          speeds.push(speed);
        } else {
          outliers += 1;
        }
        continue;
      }
      speeds.push(speed);
      if (speed < C.GPS_ONLY_WALK_MIN) {
        low += 1;
      }
    }
    var detail = { n: n, nulls: nulls, inRange: speeds.length - low - vehicle, outRange: low + vehicle,
      outliers: outliers, cv: null };
    var result = function (walking, reason, variation) {
      detail.walking = walking;
      detail.reason = reason;
      detail.cv = variation;
      return detail;
    };
    if (nulls > 0) {
      return result(false, "no gps", null);
    }
    if (speeds.length < C.REGULAR_MIN_READINGS) {
      return result(false, "short", null);
    }
    if (vehicle > 0) {
      return result(false, "vehicle", null);
    }
    if (low > C.GPS_ONLY_LOW_ALLOWED) {
      return result(false, "slow", null);
    }
    var variation = cv(speeds);
    if (!(variation < C.GPS_ONLY_CV_MAX)) {
      return result(false, "irregular", variation);
    }
    return result(true, "ok", variation);
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
      if (!isNumber(rec.gpsSpeed) || !isNumber(rec.gpsAcc)) {
        return fail("missing");
      }
      if (isNumber(rec.cadence)) {
        cadences.push(rec.cadence);
      }
      speeds.push(rec.gpsSpeed);
      accuracies.push(rec.gpsAcc);
    }
    if (cadences.length < C.LEARN_MIN_VALID_CADENCE) {
      return fail("few valid cadence");
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
      cadence: { valid: false, cadence: null, score: 0, reason: "short", rms: null },
      fixes: [],
      lastFix: null,
      ignoredStale: 0,
      gps: null,
      gpsOnly: null,
      cadStats: { nulls: 0, count: 0, cv: null },
      walkingSource: "",
      trace: null,
      raw: null,
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
      renderDebug();
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
      if (est.lastMotionAt !== null && t <= est.lastMotionAt) {
        return false;
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

    /* A fix is stamped with the time of the position itself (position.timestamp), never the time the callback ran,
       so a cached position delivered by the watch is old and is ignored when it is more than GPS_WATCH_STALE_S old. */
    function ingestFix(fix) {
      var nowMs = clock();
      var item = {
        t: isNumber(fix.t) ? Math.min(fix.t, nowMs) : nowMs,
        lat: fix.lat,
        lon: fix.lon,
        accuracy: fix.accuracy,
        speed: isNumber(fix.speed) ? fix.speed : null
      };
      if (!isNumber(item.lat) || !isNumber(item.lon) || !isNumber(item.accuracy)) {
        return false;
      }
      if ((nowMs - item.t) / 1000 > C.GPS_WATCH_STALE_S) {
        est.ignoredStale += 1;
        return false;
      }
      // Every fresh watch success goes to the page, which may use it as a newer fix and so refresh the fix age.
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
      est.lastFix = item;
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
        : { valid: false, cadence: null, score: 0, reason: est.lastMotionAt === null ? "none" : "stale", rms: null };
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
      est.gpsOnly = detectWalkingGpsOnly(est.recs, nowMs, C);
      est.cadStats = cadenceStats(est.recs, nowMs);
      var verdict;
      est.walkingSource = "cadence";
      if (motionDead) {
        verdict = est.gpsOnly;
        est.walkingSource = "gps";
      } else {
        verdict = detectWalking(est.recs, est.gps, nowMs, C);
        // A steady GPS speed from a fresh fix counts as walking even when the cadence is irregular or missing.
        if (!verdict.walking && verdict.reason !== "vehicle" && verdict.reason !== "gps still" && est.gpsOnly.walking) {
          verdict = { walking: true, reason: "ok", cv: est.gpsOnly.cv };
          est.walkingSource = "gps";
        }
      }
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
      if (est.trace !== null && est.trace.active) {
        traceRow(nowMs);
      }
      if (est.raw !== null && est.raw.active) {
        rawCollect();
      }
      renderDebug();
      return api.snapshot();
    }

    /* Readings with no cadence in the walking window, and the variation of the ones that have it. */
    function cadenceStats(recs, nowMs) {
      var from = nowMs - (C.REGULAR_S + 0.5) * 1000;
      var values = [];
      var count = 0;
      var nulls = 0;
      for (var i = 0; i < recs.length; i++) {
        if (recs[i].t >= from) {
          count += 1;
          if (isNumber(recs[i].cadence)) {
            values.push(recs[i].cadence);
          } else {
            nulls += 1;
          }
        }
      }
      return { nulls: nulls, count: count, cv: values.length >= 2 ? cv(values) : null };
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

    /* The time of a motion event: its own timeStamp when that agrees with the clock to within 2 s (so events
       delivered in a burst keep their spacing), otherwise the time the handler ran. event.interval is never used. */
    function eventTime(event) {
      var now = clock();
      var stamp = event ? event.timeStamp : undefined;
      if (isNumber(stamp) && stamp > 0) {
        var origin = win && win.performance && isNumber(win.performance.timeOrigin) ? win.performance.timeOrigin : null;
        var epoch = stamp > 1e12 ? stamp : origin !== null ? origin + stamp : null;
        if (epoch !== null && Math.abs(epoch - now) <= 2000) {
          return epoch;
        }
      }
      return now;
    }

    function onMotionEvent(event) {
      ingestMotion({
        t: eventTime(event),
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
        t: isNumber(position.timestamp) ? position.timestamp : clock(),
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
      est.lastFix = null;
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

    /* ----- debug readout and trace (only with ?pace=debug; remove before submission) ----- */

    var TRACE_COLUMNS = ["t", "cadence", "cad_ok", "score", "cad_cv", "rms", "gps", "gps_kind", "gps_acc",
      "fix_age", "speed_fix_age", "walking", "reason", "source", "mode", "used", "null_cad", "go_n", "go_in",
      "go_out", "go_cv", "go_fail", "step", "n", "learn", "best_in_range_f", "best_in_range_score",
      "best_overall_f", "best_overall_score", "best_low_f", "best_low_score", "cad_pick_reason", "used_src",
      "smoothed", "go_outliers"];
    var TRACE_CONSTANTS = ["RUN_REJECT_RATIO", "GPS_ONLY_CV_MAX", "LEARN_MIN_VALID_CADENCE", "AUTOCORR_MIN",
      "MOTION_RMS_MIN", "STEADY_CV_MAX", "STRIDE_MIN_HZ", "STRIDE_MAX_HZ", "STRIDE_MIN_SCORE",
      "VEHICLE_CONFIRM_READINGS"];
    var debugEl = null;
    var debugOpen = false;

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

    function num(value, digits) {
      return isNumber(value) ? value.toFixed(digits) : "-";
    }

    /* The one reason shown in the top bar. */
    function whyReason() {
      var context = typeof opts.debugContext === "function" ? opts.debugContext() : {};
      if (context && context.demo) {
        return "demo mode";
      }
      if (est.latched) {
        return "near stop (estimator off)";
      }
      if (!est.wanted) {
        return "journey not started";
      }
      if (est.permission === "denied" || est.permission === "unavailable") {
        return "no motion permission";
      }
      if (est.motion === "off" || !est.motionSeen) {
        return "no motion events";
      }
      if (est.walking) {
        return est.mode === "gps" || est.mode === "cadence" || est.gps !== null ? "ok" : "no GPS speed";
      }
      switch (est.walkingReason) {
        case "short": return "short window";
        case "irregular": return "irregular cadence";
        case "gps still": return "gps still";
        case "no gps": return "no GPS speed";
        default: return "not walking";
      }
    }

    function buildDebug() {
      var doc = win.document;
      var old = doc.getElementById("pace-debug");
      if (old && old.parentNode) {
        old.parentNode.removeChild(old);
      }
      var make = function (tag, className) {
        var node = doc.createElement(tag);
        node.className = className;
        return node;
      };
      var root = make("div", "pace-debug");
      root.id = "pace-debug";
      var bar = make("button", "pace-debug__bar");
      bar.type = "button";
      bar.setAttribute("aria-expanded", "false");
      var panel = make("div", "pace-debug__panel");
      panel.hidden = true;
      var text = make("pre", "pace-debug__text");
      var actions = make("div", "pace-debug__actions");
      var record = make("button", "pace-debug__button");
      record.type = "button";
      record.textContent = "Record trace";
      var copyButton = make("button", "pace-debug__button");
      copyButton.type = "button";
      copyButton.textContent = "Copy trace";
      var rawButton = make("button", "pace-debug__button");
      rawButton.type = "button";
      rawButton.textContent = "Copy raw motion";
      var status = make("p", "pace-debug__status");
      var area = make("textarea", "pace-debug__area");
      area.hidden = true;
      area.readOnly = true;
      area.rows = 6;
      actions.appendChild(record);
      actions.appendChild(copyButton);
      actions.appendChild(rawButton);
      panel.appendChild(text);
      panel.appendChild(actions);
      panel.appendChild(status);
      panel.appendChild(area);
      root.appendChild(bar);
      root.appendChild(panel);
      doc.body.appendChild(root);
      bar.addEventListener("click", function () {
        debugOpen = !debugOpen;
        panel.hidden = !debugOpen;
        root.classList.toggle("is-open", debugOpen);
        bar.setAttribute("aria-expanded", debugOpen ? "true" : "false");
      });
      record.addEventListener("click", function () {
        api.traceStart();
      });
      copyButton.addEventListener("click", function () {
        api.copyTrace();
      });
      rawButton.addEventListener("click", function () {
        api.copyRaw();
      });
      debugEl = { root: root, bar: bar, panel: panel, text: text, status: status, area: area };
    }

    function traceStatusText() {
      if (est.trace === null) {
        return "no trace recorded";
      }
      var raw = est.raw === null ? 0 : est.raw.values.length;
      if (est.trace.active) {
        return "recording " + est.trace.rows.length + "/" + C.TRACE_SECONDS + " s, raw " + raw;
      }
      return "trace ready: " + est.trace.rows.length + " rows, raw " + raw + " values";
    }

    function renderDebug() {
      if (!debugWanted() || !win || !win.document || !win.document.body) {
        return;
      }
      if (debugEl === null) {
        buildDebug();
      }
      var s = api.snapshot();
      var send = peekSend(clock());
      debugEl.bar.textContent = "mode " + s.mode + " · used " + num(send ? send.speed : null, 2) +
        " m/s · " + whyReason();
      debugEl.text.textContent = [
        "mode " + s.mode + (s.walking ? " (walking by " + s.walkingSource + ")" : " (" + s.walkingReason + ")"),
        "cadence " + num(s.cadence, 2) + " score " + num(s.cadenceScore, 2) + " rms " + num(s.motionRms, 2) +
          " null " + s.nullCadence + " cv " + num(s.cadenceCv, 2),
        "gps " + num(s.gpsSpeed, 2) + " m/s " + s.gpsKind + " acc " + num(s.gpsAccuracy, 0) + " m age " +
          num(s.speedFixAge, 1) + " s",
        "fix age " + num(s.fixAge, 1) + " s, stale ignored " + s.ignoredStale,
        "gps-only n " + s.gpsOnly.n + " in " + s.gpsOnly.inRange + " out " + s.gpsOnly.outRange + " outliers " +
          s.gpsOnly.outliers + " cv " +
          num(s.gpsOnly.cv, 2) + " " + s.gpsOnly.reason,
        "pick " + s.cadenceDiag.pick + " in " + num(s.cadenceDiag.bestInF, 2) + "/" +
          num(s.cadenceDiag.bestInScore, 2) + " all " + num(s.cadenceDiag.bestOverallF, 2) + "/" +
          num(s.cadenceDiag.bestOverallScore, 2) + " low " + num(s.cadenceDiag.bestLowF, 2) + "/" +
          num(s.cadenceDiag.bestLowScore, 2),
        "step " + num(s.stepLength, 2) + " m n=" + s.stepCount + " learn: " + s.lastLearn,
        "used " + num(send ? send.speed : null, 2) + " m/s " + (send ? send.source : "-") + " smooth " +
          num(s.smoothed, 2) + " sent " + num(s.sent, 2),
        "motion " + s.motion + " events " + s.motionHandlerCalls,
        "trace: " + traceStatusText()
      ].join("\n");
      debugEl.status.textContent = traceStatusText();
    }

    /* The value a poll would send right now, without moving the slew state: {speed, source} or null. */
    function pollTarget(nowMs) {
      if (est.smoothed !== null && (est.mode !== "none" || est.frozen)) {
        return { target: est.smoothed, source: est.mode === "remembered" ? "remembered" : est.lastMeasuredMode === "cadence" ? "cadence" : "gps" };
      }
      if (est.remembered && (nowMs - est.remembered.savedAt) / 86400000 <= C.REMEMBER_MAX_AGE_DAYS) {
        return { target: est.remembered.pace, source: "remembered" };
      }
      return null;
    }

    function peekSend(nowMs) {
      var t = pollTarget(nowMs);
      if (t === null) {
        return null;
      }
      var speed;
      if (est.sent === null) {
        speed = toSendable(t.target, C);
      } else if (nowMs - est.sentAt >= C.SLEW_MIN_INTERVAL_MS) {
        speed = toSendable(slew(est.sent, clampSpeed(t.target, C), C), C);
      } else {
        speed = est.sent;
      }
      return { speed: speed, source: t.source };
    }

    /* One row per second, numbers and short tokens only: no position and no time of any position. */
    function traceRow(nowMs) {
      var trace = est.trace;
      if (trace.start === null) {
        trace.start = nowMs;
      }
      var gps = est.gps;
      var go = est.gpsOnly;
      var d = est.cadence;
      var send = peekSend(nowMs);
      var row = [
        Math.round((nowMs - trace.start) / 1000),
        num(est.cadence.cadence, 2),
        est.cadence.valid ? 1 : 0,
        num(est.cadence.score, 2),
        num(est.cadStats.cv, 3),
        num(est.cadence.rms, 2),
        num(gps ? gps.speed : null, 2),
        gps ? (gps.derived ? "derived" : "reported") : "missing",
        num(gps ? gps.accuracy : null, 0),
        num(est.lastFix ? (nowMs - est.lastFix.t) / 1000 : null, 1),
        num(gps ? gps.age : null, 1),
        est.walking ? 1 : 0,
        String(est.walkingReason).replace(/ /g, "_"),
        est.walkingSource,
        est.mode,
        num(send ? send.speed : null, 2),
        est.cadStats.nulls,
        go.n,
        go.inRange,
        go.outRange,
        num(go.cv, 3),
        String(go.reason).replace(/ /g, "_"),
        num(est.step.length, 2),
        est.step.count,
        String(est.lastLearn || "-").replace(/ /g, "_"),
        num(d.bestInF, 2),
        num(d.bestInScore, 2),
        num(d.bestOverallF, 2),
        num(d.bestOverallScore, 2),
        num(d.bestLowF, 2),
        num(d.bestLowScore, 2),
        d.pick || "-",
        send ? send.source : "-",
        num(est.smoothed, 2),
        go.outliers
      ];
      trace.rows.push(row.join(","));
      if (trace.rows.length >= C.TRACE_SECONDS) {
        trace.active = false;
      }
    }

    /* Raw motion capture: the gravity-removed magnitude the estimator uses, resampled to RAW_HZ, two decimals. */
    function rawCollect() {
      var raw = est.raw;
      var n = est.times.length;
      if (n < 2) {
        return;
      }
      var t1 = est.times[n - 1];
      if (raw.next === null) {
        raw.next = Math.max(raw.startAt, est.times[0]);
      }
      raw.next = Math.max(raw.next, est.times[0]);
      if (raw.next > t1) {
        return;
      }
      var grid = resample(est.times, est.values, raw.next, t1, C.RAW_HZ);
      var limit = C.TRACE_SECONDS * C.RAW_HZ;
      for (var i = 0; i < grid.length && raw.values.length < limit; i++) {
        raw.values.push(Math.round(grid[i] * 100) / 100);
      }
      raw.next += grid.length * (1000 / C.RAW_HZ);
      if (raw.values.length >= limit) {
        raw.active = false;
      }
    }

    /* Copies text with the clipboard, or shows it in the text area when that fails. Never stored or sent. */
    function copyText(text) {
      var clip = opts.clipboard !== undefined ? opts.clipboard : nav && nav.clipboard;
      var showText = function () {
        if (debugEl !== null) {
          debugEl.area.hidden = false;
          debugEl.area.value = text;
          debugEl.area.select();
        }
      };
      if (!text) {
        return Promise.resolve("empty");
      }
      if (clip && typeof clip.writeText === "function") {
        try {
          return Promise.resolve(clip.writeText(text)).then(function () {
            if (debugEl !== null) {
              debugEl.area.hidden = true;
            }
            return "copied";
          }, function () {
            showText();
            return "shown";
          });
        } catch (error) {
          showText();
          return Promise.resolve("shown");
        }
      }
      showText();
      return Promise.resolve("shown");
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
        // A new Start journey tap or leg: no carry-over of the last smoothed speed, the hold or the slew state.
        // A remembered pace, if one is loaded, is then what a poll sends (source "remembered").
        est.smoothed = null;
        est.lastSpeed = null;
        est.lastWalkingAt = null;
        est.lastMeasuredMode = null;
        est.mode = "none";
        est.sent = null;
        est.sentAt = -Infinity;
        est.sentSource = null;
        renderDebug();
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
        var t = pollTarget(nowMs);
        if (t === null) {
          return null;
        }
        if (est.sent === null) {
          est.sent = toSendable(t.target, C);
          est.sentAt = nowMs;
        } else if (nowMs - est.sentAt >= C.SLEW_MIN_INTERVAL_MS) {
          est.sent = toSendable(slew(est.sent, clampSpeed(t.target, C), C), C);
          est.sentAt = nowMs;
        }
        est.sentSource = t.source;
        return { speed: est.sent, source: t.source };
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
          frozen: est.frozen,
          walkingSource: est.walkingSource,
          motionRms: est.cadence.rms,
          cadenceCv: est.cadStats.cv,
          nullCadence: est.cadStats.nulls,
          gpsKind: est.gps ? (est.gps.derived ? "derived" : "reported") : "missing",
          speedFixAge: est.gps ? est.gps.age : null,
          fixAge: est.lastFix && est.lastTickAt !== null ? (est.lastTickAt - est.lastFix.t) / 1000 : null,
          ignoredStale: est.ignoredStale,
          cadenceDiag: est.cadence,
          gpsOnly: est.gpsOnly || { n: 0, nulls: 0, inRange: 0, outRange: 0, outliers: 0, cv: null, reason: "-" }
        };
      },

      /* Debug trace (only used by the ?pace=debug readout). Kept in memory, never stored or sent. */
      traceStart: function () {
        est.trace = { start: null, rows: [], active: true };
        est.raw = { startAt: clock(), next: null, values: [], active: true };
        renderDebug();
      },

      traceText: function () {
        if (est.trace === null) {
          return "";
        }
        var constants = TRACE_CONSTANTS.map(function (name) { return name + "=" + C[name]; }).join(" ");
        return "# " + constants + "\n" + TRACE_COLUMNS.join(",") + "\n" + est.trace.rows.join("\n");
      },

      /* First line "hz=25", then the values, 25 to a line. */
      rawText: function () {
        if (est.raw === null || !est.raw.values.length) {
          return "";
        }
        var lines = ["hz=" + C.RAW_HZ];
        for (var i = 0; i < est.raw.values.length; i += C.RAW_HZ) {
          lines.push(est.raw.values.slice(i, i + C.RAW_HZ).map(function (v) { return v.toFixed(2); }).join(","));
        }
        return lines.join("\n");
      },

      copyTrace: function () {
        return copyText(est.trace === null || !est.trace.rows.length ? "" : api.traceText());
      },

      copyRaw: function () {
        return copyText(api.rawText());
      },

      debugWhy: whyReason,

      debugArea: function () {
        return debugEl === null ? null : debugEl.area;
      },

      /* Test hooks: feed synthetic input and step the clock by hand. */
      ingestMotion: ingestMotion,
      ingestFix: ingestFix,
      tick: tick
    };

    bindVisibility();
    renderDebug();
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
