# Advisor avatars

Each advisor is a small glossy robot: the D01-r03 cast from the Figma file, ported
from its SVG generator. One `Robot` component draws any advisor at any size from a
JSON appearance config the user can change and the browser keeps.

```tsx
import { Robot } from "@/avatars/Robot"

<Robot advisor="cio" size={64} state="thinking" />
```

## `Robot` props

| Prop | Type | Default | Meaning |
|---|---|---|---|
| `advisor` | `AdvisorId` | required | Which robot: `cio`, `cfo`, `planner`, `tax`, `research`, `diligence`, `scout`, `macro`, `options`, `technicals`, `risk`, `realestate`, `ventures`. Use `advisorIdFor(skillName)` to map skill names (`plan` is the planner); it returns `null` for skills without a robot. |
| `size` | `number` | `64` | Width and height in pixels. At 40 or less the blur filters and the screen sheen are left out, and the eye glow becomes a solid lighter circle, so small robots stay crisp. |
| `appearance` | `Appearance` | the stored look | Draws this look instead of the stored one. The customize preview passes its draft here. Without it the robot reads `fo.avatar.v1.<advisor>` and re-renders whenever that look is saved or reset. |
| `state` | `RobotState` | `"idle"` | The pose: `idle`, `thinking`, `reading`, `writing`, `speaking`, `done`, `error`, `sleeping`. `stateFromRun` in `states.ts` picks it from a run. |
| `live` | `boolean` | `false` | Animates the state (see States and animation). Without it, and always under `prefers-reduced-motion: reduce`, the robot is its static pose. |
| `speed` | `number` | the look's `speed` | Animation speed multiplier, 0 to 2. 0 pauses the animation. |
| `level` | `number` | `0` | Speaking amplitude, 0 to 1, from `useSpeakingLevel`; it opens the mouth while speaking. |
| `className` | `string` | none | Passed to the `<svg>`. |

The `<svg>` has `role="img"` and `aria-label="<Advisor name> <state>"`, for example
"Real estate thinking". It carries `data-advisor`, `data-state`, `data-live` (`"true"`
only while it animates) and `data-finish`, and the speed as the CSS custom property
`--fo-avatar-speed`. Its
background is transparent. Groups are named for animation: `data-part` is `head`,
`ears`, `antenna`, `eyes`, `mouth`, `details` or `sleep`, and the lighting layers
carry `data-layer` (`shadow`, `shell`, `specular`, `rim`, `screen`, `sheen`,
`glow`). The two contact-shadow ellipses carry `data-shadow` (`soft`, `core`);
`animations.css` deepens them inside `.dark`, where a 9% black shadow would vanish.

## Appearance

```ts
type Appearance = {
  version: 1
  shape: Shape
  shell: string // #RRGGBB
  trim: "steel" | "silver" | "brass" | "copper" | "black" | string
  screen: "tinted" | "white" | "mint" | "amber" | string
  finish: "gloss" | "matte"
  antenna: "none" | "ball" | "compass" | "flag" | "periscope" | "twin"
  accessory: boolean
  eyes: "pill" | "dot" | "square" | "ring" | "bar"
  speed: number // 0 to 2
}
```

The CIO's default, as stored:

```json
{
  "version": 1,
  "shape": "cio",
  "shell": "#2F5BD3",
  "trim": "steel",
  "screen": "tinted",
  "finish": "gloss",
  "antenna": "compass",
  "accessory": true,
  "eyes": "pill",
  "speed": 1
}
```

| Option | Values |
|---|---|
| `shape` | Each advisor's own silhouette (the thirteen ids above) plus `rounded`, `square`, `capsule`, `circle`, `hexagon`, `dome`, `wide`, `house`, `rocket`. A shape owns the head, the screen, eye positions, ears and molded details. |
| `shell` | Any `#RRGGBB`. `SWATCHES` lists the fourteen cast colours: Cobalt, Sky, Teal, Green, Olive, Gold, Orange, Coral, Red, Pink, Purple, Indigo, Slate, Graphite. Real estate's default, Terracotta `#C8743E`, is not a swatch. |
| `trim` | A metal from `TRIMS` or a custom hex. Trim paints ears, bolts, rims, lens bezels and antenna stems with a vertical gradient (steel runs `#EEF1F5` to `#98A2B0`). |
| `screen` | The eye glow. `tinted` is mint on dark shells (luminance under 0.25) and otherwise the shell mixed 62% toward white; `white`, `mint` and `amber` are fixed (`SCREENS`); a hex sets it directly. |
| `finish` | `gloss` draws the specular highlight and rim light; `matte` leaves both out and flattens the shell gradient. |
| `antenna` | Drawn behind the head from the shape's mount point. Defaults: CIO compass, Planner flag, Scout periscope, Options twin, Research and Macro ball, others none. On a tall head an antenna slides down behind it rather than leave the viewBox. |
| `accessory` | The advisor's role piece: CFO coin slot and crank, Tax eyeshade and pencil, Research camera-lens rim, Diligence glasses and check badge, Scout binocular lenses, Macro planet ring, Options two-tone eyes, Technicals headset and screen chart, Risk helmet crest, Real estate chimney and window, Ventures fins, nose light and porthole rim. The CIO, Planner and Scout's signature pieces are their antennas, so for the CIO and Planner this switch changes nothing. Accessories follow the advisor onto any shape: rims, lenses and glasses are sized from the chosen screen and eyes, the rest are mapped from the home silhouette's head box. |
| `eyes` | The eye style. Every style has a pose for every state and is scaled down when the chosen screen is too small for it. |
| `speed` | Animation speed multiplier, clamped to 0 to 2. |

`defaultAppearance(id)` gives an advisor's own look. `parseAppearance(value, id)`
accepts an object or its JSON text, ignores unknown fields, and replaces each missing
or invalid field with the default; a config with another `version` yields the
default. `serializeAppearance` writes JSON with a fixed key order and `isDefault`
compares against the default. `mix(a, b, t)`, `luminance(hex)`, `glowColors` and
`trimColors` are the colour helpers the renderer uses.

## Persistence

`store.ts` keeps one look per advisor in `localStorage` under
`fo.avatar.v1.<advisorId>`; the server is never written to. `loadAppearance`,
`saveAppearance` and `resetAppearance` wrap every storage access in `try`/`catch`:
blocked or corrupted storage gives the default look, and a save that storage refuses
returns `false`. `subscribe(advisorId, listener)` notifies on save and reset (and on
a save in another tab), and `useAppearance(advisorId)` builds on
`useSyncExternalStore`, so every mounted robot for an advisor updates together.

## States and animation

`states.ts` maps a run and the events the app has received to a state with
`stateFromRun(run, events, { serverReachable })`, a pure function:

| Condition | State |
|---|---|
| The server is unreachable | `sleeping` |
| No run, or a finished run older than 8 s | `idle` |
| `queued` or `verifying`, or `running` with no tool call yet in this turn | `thinking` |
| The latest call is an `fo` command or a Read, Grep or Glob | `reading` |
| The latest call is `fo report write`, or a Write or Edit under `reports/` | `writing` |
| A top-level `delta` arrived within the last 1.5 s | `speaking` |
| `completed` | `done` |
| `failed` | `error` |
| `cancelled`, `partial` or `awaiting_input` | `idle` |

A turn starts at the latest `user` event, and a `status` event in the stream wins over
the run record. `useAvatarState` wraps the function and re-renders when a window closes.
`useSpeakingLevel(events)` turns each new delta into an amplitude (longer deltas raise it
higher) that decays to zero over 300 ms on animation frames; it stays 0 under reduced
motion. `useReducedMotion()` reads the media query.

`animations.css`, imported by `Robot.tsx`, holds the keyframes. A live robot gets the
classes `fo-avatar-live` and `fo-avatar-<state>` (and `fo-avatar-paused` at speed 0),
and every rule sits inside `@media (prefers-reduced-motion: no-preference)`. Animations
move the `data-part` groups with the individual `translate`, `rotate` and `scale`
properties, so they compose with each other and with the groups' SVG transforms; every
duration is divided by `--fo-avatar-rate`. Idle blinks every 3 to 5 s and looks around
every 4 to 7 s, tilting the head 2 degrees, with a gentle bob; each instance's periods and
delays come from its id, so robots on one page blink out of step. Thinking drifts the eyes
up and right and pulses the three dots; reading sweeps a scan line (`data-anim="scan"`,
invisible when static) down the screen; writing fills the progress bar
(`data-anim="fill"`) and starts over; speaking scales the mouth by `--fo-avatar-level`
and jitters its bars; done bounces once; error shakes once into its tilted pose; sleeping
breathes and drifts its z's.

In the app, the advisor page header shows a live robot with its state named beneath it,
following the open conversation: the chat publishes its run and events through
`publishRun` in `components/advisor-avatar.tsx`. Each sidebar row shows a static 24 px
robot (sleeping while the server is unreachable) that turns live while that advisor has a
run in progress. Skills without a robot keep their icon.

## Playground and screenshots

`/playground/robots` (reachable by URL only; nothing in the app links to it) shows
every default at 24, 34, 64 and 160 px on a light and a dark panel, the eight states
for a chosen advisor at 120 px, six preset combinations, the live editor with Copy
JSON and a text area that applies a pasted config through `parseAppearance`, and both
customize UIs: the Mac inspector in a 320 px column showing Speaking, and the phone
sheet open in a 375 px frame. It needs no office and makes no API calls: it renders
outside the app shell with `OfflineAppData`, and the inspector gets fixed reads.

`?shot=<section>` renders one section (`defaults`, `states`, `combinations`, `editor`,
`customize`) with no page chrome on a white or `#111` background picked by
`&theme=light|dark`, and sets `data-ready="true"` on the section once fonts have
loaded; `&advisor=<id>` picks the states advisor. `npm run screenshots` (see
`app/README.md`) captures the set in `docs/explainers/robots/`.

## Rendering

The robots are SVG with painted lighting rather than real-time 3D (KTD16). A WebGL
renderer would add a large runtime to a bundle that ships inside the Python wheel,
needs a context per live instance while browsers allow only about sixteen and the
sidebar alone shows thirteen robots, and gets blurry at 24 px. SVG has no
dependencies, stays crisp at every size, and costs nothing to keep on the page when
static. What it cannot do is real light parallax as a head turns; idle motion moves
the eyes and tilts the head group instead.

The molded look is painted in layers, back to front: a contact shadow (a blurred
ellipse over a crisp one), ears and trim in the trim gradient, the antenna, the shell
with a vertical gradient (the shell lightened 42% toward white at the top, the shell
itself at 55%, darkened 20% at the base) and a faint dark outline, a radial specular
highlight offset to the upper left with the cast's glint, a rim-light stroke that
fades from the lit upper-left edge, the recessed screen (a dark vertical gradient, an
inner shadow from the top, a faint inner edge and a top sheen), the eyes as a blurred
glow duplicate at 85% opacity behind the crisp eyes, state extras along the bottom of
the screen, and last the accessory overlays. Every gradient and filter id is scoped
with `useId`, so any number of robots can share a page. Geometry lives in data:
silhouettes in `shapes.ts`, part colours, antennas, accessories and eye poses in
`parts.tsx`, lighting constants in `Robot.tsx`.
