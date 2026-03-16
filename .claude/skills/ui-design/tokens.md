# Vesta Design Tokens

Every design value in the codebase. If a value isn't here, don't invent one — ask or derive from these.

## Window Configuration

| Property | Value |
|----------|-------|
| Window size | 380x380px (fixed, square) |
| Decorations | false (custom titlebar) |
| Resizable | false |
| Transparent | true |
| Shadow | false (CSS handles it) |
| Titlebar height | 40px |

## Color Palette

### Neutrals (warm brown undertone throughout)
| Step | Light Mode | Dark Mode |
|------|-----------|-----------|
| Darkest text | `#1a1816` | `#e8e0d8` |
| Dark text | `#3d3a36` | `#b0a8a0` |
| Medium text | `#5a5450` | `#8a8078` |
| Muted text | `#7a726a` / `#807870` | `#8a8078` |
| Subtle text | `#9a928a` | `#6a625a` |
| Placeholder | `#c4bdb5` | `#5a5450` |
| Disabled | `#b5aba1` | `#6a625a` |
| Lightest text | `#a09890` | `#b0a8a0` |

### Backgrounds
| Surface | Light Mode | Dark Mode |
|---------|-----------|-----------|
| Window | `rgba(248, 246, 243, 0.96)` | `rgba(28, 27, 26, 0.96)` |
| Window (dark views) | — | `rgba(17, 17, 16, 0.96)` |
| Card | `rgba(255, 255, 255, 0.5)` | `rgba(255, 255, 255, 0.04)` |
| Card hover | `rgba(255, 255, 255, 0.8)` | `rgba(255, 255, 255, 0.08)` |
| Button | `rgba(255, 255, 255, 0.7)` | `rgba(255, 255, 255, 0.08)` |
| Button hover | `white` | `rgba(255, 255, 255, 0.14)` |
| Input | `white` | `rgba(255, 255, 255, 0.06)` |
| Menu | `rgba(255, 255, 255, 0.85)` | `rgba(40, 38, 36, 0.9)` |
| Menu item hover | `rgba(0, 0, 0, 0.05)` | `rgba(255, 255, 255, 0.08)` |
| Tooltip | `rgba(30, 28, 26, 0.85)` | same |
| Input bar | `rgba(255, 255, 255, 0.02)` | same |
| Selection | `rgba(139, 126, 116, 0.25)` | `rgba(139, 126, 116, 0.4)` |

### Primary Buttons (inverted in dark mode)
| Property | Light Mode | Dark Mode |
|----------|-----------|-----------|
| Background | `#1a1816` | `#e8e0d8` |
| Text | `#f0ece7` | `#1c1b1a` |
| Hover bg | `#2d2a26` | `#f0ece7` |
| Hover text | `white` | `#1c1b1a` |

### Semantic Colors
| Role | Light | Dark |
|------|-------|------|
| Success/alive dot | `#66bb6a` | `#66bb6a` |
| Success glow | `rgba(102, 187, 106, 0.4)` | same |
| Status alive text | `#7a9e70` | `#8aae80` |
| Error/danger text | `#c45450` | `#e07070` |
| Danger hover text | `#a03c38` | `#f08080` |
| Danger hover bg | `#fdf3f2` | `rgba(224, 112, 112, 0.12)` |
| Danger hover border | `rgba(196, 84, 80, 0.15)` | `rgba(224, 112, 112, 0.15)` |
| Warning/thinking | `#ffa726` | `#ffa726` |
| Warning glow | `rgba(255, 167, 38, 0.4)` | same |
| Platform warning | `#e0a030` | `#e0a030` |
| Notification text | `rgba(255, 200, 100, 0.7-0.8)` | same |
| Notification bg | `rgba(255, 200, 100, 0.06)` | same |
| Notification border | `rgba(255, 200, 100, 0.1)` | same |
| Link | `rgba(130, 180, 255, 0.9)` | same |
| Link hover | `rgba(160, 200, 255, 1)` | same |
| Assistant text | `rgba(140, 200, 130, 0.9)` | same |
| Tool text | `rgba(255, 255, 255, 0.4)` | same |
| Progress fill | `#8b7e74` | `#a09080` |
| Progress track | `rgba(0, 0, 0, 0.05)` | `rgba(255, 255, 255, 0.06)` |

### Borders
| Context | Light Mode | Dark Mode |
|---------|-----------|-----------|
| Window | `rgba(0, 0, 0, 0.08)` | `rgba(255, 255, 255, 0.06)` |
| Card | `rgba(0, 0, 0, 0.06)` | `rgba(255, 255, 255, 0.06)` |
| Card hover | `rgba(0, 0, 0, 0.1)` | `rgba(255, 255, 255, 0.1)` |
| Button | `rgba(0, 0, 0, 0.08)` | `rgba(255, 255, 255, 0.06)` |
| Button hover | `rgba(0, 0, 0, 0.12)` | `rgba(255, 255, 255, 0.1)` |
| Input | `rgba(0, 0, 0, 0.08)` | `rgba(255, 255, 255, 0.08)` |
| Input focus | `rgba(0, 0, 0, 0.2)` | `rgba(255, 255, 255, 0.15)` |
| Menu | `rgba(0, 0, 0, 0.08)` | `rgba(255, 255, 255, 0.08)` |
| Topbar divider | `rgba(255, 255, 255, 0.05)` | same |
| Input bar divider | `rgba(255, 255, 255, 0.05)` | same |
| Orb ring | `rgba(255, 255, 255, 0.08)` | same |
| Add card (dashed) | `rgba(0, 0, 0, 0.1)` | `rgba(255, 255, 255, 0.08)` |

### Orb Colors
| State | Gradient (at 38% 32%) | Glow | Ambient |
|-------|----------------------|------|---------|
| Alive | `#b8ceb0 → #7a9e70 → #5a7e50` | `rgba(138, 180, 120, 0.35)` | `rgba(138, 180, 120, 0.08)` |
| Thinking/Tool | `#e8d0a0 → #c4a060 → #a08040` | `rgba(200, 170, 100, 0.4)` | `rgba(200, 170, 100, 0.12)` |
| Booting | `#c4deb8 → #8ab880 → #6a9e5a` | same as alive | same |
| Auth | `#c0d0e8 → #80a0c4 → #6080a4` | `rgba(100, 150, 200, 0.35)` | `rgba(100, 150, 200, 0.1)` |
| Dead/Stopped | `#c4bdb5 → #a09890 → #8b7e74` | `rgba(160, 152, 144, 0.2)` | dim |

### Window Controls (macOS)
| Control | Active Color | Border | Inactive |
|---------|-------------|--------|----------|
| Close | `#ed6a5f` | `#e24b41` | `#dddddd` |
| Minimize | `#f6be50` | `#e1a73e` | `#dddddd` |
| Fullscreen | `#61c555` | `#2dac2f` | `#dddddd` |
| Glyph (hover) | `rgba(0, 0, 0, 0.5)` | — | — |

### Window Controls (Windows)
| Control | Hover BG | Icon Color |
|---------|----------|------------|
| Close | `#c42b1c` | white |
| Minimize | subtle gray | inherit |
| Maximize | subtle gray | inherit |

### Window Controls (Linux/GNOME)
Flat icon buttons, no colored backgrounds. Subtle highlight on hover. Icons: × − □.

## Typography

| Element | Size | Weight | Tracking | Line-height |
|---------|------|--------|----------|-------------|
| h1 (onboarding) | 22px | 600 | -0.03em | — |
| Agent name | 16px | 550 | -0.01em | — |
| Card name | 14px | 550 | -0.01em | — |
| Body / input | 14px | 400 | 0.01em | — |
| Button text | 12-13px | 500 | 0.01em | — |
| Topbar title | 13px | 500 | 0.01em | — |
| Prompt char / textarea | 13px | 500/400 | — | 1.4 |
| Mono output | 12px | 400 | — | 1.75 |
| Status text | 11px | 450 | 0.04em | — |
| Card status | 11px | 400 | 0.02em | — |
| Label/hint | 11px | 400 | 0.02-0.04em | — |
| Tooltip | 11px | 450 | 0.02em | — |
| Tool/notification lines | 11px | 400 | — | — |
| Error details | 10px | 400 | — | 1.4 |
| Logo mark | 32px | 300 | -2px | — |

### Font Stacks
- **UI**: `"Inter", -apple-system, BlinkMacSystemFont, system-ui, sans-serif`
- **Mono**: `"SF Mono", "Fira Code", "JetBrains Mono", "Consolas", monospace`
- Stream-ended label uses Inter (not mono) even inside console view.

## Spacing

### Padding
| Context | Value |
|---------|-------|
| Buttons (standard) | `8px 16px` |
| Buttons (onboarding) | `8px 24px` |
| Buttons (icon-only) | `8px 10px` |
| Input field | `12px 16px` |
| Output panel | `16px 20px` |
| Input bar | `12px 20px` |
| Topbar | `8px 16px` |
| Titlebar | `0 16px` |
| Cards | `24px 16px` |
| Grid/onboarding container | `40px` |
| Menu container | `4px` |
| Menu items | `8px 12px` |
| Tooltip | `4px 10px` |
| Reconnect bar | `6px 20px` (when visible) |
| Toggle button | `4px 6px` |
| Error details | `8px 10px` |

### Gaps
| Context | Value |
|---------|-------|
| Thinking dots | `4px` |
| Empty dots | `4px` |
| Topbar items | `8px` |
| Action buttons | `8px` |
| Card contents | `8px` |
| Input bar | `8px` |
| Grid cards | `12px` |
| Status label to name | `4px` |
| Creature area children | `20px` |

### Sizes
| Element | Size |
|---------|------|
| Window | 380x380px |
| Titlebar | 40px height |
| Back button | 44x44px |
| Window control button | 20x20px |
| Window control dot | 12x12px |
| Connection dot (chat) | 6x6px |
| Status dot (grid) | 10x10px |
| Thinking/empty dots | 4x4px |
| Orb container | 140x140px |
| Orb body | 100x100px (inset 20px) |
| Scrollbar width | 6px (output), 4px (textarea) |
| Progress track | 2px height |
| Progress fill | 35% width |
| Progress max-width | 280px |
| Input max-height | 120px |
| Error details max-height | 150px |
| Grid column min | 140px |
| Grid max-width | 480px |
| Card max-width | 360px (onboarding) |
| Name max-width | 120px (card), 200px (agent view) |
| Menu min-width | 120px |

## Border Radius

All use `corner-shape: squircle` alongside `border-radius`.

| Element | Radius |
|---------|--------|
| Window | 12px |
| Cards | 12px |
| Buttons | 8px |
| Input | 8px |
| Menu dropdown | 10px |
| Menu items | 6px |
| Tooltip | 6px |
| Tool toggle | 4px |
| Scrollbar thumb | 3px (output), 2px (textarea) |
| Code inline | 3px |
| Progress track/fill | 2px |
| Dots/indicators | 50% (circle) |

## Shadows

| Context | Light Mode | Dark Mode |
|---------|-----------|-----------|
| Window | `0 0 0 0.5px rgba(0,0,0,0.06), 0 8px 40px rgba(0,0,0,0.08), 0 2px 12px rgba(0,0,0,0.04)` | `0 0 0 0.5px rgba(255,255,255,0.04), 0 8px 40px rgba(0,0,0,0.3), 0 2px 12px rgba(0,0,0,0.2)` |
| Card hover | `0 4px 16px rgba(0,0,0,0.06)` | `0 4px 16px rgba(0,0,0,0.2)` |
| Button hover | `0 2px 12px rgba(0,0,0,0.06)` | `0 2px 12px rgba(0,0,0,0.2)` |
| Primary hover | `0 2px 16px rgba(0,0,0,0.12)` | `0 2px 16px rgba(0,0,0,0.3)` |
| Primary hover (onboarding) | `0 2px 12px rgba(0,0,0,0.1)` | `0 2px 12px rgba(0,0,0,0.3)` |
| Menu dropdown | `0 4px 20px rgba(0,0,0,0.08)` | `0 4px 20px rgba(0,0,0,0.3)` |
| Green dot glow | `0 0 8px rgba(102,187,106,0.4)` | same |
| Red dot glow | `0 0 8px rgba(224,112,112,0.3)` | same |
| Connection dot glow | `0 0 6px rgba(102,187,106,0.4)` | same |
| Thinking dot glow | `0 0 6px rgba(255,167,38,0.4)` | same |
| Focus ring (input) | `0 0 0 3px rgba(0,0,0,0.03)` | `0 0 0 3px rgba(255,255,255,0.04)` |
| Focus-visible ring | `0 0 0 3px rgba(139,126,116,0.2)` | `0 0 0 3px rgba(255,255,255,0.1)` |
| Orb body inset | `inset 0 -8px 20px rgba(0,0,0,0.15), inset 0 4px 12px rgba(255,255,255,0.15)` | same |
| Orb glow blur | `blur(18px)` | same |

## Animations

### Spring Easings (defined on :root)
```css
--spring: cubic-bezier(0.16, 1, 0.3, 1);
--spring-bouncy: cubic-bezier(0.34, 1.56, 0.64, 1);
--spring-snappy: cubic-bezier(0.2, 0, 0, 1);
```
With `@supports (animation-timing-function: linear(0, 1))`, each has a `linear()` approximation for true spring feel.

### Keyframe Animations
| Name | Duration | Easing | Effect | Used in |
|------|----------|--------|--------|---------|
| `viewIn` | 0.6s | `--spring` | scale(0.97)→1 + fade | GridView, AgentView entrance |
| `panelIn` | 0.35s | `--spring` | fade only | Chat, Console entrance |
| `fadeSlideIn` | 0.5s | `--spring` | translateY(10px)→0 + fade | Onboarding steps |
| `menuIn` | 0.15s | `--spring` | translateY(4px)→0 + scale(0.96→1) | Menu dropdown |
| `popIn` | 0.4s | `--spring-bouncy` | scale(0.5)→1 + fade | Done/platform icons |
| `lineIn` | 0.15s | ease-out | translateY(2px)→0 + fade | Log/chat lines |
| `msgIn` | 0.4s | ease | translateY(4px)→0 + fade | Progress messages |
| `breathe` | 2.5s | ease-in-out | opacity 0.3↔0.8, scale 1↔1.03 | Loading logo (infinite) |
| `float` | 2-4s | ease-in-out | translate 0↔-6px | Orb bob (infinite) |
| `glow-pulse` | 1.2-3s | ease-in-out | opacity 0.7↔1, scale 1↔1.08 | Orb glow (infinite) |
| `orb-breathe` | 1.2-3s | ease-in-out | scale 1↔1.03 | Orb body (infinite) |
| `dot-pulse` | 1.4s | ease-in-out | opacity 0.3↔1, scale 0.8↔1 | Loading/thinking dots (infinite) |
| `shake` | 0.3s | ease | translateX ±3px | Error text |
| `slide` | 1.8s | cubic-bezier(0.4,0,0.2,1) | translateX -120%→400% | Progress bar (infinite) |
| `shrink-away` | 0.6s | `--spring` | scale→0.7, opacity→0.3 | Deleting orb |
| `orb-wind-down` | 0.8s | `--spring` | scale→0.92, colors→gray | Stopping orb |
| `orb-wake-up` | 0.8s | `--spring` | scale 0.92→1.03 | Starting orb |
| `glow-swell` | 0.8s | ease-in-out | opacity 0.4↔1, scale 1↔1.12 | Starting/booting glow (infinite) |
| `fade-out` | 0.4-0.5s | ease | opacity→0 | Stopping glow/ring |

### Transitions
| Context | Duration | Easing | Properties |
|---------|----------|--------|------------|
| Button hover | 0.15-0.2s | `--spring-bouncy` | all |
| Window control press | 0.15s | `--spring-bouncy` | all |
| Card hover | 0.2s | `--spring-bouncy` | all |
| Status dot color | 0.4s | `--spring` | all |
| Status dot (grid) | 0.3s | ease | all |
| Tool toggle | 0.2s | `--spring` | all |
| Menu item hover | 0.12s | ease | background |
| Tooltip | 0.12s | ease | opacity, transform |
| Input focus | 0.2s | `--spring` | all |
| Orb body/glow/ring | 0.8s | `--spring` | background, box-shadow, transform, opacity |
| View content | 0.5s | ease | opacity (ready) |
| View swap | 0.15s | ease | opacity (transitioning) |
| Window bg | 0.35s | ease | background, border-color, box-shadow |
| Reconnect bar | 0.2s | `--spring` | max-height, opacity, padding, border-color |
| Onboarding dim | 0.25s | ease | opacity |
| Add icon color | 0.2s | ease | color |
| Orb highlight | 0.8s | `--spring` | opacity |

### Interactive Feedback
| Interaction | Transform | Shadow |
|-------------|-----------|--------|
| Button hover | `translateY(-1px)` | add shadow |
| Card hover | `translateY(-2px)` | add shadow |
| Button active | `scale(0.97)` | remove shadow |
| Card active | `scale(0.97)` | remove shadow |
| Window control active | `scale(0.85)` | — |
| Tool toggle active | `scale(0.95)` | — |
| Tooltip visible | `translateY(-8px → -12px)` | — |

### Dot Stagger Delays
| Dot | Delay |
|-----|-------|
| 1st | 0s |
| 2nd | 0.2s |
| 3rd | 0.4s |

## Z-Indices
| Element | Z-Index |
|---------|---------|
| Tooltip | 200 |
| Titlebar | 100 |
| Back button (AgentView) | 10 |
| Window control SVG | 1 |

## Timing Constants (JS/TS)
| Constant | Value | Used in |
|----------|-------|---------|
| Initial load delay | 400ms | App mount |
| View swap delay | 150ms | setView() |
| Status poll interval | 5000ms | GridView, AgentView |
| Message cycle interval | 3000ms | Onboarding creation |
| Disconnect debounce | 2000ms | Chat stableConnected |
| Orb leave delay | 150ms | AgentView pointer leave |
| WS reconnect base | 1000ms | ws.ts |
| WS reconnect max | 30000ms | ws.ts |
| Max messages | 5000 | Chat, ws.ts |
| Auto-scroll threshold | 40px | scroll.ts |
| Orb LERP | 0.015 | AgentView |
| Orb SNAP | 0.5px | AgentView |
| Orb range | ±14px | AgentView |

## Orb Anatomy
| Layer | Inset | Blur | Key Property |
|-------|-------|------|-------------|
| Ambient | -30px | — | Faint colored halo, 0.08 opacity |
| Glow | -5px | 18px | Colored radial gradient, 0.35 opacity |
| Ring | 14px | — | 1px white border, 0.08 opacity |
| Body | 20px | — | 3-stop radial gradient, inset shadows |
| Highlight | — | 2px | White ellipse, top 18% left 28%, 28%x20% |

Light source: upper-left (gradient centered at 38% horizontal, 32% vertical).
