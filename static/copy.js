/* Exact user-facing strings from PROJECT_PLAN.md.
   This file is a classic script so the style guide can open as a file.
   The constants object is `copy`. */

var QUICK_PICKS = ["NUS", "Orchard Road", "Changi Airport"];

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
  /* proposed, approved: the explanation is three sentences. Python builds sentences one and two from these
     templates and keeps sentence three to a fixed clause per action unless the model supplies a valid one. */
  explanation: {
    busArrivingNow: "The bus is arriving now.",
    busMinutes: "The bus is {e} minutes away.",
    busOneMinute: "The bus is 1 minute away.",
    walkDefault: "Given the walking time is only {w} minutes, you have {t} minutes to get to the bus stop.",
    walkMayNotReach: "Given the walking time is {w} minutes, you may not reach the stop before the bus.",
    walkUnlikely: "Given the walking time is {w} minutes, catching this bus is unlikely.",
    locationUncertain: "Your location is uncertain, so the walking time may be off.",
    leg2Default: "Given you are about {w} minutes from the stop, you have {t} minutes to get to the bus stop.",
    adviceSentence: "It is advisable to {advice}.",
    advice: {
      wait: "wait for your leave-by alert",
      leaveNow: "leave now and walk to the bus stop",
      switchRoute: "switch to another bus",
      doNotRely: "not rely only on this estimate"
    }
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
    naMessage: "Destination ride duration unavailable; cannot verify target arrival time.",
    estimateTarget: "Arrive about {point} ({range})",
    estimateOnly: "Estimated arrival about {point} ({range})",
    late: "about {minutes} min late",
    missLabel: "If you miss it",
    missWithLate: "Next Bus {service} in {minutes} min · arrive about {point} ({late})",
    missNoSpare: "Next Bus {service} in {minutes} min · arrive about {point}",
    missWait: "Next Bus {service} in {minutes} min",
    warning: "Earliest arrival is about {earliest}, after your {target} target.",
    changeTime: "Change time",
    noTarget: "No target",
    in30: "In 30 min",
    inHour: "In 1 hour",
    custom: "Custom",
    resolved: "Arrive by {time}",
    past: "That time has already passed. Choose a later time.",
    tomorrow: "(tomorrow)",
    displayTime: "{label} · {time}"
  },
  noRoute: "No direct or 1-transfer bus connection available for this trip.",
  noDirectBus: "no direct bus from near you — a transfer may still work",
  demoBanner: "SIMULATED DEMO MODE",
  simulated: "[SIMULATED]",
  /* proposed, approved */
  ifCatchPrefix: "If you catch this bus: ",
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
    /* proposed, approved */
    trackingStopped: "Tracking stopped",
    noHistoryYet: "no history yet",
    noHistoricalReliabilityYet: "no historical reliability yet"
  },
  home: {
    subtitle: "AI-powered bus guidance in Singapore",
    heroLeave: "Know when to leave.",
    heroCatch: "Catch your bus.",
    heroSupport: "Get real-time bus information, catch probability and personalised leave-by time.",
    heading: "Where do you want to go?",
    placeholder: "e.g. Marina Bay Sands, NUS, Orchard Road",
    quickPicks: QUICK_PICKS,
    locationTitle: "Your location",
    locationGetting: "Using your current location…",
    arriveBy: "Arrive by",
    selectTime: "Select time",
    findRoute: "Find my route",
    homeLabel: "Bus Catch Assistant, go to home",
    required: "Required",
    requiredDestination: "Enter a destination to continue.",
    requiredArrive: "Choose when you need to arrive, or select No target.",
    resultsHeading: "Results from OneMap",
    resultsHint: " (Choose a place)",
    useDestination: "Use this destination",
    back: "Back",
    appearance: "Appearance",
    light: "Light",
    dark: "Dark",
    locationFound: "Location found",
    leaveTitle: "Leave this journey? Live tracking will stop.",
    stay: "Stay",
    leave: "Leave"
  },
  destinationStops: {
    title: "Nearby destination bus stops",
    infoLabel: "About these stops",
    info: "Bus stops within 600 m of your destination. Stops with a direct bus from near you come first, nearest first. Best option is the shortest walk among them.",
    bestOption: "Best option",
    selectStop: "Select destination stop",
    range: "Range: {distance}",
    walk: "{minutes} min walk ({distance})",
    locate: "Centre map on your location",
    none: "No destination stops were found within 600 m.",
    unavailable: "Destination stops are unavailable.",
    finding: "Finding destination stops…",
    needLocation: "Location unavailable. Destination stops need your current location."
  },
  confirmDestination: {
    selectedDestination: "Selected destination",
    destinationStop: "Destination bus stop",
    edit: "Edit",
    editDestination: "Edit destination",
    editStop: "Edit destination bus stop",
    info: "We'll find the best nearby boarding stops, check live bus arrivals and calculate your catch probability and leave-by time.",
    action: "Confirm and find buses"
  },
  journeyOverview: {
    title: "Your journey",
    from: "From",
    currentLocation: "Your current location",
    toBoarding: "{distance} to boarding stop",
    boardingStop: "Boarding stop",
    walk: "~ {minutes} min walk",
    busService: "Bus service",
    bus: "Bus {service}",
    to: "To {destination}",
    arrivingIn: "Arriving in {minutes}",
    transferStop: "Transfer stop",
    destinationStop: "Destination stop",
    walkToDestination: "~ {minutes} min walk to destination",
    destination: "Destination",
    edit: "Edit",
    editDestinationStop: "Edit destination stop",
    editDestination: "Edit destination",
    editArriveBy: "Edit arrive by time",
    startJourney: "Start journey",
    planning: "Planning your journey…",
    needLocation: "Location unavailable. Destination stops need your current location.",
    tryAgain: "Try again",
    noRoute: "No direct or 1-transfer bus connection available for this trip.",
    editDestinationAction: "Edit destination",
    editArriveByAction: "Edit arrive-by time",
    unavailable: "Nearby stops are unavailable.",
    reasonTargetMet: "Chosen for you: it should get you there by your arrive-by time.",
    reasonTargetMissed: "No route meets your arrive-by time. This one should get you there earliest.",
    reasonNoTarget: "Chosen for you: the quickest option we found.",
    leg2Note: "Live tracking starts when you reach the transfer stop.",
    /* omitted when the headway is not available */
    leg2Headway: "Schedule: about every {minutes} min."
  },
  liveCatch: {
    /* proposed, needs approval; a deliberate deviation from mockup 7, recorded in the plan */
    chanceToCatch: "Chance to catch Bus {service}",
    /* proposed, needs approval: the Page C current-bus card */
    chanceToCatchPageC: "Chance to catch your Bus {service}",
    /* proposed, needs approval: muted line under the heading; the stop name follows after " · " */
    arrivingIn: "Arriving in {n} min",
    arrivingSoon: "Arriving in <1 min",
    arrivingNow: "Arriving now",
    /* proposed, needs approval: the ring's aria-label; {eta} and {at} are dropped when unknown */
    ringLabel: "{p} percent chance of catching Bus {service}{eta}{at}, range {a} to {b} percent",
    ringEta: " arriving in {n} minutes",
    ringEtaSoon: " arriving in under 1 minute",
    ringEtaNow: " arriving now",
    ringAt: " at {stop}",
    /* proposed, needs approval */
    chanceToCatchLeg2: "Chance to catch Bus {service} at {stop}",
    range: "Range: {range_low} – {range_high}%",
    caption: "if you leave now and walk at a normal pace",
    unavailable: "Unavailable",
    missed: "Missed",
    leaveBy: "Leave by",
    leaveNow: "Leave now",
    /* deliberate deviation from mockup 7: the tile shows the action, never a clock time */
    waitForAlert: "Wait for Leave By Alert",
    estimatedArrival: "Estimated arrival",
    aiTitle: "AI Explanation",
    /* proposed, needs approval */
    aiNote: "Probabilities come from the app's own calculation. AI only explains them."
  },
  rerouteProposal: {
    /* proposed, needs approval */
    warningTitle: "You're unlikely to catch Bus {service}",
    /* proposed, needs approval */
    warningTimedTitle: "You're unlikely to catch the Bus {service} arriving in {minutes}",
    warningLine: "Catch probability: {point}% (range {range_low}–{range_high}%)",
    betterFound: "Better option found",
    recommended: "Recommended option",
    arrivesIn: "Arrives in {minutes}",
    toDestination: "To {destination}",
    leaveBy: "Leave by {time}",
    arrive: "Arrive {time}",
    rangeNote: "range {range_low}–{range_high}%",
    switchTo: "Switch to Bus {service} in {minutes}",
    alternatives: "Alternative options",
    alternativeChance: "{point}% chance",
    alternativeRange: "(range {range_low}–{range_high}%)",
    /* proposed, needs approval */
    otherBuses: "Other buses at your stop",
    /* proposed, needs approval */
    seeOtherBuses: "See other buses",
    /* proposed, needs approval */
    currentWarning: "Catching this bus is unlikely. Here are your other options.",
    /* proposed, needs approval */
    updated: "Updated {time}",
    /* proposed, needs approval */
    refreshLabel: "Refresh other buses",
    /* proposed, needs approval */
    optionsFailed: "Could not load other buses. Try the refresh button.",
    /* approved wording */
    pillHighest: "Highest catch probability",
    /* approved wording */
    pillQuick: "Reach your destination quickly",
    reachDestination: "Reach destination about {time}",
    atYourStop: "At your stop",
    walkTo: "Walk to {stop} ({distance})",
    afterTarget: "After your target",
    showMore: "Show more",
    showFewer: "Show fewer",
    /* proposed, needs approval */
    newJourneyTitle: "Your new journey",
    /* proposed, needs approval */
    newJourneyReason: "Switching because your current bus is unlikely to be caught.",
    /* proposed, needs approval */
    busLeftNotice: "Bus {service} has left. Here are your other options.",
    /* proposed, needs approval */
    alreadyLeft: "That bus has already left. Choose another option.",
    /* proposed, needs approval: browser notification while a proposal is pending */
    pendingNotificationTitle: "Better option — Bus {new_service}",
    /* proposed, needs approval: browser notification while a proposal is pending */
    pendingNotificationBody: "A better option is available. Open the app to switch.",
    /* proposed, needs approval: written by Python (recommend.py REASON_TEXT), shown here for the style guide only */
    reasonFastestRushing: "Your arrive-by time is close, so Bus {s} is recommended: it should get you to your destination first.",
    reasonHighestChanceOnTime: "Bus {s} is recommended: it has the highest chance of catching, and it should still get you there by your arrive-by time.",
    reasonHighestChance: "Bus {s} is recommended: it has the highest chance of catching.",
    reasonShorterWalk: "Bus {s} has a similar chance to the other options, and the walk to its stop is shorter.",
    reasonNoneByTarget: "No option should reach your destination by your arrive-by time. Bus {s} should get you there earliest.",
    advisable: "It is advisable to {advice}."
  },
  liveTracking: {
    refresh: "Refresh live arrivals",
    nextBuses: "Next 3 buses",
    arriving: "(Arriving)",
    liveAvailable: "Live bus location available",
    liveUnavailable: "Live bus location unavailable",
    monitored: "Monitored (live GPS)",
    notMonitored: "Not monitored (no GPS)",
    gpsAccuracy: "GPS accuracy",
    lastUpdate: "Last update",
    secondsAgo: "{seconds} seconds ago",
    minutesAgo: "{minutes} min {seconds} sec ago",
    noValue: "—"
  },
  /* proposed, needs approval: every string in catchPrompt, transferAlert and leg2 */
  catchPrompt: {
    seeArrivals: "See bus arrival times",
    thenBus: "Then Bus {service} at {stop}",
    question: "Did you catch the bus?",
    yes: "Yes, I caught it",
    no: "No, I missed it",
    endUnanswered: "Tracking ended. Your bus's expected arrival time has passed.",
    endMax: "Tracking stopped after 60 minutes.",
    planNew: "Plan a new journey",
    onWayTitle: "On your way",
    boarded: "On board",
    transferNote: "We'll alert you when you're near {transfer stop}. Keep this page open."
  },
  transferAlert: {
    prompt: "You are reaching the second bus stop",
    next: "Next",
    notificationTitle: "Get ready to change bus",
    notificationBody: "You are reaching {stop name}. Tap to check your chance of catching Bus {service}.",
    noGps: "Turn on location to get a transfer alert."
  },
  leg2: {
    caption: "based on how far you are from the stop",
    reachLabel: "Reach the stop"
  },
  liveMap: {
    fullRoute: "Full route",
    nearMe: "Near me"
  },
  leaveNowBanner: {
    app: "Bus Catch Assistant",
    now: "now",
    viewDetails: "View details",
    dismiss: "Dismiss"
  },
  quality: {
    stale: {
      heading: "LTA data is stale",
      updated: "Last update: {time}",
      arriving: "Arriving in {minutes} min (estimated)",
      body: "Due to stale data, we cannot give a catch probability or recommend leaving now. Please wait for live data or try again later."
    },
    unavailable: "No live arrival data available. No previous successful update.",
    noService: "No buses currently in service at this stop.",
    uncertain: {
      heading: "Location uncertain",
      /* proposed, needs approval */
      ageBody: "Your location hasn't updated for {seconds} s. We'll show a wider range for the catch probability and won't suggest \"leave now\" from this fix.",
      body: "Your GPS accuracy is {accuracy}. We'll show a wider range for the catch probability and won't suggest \"leave now\" from this fix."
    }
  }
};
