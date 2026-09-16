# Library PUP — UI/UX Redesign Design Document
Generated: 2026-09-16

## 1. Concept & Vision

A polished, dark-themed media discovery interface that feels like a premium streaming service's web app — not a ops dashboard. The UI should feel **fast**, **confident**, and **inviting**: you're not managing downloads, you're picking what to watch tonight. Every interaction should feel intentional and responsive.

The personality is "midnight movie club" — deep purple-black backgrounds, warm amber/gold accents (movie marquee vibes), crisp white text, and smooth micro-interactions that make browsing feel like a treat rather than a chore.

---

## 2. Design Language

### Aesthetic Direction
**Reference**: Premium dark streaming apps (Max, Criterion Channel) meets modern dev tools (Linear, Vercel). Deep dark backgrounds with warm accent colors, generous whitespace, crisp typography.

### Color Palette
```
--color-bg-base:       #0d0d14   /* Near-black with blue undertone */
--color-bg-surface:     #16161f   /* Card/panel backgrounds */
--color-bg-elevated:   #1e1e2a   /* Hover states, dropdowns */
--color-bg-overlay:     #252535   /* Modals, toasts */

--color-border:        #2a2a3a   /* Subtle borders */
--color-border-strong: #3d3d52   /* Focus rings, dividers */

--color-text-primary:  #f0f0f5   /* Headings, primary content */
--color-text-secondary:#9090a8   /* Meta, labels */
--color-text-muted:    #5a5a70   /* Placeholders, disabled */

--color-accent:        #f59e0b   /* Amber — primary actions, highlights */
--color-accent-hover:  #fbbf24   /* Amber light — hover */
--color-accent-subtle: #78350f   /* Amber dark — badges, tags */

--color-success:       #22c55e   /* Green — added, success */
--color-success-subtle:#14532d   /* Green dark — success badges */
--color-error:         #ef4444   /* Red — errors, danger */
--color-error-subtle:  #7f1d1d   /* Red dark — error states */

--color-purple:        #8b5cf6   /* Purple — secondary accent, branding */
--color-purple-subtle: #4c1d95   /* Purple dark — purple badges */
```

### Typography
- **Font stack**: `system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif`
- **Heading scale**: 1.4rem (h1), 1.1rem (h2), 0.95rem (h3)
- **Body**: 0.9rem, line-height 1.5
- **Mono**: For badges/tags: `'SF Mono', 'Fira Code', Consolas, monospace`

### Spatial System
```
--space-1: 0.25rem   /* 4px */
--space-2: 0.5rem    /* 8px */
--space-3: 0.75rem   /* 12px */
--space-4: 1rem      /* 16px */
--space-5: 1.5rem    /* 24px */
--space-6: 2rem      /* 32px */
--space-8: 3rem      /* 48px */

--radius-sm: 0.375rem  /* 6px */
--radius-md: 0.5rem    /* 8px */
--radius-lg: 0.75rem   /* 12px */
--radius-xl: 1rem      /* 16px */
--radius-full: 9999px  /* Pills */

--shadow-sm: 0 1px 2px rgba(0,0,0,0.4)
--shadow-md: 0 4px 12px rgba(0,0,0,0.5)
--shadow-lg: 0 8px 24px rgba(0,0,0,0.6)
```

### Motion Philosophy
- **Duration**: 150ms for micro-interactions, 250ms for state changes, 350ms for entrances
- **Easing**: `cubic-bezier(0.4, 0, 0.2, 1)` for most transitions
- **Hover lift**: cards lift 2px + shadow deepens on hover
- **Stagger**: result cards animate in with 30ms stagger
- **Autocomplete**: dropdown fades + slides in 150ms
- **Toast**: slides in from top, auto-dismisses after 4s

---

## 3. Component Inventory

### Topbar
- **Layout**: flex row, logo left, controls right
- **Logo**: "📚 Library" text mark with book icon (inline SVG)
- **User pill**: avatar circle with initials + dropdown select for Jellyfin users
- **Status dot**: green (all upstreams reachable) / amber (partial) / red (all down)
- **States**: normal, user-menu-open, status-degraded

### Search Bar (Hero)
- **Layout**: full-width, centered, max-width 640px, with autocomplete dropdown
- **Input**: large (1.1rem), 48px height, rounded-full, subtle glow on focus
- **Dropdown**: max 5 movies + 5 shows, poster thumbnails, kind badge, title + year
- **States**: empty, typing, loading, results, no-results
- **Keyboard**: Arrow Up/Down navigates, Enter submits, Escape closes

### Media Card
- **Layout**: poster thumbnail (aspect 2:3), meta below
- **Poster**: lazy-loaded img with fallback placeholder (first 2 letters of title)
- **Meta**: title (truncated 1 line), year, runtime (movies only)
- **Genres**: up to 2 genre pills below meta (truncated)
- **Action**: "Add to [Movie/Show]" button or "✓ In library" disabled state
- **States**: default, hover (lift + glow), added (success border flash), already-in-library (disabled)
- **Responsive**: 1 col mobile, 2 col tablet, 3-4 col desktop

### Starter Pack Card
- **Layout**: colored left border (per theme), title, description, title list (scrollable), count badge
- **Theme colors**: purple (movies), blue (shows), amber (mixed)
- **Action**: "Add all" button
- **States**: default, hover, loading (spinner during bulk add)

### Tonight Panel
- **Layout**: mood input bar (like search), ranked results list
- **Result row**: score badge (amber), title, year, genre pills, summary snippet, Add button
- **Score badge**: amber pill with number, "score" label
- **States**: empty (prompt), typing, loading, results, no-matches

### Toast Notification
- **Layout**: top-center, slides in, auto-dismiss
- **Variants**: success (green left border), error (red left border), info (purple left border)
- **Content**: bold title + body text
- **Animation**: fade + slide from top, 350ms

### Empty States
- **No results**: illustration (SVG), "Nothing found", hint text
- **No upstream**: warning icon, "Can't reach services", retry suggestion
- **Empty library**: movie icon, "Your library is empty", starter pack CTA

### Status Strip (Home)
- **Layout**: horizontal row of stat tiles
- **Stats**: Movies count, Shows count, JF Users count, Prowlarr indexers
- **Tile**: number (large, amber), label (small, muted)

---

## 4. UI State Map

| Page / View | Entry | Content | Empty State |
|---|---|---|---|
| Home (`/`) | direct or `?user=x` | Search bar, Tonight input, Random button, Starter packs, Status strip | Starter packs + empty search hint |
| Search (`/search?q=x`) | GET form submit | Results grid | "No results for 'x'" |
| Tonight (`/tonight?q=x`) | GET form submit | Ranked list with scores | "Tell me your mood" |
| Random (`/random`) | GET form submit | Single picked card | "No candidates" |
| Add Movie POST | form POST | Toast inline + back link | n/a |
| Add Series POST | form POST | Toast inline + back link | n/a |
| Pack POST | form POST | Toast + list of results + back | n/a |

---

## 5. Technical Approach

### Architecture
- **Server**: Python `http.server.ThreadingTCPServer` — no framework, no dependencies
- **Static assets**: `live.js` served via `/static/live.js` endpoint
- **Styling**: CSS custom properties (design tokens) embedded in Python string, served inline in `<style>` tag
- **Client JS**: Vanilla JS in `live.js`, no build step, no dependencies
- **No npm/node**: Pure Python + vanilla JS — container-friendly

### CSS Architecture
- All tokens defined as CSS custom properties on `:root`
- BEM-ish class naming: `.card`, `.card__poster`, `.card__body`
- No external fonts (system stack only)
- No images required at build time (posters come from upstream APIs)

### Responsive Breakpoints
```css
/* Mobile first */
.results-grid { grid-template-columns: 1fr; gap: 1rem; }
@media (min-width: 480px) { .results-grid { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 768px) { .results-grid { grid-template-columns: repeat(3, 1fr); } }
@media (min-width: 1024px) { .results-grid { grid-template-columns: repeat(4, 1fr); } }
```

### Accessibility Requirements
- Skip-to-content link (`.skip`)
- `role="listbox"` on autocomplete dropdown
- `aria-selected` on active suggestion
- `aria-label` on all form controls
- Focus visible on all interactive elements
- `color-scheme: dark` meta tag (already present)

---

## 6. Improvement Opportunities Over Current Design

1. **Design tokens**: Current CSS is hardcoded values throughout. New design uses CSS custom properties throughout for consistency and theming.
2. **Card hover states**: Current cards have no hover effect. New design adds lift + shadow + subtle glow.
3. **Autocomplete dropdown**: Current dropdown is basic. New design has poster thumbnails, kind badges, keyboard navigation with visual active state.
4. **Score badges**: Tonight results show a numeric score — new design makes this a prominent amber pill.
5. **Genre pills**: New design shows genre tags on cards for quick scanning.
6. **Toast system**: Current "toast-inline" is page-embedded. New design has a floating toast region with slide-in animation.
7. **Starter pack cards**: Current packs are text-only. New design has themed color coding and scrollable title lists.
8. **Empty states**: Current empty states are plain text. New design has illustrated SVG placeholders.
9. **Status strip**: Current status is a simple grid. New design uses tile cards with larger numbers and better hierarchy.
10. **Responsive grid**: Current grid is `auto-fill` only. New design has explicit breakpoints for better mobile layout.
