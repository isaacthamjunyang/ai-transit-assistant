/* Exact user-facing strings from PROJECT_PLAN.md.
   This file is a classic script so the style guide can open as a file.
   The constants object is `copy`. */

var copy = {
  notificationCard: {
    title: "Notifications Optional",
    description: "Get an audio/visual alert 60 seconds before your walk deadline.",
    action: "Enable Notifications",
    granted: "Notifications active — Leave-now alert set"
  },
  deniedBanner: "Browser notifications are blocked. Keep this page open to see live leave-by alerts.",
  cautionBanner: "⚠ Catch chance dropping ({point}%). Tap to enable Leave-Now Alert.",
  leaveNow: {
    title: "Leave Now — Bus {service_no}",
    body: "Walk to {stop_name} ({stop_code}) now to catch Bus {service_no}. Catch probability: {point}% ({range_low}–{range_high}%)."
  },
  rerouteCard: {
    title: "Route Updated",
    message: "Switched to Bus {new_service} at {new_stop_name} ({new_stop_code}).",
    probability: "Catch probability: {new_point}% (range {new_low}–{new_high}%) vs previous {old_point}%."
  },
  rerouteNotification: {
    title: "Route Updated — Bus {new_service}",
    body: "Switched to Bus {new_service} at {new_stop_name}. Catch probability: {new_point}% (range {new_low}–{new_high}%)."
  },
  noBetter: {
    standard: "Primary bus target has low catch probability ({point}%), but no better direct alternative meets the 15% improvement threshold.",
    postReroute: "Primary bus target has low catch probability ({point}%), but no better direct alternative meets the post-reroute 20% improvement threshold."
  },
  fallback: "Catch probability: {point}% (range {range_low}–{range_high}%). {action_advice_text}",
  actionAdvice: {
    wait: "Wait for your leave-by alert.",
    leaveNow: "Leave now to walk to the bus stop.",
    switchRoute: "Route updated to an alternate service.",
    doNotRely: "Data uncertain; do not rely solely on this estimate."
  },
  scenarios: [
    "LTA API Timeout / Proxy Error",
    "Stale Data Poll",
    "Schedule-Only / Monitored = 0",
    "GPS Fix/Age Penalty",
    "Auto-Reroute Opportunity",
    "OneMap Zero Results / API Error",
    "Unsafe / Contradictory OpenAI Output"
  ],
  arriveBy: {
    onTrack: "Arrive-by check: On track",
    onTrackMessage: "Estimated arrival is at or before your requested time.",
    risk: "Arrive-by check: Risk of delay",
    riskMessage: "Rough check: may miss arrive-by time.",
    na: "Arrive-by check: N/A",
    naMessage: "Destination ride duration unavailable; cannot verify target arrival time."
  },
  noRoute: "No direct or 1-transfer bus connection available for this trip.",
  noDirectBus: "no direct bus from near you — a transfer may still work",
  demoBanner: "SIMULATED DEMO MODE",
  simulated: "[SIMULATED]",
  aiExplanationTitle: "AI Explanation",
  updatingExplanation: "● Updating explanation...",
  probabilityExample: "64% (range 51–78%)",
  pace: {
    slower: {
      title: "Walk slower",
      detail: "You have time. A relaxed pace should still work."
    },
    slightly_slower: {
      title: "Walk slightly slower",
      detail: "You can ease your pace a little."
    },
    steady: {
      title: "Keep a steady pace",
      detail: "A normal walking pace works."
    },
    slightly_faster: {
      title: "Walk slightly faster",
      detail: "A slightly brisker walk improves your chances."
    },
    faster: {
      title: "Walk faster",
      detail: "A brisk walk improves your chances. Stay on footpaths and use crossings."
    },
    unlikely: {
      title: "Unlikely at a normal pace",
      detail: "Walking faster is unlikely to be enough. Check the reroute options or the next bus."
    }
  },
  status: {
    live: "live",
    scheduleOnly: "schedule only",
    locationUncertain: "location uncertain",
    stale: "stale",
    unavailable: "unavailable",
    noHistoryYet: "no history yet",
    noHistoricalReliabilityYet: "no historical reliability yet"
  },
  quality: {
    stale: {
      heading: "LTA data is stale",
      updated: "Last update: {time} ago",
      body: "Due to stale data, we cannot give a catch probability or recommend leaving now. Please wait for live data or try again later."
    },
    uncertain: {
      heading: "Location uncertain",
      body: "Your GPS accuracy is {accuracy} m. We'll show a wider range for the catch probability and won't suggest \"leave now\" from this fix."
    }
  }
};
