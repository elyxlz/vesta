# Apple Human Interface Guidelines, distilled for the Vesta product critique

Distilled from developer.apple.com/design/human-interface-guidelines (fetched 2026-07-09).
Every bullet is a concrete, checkable rule; the citation names the HIG page it comes from.
Used by `.claude/workflows/product-critique.js`: each critique lens reads its assigned sections.
Vesta's intentional identity (the workflow's STYLE_GUARD) overrides the HIG where they conflict:
all-lowercase copy, no dash separators, the oklch palette, squircle radii. Apply these rules
within that identity; for example, HIG capitalization rules reduce to "pick one style and apply it
everywhere", which for Vesta is lowercase.

## Layout

- Group related items using negative space, background shapes, colors, materials, or separator lines; content and controls must remain clearly distinct from each other. (HIG: Layout)
- Give essential information the most space and make it visible right away; move nonessential or secondary details to another part of the window or an additional view. (HIG: Layout)
- Extend backgrounds, full-bleed artwork, and scrollable layouts to the very edges of the screen or window; controls and navigation (sidebars, tab bars) float above content, not on the same plane. (HIG: Layout)
- Place the most important items near the top and leading side (reading order); account for right-to-left languages. (HIG: Layout)
- Align components with one another; alignment plus indentation should communicate the information hierarchy and make content scannable. (HIG: Layout)
- Use progressive disclosure for large collections: partially show items or use disclosure controls to indicate hidden content exists. (HIG: Layout)
- Provide enough space around controls and group them in logical sections; unrelated controls placed too close together are hard to tell apart. (HIG: Layout)
- Respect system-defined safe areas and margins; the layout must adapt to screen sizes, orientations, resizable windows, Dynamic Type sizes, and locale (RTL, text length). (HIG: Layout)
- Test the largest and smallest layouts first; when artwork must adapt, scale it without changing its aspect ratio (never stretch). (HIG: Layout)
- Design for the full-size view first; as a window narrows, defer switching to a compact layout for as long as possible, and hide tertiary columns (e.g. inspectors) before restructuring. (HIG: Layout)
- On desktop, avoid placing controls or critical information at the bottom edge of a window; people often move windows so the bottom is offscreen. (HIG: Layout)
- Minimum touch control size: 44x44 pt default, 28x28 pt absolute minimum (macOS pointer targets: 28x28 pt default, 20x20 pt minimum); allow ~12 pt padding around bezeled controls and ~24 pt around borderless ones. (HIG: Accessibility)

## Typography

- Follow platform default and minimum text sizes: iOS/iPadOS 17 pt default, 11 pt minimum; macOS 13 pt default, 10 pt minimum; thin-weight custom fonts need sizes above these minimums. (HIG: Typography)
- Avoid Ultralight, Thin, and Light font weights; prefer Regular, Medium, Semibold, or Bold, especially at small sizes. (HIG: Typography)
- Convey hierarchy by adjusting font weight, size, and color; maintain the relative hierarchy and visual distinction when text sizes change. (HIG: Typography)
- Minimize the number of typefaces; mixing many typefaces obscures hierarchy and reads as inconsistent. (HIG: Typography)
- Use the built-in text-style scale; iOS at the default (Large) size: Large Title 34/41, Title 1 28/34, Title 2 22/28, Title 3 20/25, Headline 17 semibold, Body 17/22, Callout 16/21, Subhead 15/20, Footnote 13/18, Caption 1 12/16, Caption 2 11/13 (pt size/leading). (HIG: Typography)
- macOS text-style scale: Large Title 26/32, Title 1 22/26, Title 2 17/22, Title 3 15/20, Headline 13 bold, Body 13/16, Callout 12/15, Subheadline 11/14, Footnote 10/13, Caption 10/13. (HIG: Typography)
- Support user text-size adjustment (Dynamic Type); verify the layout works and text stays legible at every size, including accessibility sizes (Body scales 14 pt at xSmall up to 53 pt at AX5). (HIG: Typography)
- Keep truncation minimal as font size increases: aim to show as much useful text at the largest accessibility size as at the largest standard size; let labels wrap to multiple lines. (HIG: Typography)
- At large font sizes, switch inline layouts (glyph + text + timestamp) to stacked layouts and reduce the number of text columns. (HIG: Typography)
- Increase the size of meaningful interface icons as font size increases so glyphs keep pace with text. (HIG: Typography)
- Use loose leading for long passages and wide columns; use tight leading only for one or two lines in height-constrained spots, never for 3+ lines. (HIG: Typography)
- Custom fonts must meet the same legibility minimums and implement Dynamic Type and Bold Text behaviors that system fonts get automatically. (HIG: Typography)

## Color

- Never use the same color for different meanings; if a color signals interactivity, don't use it (or a similar color) to stylize noninteractive text. (HIG: Color)
- Every color must work in light, dark, and increased-contrast contexts; custom colors need light and dark variants plus an increased-contrast option for each. (HIG: Color)
- Never rely on color alone to differentiate objects, indicate interactivity, or convey essential information; add text labels or distinct glyph shapes. (HIG: Color)
- Meet minimum contrast: 4.5:1 for text up to 17 pt, 3:1 for text 18 pt and up or bold text (WCAG Level AA values used by Apple's Accessibility Inspector). (HIG: Accessibility)
- Don't hard-code system color values; use semantic color APIs, since actual values fluctuate between OS releases. (HIG: Color)
- Don't redefine semantic colors' meanings: never use a separator color as text or a secondary-label color as a background. (HIG: Color)
- Use the background hierarchy as designed: primary for the overall view, secondary for grouping within it, tertiary for grouping within secondary; foreground uses label/secondaryLabel/tertiaryLabel/quaternaryLabel plus placeholder, separator, and link colors. (HIG: Color)
- Apply accent color sparingly and reserve it for genuine emphasis (primary actions, status); don't color the backgrounds of multiple controls at once. (HIG: Color)
- Over colorful backgrounds or rich content, prefer monochromatic control labels or an accent with clearly sufficient differentiation; too much color hurts label legibility. (HIG: Color)
- Test the color scheme under varied lighting, devices, and color profiles (sRGB vs Display P3); provide per-color-space variants if similar P3 colors or gradients degrade on sRGB. (HIG: Color)
- Respect the user's chosen accent color where the platform offers one (macOS replaces the app accent with the user's selection). (HIG: Color)

## Dark Mode

- Don't offer an app-specific appearance setting; respect the systemwide light/dark preference. (HIG: Dark Mode)
- The app must look good in both appearances, including the Auto setting where the mode switches while the app is running. (HIG: Dark Mode)
- Dark palettes are not inversions: backgrounds get dimmer and foregrounds brighter; don't build dark mode by inverting light colors. (HIG: Dark Mode)
- Use semantic colors that adapt automatically; custom colors need explicit bright and dim variants, never hard-coded values. (HIG: Dark Mode)
- Keep contrast between colors no lower than 4.5:1; for custom foreground/background pairs strive for 7:1, especially in small text. (HIG: Dark Mode)
- Slightly darken content images that have white backgrounds to prevent them from glowing against dark surroundings. (HIG: Dark Mode)
- Use the same icon/image asset in both modes only if it truly works in both; otherwise provide separate light and dark assets (e.g. add a subtle outline only for the light variant). (HIG: Dark Mode)
- Use base vs elevated dark background sets to convey layering: elevated (brighter) backgrounds for foreground surfaces like modals and popovers, base (dimmer) for receding layers. (HIG: Dark Mode)
- Use system-provided label colors (primary through quaternary) and system text controls so text adapts and picks up vibrancy automatically. (HIG: Dark Mode)
- Test dark mode with Increase Contrast and Reduce Transparency turned on, separately and together; watch for dark-on-dark text. (HIG: Dark Mode)
- A permanently dark interface is acceptable only for immersive media experiences where the UI must recede. (HIG: Dark Mode)

## Materials

- Use materials to visually separate foreground elements (text, controls) from background content; letting background color pass through establishes hierarchy and sense of place. (HIG: Materials)
- Reserve the floating-glass material (Liquid Glass) for the control and navigation layer (tab bars, sidebars, toolbars); never use it in the content layer or for app backgrounds. (HIG: Materials)
- Apply glass effects to custom controls sparingly; limit them to the most important functional elements, since overuse distracts from content. (HIG: Materials)
- Use the regular (blurring, luminosity-adjusting) variant for components with significant text such as alerts, sidebars, and popovers; use the clear (highly translucent) variant only over visually rich media backgrounds. (HIG: Materials)
- When clear glass sits over bright content, add a dark dimming layer of 35% opacity; skip it if the content is already dark or the player controls provide their own. (HIG: Materials)
- Choose materials and vibrancy effects by semantic purpose, not by the apparent color they impart; system settings can change their appearance. (HIG: Materials)
- Always use vibrant (system-defined) colors for text, fills, and separators on top of materials to guarantee legibility. (HIG: Materials)
- Thicker (more opaque) materials give better contrast for text and fine detail; thinner (more translucent) materials preserve context by revealing the background. (HIG: Materials)
- The standard content-layer materials are ultra-thin, thin, regular (default), and thick; avoid the lowest-contrast (quaternary) vibrancy on thin and ultra-thin materials. (HIG: Materials)

## Icons

- Each interface icon expresses a single concept in a highly simplified, instantly recognizable form using a familiar visual metaphor tied to its action or content. (HIG: Icons)
- Keep all interface icons in the app consistent in size, level of detail, stroke weight, and perspective; adjust dimensions so mixed icons look optically equal. (HIG: Icons)
- Match the weight of icons to adjacent text unless deliberately emphasizing one over the other. (HIG: Icons)
- Optically center asymmetric icons (bake the offset into the asset's padding) rather than relying on geometric centering. (HIG: Icons)
- Author custom interface icons in a vector format (PDF or SVG) so they scale to high-resolution displays. (HIG: Icons)
- Provide alternative text labels (accessibility descriptions) for every custom interface icon. (HIG: Icons)
- Include text inside an icon only when essential to the meaning; localize any characters and provide a flipped variant for right-to-left contexts. (HIG: Icons)
- Prefer SF Symbols (or symbol-consistent equivalents); tint them with dynamic system colors so they adapt to dark mode, vibrancy, and accessibility settings. (HIG: SF Symbols)
- Use symbol weights that match the text font (nine weights, ultralight to black) and scales (small/medium/large) to tune emphasis without breaking weight matching. (HIG: SF Symbols)
- Use the outline variant alongside text in toolbars and lists; use the fill variant for tab bars, swipe actions, and selected states where more visual emphasis is needed. (HIG: SF Symbols)
- Use variable color only to communicate change over time (progress, strength); use hierarchical rendering, not variable color, to convey depth. (HIG: SF Symbols)
- Animate symbols judiciously and only with a clear communicative purpose; custom symbols must match system symbols in detail, optical weight, alignment, and perspective, and never replicate Apple products or appear in logos/app icons. (HIG: SF Symbols)

## Images

- Provide every bitmap asset at each scale factor the platform needs: @2x and @3x for iOS, @1x and @2x for macOS; a missing scale shows as blur or pixelation. (HIG: Images)
- Design raster images at the lowest resolution with control points on whole-pixel values, then scale up; @2x/@3x are clean multiples of @1x. (HIG: Images)
- Use the right format per type: de-interlaced PNG for bitmap/raster work, 8-bit palette PNG when 24-bit color isn't needed, JPEG or HEIC for photos, PDF or SVG for flat artwork needing high-resolution scaling. (HIG: Images)
- Embed a color profile in every image so colors reproduce as intended across displays; sRGB is the safe default, Display P3 at 16 bits/channel PNG for wide-gamut art. (HIG: Color)
- Always test images on a range of actual devices; artwork that looks good at design time can appear pixelated, stretched, or compressed in situ. (HIG: Images)
- When a display context would crop or letterbox artwork, scale it while preserving aspect ratio so important visual content remains visible; never distort. (HIG: Layout)

## Branding

- Branding always defers to content: no screen space spent on elements that only display a brand asset; incorporate brand in refined, unobtrusive ways. (HIG: Branding)
- Don't repeat the logo throughout the app; people rarely need reminding which app they're using, and the space is better spent on information and controls. (HIG: Branding)
- Never use the launch screen as a branding moment (it disappears too fast to convey anything); put brand expression in a welcome or onboarding screen instead. (HIG: Branding)
- Express brand primarily through an accent color applied to interface icons, buttons, and text; accept that some platforms let users override it. (HIG: Branding)
- Use a custom brand font only if it is legible at all sizes and supports bold text and larger type; a strong pattern is custom font for headlines/subheads with the system font for body and captions. (HIG: Branding)
- Even a highly stylized interface must keep standard patterns: components in expected locations and standard symbols for common actions. (HIG: Branding)
- Apply the brand's voice and tone consistently across all written communication in the product. (HIG: Branding)
- Keep Apple (or any third-party) trademarks out of the app name and imagery. (HIG: Branding)

## Motion

- Every animation must serve a purpose (orient, give feedback, show a relationship); gratuitous or excessive motion distracts and can cause physical discomfort, so cut any animation that exists "for the sake of adding motion". (HIG: Motion)
- Motion must never be the only channel for important information; supplement it with text, color, sound, or haptics so it works with animations disabled. (HIG: Motion)
- Honor Reduce Motion (`prefers-reduced-motion`): reduce automatic and repetitive animations, including zooming, scaling, and peripheral motion; tighten springs to reduce bounce; avoid animating z-axis/depth changes. (HIG: Accessibility)
- Feedback motion must follow the user's gesture and mental model: a view revealed by sliding down from the top must dismiss by sliding back up, not sideways. (HIG: Motion)
- Keep feedback animations brief and precise; short, lightweight animation tied exactly to the triggering action conveys more than prominent animation. (HIG: Motion)
- Avoid adding motion to UI interactions that occur frequently; users shouldn't pay an animation tax on every routine interaction with a custom element. (HIG: Motion)
- Let people cancel or skip past motion; never block input until an animation completes, especially one seen repeatedly. (HIG: Motion)
- Animations that track a gesture directly (finger/pointer-driven) are safer under Reduce Motion than self-running ones. (HIG: Accessibility)
- Be cautious with fast-moving or blinking animation; in excess it distracts, causes dizziness, and can trigger epileptic episodes. (HIG: Accessibility)
- For games/canvas content, hold a consistent 30-60 fps frame rate; inconsistent frame pacing reads as jank. (HIG: Motion)

## Feedback

- Match delivery to significance: passive, in-context display for status; interruptive alert only for critical, ideally actionable information. (HIG: Feedback)
- Deliver every piece of feedback through more than one channel (color plus text, sound, or haptics) so it survives silenced devices, looked-away users, and VoiceOver. (HIG: Feedback)
- Integrate status into the interface near the items it describes (e.g. unread count and last-updated line in the toolbar) rather than forcing a modal or a separate screen. (HIG: Feedback)
- Alerts lose impact when overused; if an alert delivers unimportant information, downgrade it to inline status. (HIG: Feedback)
- Warn before actions causing unexpected, irreversible data loss; do NOT warn when data loss is the expected result of the action (Finder doesn't confirm every file deletion). (HIG: Feedback)
- Confirm completion only for genuinely significant actions (e.g. a payment); users expect success, so routine operations only need feedback on failure. (HIG: Feedback)
- When a command can't be carried out, say so and explain why (e.g. Maps: "can't provide directions to and from the same location"), never fail silently. (HIG: Feedback)
- Provide an opportunity to correct a mistake, not just a report that it happened. (HIG: Feedback)

## Loading

- Show something as soon as possible: placeholder text, skeleton graphics, or animation immediately, replaced as content arrives; a blank screen reads as a broken app. (HIG: Loading)
- Content should display instantly; once loading takes "more than a moment or two", show a progress indicator. (HIG: Loading)
- Use a determinate progress bar when duration is knowable, an indeterminate spinner only when it isn't. (HIG: Loading)
- Load in the background and keep the rest of the app usable; never lock the whole UI for one loading region. (HIG: Loading)
- For unavoidably long waits, give people something useful or interesting to view (tips, hints, feature intros), and estimate remaining time accurately enough that the placeholder content isn't cut off or repeated. (HIG: Loading)
- Download large assets in the background at nondisruptive times (after install, during updates) rather than blocking first use. (HIG: Loading)
- An indeterminate animated spinner implies the user must keep watching; for long processes prefer telling them they'll be notified on completion. (HIG: Feedback)

## Launching

- Launch instantly; users tolerate at most "a couple of seconds" before first interaction. (HIG: Launching)
- The launch/startup screen must be nearly identical to the app's first screen; any differing elements produce an unpleasant flash at handoff (if the first frame is a solid color, the launch screen is only that color). (HIG: Launching)
- Match the launch screen to the current appearance mode (light/dark) and orientation. (HIG: Launching)
- No text on the launch screen (it can't localize), and no logos, branding, or "About"-style artwork unless they're a fixed part of the first screen; the launch screen is not a branding opportunity. (HIG: Launching)
- If branding must appear, put a splash screen at the start of onboarding, not in the launch path. (HIG: Launching)
- Restore previous state on restart, granularly: scroll positions, window size/position/state, the user's last location in the app; never make people retrace steps. (HIG: Launching)
- Downplay the launch experience; its sole function is making the app feel quick and immediately ready. (HIG: Launching)

## Gestures

- Provide more than one way to perform every task; never assume a specific gesture is available to the user (voice, keyboard, switch access must reach the same outcome). (HIG: Gestures)
- Standard gestures keep standard meanings: tap activates/selects, swipe reveals actions or scrolls, drag moves, double tap zooms, long-press reveals more; don't repurpose them for app-unique actions or invent a new gesture for a standard action. (HIG: Gestures)
- Respond to gestures immediately with feedback that tracks the gesture and predicts its result (e.g. partial swipe reveals partial state). (HIG: Gestures)
- Indicate when a gesture is unavailable (locked/disabled states visually distinct); an unresponsive gesture reads as a frozen app. (HIG: Gestures)
- Custom gestures must be discoverable, straightforward, distinct from other gestures, and never the only way to perform an important action. (HIG: Gestures)
- Shortcut gestures supplement visible controls, never replace them: an edge-swipe back gesture accompanies a Back button, it doesn't remove it. (HIG: Gestures)
- Don't conflict with system/OS gestures (edge swipes, three-finger undo/redo, four-finger app switch); users expect those to work everywhere. (HIG: Gestures)
- If describing a gesture requires complicated language or graphics, it's too hard to learn; simplify it. (HIG: Gestures)
- Use the simplest gesture possible for frequent interactions; avoid multi-finger or complex gestures for anything repetitive, and always offer an onscreen control alternative (e.g. a button beside swipe-to-dismiss). (HIG: Accessibility)
- Touch targets: 44x44 pt default (28x28 pt absolute minimum) on touch platforms; 28x28 pt default (20x20 pt minimum) for pointer-driven desktop. (HIG: Accessibility)
- Spacing matters as much as size: roughly 12 pt padding around bezeled controls, 24 pt around borderless ones, to prevent mis-taps. (HIG: Accessibility)

## Keyboards

- Support full keyboard access: every window, menu, control, and feature must be reachable and operable with keyboard alone; test with keyboard-only navigation. (HIG: Keyboards)
- Don't repurpose standard shortcuts (Cmd/Ctrl+C, V, Z, F, W, Q, comma for settings, Esc to cancel, Cmd+Period to cancel); redefine one only if its standard action is meaningless in your app. (HIG: Keyboards)
- Add custom shortcuts only for the most frequently used app-specific commands; too many makes the app feel hard to learn. (HIG: Keyboards)
- Don't create a new shortcut by adding a modifier to an existing shortcut for an unrelated command (Shift+Cmd+Z belongs to Redo, nothing else). (HIG: Keyboards)
- Use modifiers conventionally: Command/Ctrl as primary, Shift as the complement of a related shortcut, Option/Alt sparingly for power features; avoid Control on macOS (reserved by the system); list modifiers in the order Control, Option, Shift, Command. (HIG: Keyboards)
- Match the virtual keyboard/input type to the content (email, numeric, URL, search); set semantic input types so autofill and corrections work, and customize the Return/submit key label to the action (e.g. Search). (HIG: Virtual keyboards)
- Never let the on-screen keyboard cover the field being edited or nearby critical controls; lay out against the keyboard's actual extent. (HIG: Virtual keyboards)

## Focus and selection

- Use the system focus appearance (native focus ring / `:focus-visible` styling); create custom focus effects only when absolutely necessary. (HIG: Focus and selection)
- Never move focus without user interaction; the one exception: when the focused item disappears during discrete directional navigation (keyboard/arrow keys), move focus to an adjacent item, otherwise hide the focus indicator. (HIG: Focus and selection)
- Focusing an item may select it, but must not trigger a distracting context shift (opening a new view); activation requires a separate deliberate action. (HIG: Focus and selection)
- Use a focus ring for text and search fields; use a full-row/cell highlight for items in lists and collections (a ring is acceptable only for cell-filling content like a photo). (HIG: Focus and selection)
- Focused list items get accent-color highlight with white/contrasting text; unfocused items keep standard text on a neutral highlight. (HIG: Focus and selection)
- Tab moves focus between groups/regions (sidebar, list, grid); arrow keys move directionally within a group; verify both work in custom composite widgets. (HIG: Focus and selection)
- Tab order follows reading order: leading to trailing, top to bottom; adjust custom views so focus traversal makes spatial sense (a vertical stack traverses fully before moving on). (HIG: Focus and selection)
- When a group receives focus, its primary (most likely wanted) item receives focus automatically; set focus priority accordingly. (HIG: Focus and selection)
- Ensure the focus ring's shape matches the element's actual contour (rounded corners, custom shapes) and isn't clipped or occluded by parent containers or badges. (HIG: Focus and selection)

## Pointing devices

- Respond to pointer gestures consistently with system conventions; never redefine systemwide trackpad/mouse gestures (back/forward swipe, pinch zoom, scroll). (HIG: Pointing devices)
- The experience must be equivalent across input modes: gestures, pointer, keyboard, or touch reach the same outcomes without mode-specific relearning. (HIG: Pointing devices)
- Modifier-key semantics stay identical regardless of input: e.g. Option/Alt-drag duplicates whether dragging by touch or pointer. (HIG: Pointing devices)
- Auto-hiding controls (minimized toolbars, video controls) must reveal on pointer hover and re-hide when the pointer leaves. (HIG: Pointing devices)
- Change the cursor to communicate affordance: I-beam over text, pointing hand over links, open/closed hand for pannable content, axis arrows for resize, "not allowed" for invalid drop targets, copy badge for Option-drag. (HIG: Pointing devices)
- Hover effects by element type: background-highlight for small transparent-background controls, lift/elevation for small opaque elements, custom scale/tint/shadow only for large elements. (HIG: Pointing devices)
- Give interactive elements comfortable hit regions beyond their visible bounds: about 12 pt padding around bezeled elements, about 24 pt around borderless ones; too small feels finicky, too large makes the pointer feel sticky. (HIG: Pointing devices)
- Make adjacent toolbar buttons' hit regions contiguous so the cursor doesn't flicker back to default between them. (HIG: Pointing devices)
- Don't scale on hover when the element has no room to grow (table rows, dense grids); use tint instead, and never use shadow without scale (an unscaled element with a shadow looks wrong). (HIG: Pointing devices)
- No gratuitous or decorative pointer/hover effects; users expect pointer changes to mean something. (HIG: Pointing devices)
- Keep custom cursors simple and instantly legible; never attach instructional text to the pointer. (HIG: Pointing devices)
- Hover annotations may show useful data (coordinates, dimensions during resize), not instructions. (HIG: Pointing devices)

## Onboarding

- People should be able to understand the app by experiencing it; onboarding is a fallback, not a requirement, and must be fast, fun, and optional. (HIG: Onboarding)
- Teach through interactivity: let people safely perform the task they're learning instead of viewing instructional material. (HIG: Onboarding)
- Prefer context-specific tips shown near the relevant UI over a single monolithic onboarding flow. (HIG: Onboarding)
- Keep any prerequisite onboarding brief and free of memorization; teaching too much overwhelms and reduces retention. (HIG: Onboarding)
- Make tutorials skippable on first launch, never re-present a skipped tutorial, and keep it findable later (help, account, or settings area). (HIG: Onboarding)
- Onboarding teaches your app only, never how to use the system or device. (HIG: Onboarding)
- Postpone nonessential setup and customization: ship reasonable defaults so people can start immediately with zero configuration. (HIG: Onboarding)
- Request permissions during onboarding only if the app can't function without them; otherwise ask at first use of the specific feature, explaining the benefit. (HIG: Onboarding)
- Don't put licensing/legal text in onboarding, and don't ask for ratings or purchases before people have engaged with the app. (HIG: Onboarding)

## Entering data

- Get information from the system whenever possible; never ask for data you can gather automatically or via a permission. (HIG: Entering data)
- Be clear about the data you need: a descriptive label (e.g. "Email") or format hint in the field (e.g. "username@company.com"). (HIG: Entering data)
- Prefill fields with reasonable defaults to minimize decision-making and speed entry. (HIG: Entering data)
- Prefer choices over typing: use a picker, menu, or selection component whenever the options can be listed. (HIG: Entering data)
- Support paste and drag-and-drop for data entry wherever possible. (HIG: Entering data)
- Validate dynamically: verify values as they're entered and flag problems immediately, not after a full form is submitted. (HIG: Entering data)
- Make required fields enforce themselves: keep Next/Continue disabled until required data is entered. (HIG: Entering data)
- Use obscured input for sensitive data, and never prepopulate a password field. (HIG: Entering data)

## Modality

- Present content modally only when there's a clear benefit; modality removes context and demands a dismissal action, so it must earn that cost. (HIG: Modality)
- Keep modal tasks simple, short, and streamlined; a complicated modal makes people lose track of the suspended task. (HIG: Modality)
- Never build an "app within your app": if a modal must contain subviews, provide a single path through them and no buttons mistakable for dismiss. (HIG: Modality)
- Always give an obvious, platform-conventional way to dismiss a modal (e.g. a close button in the expected position). (HIG: Modality)
- If closing a modal could lose user-generated content, confirm first and offer a way to resolve it (e.g. a save option). (HIG: Modality)
- Title every modal with its task so people keep their place after switching context. (HIG: Modality)
- Never show two modals at once; require dismissal before presenting another. Only an alert may sit on top, and never more than one alert. (HIG: Modality)
- Reserve full-screen modality for immersive content or complex multistep tasks that benefit from minimized distraction. (HIG: Modality)

## Alerts

- Use alerts sparingly; each must offer only essential information and useful actions. (HIG: Alerts)
- Never use an alert for purely informational, non-actionable content; surface that in context instead (e.g. an inline indicator for a lost connection). (HIG: Alerts)
- No alerts for common, undoable actions, destructive included (e.g. deleting an email); alert only for uncommon, irreversible destructive actions. (HIG: Alerts)
- Don't show an alert at app startup; surface startup problems non-intrusively (e.g. cached data plus a label). (HIG: Alerts)
- Structure: a title, optional informative text, and at most three buttons. (HIG: Alerts)
- Title must succinctly say what happened, where, and why; never "Error" or a bare error code, and never longer than two lines. (HIG: Alerts)
- Alert copy is direct, neutral, and approachable: never oblique, accusatory, or severity-masking. (HIG: Alerts)
- Include a message only if it adds value; keep it short, complete sentences, sentence case. Don't explain what the buttons do. (HIG: Alerts)
- Button titles are one or two words, verbs describing the result ("View All", "Reply", "Delete"); "OK" only for purely informational alerts, never "Yes"/"No". (HIG: Alerts)
- A destructive action always gets a Cancel button (exact title "Cancel", placed leading/bottom, never the default); style a destructive button as destructive only when the user didn't deliberately choose that action. (HIG: Alerts)
- Default button goes trailing/top; if you want people to actually read the alert, make no button the default. (HIG: Alerts)
- Offer choices related to an intentional action via an action sheet/confirmation dialog, not an alert. (HIG: Alerts)

## Settings

- Ship defaults that give the best experience to the most people; ideally no adjustment is needed before first use. (HIG: Settings)
- Minimize the number of settings; too many make the app less approachable and each setting harder to find. (HIG: Settings)
- Don't use settings to ask for information the app can detect itself (connected hardware, dark mode, locale). (HIG: Settings)
- Never duplicate systemwide settings (accessibility, appearance, authentication) inside the app; respect the system's values. (HIG: Settings)
- Custom settings areas hold only general, infrequently changed options; frequently changed options don't belong there. (HIG: Settings)
- Put task-specific options (show/hide, sort, filter) inline in the screens they affect, not in a separate settings area that disconnects them from context. (HIG: Settings)
- Expose settings through expected conventions (e.g. Cmd-Comma with a keyboard, the app menu on desktop). (HIG: Settings)
- On desktop, a settings window restores the last-viewed pane, keeps a stable non-customizable navigation, and titles itself after the visible pane. (HIG: Settings)

## Undo and redo

- Help people predict what undo/redo will do, e.g. dynamic labels like "Undo Typing" or "Redo Bold". (HIG: Undo and redo)
- Show the result of every undo/redo: if the affected content is offscreen, scroll it into view so the action never appears to do nothing. (HIG: Undo and redo)
- Support multiple undo: people expect to reverse every action since a logical checkpoint (opening or saving a document). (HIG: Undo and redo)
- Consider batch reversal for related incremental changes so people don't undo one tick at a time. (HIG: Undo and redo)
- Prefer system-standard invocations (Edit menu, Cmd-Z/Shift-Cmd-Z, standard gestures); add dedicated buttons only when necessary, with standard symbols, in a toolbar. (HIG: Undo and redo)
- Never redefine the platform's standard undo shortcuts or gestures. (HIG: Undo and redo)

## Offering help

- Relate help directly to the action the person is doing right now, and make it easy to dismiss or avoid. (HIG: Offering help)
- Never explain standard components or system behavior; describe only what the element does in your app. (HIG: Offering help)
- Match terminology to the device: never "click" on touch, never "tap" on desktop. (HIG: Offering help)
- Tips are for simple features: if a feature needs more than three actions, it's too complicated for a tip. (HIG: Offering help)
- Keep tips to one or two sentences, action-oriented, never promotional or about a different feature. (HIG: Offering help)
- Show a tip only to people who'd benefit (not to those who already use the feature), at a reasonable cadence. (HIG: Offering help)
- Tooltips describe only the indicated control, start with a verb ("Restore default settings"), don't repeat the control's name, stay under ~60-75 characters, sentence case. (HIG: Offering help)
- If a control needs a lot of text to explain, simplify the interface instead. (HIG: Offering help)

## Searching

- If search matters, give it a primary position (dedicated tab or prominent field), not a buried entry point. (HIG: Searching)
- Offer one clearly identified location that searches everything; local per-section search only when sections are clearly distinct. (HIG: Searching)
- Always display the current search scope via placeholder text, scope bar, or title. (HIG: Searching)
- Show recent searches before typing and predictive suggestions while typing so people type less. (HIG: Searching)
- If you show search history, provide a way to clear it; consider who might see it. (HIG: Searching)
- Expose app content to the system-wide search index so people can find it without opening the app. (HIG: Searching)

## Notifications

- Notifications are concise, valuable updates; get consent first and respect the user's delivery preferences. (HIG: Notifications)
- Never send multiple notifications for the same thing, even if unacknowledged; people respond at their convenience, and repeats get the app muted. (HIG: Notifications)
- Don't use a notification to instruct people to perform tasks in the app; offer inline notification actions for simple tasks instead. (HIG: Notifications)
- Use an alert, not a notification, for error messages. (HIG: Notifications)
- When the app is foregrounded, present the same information in-context (badge increment, subtle insertion), never as an interruption. (HIG: Notifications)
- Never include sensitive or confidential information; others may see the screen. (HIG: Notifications)
- Titles are short, glanceable, no ending punctuation; body is complete sentences, never manually truncated. (HIG: Notifications)
- Don't repeat the app name or icon in notification content; the system already shows them. (HIG: Notifications)
- Action buttons are short, describe their result, prefer nondestructive, and never merely open the app (tapping the notification already does that). (HIG: Notifications)
- Badges count unread notifications only, are kept current, and are never the sole channel for essential information (people can turn them off); never fake a badge with custom UI. (HIG: Notifications)

## Managing accounts

- Require an account only if core functionality demands it; otherwise let people use the app without one. (HIG: Managing accounts)
- Delay sign-in as long as possible: let people experience value first, requiring sign-in only at the committing step (e.g. purchase). (HIG: Managing accounts)
- In the sign-in view, briefly and warmly explain why an account is required and its benefits. (HIG: Managing accounts)
- Name the authentication method on the button ("Sign In with Face ID"), and only reference methods actually available in the current context. (HIG: Managing accounts)
- Prefer passkeys or platform sign-in over passwords; if passwords remain, add two-factor authentication. (HIG: Managing accounts)
- If people can create an account in the app, they must be able to delete it (not just deactivate) via an easy-to-discover path, never buried in policy pages. (HIG: Managing accounts)
- Tell people when deletion will complete and notify them when it's done; keep the in-app and web deletion flows equally easy. (HIG: Managing accounts)
- On keyboard-hostile surfaces, ask for the minimum information and offer sign-in via another device. (HIG: Managing accounts)

## Writing

- Define the app's voice (vocabulary, feeling) once and keep a shared term list; vary tone by situation (serious for errors, light for wins) without changing voice. (HIG: Writing)
- Be clear and cut ruthlessly: check that every word needs to be there; read copy aloud when in doubt. (HIG: Writing)
- Use plain, jargon-free, non-gendered language; write for localization and screen readers. (HIG: Writing)
- Be action-oriented: button and link labels are verbs; "Send" beats "Let's do it!", and links say what they lead to, never "Click here". (HIG: Writing)
- Pick one capitalization style per UI element type and apply it everywhere (for Vesta: lowercase, consistently). (HIG: Writing)
- In multistep flows, use consistent step language: a consistent opener, a consistent "Continue"/"Next", an explicit "Done". (HIG: Writing)
- Drop possessive pronouns ("Favorites", not "Your Favorites") and never use "we": "Unable to load content" beats "We're having trouble loading this content". (HIG: Writing)
- Error messages: place next to the problem, no blame, state the fix positively ("Choose a password with at least 8 characters", "Use only letters for your name"), never "Invalid name", no "oops!"/"uh-oh". (HIG: Writing)
- Empty states guide the next action with a button or link; never park crucial information in a state that disappears. (HIG: Writing)
- Settings labels are plain and practical; describe only the on state (people infer off). To reference a setting, link directly to it instead of describing where it lives. (HIG: Writing)
- Label every text field and use hint/placeholder text to show format ("name@example.com"); match urgency to delivery method (alert vs notification vs inline). (HIG: Writing)

## Accessibility

- Let people enlarge text by at least 200 percent; support Dynamic Type or equivalent user text scaling rather than fixed pixel sizes, and test layouts at the largest sizes. (HIG: Accessibility)
- Keep body text at or above platform defaults (17pt iOS, 13pt macOS) and never below minimums (11pt iOS, 10pt macOS); thin font weights need larger sizes to stay legible. (HIG: Accessibility)
- Meet WCAG AA contrast: at least 4.5:1 for text up to 17pt, 3:1 for text 18pt and up or bold, verified with a contrast calculator in both light and dark appearances. (HIG: Accessibility)
- Prefer system-defined colors with accessible variants; if defaults fall short, supply a higher-contrast scheme when the Increase Contrast setting is on. (HIG: Accessibility)
- Never convey information with color alone: pair state and function changes with distinct shapes, icons, or text. (HIG: Accessibility)
- Give controls a comfortable target: 44x44pt default (iOS/touch), never below 28x28pt; macOS default 28x28pt, minimum 20x20pt. (HIG: Accessibility)
- Space controls as carefully as you size them: roughly 12pt of padding around bezeled elements and 24pt around bezel-less ones so people don't hit the wrong control. (HIG: Accessibility)
- Every gesture has a visible alternative: if swiping dismisses a view, a tappable button must do the same; use the simplest gesture possible for frequent actions. (HIG: Accessibility)
- Support full keyboard navigation and don't override system-defined keyboard shortcuts. (HIG: Accessibility)
- Avoid views and controls that auto-dismiss on a timer; prefer dismissal by explicit action. (HIG: Accessibility)
- Never autoplay audio or video without discoverable start/stop controls, and offer a global opt-out of autoplay. (HIG: Accessibility)
- Honor Reduce Motion: cut automatic and repetitive animations (zooming, scaling, peripheral motion), replace x/y/z-axis transitions with fades, tighten springs to reduce bounce, avoid animating depth changes and blurs. (HIG: Accessibility)
- Don't communicate crucial information through audio alone: provide captions, subtitles, or transcripts, and pair audio cues with visual (or haptic) equivalents. (HIG: Accessibility)
- Provide descriptive accessible labels (not the generic defaults) for all key interface elements, including every custom control, and keep them up to date as the UI changes; correct labeling also enables voice control. (HIG: VoiceOver)
- Describe meaningful images and charts for screen readers, describing only what the image itself conveys; explicitly hide purely decorative images from assistive tech. (HIG: VoiceOver)
- Give each screen a unique, succinct title and accurate section headings; group visually related elements (e.g. image plus caption) so screen readers read them together; announce visible content or layout changes to assistive technologies. (HIG: VoiceOver)

## Inclusion

- Address people directly as "you/your", never "the user"; reserve "we/our" for the company or product. (HIG: Inclusion)
- Use plain language: define any technical term before using it, replace colloquial expressions and idioms, and treat humor as a risk (it translates and lands poorly). (HIG: Inclusion)
- Avoid unnecessary gender references: rewrite around gender-neutral nouns ("Subscribers can post recipes" not "his or her recipes"); if gender must be collected, include nonbinary, self-identify, and decline-to-state options. (HIG: Inclusion)
- Portray a range of ages, body types, races, and abilities in copy and imagery; avoid stereotyped occupations, family structures, and assumptions of affluence; avoid culture-specific assumptions (e.g. security questions that presume college or car ownership). (HIG: Inclusion)
- Write people-first about disability, include people with disabilities in representative imagery, and never use a disability as a negative metaphor. (HIG: Inclusion)
- Prepare for localization: locale-aware date/number/currency formats, layouts that survive translation and right-to-left text, and color choices checked against culture-specific meanings. (HIG: Inclusion)

## Components

- Buttons: hit region at least 44x44pt with enough surrounding space to distinguish it from neighbors, regardless of input method. (HIG: Buttons)
- Buttons: every custom button has a visible press state; without one it feels unresponsive. (HIG: Buttons)
- Buttons: at most one or two prominent (filled/accent) buttons per view; distinguish the preferred choice by style, never by size differences within a set. (HIG: Buttons)
- Buttons: labels start with a verb ("Add to Cart"); use familiar icons for familiar actions (standard share symbol, etc.). (HIG: Buttons)
- Buttons: never give the primary/default role (Return-key, accent-colored) to a destructive action; destructive actions use the red/destructive style. (HIG: Buttons)
- Text fields: placeholder text disappears on typing, so pair it with a persistent label describing the field's purpose. (HIG: Text fields)
- Text fields: use secure fields for sensitive data, match field width to the expected input length, and ensure tab order moves focus in a logical sequence. (HIG: Text fields)
- Text fields: validate at the sensible moment (e.g. email on leaving the field, password rules before leaving), show the input-appropriate keyboard on touch, and offer a trailing Clear affordance. (HIG: Text fields)
- Toggles: use only for two opposing states; make on/off visually obvious via fill, shape, or inner mark, never color alone. (HIG: Toggles)
- Toggles: switches belong in list/settings rows (row text is the label); checkboxes for hierarchies and multi-select; radio buttons for 2-5 mutually exclusive options, more than ~5 becomes a menu/select. (HIG: Toggles)
- Sliders: minimum value on the leading side, maximum on the trailing side; for wide ranges, supplement with a text field/stepper showing the exact value, and give live feedback as the value changes. (HIG: Sliders)
- Progress indicators: prefer determinate progress; switch from indeterminate to determinate as soon as duration is known, and never swap a spinner for a bar mid-task. (HIG: Progress indicators)
- Progress indicators: keep the indicator moving (a stalled one reads as frozen), pace advancement evenly, avoid vague labels like "loading", place indicators in a consistent location, and offer Cancel (plus Pause if interruption loses work) with a warning when halting has consequences. (HIG: Progress indicators)
- Menus: label items with a verb, drop articles, append an ellipsis when more input is needed, and show unavailable items dimmed rather than removed. (HIG: Menus)
- Menus: put frequent items first, group related commands with separators, give icons to all items in a group or none; use submenus sparingly, one level deep, ~5 items max. (HIG: Menus)
- Menus: for on/off attributes use a checkmark or a single changeable label (Show Map/Hide Map), adding a verb if the state vs. action is ambiguous. (HIG: Menus)
- Sheets: display only one sheet at a time (close the first before opening another); always pair Done with Cancel or Back so completing the task isn't the only exit, and never show all three together. (HIG: Sheets)
- Sheets: resizable sheets include a grabber (which also enables screen-reader resizing) and support swipe-to-dismiss, with a confirmation prompt if unsaved changes would be lost. (HIG: Sheets)
- Popovers: scope to a few related tasks; the arrow points at the triggering element without covering it; show one at a time, never stack views over a popover (alerts excepted), and auto-save work when a nonmodal popover closes from an outside click. (HIG: Popovers)
- Popovers: never use a popover for warnings (use an alert), and in compact/narrow layouts replace popovers with a sheet or full-screen view. (HIG: Popovers)
