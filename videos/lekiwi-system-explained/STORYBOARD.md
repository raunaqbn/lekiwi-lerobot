---
format: 1920x1080
duration: 125s
message: "LeKiwi stays understandable and responsive by keeping one hardware owner beside the robot while every UI reads cached, source-labeled state"
arc: concept-explainer with process
audience: "LeKiwi builders and operators"
mode: autonomous
music: "restrained technical pulse, precise and low-energy"
---

## Video direction

- **Palette:** Cobalt Grid preset only—warm paper canvas, electric cobalt ink, permanent graph-paper grid, cobalt hairlines, and scarce soft-cobalt depth. No extra status colors; warnings use typographic or hatch treatment instead of inventing red/amber.
- **Type:** Newsreader display for the conceptual claim, Hanken Grotesk for explanation, DM Mono for ports, IDs, voltage, timestamps, and state labels.
- **Motion grammar:** Long-tail, smooth `power3` feeling; each word, node, register, or boundary appears on its spoken cue across the whole frame. Final content holds still; only a caret or one low-amplitude grid pulse may remain.
- **Rhythm:** Frames 1–3 progressively build density. Frame 4 is the deliberate held/breather read after the confidence band resolves. Frame 5 is the control climax. Frame 6 simplifies into a deployment boundary. Frame 7 holds the command and cutoff for inspection.
- **Caption keep-out:** Important content remains above the bottom 17%; backgrounds and grid may bleed full frame.
- **Negative list:** No stock robot, glossy device mockup, floating bokeh, purple-blue AI gradient, nav chrome, uncontrolled camera drift, slideshow front-load-then-freeze, or screensaver motion with independent floating parts.

## Frame 1 — Online is not understood

- status: animated
- src: compositions/frames/01-online-not-understood.html
- duration: 12.278s
- transition_in: cut
- scene: A robot silhouette lights up while the words ONLINE, POWERED, FLOWING, and SAFE separate into four independent indicators.
- voiceover: "A robot can be online while its commands are idle, powered while one bus is dark, and connected while the operator is looking at the wrong voltage. Good diagnostics must say what was actually observed."
- type: hook
- persuasion: Common-belief vs reality + progressive disclosure
- beat: Surprise and recognition
- blueprint: kinetic-type-beats

**narrativeRole:** Opens the stakes in operator language: green connectivity alone does not establish a healthy, controllable robot.

**keyMessage:** Connectivity, power, command flow, and safety are separate facts.

- focal: the four independent operator facts
- roles: robot silhouette = supporting anchor · ONLINE/POWERED/FLOWING/SAFE words = foreground subjects · graph grid and diagnostic crosshair = background
- sfx: relay-click, low-system-pulse

Adapt `kinetic-type-beats`: keep the one-word-at-a-time signature, replacing hype words with operator facts.

Scene 1 (0.0–2.2s): A pale LeKiwi silhouette draws at left on the permanent grid; ONLINE stamps large at upper right as the narrator says “online” — asymmetric 40/60, three depth layers, path draw plus firm type snap.

Scene 2 (2.2–6.8s): ONLINE shifts into a four-quadrant ledger; POWERED, FLOWING, and SAFE arrive only on their spoken contrasts, each separated by a cobalt hairline and paired with a small mono indicator — full-width diagnostic matrix, discrete type sequence.

Scene 3 (6.8–10.0s): The four labels pull apart with visible gaps while “ACTUALLY OBSERVED” expands across the upper third; the robot stays quiet and the final distinction holds still for captions.

## Frame 2 — One owner, many observers

- status: animated
- src: compositions/frames/02-one-owner.html
- duration: 16.065s
- transition_in: blur-crossfade
- scene: A stable two-node wiring diagram grows from leader computer to Pi, with one serial-owner lock on each side and cached readouts branching to browser and iOS.
- voiceover: "LeKiwi solves that with one rule: one process owns each serial bus. The leader computer samples six motors. The Raspberry Pi owns nine follower motors and the cameras. Every web request reads an immutable cached snapshot."
- type: product_intro
- persuasion: Causal chain + rule of three
- beat: Orientation and clarity
- blueprint: constellation-hub

**narrativeRole:** States the architectural thesis by beat two and names the local hardware owners.

**keyMessage:** Rich observation is safe when it branches from a single deterministic owner loop.

- focal: two locked bus-owner nodes joined by ZMQ
- roles: leader and Pi owner blocks = foreground subjects · cached browser/iOS branches = supporting · graph grid and packet traces = background
- sfx: connector-seat, soft-data-ticks

Adapt `constellation-hub`: keep the hub-and-satellites signature, using two physical hubs rather than a brand mark.

Scene 1 (0.0–3.0s): ONE OWNER appears as a cobalt lock centered on a horizontal wire; it splits into leader and Pi stations as the rule is spoken — rule-of-thirds, 2-node hero filling 55% of frame, center-outward expansion.

Scene 2 (3.0–8.8s): Six small leader IDs populate the left hub; nine follower IDs and two camera glyphs populate the right hub on their spoken cues; ZMQ 5555/5556 traces draw between them — wide station diagram, progressive node and path reveal.

Scene 3 (8.8–13.0s): Browser, SSE, and iOS satellites branch outward from a single CACHED SNAPSHOT tile without crossing either serial lock; the word IMMUTABLE lands last and the completed diagram holds.

## Frame 3 — Source-labeled truth

- status: animated
- src: compositions/frames/03-source-labeled-truth.html
- duration: 17.633s
- transition_in: push-slide LEFT
- scene: Two vertical bus ledgers—leader at 5.3 volts, follower at 10.5 volts—populate with motor IDs, then state labels replace an undifferentiated red fault wall.
- voiceover: "That cache keeps sources separate. Six leader servos at about five volts can be healthy while the follower reports a three-cell rail near ten and a half. Fault, unpowered, offline, and not applicable are different diagnoses—not different shades of red."
- type: feature_showcase
- persuasion: Comparison of two options + coined vocabulary
- beat: Comprehension and relief
- blueprint: comparison-split

**narrativeRole:** Resolves the misleading voltage and all-fault UI problem with source identity and explicit state semantics.

**keyMessage:** A reading is meaningful only with its source, topology, freshness, and profile.

- focal: paired leader and follower voltage ledgers
- roles: leader/follower columns = foreground subjects · motor-ID rows = supporting · profile labels and time ticks = background metadata
- sfx: ledger-stamp, short-register-ticks

Reproduce `comparison-split`: mirrored bus ledgers open like a book and stay geometrically paired.

Scene 1 (0.0–3.0s): LEADER and FOLLOWER panels tilt open from the center seam; six and nine ID slots appear as empty ruled rows — split-screen, equal visual weight, mirrored book-open entrance.

Scene 2 (3.0–7.6s): 5.3 V fills the leader header exactly when “five volts” is spoken; 10.5 V fills the follower header on “ten and a half”; rows tick healthy independently with source badges — synchronized ledger population.

Scene 3 (7.6–11.0s): One undifferentiated FAULT wall briefly overlays the split, then fractures into FAULT / UNPOWERED / OFFLINE / N/A labels placed on distinct rows as named.

Scene 4 (11.0–13.0s): The center seam becomes SOURCE + PROFILE + FRESHNESS; both ledgers hold, proving the two voltages coexist.

## Frame 4 — Battery without false precision

- status: animated
- src: compositions/frames/04-battery-band.html
- duration: 17.398s
- transition_in: push-slide LEFT
- scene: Nine follower voltage ticks collapse to a median, which expands into a broad state-of-charge band while a runtime clock is crossed out.
- voiceover: "Battery state is an estimate, not a stopwatch. The dashboard takes the median of readable follower voltages and maps it to a deliberately wide three-cell confidence band. Motor calibration maps position; it cannot reveal chemistry, load sag, aging, or remaining runtime."
- type: social_proof
- persuasion: Worked mechanism + counterexample
- beat: Confidence with caution
- blueprint: dataviz-countup

**narrativeRole:** Demonstrates how the product handles uncertainty instead of fabricating a precise battery percentage or runtime.

**keyMessage:** Voltage supports a bounded estimate; accurate runtime needs current and pack history.

- focal: median follower voltage expanding into a confidence band
- roles: nine voltage ticks = supporting evidence · median line and band = foreground subject · crossed runtime clock = counterexample · grid = background
- sfx: nine-soft-ticks, band-bloom

Adapt `dataviz-countup`: keep the count-up and resolving instrument signature; replace a single percentage with a visibly bounded interval.

Scene 1 (0.0–3.0s): Nine small voltage readings populate a mono strip from left to right as the narrator says “estimate” — full-width evidence rail, count-up ticks.

Scene 2 (3.0–6.7s): The readings collapse toward their median; a vertical 10.5 V rule grows at center and the word MEDIAN locks above it — centered instrument, smooth converge.

Scene 3 (6.7–9.5s): A wide translucent cobalt band expands around the median as “confidence band” lands; chemistry, load, aging, and sensor resolution appear as edge annotations, one per spoken caveat.

Scene 4 (9.5–12.0s): A precise runtime clock attempts to count, is crossed by one clean diagonal, and everything settles into “ESTIMATE ≠ STOPWATCH”; this is the deliberate still breather.

## Frame 5 — The twin and the takeover

- status: animated
- src: compositions/frames/05-twin-takeover.html
- duration: 20.506s
- transition_in: zoom-through
- scene: A schematic URDF robot rotates into view; six joints illuminate on click, then an ARM TAKEOVER switch reroutes leader goals through frozen dashboard targets until STOP releases them.
- voiceover: "The same calibrated positions drive a clickable Three.js twin built from the LeKiwi URDF and CAD meshes. But browser arm mode is active control: it replaces manual leader goals with cached hold or jog targets. Press Stop and release takeover before expecting the leader to drive again."
- type: feature_showcase
- persuasion: Demonstration + cause-and-effect reveal
- beat: Mastery and alertness
- blueprint: panel-edit-live-sync

**narrativeRole:** Connects visual inspection to real control semantics and explains the common leader-arm failure mode.

**keyMessage:** The twin is an inspector; arm takeover is an explicit command source that must be released.

- focal: schematic articulated LeKiwi and the takeover routing switch
- roles: robot twin = foreground subject · six joint nodes = interactive supporting · leader/dashboard goal rails = supporting comparison · grid and joint axes = background
- sfx: servo-select, routing-switch, stop-click

Adapt `panel-edit-live-sync`: keep the live-coupling signature, replacing a generic editor with joint telemetry and explicit goal routing.

Scene 1 (0.0–3.5s): A schematic LeKiwi arm assembles from URDF-like links; six cobalt joint rings draw in on the calibrated pose — asymmetric 60/40 with robot dominant, link and joint path reveal.

Scene 2 (3.5–7.2s): A mono telemetry rail selects SHOULDER LIFT / ID 2; the matching joint and value pulse once as “clickable twin” is spoken — live-sync coupling, no cursor.

Scene 3 (7.2–11.2s): LEADER GOALS flow toward the follower until ARM TAKEOVER flips on; the route bends visibly through HOLD / JOG targets and leader packets fade to outlined ghosts — causal reroute animation.

Scene 4 (11.2–14.0s): STOP presses, TAKEOVER opens, and the leader route becomes solid again; “RELEASE BEFORE LEADER CONTROL” holds beside the now-neutral robot.

## Frame 6 — Cloud at the edge

- status: animated
- src: compositions/frames/06-cloud-boundary.html
- duration: 21.211s
- transition_in: push-slide LEFT
- scene: A deployment map pins USB, cameras, watchdog, and 30 Hz loop to the Pi; Access and Tunnel form a guarded path; Vercel, Workers, and Pages receive only static docs.
- voiceover: "Deployment preserves that boundary. Systemd keeps the owner loop beside USB and cameras. Cloudflare Access and an outbound Tunnel can protect the cached dashboard. Vercel, Workers, or GitHub Pages host the guide—not the motor loop. Serverless has no serial bus and no real-time guarantee."
- type: benefit_highlight
- persuasion: Boundary contrast + causal chain
- beat: Foresight and resolve
- blueprint: grid-card-assemble

**narrativeRole:** Makes the safe hosting model memorable and prevents a misleading serverless deployment claim.

**keyMessage:** Put authenticated reach at the edge while control remains physically local.

- focal: three-zone deployment boundary map
- roles: Pi hardware zone = foreground subject · Access/Tunnel path = supporting bridge · static host zone = supporting contrast · boundary rules and port labels = background metadata
- sfx: boundary-draw, tunnel-whoosh

Adapt `grid-card-assemble`: keep the ordered assembly signature but use unequal zones so the Pi remains visually dominant.

Scene 1 (0.0–3.0s): PI / ROBOT PLANE rises as one large left card containing USB, CAMERAS, WATCHDOG, and 30 HZ — asymmetric 60/40, short-path card assembly.

Scene 2 (3.0–7.0s): CLOUDFLARE ACCESS and TUNNEL tiles seat between operator and Pi; an outbound arrow draws from the Pi and a deny-by-default gate closes behind it — causal chain, path draw.

Scene 3 (7.0–10.3s): VERCEL, WORKERS, and PAGES form a smaller right-side STATIC DOCS strip; a USB plug icon approaches and is rejected at the zone boundary.

Scene 4 (10.3–13.0s): “REACH AT THE EDGE / CONTROL AT THE ROBOT” spans the top; the Pi card remains saturated while cloud cards reduce to outlined support and hold.

## Frame 7 — Open, inspectable, stoppable

- status: animated
- src: compositions/frames/07-open-stoppable.html
- duration: 17.842s
- transition_in: blur-crossfade
- scene: Repository files assemble into an open-source lockup, a short demo command types in, and the final frame holds a physical cutoff symbol beside the URL.
- voiceover: "The complete stack—Python host, dashboard, 3D assets, iOS client, deployment templates, tests, licenses, and this guide—is open under Apache Two. Run the demo, inspect every boundary, then test lifted with a physical power cutoff in reach."
- type: cta
- persuasion: Distillation + concrete next action
- beat: Resolve and confidence
- blueprint: prompt-type-submit-generate

**narrativeRole:** Closes on inspectability and a safe first action instead of a vague product slogan.

**keyMessage:** Open source enables verification; safe operation still requires physical supervision and cutoff.

- focal: install command and physical cutoff pairing
- roles: repository file stack = supporting proof · terminal command = foreground subject · cutoff symbol = co-focal safety anchor · URL and license = background metadata
- sfx: file-stack, key-ticks, physical-switch

Adapt `prompt-type-submit-generate`: keep the terminal-pill typing signature; remove generated-output theater because the typed demo command is the action.

Scene 1 (0.0–3.0s): Python, dashboard, URDF, iOS, deploy, tests, LICENSE, and guide file tabs assemble into a compact repository stack at left as the inventory is spoken — asymmetric 45/55, staggered short-path assembly.

Scene 2 (3.0–6.6s): A terminal pill stretches across the upper center and types `uv run --extra lekiwi lerobot-lekiwi-diagnostics --demo`; the caret advances character by character while APACHE-2.0 stamps below.

Scene 3 (6.6–10.0s): The terminal shifts slightly left; a large physical cutoff symbol seats at right with “LIFTED FIRST” and the repository URL beneath. The caret blinks; every other element holds still through the final word.
