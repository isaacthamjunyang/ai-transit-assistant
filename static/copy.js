/* Exact user-facing strings from PROJECT_PLAN.md.
   This file is a classic script so the style guide can open as a file.
   The constants object is `copy`. */

var QUICK_PICKS = ["NUS", "Orchard Road", "Changi Airport"];

var copy = {
  menuData: {
    holidays: "Public holidays updated to {year}",
    bus: "Bus data updated {date}",
    busUnknown: "Bus data date unknown",
    rail: "Train timetable updated {date}",
    railUnknown: "Train timetable date unknown",
    attribution: "Contains information from LTA DataMall under the Singapore Open Data Licence v1.0",
    unavailable: "Data status unavailable"
  },
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
  atStop: {
    tile: "At the stop",
    tileBus: "The bus is {e}\u00a0min away.",
    tileArriving: "The bus is arriving now.",
    card: "You are at the stop. You have {e} to wait.",
    cardArriving: "You are at the stop. The bus is arriving now."
  },
  /* A train as the first leg (scheduled, not live). explTrain* are the whole of the AI card's first sentence; the leave
     sentence after it is the existing one. {line} is the line's name, {e} whole minutes. Mirrors explain.S_TRAIN*. */
  train: {
    explTrain: "The {line} train is scheduled in {e}\u00a0min. Live train times are not available.",
    explTrainNow: "The {line} train is scheduled to leave now. Live train times are not available.",
    explTrainUnlikely: "The {line} train is scheduled in {e}\u00a0min, and you are {distance} from the station, but catching this train is unlikely.",
    explTrainNowUnlikely: "The {line} train is scheduled to leave now, and you are {distance} from the station, but catching this train is unlikely.",
    leaveByTrain: "Leave by {time} so you have {x} to reach your station and catch the train departing at {arrival}.",
    leaveNowTrain: "Leave now so you have {e} to reach your station and catch the train departing at {arrival}.",
    leaveNowDepartingTrain: "Leave now to try to catch the train departing at {arrival}.",
    trainNotLive: "Train times are scheduled, not live.",
    trainAbout: "about {time}",
    trainNext: "Next trains: {list}.",
    trainMiss: "If you miss it, the next train is at about {time}.",
    trainLeft: "The {line} train has left. The next one is at about {time}."
  },
  rerouteCard: {
    title: "Route Updated",
    message: "Switched to Bus {new_service} at {new_stop_name} ({new_stop_code}).",
    probability: "Catch probability: about {new_point}% vs previous about {old_point}%."
  },
  rerouteNotification: {
    title: "Route Updated — Bus {new_service}",
    body: "Switched to Bus {new_service} at {new_stop_name}. Catch probability: {new_point}% (range {new_low}–{new_high}%)."
  },
  noBetter: {
    standard: "Primary bus target has low catch probability ({point}%), but no better direct alternative meets the 15% improvement threshold.",
    postReroute: "Primary bus target has low catch probability ({point}%), but no better direct alternative meets the post-reroute 20% improvement threshold."
  },
  /* approved: the explanation is written by Python from these templates (explain.py); no model is called for it.
     Sentence one is busMinutes (or busArrivingNow) + youAre + a speed part, or the unlikely tail. Sentence two is the
     leave sentence. {x} and {e} are minutes ("1 minute", "5 minutes"). */
  explanation: {
    busArrivingNow: "The bus is arriving now",
    busMinutes: "The bus is {e} away",
    youAre: ", and you are {distance} from the stop",
    unlikely: ", but catching this bus is unlikely.",
    speedMeasured: " and walking at about {kmh}\u00a0km/h.",
    speedRemembered: " and walking at your usual speed of {kmh}\u00a0km/h.",
    speedDefault: " and walking at an average speed of {kmh}\u00a0km/h.",
    leaveBy: "Leave by {time} so you have {x} to reach your stop and catch the bus arriving at {arrival}.",
    leaveNow: "Leave now so you have {e} to reach your stop and catch the bus arriving at {arrival}.",
    leaveNowArriving: "Leave now to try to catch the bus arriving at {arrival}.",
    uncertainBy: "Your location is uncertain, so leave a little earlier than that to be safe.",
    uncertainNow: "Your location is uncertain, so the walking time may be off."
  },
  walkPage: {
    /* proposed, needs approval: the button row on Page A and the page title */
    openRow: "See current location and walking pace",
    title: "Walk to your stop",
    /* proposed, needs approval: the status card; {n} and {distance} are filled by the page */
    distance: "{distance} to the stop",
    minutes: "about {n}\u00a0min walk",
    onWay: "On your way",
    still: "Not moving",
    /* proposed, needs approval: the fourth and fifth state lines */
    away: "Moving away from the stop",
    checking: "Checking your movement…",
    arrived: "Arrived at the stop",
    waiting: "Waiting for your location…",
    recentre: "Recentre map",
    sensorDetails: "Sensor details",
    /* proposed, needs approval: the trend under the ring, from consecutive server values */
    trendRisingCloser: "Rising as you get closer",
    trendRising: "Rising",
    trendFallingAway: "Falling as you move away",
    trendFalling: "Falling as time passes",
    trendSteady: "Steady",
    /* proposed, needs approval: the Sensor details panel */
    sourceGps: "from GPS",
    sourceSteps: "from your steps",
    sourceUsual: "your usual pace",
    sourceAverage: "average pace",
    rowPace: "Walking pace",
    rowGpsSpeed: "GPS speed",
    rowGpsAccuracy: "GPS accuracy",
    rowCadence: "Steps per minute",
    rowStepLength: "Step length",
    rowSamples: "Learned samples",
    whyNotWalking: "Not walking yet",
    whyNoPermission: "No motion permission",
    whyNearStop: "Near the stop"
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
    onTrackMessage: "Estimated destination arrival is at or before your requested time.",
    risk: "Arrive-by check: Risk of delay",
    na: "Arrive-by check: N/A",
    naMessage: "Destination ride duration unavailable; cannot verify target arrival time.",
    estimateTarget: "Arrive about {point}",
    estimateOnly: "Estimated destination arrival about {point}",
    /* proposed, needs approval: the Arrive by card (overview, on your way, new journey). The main line is the app's
       estimate (the 12-hour SGT clock, a no-break space before AM or PM, "(tomorrow)" for a next-day time). The muted
       line under it is the gap to the target, worked out from the displayed clock minutes: gapBefore or gapAfter with
       an amount ("{n} mins", "1 min"; from 60 minutes gapHrMins, gapHrMinOne, or journeyOverview durationHr when the
       minutes are 0), or gapOnTarget when the minutes are the same. Only this card says "mins". With no target there is only the main line. The one-line sentences
       above stay on the live page. */
    arriveLine: "Arrive by: {time}",
    gapMinutes: "{n}\u00a0mins",
    gapMinuteOne: "1\u00a0min",
    gapHrMins: "{h}\u00a0hr {m}\u00a0mins",
    gapHrMinOne: "{h}\u00a0hr 1\u00a0min",
    gapBefore: "{amount} before target",
    gapAfter: "{amount} after target",
    gapOnTarget: "On target time",
    late: "about {minutes} min late",
    missLabel: "If you miss it",
    missWithLate: "Next Bus {service} in {minutes} min · reach destination about {point} ({late})",
    missNoSpare: "Next Bus {service} in {minutes} min · reach destination about {point}",
    missWait: "Next Bus {service} in {minutes} min",
    warning: "Earliest arrival is about {earliest}, after your {target} target.",
    changeTime: "Change time",
    noTarget: "No target",
    in30: "In 30 min",
    inHour: "In 1 hour",
    custom: "Custom",
    past: "That time has already passed today. Choose Tomorrow or a later time.",
    tooFar: "That time is more than 24 hours away. Choose an earlier time.",
    timeLabel: "Time",
    dayLabel: "Day",
    dayToday: "Today",
    dayTomorrow: "Tomorrow",
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
  probabilityExample: "about 64%",
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
    heroLeave: "Know when to leave.",
    heroCatch: "Catch your bus.",
    heroSupport: "Get real-time bus information, catch probability and personalised leave-by time.",
    heading: "Where do you want to go?",
    placeholder: "e.g. Marina Bay Sands, NUS, Orchard Road",
    quickPicks: QUICK_PICKS,
    /* proposed, needs approval: saved places on Home (up to {max}, named by the user, kept on this phone only; see
       static/saved-places.js). The three quickPicks names above are the starters shown only while nothing is saved. */
    savedPlaces: {
      note: "Saved on this phone only.",
      add: "+",
      addLabel: "Add a saved place",
      count: "{n} of {max} saved",
      chipLabel: "{name}, saved place",
      chipLabelAddress: "{name}, saved place, {address}",
      menuLabel: "Rename {name}",  /* the chip's name for assistive technology while editing */
      editToggle: "Edit",
      editToggleLabel: "Edit saved places",
      doneToggle: "Done",
      doneToggleLabel: "Done editing saved places",
      deleteMark: "\u00d7",
      deleteMarkLabel: "Delete {name}",
      addTitle: "Add a saved place",
      searchLabel: "Search for the place",
      searchPlaceholder: "Search for a place",
      searchAction: "Search",
      pickHint: "Pick a place from the results, then name it.",
      nameLabel: "Your name for this place",
      nameHint: "Up to {max} characters",
      save: "Save",
      cancel: "Cancel",
      editTitle: "Edit name",
      editAction: "Edit name",
      deleteConfirm: "Delete {name}?",
      deleteYes: "Delete",
      errorName: "Enter a name for this place.",
      errorLong: "Use {max} characters or fewer.",
      errorDuplicate: "That place is already saved.",
      errorFull: "You can save up to {max} places.",
      errorPick: "Pick a place from the results first.",
      storageUnavailable: "Can't save on this device."
    },
    locationTitle: "Your location",
    locationGetting: "Using your current location…",
    arriveBy: "Arrive by",
    selectTime: "Select time",
    findRoute: "Find my route",
    homeLabel: "Beat the Bus and MRT, go to home",
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
    title: "Nearby destination MRT stations / bus stops",
    infoLabel: "About these stops",
    info: "Bus stops and MRT or LRT stations within 600 m of your destination, nearest walk first. If no station is that close, the nearest one within 1.5 km is shown. The first one is chosen for you.",
    /* proposed, needs approval: the text on every row of the list, so the type is never told by colour alone */
    busStop: "Bus stop",
    mrtStation: "MRT station",
    lrtStation: "LRT station",
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
    /* proposed, needs approval: the same card when the chosen destination is a station */
    destinationStation: "Destination station",
    editStation: "Edit destination station",
    edit: "Edit",
    editDestination: "Edit destination",
    editStop: "Edit destination bus stop",
    info: "We'll find the best route from here by bus and MRT and work out your leave-by time.",
    action: "Confirm"
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
    /* approved: above Start journey. The server does receive the speed number. */
    motionPrivacy: "Motion data stays on your phone. Only the walking speed worked out from it is sent. Your location is sent as before.",
    motionOff: "Motion sensor is off, so your steps are not used.",
    planning: "Planning your journey…",
    needLocation: "Location unavailable. Destination stops need your current location.",
    tryAgain: "Try again",
    noRoute: "No direct or 1-transfer bus connection available for this trip.",
    /* the bus planner's sentence (the static fallback, and the destination stop list); the OneMap planner's are the
       noServiceAny, noBusClosed and noMrtClosed lines below */
    noService: "No buses are running to this destination at this time.",
    editDestinationAction: "Edit destination",
    editArriveByAction: "Edit arrive-by time",
    unavailable: "Nearby stops are unavailable.",
    /* proposed: shown on the second bus of a transfer route; the headway line is omitted when it is not available */
    headway: "Schedule: about every {minutes} min.",
    /* proposed, needs approval (plan_edits_9 4.9): one row per leg. {n} {m} {k} {w} {t} are whole numbers. */
    walkRow: "Walk {n}\u00a0min",
    walkRowTo: "{distance} to {place}",
    busToward: "To {terminus}",
    trainToward: "To {terminus}",
    /* proposed, needs approval: a loop line (Circle Line) names its way round; the platform only when one serves it */
    loopToward: "{direction} \u00b7 To {terminus}",
    clockwise: "Clockwise",
    anticlockwise: "Anticlockwise",
    directionPlatform: "{direction} \u00b7 Platform {x}",
    platformOnly: "Platform {x}",
    stopsAndMin: "{k} stops · {m}\u00a0min",
    stopOneAndMin: "1 stop · {m}\u00a0min",
    scheduledIn: "Scheduled · In {n}\u00a0min",
    scheduledInOne: "Scheduled · In 1\u00a0min",
    scheduledNow: "Scheduled · Now",
    scheduledAt: "Scheduled · {time}",
    /* proposed, needs approval: a later bus leg with a live next-bus time; the first bus says "Arriving soon" for "Due" */
    liveIn: "Live · In {n}\u00a0min",
    liveArrivingSoon: "Live · Arriving soon",
    liveNow: "Live · Now",
    arrivingSoon: "Arriving soon",
    /* proposed, needs approval: the summary card under the priority select (three labelled cells) and its durations */
    summaryTime: "Total time",
    summaryTransfers: "Transfers",
    summaryWalking: "Walking",
    summaryAria: "Total time {time}, {transfers}, walking {walk}",
    durationMin: "{n}\u00a0min",
    durationHr: "{h}\u00a0hr",
    durationHrMin: "{h}\u00a0hr {m}\u00a0min",
    transfersMany: "{t} transfers",
    transfersOne: "1 transfer",
    transfersNone: "No transfers",
    /* proposed, needs approval: the priority chips and their messages */
    priorityLabel: "Priority",
    priorityFastest: "Fastest",
    priorityFewest: "Fewest transfers",
    priorityLeastWalk: "Least walking",
    priorityBus: "Bus only",
    priorityMrt: "MRT only",
    noRouteFound: "No route found for this trip.",
    noBusOnly: "No bus-only route found. Try another priority.",
    noMrtOnly: "No MRT or LRT route found. Try another priority.",
    /* proposed, needs approval: nothing runs (the OneMap planner), by priority */
    noServiceAny: "No bus or MRT services are running to this destination at this time.",
    noBusClosed: "Bus services have stopped for now. Try another priority.",
    noMrtClosed: "MRT and LRT services have stopped for now. Try another priority.",
    needsRouteService: "Needs the route service.",
    fallbackNote: "Showing bus routes only. The route service is unavailable.",
    /* proposed, needs approval: one muted line under the summary card when the route has a bus leg. The bus minutes
       shown already include an assumed traffic factor (config.BUS_PEAK_FACTOR); no figure is put on screen. */
    trafficNote: "Bus times can vary with traffic."
  },
  /* proposed, needs approval: the ride-app card under an empty plan answer (no service, no route, walk only). The links go
     to each operator's own site with no trip data: no operator documents a prefilled link we could confirm. The distance
     is worked out on the phone from coordinates already there; it is a straight line, and says so. No money figures, no times.
     Mirrored by hand in index.html (#ride-apps). */
  rideApps: {
    heading: "No transit right now. Open a ride app:",
    distance: "About {km} km in a straight line",
    note: "These links open each app's own site. Your trip is not sent.",
    apps: [
      { name: "Grab", url: "https://www.grab.com/sg/download/" },
      { name: "Gojek", url: "https://gojek.com/sg/about" },
      { name: "CDG Zig", url: "https://www.cdgtaxi.com.sg/" },
      { name: "TADA", url: "https://tada.global" },
      { name: "Ryde", url: "https://rydesharing.com/" }
    ]
  },
  /* proposed, needs approval (plan_edits_9 4.6, 4.8): the words of the live pages for a train first leg that the server
     does not send. Mirrored by hand in index.html (TRAIN_PAGE). */
  trainPage: {
    walkTitle: "Walk to your station",
    walkDistance: "{distance} to the station",
    walkArrived: "Arrived at the station",
    catchHeading: "Chance to catch the {line} train",
    ringLabel: "about {p} percent chance of catching the {line} train{eta}{at}",
    departsIn: "Departs in {n} min",
    departsSoon: "Departs in <1 min",
    departsNow: "Departs now",
    ringDepartsIn: " departing in {n} minutes",
    ringDepartsSoon: " departing in under 1 minute",
    ringDepartsNow: " departing now",
    departsLabel: "Train departs",
    tileAway: "The train departs in {e}\u00a0min and the walk takes about {w}\u00a0min.",
    tileDeparting: "The train is departing now and the walk takes about {w}\u00a0min.",
    seeTimes: "See train times",
    question: "Did you catch the train?",
    nextTrains: "Next trains",
    scheduled: "Scheduled",
    every: "Every about {n} min",
    departsAt: "Departs {time}",
    toward: "Toward {terminus}",
    leftOnly: "The {line} train has left.",
    trainTitle: "{line} train",
    tileLabel: "{line} train, {time}",
    about: "about {time}",
    left: "The {line} train has left. The next one is at about {time}.",
    notLive: "Train times are scheduled, not live."
  },
  /* proposed, needs approval (plan_edits_9 4.2): the line names shown beside the badge */
  lineNames: {
    NS: "North-South Line",
    EW: "East-West Line",
    CG: "Changi Airport Branch",
    NE: "North-East Line",
    CC: "Circle Line",
    DT: "Downtown Line",
    TE: "Thomson-East Coast Line",
    BP: "Bukit Panjang LRT",
    SK: "Sengkang LRT",
    PG: "Punggol LRT",
    SS: "Sentosa Express"
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
    ringLabel: "about {p} percent chance of catching Bus {service}{eta}{at}",
    ringEta: " arriving in {n} minutes",
    ringEtaSoon: " arriving in under 1 minute",
    ringEtaNow: " arriving now",
    ringAt: " at {stop}",
    /* approved: muted label left of the bus arrival clock time, at the right of the ring */
    busArrives: "Bus arrives",
    caption: "if you leave now and walk at a normal pace",
    /* proposed, approved: the caption follows the source the server reports for the walking speed */
    captionCurrentPace: "if you leave now and keep walking at your current pace",
    captionUsualPace: "if you leave now and walk at your usual pace",
    /* approved: the muted line under the caption; {kmh} is the server's walk_speed_used x 3.6, one decimal */
    walkPaceGps: "Walking pace: {kmh} km/h · from GPS",
    walkPaceSteps: "Walking pace: {kmh} km/h · from your steps",
    walkPaceUsual: "Walking pace: {kmh} km/h · your usual pace",
    walkPaceNormal: "Walking pace: {kmh} km/h · normal pace",
    unavailable: "Unavailable",
    missed: "Missed",
    leaveBy: "Leave by",
    leaveNow: "Leave now",
    /* approved: the Leave by tile shows a clock time or "Leave now", never both; {n} and {w} are whole minutes */
    leaveByIn: "in {n}\u00a0min · {w}\u00a0min walk",
    leaveByInUnder: "in under 1\u00a0min · {w}\u00a0min walk",
    leaveNowBusAway: "The bus is {e}\u00a0min away and the walk takes about {w}\u00a0min.",
    leaveNowBusArriving: "The bus is arriving now and the walk takes about {w}\u00a0min.",
    leaveUncertain: "Location uncertain: leave a bit earlier to be safe.",
    estimatedArrival: "Estimated destination arrival",
    aiTitle: "AI Explanation",
    /* proposed, needs approval */
    aiNote: "Worked out from the app's own estimates."
  },
  rerouteProposal: {
    /* proposed, needs approval */
    warningTitle: "You're unlikely to catch Bus {service}",
    /* proposed, needs approval */
    warningTimedTitle: "You're unlikely to catch the Bus {service} arriving in {minutes}",
    warningLine: "Catch probability: about {point}%",
    betterFound: "Better option found",
    recommended: "Recommended option",
    arrivesIn: "Arrives in {minutes}",
    toDestination: "To {destination}",
    leaveBy: "Leave by {time}",
    arrive: "Destination arrival {time}",
    switchTo: "Switch to Bus {service} in {minutes}",
    alternatives: "Alternative options",
    alternativeChance: "{point}% chance",
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
    reasonNoneByTarget: "No option should reach your destination by your arrive-by time. Bus {s} should get you there earliest."
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
  /* proposed, needs approval: every string in catchPrompt */
  catchPrompt: {
    seeArrivals: "See bus arrival times",
    thenBus: "Then Bus {service} at {stop}",
    /* proposed, needs approval: the same line when the next leg is a train */
    thenTrain: "Then {line} at {station}",
    question: "Did you catch the bus?",
    yes: "Yes, I caught it",
    no: "No, I missed it",
    endUnanswered: "Tracking ended. Your bus's expected arrival time has passed.",
    endMax: "Tracking stopped after 60 minutes.",
    planNew: "Plan a new journey",
    onWayTitle: "On your way",
    boarded: "On board"
  },
  /* proposed, needs approval: every string in onWay. Mirrored by hand in index.html (ON_WAY_TEXT). The Next line and the Get off
     alert on the On your way screen. The position the alert uses is read and compared on the phone only. */
  onWay: {
    nextGetOff: "Next: Get off at {place}",
    nextWalk: "Next: Walk {n}\u00a0min to {place}",
    nextBoardBus: "Next: Board Bus {service} at {place}",
    nextBoardTrain: "Next: Board the {line} train at {place}",
    getOffBus: "Get off next stop: {place}",
    getOffTrain: "Get off at {station}",
    dismiss: "Dismiss",
    done: "Done",
    privacy: "Your position stays on this phone. It is used only for the Get off alert and is never sent, stored or logged.",
    openNote: "Works while this page is open."
  },
  liveMap: {
    fullRoute: "Full route",
    nearMe: "Near me"
  },
  leaveNowBanner: {
    app: "Beat the Bus and MRT",
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
