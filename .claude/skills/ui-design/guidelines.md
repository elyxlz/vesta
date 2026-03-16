# Design Guidelines

Principles, rules, and craft details. Every new component, animation, or interaction must follow these.

## 1. Core Design Philosophy

Vesta is a warm, living companion — not a cold tool. Every design choice serves this:

- **Warm over cool**: brown-tinted grays (#1a1816, not #1a1a1a). Earthy, not sterile. Warm grays feel more natural and inviting; cool grays feel clinical.
- **Alive over static**: spring physics, breathing animations, parallax follow. The orb feels present.
- **Invisible until needed**: controls at low opacity, revealed on hover. Chrome disappears. Linear's philosophy: "invisible details."
- **Glass over solid**: translucent surfaces with backdrop blur. Depth through transparency, not heavy shadows.
- **Squircle over circle**: continuous curvature on every rounded element. A squircle has no discontinuous curvature jump — the eye detects this subconsciously.

## 2. Apple Human Interface Guidelines

### Touch/Click Targets
- **Minimum 44x44 points** for every interactive element. This equals ~1cm x 1cm physically.
- Between adjacent targets: minimum 8px spacing to prevent misclicks.
- Edge targets (near window borders): extend hit area to the edge — Fitts's Law says edge/corner targets have infinite depth, making them faster to hit.
- Nested targets: inner target must be clearly distinguishable from outer. Avoid nesting clickable inside clickable.
- Primary actions should be larger and closer to the user's natural pointer resting position.

### Navigation
- **Back button**: always top-left. Chevron icon pointing left. 44x44px minimum.
- Navigation transitions: push (slide) for drill-down, fade for lateral moves, modal (bottom-up) for interruptions.
- Every view must have an escape hatch (back button, Escape key, or click-outside-to-dismiss).
- Destructive items in menus: always at the bottom, always red, separated by a divider.
- Long-press on back button reveals navigation stack (iOS 14+ pattern — consider for breadcrumb tooltips).

### Window Chrome (Desktop) — Cross-Platform

Custom titlebar: 40px height. `decorations: false` in Tauri config. Draggable region excludes all interactive elements — use `window.startDragging()` in Tauri, not CSS `-webkit-app-region`.

#### macOS — Traffic Lights (left-aligned)
- **Order**: Close (red), Minimize (yellow), Fullscreen (green) — left to right.
- **Dot size**: 12px diameter. **Gap**: 8px between dots. **Offset**: 8px from left, vertically centered.
- **Colors (focused)**: Close `#ed6a5f` (border `#e24b41`), Minimize `#f6be50` (border `#e1a73e`), Fullscreen `#61c555` (border `#2dac2f`).
- **Colors (unfocused/inactive window)**: all three become uniform gray `#dddddd` (border `#d1d0d2`).
- **Glyphs**: hidden at rest. On hover of the **group** (not individual), all three show: × (close), − (minimize), ↗ (fullscreen). Glyph color: dark tints of each button color.
- **Press**: slightly darker shade of each color.
- **Close behavior**: on macOS, close should **hide** the window (app stays in dock), not quit. Quit is Cmd+Q.
- Consider using Tauri's `titleBarStyle: "overlay"` to get **native** traffic lights instead of custom — feels most native and handles edge cases (force touch, accessibility).

#### Linux — GNOME/KDE Style (right-aligned)
- **GNOME default**: only Close button, on the **right**. Ubuntu overrides to left (macOS-like).
- **KDE default**: Minimize, Maximize, Close — all on the right.
- **Style**: flat icon buttons (not colored dots). No background at rest, subtle highlight on hover. Icons: × (close), − (minimize), □ (maximize).
- **Hit targets**: ~24x24px within ~46px header bar.
- **Close behavior**: close = quit the app.

#### Windows — Caption Buttons (right-aligned)
- **Order**: Minimize, Maximize/Restore, Close — right side of title bar.
- **Style**: full-bleed backplate buttons (no border, fills title bar height). Icons use Segoe Fluent Icons.
- **Button width**: ~46px each. Height matches title bar (32px standard).
- **Hover**: Close gets red background (`#c42b1c`) with white icon. Minimize/Maximize get subtle gray highlight.
- **Close behavior**: close = quit the app.
- Consider using Tauri's `titleBarOverlay: true` for native caption buttons.

#### Implementation Strategy
- Use `@tauri-apps/plugin-os` to detect platform at runtime.
- Render platform-appropriate controls (dots on macOS, icons on Linux/Windows).
- Position: left on macOS, right on Linux/Windows.
- Active press: `scale(0.85)` on macOS dots, no scale on Windows/Linux buttons.

### Typography

#### Apple SF Pro Tracking Reference
Tracking varies inversely with size — large text gets tight, small text gets loose:

| Size | Tracking | Equivalent |
|------|----------|-----------|
| 34pt+ | +0.37-0.40 | +1.1% |
| 22pt | +0.35 | +1.6% |
| 17pt (body) | -0.41 | -2.4% |
| 15pt | -0.24 | -1.6% |
| 13pt | -0.08 | -0.6% |
| 11pt | +0.07 | +0.6% |
| 10pt | +0.12 | +1.2% |

#### Vesta's Typography Rules
- System font stack: Inter → -apple-system → BlinkMacSystemFont → system-ui → sans-serif.
- `-webkit-font-smoothing: antialiased` always.
- **Our tracking**: tight (-0.01 to -0.03em) for 16px+, generous (0.02-0.04em) for 11px. Follows Apple's inverse pattern.
- **Weight hierarchy**: 600 headings, 550 names/emphasis, 500 buttons, 450 status, 400 body, 300 logo mark.
- **Line heights**: 1.4 mono/code, 1.6 body text, 1.75 chat output. Apple's body ratio is ~1.29x (22/17); ours is more generous for scanability.
- **Line length**: 50-75 characters optimal (Baymard, NNGroup). Sweet spot: 66 chars. Our 380px window naturally constrains this.
- **Minimum readable size**: 10px (error details only). Never go below 10px. Body minimum: 12px.

### Color

#### Rules
- Never pure black (#000000) or pure white (#FFFFFF). Darkest: #1a1816. Lightest: #f0ece7.
- Dark mode backgrounds: warm dark gray (rgba(28,27,26,0.96)). Apple uses #000000 for OLED true black — we don't (no OLED displays in desktop).
- Dark mode text: cream (#e8e0d8), not white — reduces glare and halation effect.
- **60-30-10 rule**: 60% dominant (window bg), 30% secondary (cards, panels), 10% accent (status, CTAs).

#### Dark Mode Color Shifting (Apple's approach)
Apple's system colors don't just invert — they shift:
- Colors are **lightened and slightly shifted in hue** for dark backgrounds.
- Fully saturated colors vibrate on dark backgrounds — reduce saturation 10-20%.
- Gray scale **inverts its order**: light grays become dark grays and vice versa.
- Our approach: primary buttons flip entirely (dark bg → cream bg) to maintain contrast hierarchy. This is intentional, not just inversion.

#### Contrast Requirements
- WCAG AA minimum: 4.5:1 for normal text, 3:1 for large text (18pt+) and UI components.
- WCAG AAA recommended: 7:1 for optimal accessibility.
- System semantic colors automatically meet requirements in both modes.
- Test with Increase Contrast accessibility setting — increase border opacity, reduce transparency.

### Spring Animations

#### Apple's Spring Model (iOS 17+/SwiftUI)
Three presets, all default to 0.5s duration:

| Preset | Bounce | Character |
|--------|--------|-----------|
| `.smooth` | 0 | No overshoot, gradual deceleration |
| `.snappy` | 0 | Small bounce, crisp feel |
| `.bouncy` | 0 | Higher bounce, playful feel |

- `bounce` range: -1.0 to 1.0. 0 = critically damped. 0.15 = slightly brisk. 0.3 = noticeably bouncy. >0.4 = too much for UI.
- Traditional: damping 15, stiffness 170. dampingFraction 0.75 = balanced default.

#### Our Spring Values
```css
--spring: cubic-bezier(0.16, 1, 0.3, 1);        /* ~smooth: layout transitions */
--spring-bouncy: cubic-bezier(0.34, 1.56, 0.64, 1); /* ~bouncy: interactive feedback */
--spring-snappy: cubic-bezier(0.2, 0, 0, 1);     /* ~snappy: fast utility */
```

#### Duration Rules
| Context | Duration | Easing |
|---------|----------|--------|
| Button press feedback | 0.15-0.2s | `--spring-bouncy` |
| Tooltip show/hide | 0.12s | ease |
| Menu entrance | 0.15s | `--spring` |
| Panel entrance | 0.35s | `--spring` |
| View entrance | 0.6s | `--spring` |
| State change (orb) | 0.8s | `--spring` |
| Exit animations | ~200ms | (faster than entrance) |
| Entrance animations | ~300ms | (slower than exit) |

- **Exit faster than entrance**: users care about what's arriving, not what's leaving.
- **Interruptible**: new animation takes over mid-flight, preserving velocity.
- **Never linear easing**: constant velocity doesn't exist in nature. Always decelerate or spring.

### Accessibility
- `prefers-reduced-motion: reduce`: disable ALL continuous/decorative animations (float, breathe, pulse, dot-pulse). Replace slide transitions with cross-dissolves. Keep instant state changes (opacity, color).
- `prefers-color-scheme: dark`: every component needs dark mode overrides. No exceptions.
- `prefers-contrast: more`: not yet implemented — plan for it. Increase border opacity to 0.2+, reduce transparency, increase text contrast.
- Focus indicators: `:focus-visible` outline removed globally — any NEW focusable element must add a visible focus style (box-shadow ring, not outline).
- ARIA: `aria-label` on every icon-only button. `role="group"` for control clusters. `inert` on hidden/inactive panels.
- Bold text accessibility: if a user enables bold text system-wide, ensure text doesn't overflow its container.

## 3. Response Time Psychology

### Nielsen's Three Limits (foundation for all timing decisions)

| Threshold | User Perception | Required Feedback |
|-----------|----------------|-------------------|
| **100ms** | Feels instantaneous. User feels they caused the outcome. | None — just show the result |
| **1000ms** | Flow of thought stays seamless. User senses delay but feels in control. | Cursor change or subtle indicator |
| **10s** | Attention limit. User starts thinking about other things. | Progress indicator + ability to cancel |

### Doherty Threshold (400ms)
Below 400ms the brain stays in action mode. Above it, the brain switches to wait mode. Productivity soars when response stays under 400ms (IBM Systems Journal, 1982). Every interaction in our app should complete or show meaningful feedback within 400ms.

### AI-Specific Timing
- **Time to first token (TTFT)**: must be under 500ms for chat to feel responsive; under 100ms for code completion.
- **Streaming is baseline**: users watching tokens arrive in real-time. Waiting until completion feels broken.
- Show "thinking..." indicator almost immediately — those first moments carry disproportionate psychological weight.
- Consistent response times produce greater satisfaction than variable ones. Slightly slower but predictable beats occasional fast + long delays.

## 4. Interaction Patterns

### Hover, Press, Active
- **Hover**: lift element (`translateY(-1px)` for buttons, `-2px` for cards) + add shadow. Increase opacity/color brightness.
- **Active/Press**: squish (`scale(0.97)` for standard, `scale(0.85)` for window controls) + remove shadow. Must trigger within 100ms (Nielsen's instantaneous threshold).
- **Transition**: 0.15-0.2s with `--spring-bouncy` for interactive elements. Never linear.
- All buttons follow: transparent bg → subtle highlight on hover → press feedback on active.

### View Transitions
- **Pattern**: fade out current (0.15s, opacity→0) → swap content → fade in new (0.5s, opacity→1).
- Implementation: `setView()` sets `transitioning=true`, waits 150ms, changes state, sets `transitioning=false`.
- New views animate in with `viewIn` (0.6s, scale 0.97→1 + fade) or `panelIn` (0.35s, fade).
- Initial app load: 400ms delay before checking state (lets window render settle).
- Under `prefers-reduced-motion`: replace slides with cross-dissolves.

### Tooltips
- Trigger: `data-tip` attribute on any element. Global pointer-tracking system.
- **Show immediately** — our tooltips follow the cursor, no hover delay. (Standard guideline is 300-500ms delay, but cursor-tracking tooltips are different from stationary ones.)
- Position: centered above cursor, clamped 40px from window edges.
- Appearance: 11px, weight 450, dark bg with blur(8px) backdrop, 0.12s fade transition.
- `pointer-events: none` — tooltip never intercepts clicks.
- RAF-throttled position updates to prevent excessive DOM writes.

### Menus & Dropdowns
- Position: above the trigger button (`bottom: calc(100% + 6px)`), right-aligned.
- Entrance: `menuIn` animation (0.15s, translateY 4px + scale 0.96→1).
- Dismiss: click outside OR Escape key. Both clear the menu and any confirm state.
- Glass surface: translucent bg + blur(16px) + subtle border.
- Items: 8px 12px padding, 6px squircle radius, 0.12s hover transition.
- **Destructive items: red text, red-tinted hover bg. Always last in the menu, separated visually.**
- Keyboard navigation: support arrow keys and Enter within menus (not yet implemented — plan for it).

### Destructive Actions
- **Two-step inline confirmation**: first click shows "confirm" + "cancel" buttons. No modal dialogs.
- This is better than modals for non-critical destructive actions — doesn't interrupt flow (Smashing Magazine).
- For truly irreversible actions (account deletion): consider type-to-confirm pattern (GitHub's "type the repo name").
- Confirm button: red (danger) styling. Cancel button: muted styling.
- Both buttons disable during operation (`pointer-events: none`, `opacity: 0.25`).
- Visual feedback: orb shrinks + fades during deletion (0.6s). Irreversible feel.
- Never auto-dismiss the confirmation — user must explicitly confirm or cancel.
- **Never place destructive options adjacent to benign options** without clear visual separation (NNGroup proximity principle).
- **Don't rely solely on red**: ~8% of men are color blind. Always pair red with icons, text labels, and positional cues.

### Error Display
- Error text: 12px, weight 450, red (#c45450 light / #e07070 dark).
- Shake animation on appear (±3px, 0.3s) — catches eye without being aggressive.
- Expandable raw details: "show details" toggle → `<pre>` block (10px monospace, max-height 150px, scrollable).
- Error persists until user retries or navigates away. **Never auto-dismiss errors** — toasts are poor for errors (users don't finish reading before they disappear, and they're positioned far from the problem).
- Error formatting: `formatError()` maps technical messages to human-friendly explanations.
- **Error severity levels**: success (green), info (blue), warning (amber), error (red). We currently only use error — expand if needed.

### Empty States
- Structure: headline → secondary explanation → CTA (if applicable).
- Three pulsing dots (4px, staggered 0.2s delay) + descriptive label.
- Label: 12px, very dim color, lowercase.
- Centered vertically and horizontally in the container.
- Context-specific messages: "connecting...", "streaming logs...", "[name] is listening. say something."
- Well-designed empty states increase retention by up to 50% when personalized (UX research).

### Loading / Progress
- **< 1s**: no indicator needed.
- **1-10s**: indeterminate progress bar (our thin 2px bar pattern).
- **> 10s**: progress bar + rotating descriptive messages (our onboarding pattern).
- Our bar: 2px track, 35% fill, slides left-to-right over 1.8s. Max-width: 280px.
- Rotating messages cycle every 3s. Messages are specific: "preparing email & calendar...", "loading browser & research tools..."
- Message entrance: `msgIn` animation (0.4s, translateY 4px + fade).
- **Never use spinners** — they create uncertainty (no time estimate). Progress bars + text reduce abandonment by up to 30%.
- Users who see an animated progress indicator wait 3x longer before clicking away (University of Nebraska-Lincoln).

### Inline Validation
- **Validate on blur** (when user leaves a field), not during typing. Real-time keystroke validation decreases completion by 8-12% due to anxiety (Baymard).
- Inline validation produces: 22% increase in success rates, 22% decrease in errors, 31% increase in satisfaction, 42% decrease in completion times (Luke Wroblewski study).
- Never show errors on empty fields that haven't been interacted with yet.
- Remove error messages as soon as the input is corrected.

## 5. Real-Time / WebSocket UX

### Connection States
- **Connected**: green dot (6px) with glow shadow. Solid, confident.
- **Thinking**: amber dot with glow. 0.4s spring color transition.
- **Disconnected**: gray dot, no glow. Only shown after **2s debounce** (prevents flicker on brief hiccups). Research supports delaying "offline" banners by at least a few seconds to suppress transient interruptions.
- **Reconnecting**: golden bar slides down from topbar ("reconnecting..." text, 0.2s expand). Tell users both state AND what actions they can still take.

### Reconnection Strategy
- Initial delay: 1000ms. Exponential backoff: doubles each attempt, max 30000ms.
- Reset to base delay on successful connect or explicit `resetReconnect()`.
- Visual: reconnect bar appears after 2s disconnect. No user action needed — auto-reconnects.
- Implement heartbeat/ping to detect dead connections faster than TCP timeouts.

### Scroll Pinning (Chat/Logs)
- Auto-scroll to bottom when user is within 40px of bottom.
- If user scrolled up manually: respect their position, don't force scroll.
- Show a **"New messages" pill** when new messages arrive while user is scrolled up (not yet implemented — plan for it).
- On new content: `await tick()` before scrolling (let DOM update first).
- Max 5000 messages in memory. Older messages silently pruned.

### Message Deduplication
- Track pending outgoing messages in `Map<string, count>`.
- When server echoes back: decrement count, skip rendering the duplicate.
- Optimistic UI: show user's message immediately with local timestamp.
- Optimistic items should be visually subtle (our pattern: same styling, no dimming — since chat messages almost always succeed).

### Animation Suppression
- On initial history load: suppress `lineIn` animations (`suppressAnim` flag).
- Re-enable after first `requestAnimationFrame`. Prevents 500+ lines all animating at once.
- **When NOT to animate**: repeated/high-frequency actions, bulk operations, keyboard navigation (tab focus must be instant), and under `prefers-reduced-motion`.

## 6. Visual Craft Details

### Shadows
- **Multi-layer technique**: ambient (large, soft, omnidirectional) + key (smaller, darker, directional from above) + contact (thin, darkest at base).
- **Never pure black shadows**: tint with the surface color. `hsl(var(--shadow-color) / opacity)` approach. Our shadows use `rgba(0,0,0,...)` but with low opacity so the warm background bleeds through.
- **Elevation states**: hover adds shadow (floating), active removes it (pressed). Resting state has minimal or no shadow.
- **Window shadow**: 3 layers — 0.5px ring (structural) + 40px ambient (depth) + 12px key light (direction).
- Animate `box-shadow` over 0.2s. Use `will-change: box-shadow` for performance-critical elements.
- **Josh Comeau's elevation scale**: Low (3 layers, 0.7-2.5px), Medium (4 layers, 0.7-12.6px), High (6+ layers, 0.7-62.9px). Opacity per layer: 8-20%.

### Glass Morphism
- **Blur by context**: 8px for tooltips (subtle frost), 16px for menus/dropdowns (heavy frost, content behind is abstract).
- **Background opacity**: 0.85-0.96 for readable surfaces, 0.02-0.08 for subtle tints (input bar).
- **Border treatment**: 1px rgba border (0.06-0.08 opacity) reinforces the glass edge. Light mode needs stronger boundaries (light-on-light flattens).
- **Limit glass elements**: max 3-5 per viewport for 60fps. `backdrop-filter` is GPU-accelerated but expensive when layered.
- Use `@supports (backdrop-filter: blur())` for progressive enhancement.
- **When glass helps**: layered navigation, overlays where context behind matters, creating visual hierarchy.
- **When glass hurts**: monochrome/flat backgrounds (nothing to see through), overuse (>5 elements), when readability is critical.

### Squircles
- CSS `corner-shape: squircle` on every rounded element. Falls back to regular `border-radius` gracefully.
- **Why**: a rounded rectangle has **discontinuous curvature** — curvature jumps from 0 (flat) to 1/r (corner) abruptly. A squircle has **continuous curvature** — smooth transition. The eye detects this subconsciously.
- **The math**: superellipse `|x/a|^n + |y/b|^n = 1`. n=2 is a circle, n=4 is a classic squircle, n≈5 is Apple's icon shape.
- **Radius scaling**: radius scales with element size. 12px for large surfaces (window, cards), 8px for buttons/inputs, 6px for menu items, 4px for small controls.
- **Nested squircles**: inner radius = outer radius - gap. Menu (10px) → menu items (6px) with 4px padding. Apple's app icon radius: 23.1% of icon width.

### Borders
- **Prefer spacing or shadows over borders**. Borders are the last resort (Refactoring UI: "Use fewer borders. Try box shadows, contrasting backgrounds, or more space instead.").
- **Opacity ranges**: 0.05-0.08 for ghost dividers, 0.08-0.12 for structural, 0.15+ for interactive elements.
- Always use `rgba()` so borders adapt to light/dark mode automatically.
- 1px solid for all borders.

### Color Science
- **Warm grays**: all neutrals have a brown/amber undertone. Adding even slight saturation to grays (vs pure neutral) makes designs feel more polished.
- **60-30-10 rule**: 60% dominant (window bg), 30% secondary (cards, panels), 10% accent (status colors, CTAs). Use the same accent color for all interactive elements to build pattern recognition.
- **Dark mode ≠ inversion**: dark mode uses different values, not inverted ones. Primary buttons flip (dark bg → cream bg) to maintain contrast hierarchy.
- **Perceived brightness**: yellow appears lightest, blue appears darkest at the same HSL lightness. Adjust luminance per hue for visual consistency.
- **Cohesive palette**: keep saturation consistent across colors, vary hue and lightness. Our neutrals all share the same warm undertone.

### Icons
- **Stroke weight**: 1.8px for 24px viewBox icons (our standard). Keep weight identical across the entire set.
- **Line caps/joins**: always round (`stroke-linecap="round" stroke-linejoin="round"`). Matches warm, friendly aesthetic. Never mix cap styles within a set.
- **Optical correction**: circles need to be ~2-3% larger than squares to appear the same size. Triangles/pointed shapes extend beyond the grid boundary.
- **Rendered size**: 15x15px navigation, 14x14px inline, 20x20px prominent. Larger decorative: 36x36px, 40x40px (use stroke-width 1.5 at these sizes).
- **Color inheritance**: always `fill="none" stroke="currentColor"`.
- **Fill vs stroke convention**: outline = inactive/default, filled = active/selected (common in tab bars — consider if we add navigation tabs).

### Spacing
- **4px base grid**: all spacing values are multiples of 4 (4, 8, 12, 16, 20, 24, 28, 32, 40).
- **Internal < external**: padding within a component must be less than margin between components (Gestalt proximity — related items are closer together).
- **Padding ratio**: vertical padding ≈ 0.5-0.75x font size, horizontal ≈ 1-1.5x font size. Larger text needs proportionally less padding.
- **Consistent gaps**: 8px between related items (buttons in a row), 12px between sections, 20px for major separations.
- **Optical vs mathematical alignment**: text often needs +1-2px vertical offset because the visual center differs from the bounding box center. Always check alignment visually.

### Animation Craft
- **Why linear looks robotic**: constant velocity doesn't exist in nature. Everything accelerates and decelerates.
- **Follow-through** (Disney principle 8): elements overshoot their target slightly, then settle back. Creates organic, physical feeling. Our `--spring-bouncy` does this.
- **Staggered animations**: optimal delay between items is 30-50ms (creates a wave without feeling slow). Our dot-pulse uses 200ms stagger — appropriate for 3 items.
- **Exit faster than entrance**: exit ~200ms, enter ~300ms. Exits use acceleration (ease-in); entrances use deceleration (ease-out).
- **When NOT to animate**: repeated/high-frequency actions, bulk operations, keyboard navigation, under `prefers-reduced-motion`. Animation must be purposeful — if it interrupts flow, remove it.

## 7. Onboarding

### Apple's Onboarding Rules
- Apps should be usable immediately. Onboarding should be minimal and optional.
- Maximum 3 screens for welcome flow. Every screen must have a skip option.
- Defer sign-in until the user needs it. Don't gate the app behind login on first launch.
- Show the actual app interface, not abstract illustrations.
- Request permissions at the moment the feature is used, not upfront. Apps that defer permissions see 28% higher grant rates.

### Research-Backed Numbers
- **3-5 steps** see the best activation rates. Over 5 steps: 72% abandon.
- **Time to first value**: 72% say completing onboarding in under 1 minute is important. Reducing TTV by 30% yields 15-25% increase in conversion (Intercom).
- **Only 12%** of users rate their onboarding as "effective" — the bar is low, do it well.
- Over 30% of onboarding steps are unnecessary and can be removed.

### Our Flow
- **Steps**: platform check → name → creating → auth → done. Linear, no branching.
- Each step slides in with `fadeSlideIn` (0.5s, translateY 10px + fade).
- Between steps: 0.15s fade transition (dims to 0.7 opacity, swaps, fades back).
- **Cancel/back available** at every step. Cancel returns to name step, clears all state.
- Cancel should not destroy entered data — preserve form state.
- Back button should return to previous step with data preserved (59% of sites violate back-button expectations — Baymard).

### Name Input
- Centered text, 14px, squircle border.
- Focus ring: 3px box-shadow (brown-tinted, not blue).
- Live normalization preview below: shows how the name will be transformed.
- Preview only shows if different from typed input.
- Never use placeholder as label — placeholders disappear on focus. We use a placeholder ("e.g. jarvis") alongside a heading, which is acceptable.

### Progress Communication
- Rotating messages every 3s during creation: gives sense of progress without real metrics.
- Messages are specific: "preparing email & calendar...", "loading browser & research tools..."
- Indeterminate progress bar above messages.
- Users who see animated progress wait 3x longer before abandoning.

### Error Recovery
- Errors during creation: show error + "try again" button, return to name step.
- Errors during auth: show error + "retry" button, stay on auth step.
- All errors show human-friendly message with optional "show details" toggle for the raw error.
- Help users "recognize, diagnose, and recover from errors" (Nielsen heuristic).

### Completion
- Green checkmark icon with `popIn` animation (0.4s, scale 0.5→1, spring-bouncy).
- "[name] is ready" heading + "say hi." subtext + "continue" button.
- "continue" returns to grid view where the new agent card appears.

## 8. The Orb (Agent Status Visualization)

The orb is Vesta's signature UI element — a living entity that communicates state through color, motion, and reactivity.

### Parallax Follow
- LERP factor: 0.015 (1.5% per frame toward cursor position). Creates smooth, organic lag.
- Snap threshold: 0.5px — when close enough, snap to exact position.
- Movement range: ±14px from center.
- On pointer leave: 150ms delay before resetting to center (prevents jitter).
- RAF loop: runs only while moving, cancels when snapped (performance).

### State Machine
| State | Color | Float Speed | Breathe Speed | Glow |
|-------|-------|-------------|---------------|------|
| Alive (idle) | Green | 4s | 3s | Pulse 3s |
| Thinking | Amber | 2s | 1.2s | Pulse 1.2s |
| Tool use | Amber | 2s | 1.2s | Pulse 1.2s |
| Booting | Pale green | 3s | 2s | Swell 1.5s |
| Auth | Blue | 3s | 2s | Pulse 2s |
| Stopping | → Gray | — | Wind-down 0.8s | Fade 0.5s |
| Starting | → Green | — | Wake-up 0.8s | Swell 0.8s |
| Deleting | → Gone | — | Shrink 0.6s | Fade 0.4s |
| Dead | Gray | — | Static (scale 0.92) | Dim (0.15) |

Design rationale: thinking/tool_use animations are 2-2.5x faster than idle — communicates increased activity. Blue for auth = "waiting on external action." Gray = no life.

### Anatomy
- Container: 140x140px. `will-change: transform` (GPU compositing).
- Body: 100x100px circle (inset 20px). Radial gradient with highlight at 38%, 32% (upper-left light source).
- Highlight: ellipse at top-left (18% top, 28% left), 28%x20%, white radial gradient, blur(2px). Simulates specular reflection.
- Glow: extends 5px beyond body, blur(18px), colored radial gradient. Creates atmospheric halo.
- Ring: inset 14px from container, 1px white at 0.08 opacity. Subtle structural definition.
- Ambient: extends 30px beyond container, very faint colored halo (0.08 opacity). Environmental light spill.

## 9. View Transition Flashing (Known Issues)

The app has several sources of visual flashing during view transitions. These must be considered when modifying transition logic.

### Root Causes

1. **`setView` timing mismatch**: The 150ms `setTimeout` in `setView()` doesn't perfectly sync with the 0.15s CSS transition on `main.transitioning`. The component swap happens at T=150ms while the CSS fade-out may still be in-flight.

2. **Window background transition lag**: The `.window` background transitions over 0.35s (light↔dark), but the content swaps at 150ms. The background is mid-transition when new content appears, creating a color flash — especially visible on grid↔chat/console transitions.

3. **Nested opacity animations**: The `main` container fades in (0.5s) while child views also have entrance animations (`viewIn` 0.6s, `panelIn` 0.35s). This double-fading can appear as flicker. The `panelIn` animation is effectively redundant with the parent fade.

4. **Empty state flash on mount**: Both GridView and Chat render with empty data (`agents = []`, `lines = []`) before their async `onMount` calls complete. The grid shows blank before populating; chat shows "connecting..." before WebSocket handshake + history load.

5. **WebSocket `onopen` clears messages**: `_messages.set([])` in ws.ts creates a blank frame before the server sends the history event.

6. **Opacity transition duration switch**: If `setView` is called while `main` is still fading in (0.5s), the `main.transitioning` class switches the transition to 0.15s mid-animation, causing a visual jump.

### Affected Transitions

| Transition | Issues |
|-----------|--------|
| Grid → Chat/Console | Background flash (light→dark), WebSocket empty state |
| Chat/Console → Grid/AgentView | Background flash (dark→light), empty grid |
| Grid → AgentView | Status default values until API responds |
| Any → Any | 150ms/CSS timing mismatch, nested opacity |

### Rules for New Transitions

- Never change transition duration mid-animation
- Ensure background color transition completes before or simultaneously with content swap
- Pre-fetch data before transitioning when possible (or carry previous state)
- Avoid redundant entrance animations on children when parent is already fading in
- Test every transition path: grid↔agent-home↔chat↔console, and back

## 10. Cross-Platform Native Feel

### Platform Detection
- Use `@tauri-apps/plugin-os` (`platform()` returns `"macos"`, `"linux"`, `"windows"`).
- Detect once at app startup, store in a reactive variable, pass to components as needed.
- Current platform detection exists on the Rust backend via `platform-check` CLI command — but for UI-only decisions (window controls, shortcuts), detect in the frontend.

### Window Vibrancy (Already Implemented)
- **macOS**: `NSVisualEffectMaterial::HudWindow` via `window-vibrancy` crate.
- **Windows**: Mica (Win 11) with Acrylic fallback (Win 10).
- **Linux**: no vibrancy — standard window manager compositing.

### Scrollbars
- macOS has overlay scrollbars by default (appear on scroll, auto-hide). Our `::-webkit-scrollbar` overrides force always-visible thin scrollbars.
- This is acceptable for our 380px window — overlay scrollbars can be jarring in small views.
- Keep current approach: 6px track, transparent background, semi-transparent thumb.

### Keyboard Shortcuts
- macOS: Cmd (Meta) is the primary modifier. Cmd+Q = quit, Cmd+W = close window.
- Windows/Linux: Ctrl is the primary modifier. Alt+F4 = close, Ctrl+Q = quit (some apps).
- When adding shortcuts, check `e.metaKey` on macOS, `e.ctrlKey` on Windows/Linux.
- Escape is universal — use for back/dismiss on all platforms.

### Close vs Hide
- **macOS**: closing the window should hide it (app stays in dock). Quit is Cmd+Q. This is the native convention for document-less utility apps.
- **Windows/Linux**: close = quit is standard.
- Implementation: use Tauri's `on_close_requested` event with platform detection.

### State Initialization Anti-Pattern
- **Problem**: initializing `$state` with default values (e.g., `"idle"`, `false`) causes flash when the real value arrives from a store or API.
- **Fix**: use `get(store)` from `svelte/store` to read the current store value synchronously at initialization time.
- Example: `let agentStateVal = $state(get(connection.agentState))` instead of `$state("idle")`.
- This eliminates the one-frame gap between component mount and first `$effect` subscription callback.

## 11. Component Checklist

Before shipping any new UI:

1. Dark mode `@media (prefers-color-scheme: dark)` block with all color overrides
2. Reduced motion `@media (prefers-reduced-motion: reduce)` — disable continuous animations, replace slides with fades
3. All interactive elements ≥ 44x44px
4. `corner-shape: squircle` on every rounded element
5. Spring easing (`--spring-bouncy` for interactions, `--spring` for layout)
6. `rgba()` backgrounds, never solid hex
7. No pure black/white — use warm palette values from tokens.md
8. Hover: lift + shadow. Active: squish + no shadow
9. `data-tip="label"` on icon-only buttons
10. `user-select: none` on non-content elements
11. `aria-label` on icon-only buttons
12. Entrance animation (`viewIn`, `panelIn`, or `fadeSlideIn`)
13. Escape key dismisses the view (where appropriate)
14. Error states with shake + expandable details
15. Loading states with progress bar + descriptive message (no spinners)
16. Response feedback within 100ms (Nielsen's instantaneous threshold)
17. Test with Increase Contrast + Reduce Transparency accessibility settings
18. Initialize `$state` from store values with `get(store)`, never hardcoded defaults that cause flash
19. Test on all target platforms (macOS, Linux, Windows) for native feel
