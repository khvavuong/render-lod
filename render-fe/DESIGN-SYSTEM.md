# Design System — Auto Design

This document is a **contract**, not a suggestion. Read it before adding a
screen: most of the decisions here are already settled, and several are held in
place by automated guards.

A design system does not die from missing documentation. It dies because someone
in a hurry types `#1890ff` straight into a component and it works. Six months
later there are seventeen blues in the same product and no rebrand is feasible.
So wherever a rule can be checked by machine, here it is — see §9.

---

## 1. Stack

| Thing | Choice | Why |
|---|---|---|
| Component library | **Ant Design 5** | The most complete enterprise set; ships Vietnamese; its tables and forms hold up under real data volume |
| Framework | React 19 + TypeScript (strict) | |
| Build | Vite 6 | |
| Routing | React Router 7 (`createBrowserRouter`) | |
| Tests | Vitest + Testing Library | |

---

## 2. Language: English code, Vietnamese product copy

**All code is English.** Identifiers, function names, file names, comments, test
names, and the docs in this folder.

**All product copy is Vietnamese.** Menu labels, page headings, button text,
empty states, `aria-label`s — every string a user reads.

The split is deliberate, not an oversight:

> Identifiers, comments and file names are read by whoever maintains this —
> including tooling, stack traces and `git grep`. Mixing scripts there makes all
> of those worse. The words on screen are read by Vietnamese users; translating
> them would ship a different product.

Note that `autodesign-core` (the Python side) is written in Vietnamese
throughout. The language boundary sits at the folder edge, and that is fine —
what is not fine is a boundary running through the middle of a file.

`ConfigProvider` loads `locale={viVN}`. Without it antd's calendars, pagination
and confirm buttons come out in English in the middle of our Vietnamese — the
kind of thing users notice immediately without being able to name it.

### What the guard checks, and what it deliberately allows

`src/conventions.test.ts` checks the three halves that can be verified without
guessing: **comments**, **declared names**, **file names**. String literals and
JSX text are left alone — that is exactly where the Vietnamese belongs.

Two loopholes, both learned from watching the guard misfire:

- It looks for **Vietnamese letters**, not for every non-ASCII character. An em
  dash and an arrow are English typography; banning them would push comments
  toward worse punctuation for no gain.
- **Quoted spans inside a comment are skipped**, so an English sentence may quote
  a Vietnamese label — `` `Cần bổ sung` `` — to say what it is talking about.
  Forbidding that makes comments less useful, not more English.

---

## 3. Colour

### 3.1 Brand

| Token | Value | Used for |
|---|---|---|
| `BRAND_RED` | `#E3212C` | The logo. Destructive actions (delete, cancel, revoke). |
| `BRAND_BLACK` | `#000000` | The heaviest text. **Never a background.** |

The red is **measured from the logo file itself**, not guessed: 132,818 pixels in
`public/logo/logo-ngang.png` carry exactly this value. Taken as the most frequent
colour rather than the mean — the mean would blend in the anti-aliased edges and
come out lighter than the real thing.

### 3.2 The primary colour is BLUE, not the brand red

```ts
export const PRIMARY = '#1677ff'
```

A deliberate decision, not a forgotten one:

> Red already carries a meaning in an enterprise UI — *danger, delete, wrong*. If
> the Save button is also red, users lose that signal exactly when they need it
> most.

So red keeps its job and appears only in the logo and on destructive actions.
Change your mind and you change one line — every button, link and tab follows.

### 3.3 Neutrals

| Token | Value | Meaning |
|---|---|---|
| `TEXT` | `rgba(0,0,0,.88)` | Primary text |
| `TEXT_SECONDARY` | `rgba(0,0,0,.45)` | Secondary text, labels, descriptions |
| `BORDER` | `#e5e7eb` | Divides regions (sidebar, header) |
| `BORDER_SPLIT` | `#f0f0f0` | Divides rows inside one block |
| `BG_CANVAS` | `#f5f5f5` | Content area background |
| `BG_SURFACE` | `#ffffff` | Cards, tables, header |
| `BG_SELECTED` | `#e6f4ff` | Open sidebar item, active tab |
| `BG_MUTED` | `#f0f0f0` | Avatars, empty states, table headers |

### 3.4 Rules

- **No component writes a colour inline.** Take it from `@/theme/tokens`. There
  is a guard (§9).
- Restyle antd **only through `ConfigProvider`**, never by overriding `.ant-*`
  classes in CSS. Those class names are antd's implementation detail, not a
  contract with us; a CSS override dies quietly on the next upgrade, whereas a
  token fails loudly at compile time.

Need something antd has no dedicated token for? Override a **global token scoped
to that component**. A real example: the active tab needs a pale blue fill, and
antd takes the active tab's background from `colorBgContainer` —

```ts
components: { Tabs: { colorBgContainer: t.BG_SELECTED } }
```

---

## 4. The shell

```
┌──────────────────────────────────────────────────────────┐
│ [logo · 240px] ☰  Page name              user menu ▾ 64px │
├──────────────┬───────────────────────────────────────────┤
│              │ ▣ Tab  Tab  Tab                      40px │
│   sidebar    ├───────────────────────────────────────────┤
│    240 px    │                                           │
│              │   content — 24px padding                  │
│              │                                           │
└──────────────┴───────────────────────────────────────────┘
```

| Token | Value |
|---|---|
| `SIDER_WIDTH` | 240 |
| `SIDER_WIDTH_COLLAPSED` | 64 |
| `HEADER_HEIGHT` | 64 |
| `TABBAR_HEIGHT` | 40 |
| `CONTENT_PADDING` | 24 |

The first three lock the layout together, so they live in one place rather than
scattered through each part's CSS — one pixel out and there is a visible seam.

**The logo box is exactly as wide as the sidebar.** Its right edge lines up with
the sidebar's at every window width. This is the only vertical line running the
full height of the screen.

**Height is pinned at `100vh` and divided with flex** — the page is never allowed
to grow. That keeps the sidebar and tab strip still while a long table scrolls,
so nobody has to scroll back to the top just to switch screens.

---

## 5. Navigation — one source of truth

`src/app/nav.ts` is the **only source**. The sidebar, the tab strip, every page
heading, the current-page name in the header and the route table all read from
it.

```ts
{ path: '/cai-dat',
  label: 'Cài đặt',
  description: 'Kết nối ACC, khoá mô hình ngôn ngữ, người dùng và phân quyền',
  icon: SettingOutlined }
```

In most admin UIs those are five hand-copied lists, and they drift apart the
second someone adds a screen: the sidebar says "Bộ bàn giao", the tab says "Kết
quả", the page heading still carries the name it had three months ago. Worse: the
menu has six entries, the route table has five, and the extra one leads to a
blank area — nobody finds it, because it is the least-used entry.

**Adding a screen = adding one line to `NAV`.** The route table is generated from
it (`router.tsx`), so a menu entry can never lead to a blank page, and a page can
never be alive with no way in. `NAV` itself now has two entries — see below for
where the rest of the pipeline went.

### Four stages, one screen, two menu entries

A submission still passes through the same four stages it always did:

```
documents in  →  machine reads  →  human checks  →  bundle released
"what was        (background)      "did it read     "which revision
 sent in"                           it right"        goes out"
```

Those stages used to be four menu entries. They now live inside **one screen** —
`Hồ sơ dự án` (`ProjectWorkspacePage`, at `/du-an/:code`) — because a user working
a submission moves between them constantly, and a menu click between each step
was four clicks too many for one train of thought. That screen carries no `NAV`
entry of its own: it is reached by **choosing a project**, not by clicking a menu
item, so `HomePage` lists projects and navigates to `/du-an/:code` directly. The
menu itself is left answering a smaller question — *which project, or
settings* — which is why it is down to two entries: `Dự án` (Home, and the
project picker) and `Cài đặt`.

The "machine reads" stage still gets no entry point of its own inside that
screen either. It runs in the background, and what users need to see is its
result, not the stage itself.

`Cần bổ sung` and `Xác nhận trường` still answer two different people even though
both used to be separate menu entries: the engineer asks *"did the machine read
it right"*, the client asks *"what else must I hand over"*. That split did not
go away when the menu entries did — it is now a distinction the workspace screen
draws for itself (filter chips, sections — Task 5's call), not two separate
places to click. This is NT-16, already settled in the pipeline when
`additon.md` was split out of `context.json`.

Because `/du-an/:code` is a parametrised route with no static `NAV` entry, it
cannot be a plain sidebar item, and it is not held to the "every menu entry has a
route" guard in the other direction — the guard only checks menu → route, not
route → menu. `src/app/layout/tabs.ts` fills the resulting gap with two small
pure functions: `canOpenTab` also accepts a project workspace path (so it still
gets a tab), and `labelFor` gives that tab a meaningful label — the project
code — instead of falling back to the raw path string.

### Selection comes from the URL

`selectedKeys={[selectedMenuKeyFor(pathname)]}` — never a `useState` running
alongside. When the user hits the browser's Back button, the sidebar has to
follow. `selectedMenuKeyFor` (`src/app/layout/tabs.ts`) resolves a project
workspace path to the `Dự án` key, since that is the entry the user reached it
through; every other path selects itself.

---

## 6. The tab strip

Several screens open at once, like a browser. The closing rules live in
`src/app/layout/tabs.ts` as a **pure function**, out of React, because closing is
where this pattern goes wrong:

| Situation | Behaviour | Why |
|---|---|---|
| Close a tab that is **not** on screen | Stay put | The user is mid-task on the active tab; dragging them off it throws that work away |
| Close the active tab | Go **left** | The left neighbour is the tab that opened this one, so it is closer to what they were doing |
| Close the active first tab | Go right | No left neighbour to fall back to |
| Close the last tab | Go home | A content area with no tabs is a dead end — nothing left to click |
| The only tab | No close button | Closing it would reopen it immediately; the button is an empty promise |

A path not on the map (404) **opens no tab** — otherwise a mistyped URL sits in
the strip labelled with the raw path string. A project workspace path
(`/du-an/WEGO-2026`) is not on `NAV` either, but it is not a 404: `canOpenTab`
recognises it separately (see §5) and it opens a tab labelled with the project
code.

---

## 7. Shared components

### `<PageHeader>`

The top of **every** page: its name, one line saying what it is for, and a slot
on the right for primary actions.

```tsx
<PageHeader title={item.label} description={item.description}
            extra={<Button icon={<SwapOutlined />}>Đổi dự án</Button>} />
```

If each page built its own header, type sizes and margins would drift with every
screen added, and users would feel — without being able to point at it — that the
pages do not belong to the same product.

### `<NotBuilt>`

A screen that has a place but no body yet. **Says plainly it is not built**,
instead of laying out invented numbers to fill the space.

> Fake figures in an internal demo live a very long time: they survive the
> presentations, and someone ends up making a decision on them.

Placeholder data that must exist gets a name that says so
(`PLACEHOLDER_PROJECTS`) and its own file, so only one file has to go when the
API lands.

---

## 8. Scale

| Thing | Value |
|---|---|
| Body text | 14px |
| Secondary text | 13px · `TEXT_SECONDARY` |
| Page heading | `<Title level={4}>` (20px) · weight 600 |
| Corner radius | 6px |
| Button height | 32px |
| Grid gap | 16px — `<Row gutter={[16,16]}>` |
| Menu item height | 40px |

Type: **Inter**, falling back to `-apple-system → Segoe UI → Roboto`. System
fonts render Vietnamese diacritics well and cost no network round-trip before the
page appears.

Responsive card grid: `xs={24} sm={12} lg={8} xxl={6}` — one column on a phone,
four on a wide monitor.

**The keyboard focus ring is never disabled.** This is a screen people work in
all day; anyone navigating by Tab has to see where they are.

---

## 9. Rules enforced by machine

Good intentions do not enforce themselves. These are held by tests — `npm test`:

| Rule | Test |
|---|---|
| Comments are English prose | `conventions.test.ts` |
| Declared names are ASCII | `conventions.test.ts` |
| File names are ASCII | `conventions.test.ts` |
| No file outside `theme/` writes a hex colour inline | `theme/tokens.test.ts` |
| `BRAND_RED` equals the colour measured in the logo | `theme/tokens.test.ts` |
| The primary colour is **not** the brand red | `theme/tokens.test.ts` |
| Every menu entry has a route | `app/nav.test.tsx` |
| Every page takes its heading and description from `NAV` | `app/nav.test.tsx` |
| Unbuilt screens say so instead of showing fake figures | `app/nav.test.tsx` |
| All five closing rules in §6 | `app/layout/tabs.test.ts` |

A failing guard means the design system was just broken, not that the guard is
wrong. Read the reasoning inside the test before changing it.

> The colour guard caught its first violation in the same session that wrote it —
> a `#f0f0f0` typed straight into `UserMenu.tsx`. That is why it exists.

---

## 10. Adding a screen

1. Add one line to `NAV` in `src/app/nav.ts` — path, label, description, icon.
   The route, the menu entry, the tab and the page heading all follow.
2. Until there is real content, `PlaceholderPage` handles the display. **No page
   file needed yet.**
3. When real content arrives: create `src/pages/YourPage.tsx`, open with
   `<PageHeader>`, then point its `element` in `router.tsx` at it.
4. No colour or size constant written inline — take it from `@/theme/tokens`.
5. Code in English, copy in Vietnamese (§2).
6. `npm test`.

---

## 11. Not built

Written down so nobody assumes otherwise:

- **Sign-in.** `src/app/session.ts` returns a fixed account named *"Dev Bypass"* —
  the name is kept deliberately, because a fake account wearing a real person's
  name is one nobody notices has never been replaced. APS 3-legged sign-in fills
  this in (Task 0 of `docs/plans/2026-08-29-quan-tri-tai-lieu.md`).
- **The project list.** `PLACEHOLDER_PROJECTS` in `src/app/project.ts`.
- **`Hồ sơ dự án` — the project workspace, at `/du-an/:code`.** It is routed and
  reachable from Home, but `ProjectWorkspacePage` is a heading and nothing else
  today. It needs real data, which needs the backend, which is waiting on Task 0.
- **The field table inside that screen** — the first piece of it with real
  value; see [README](./README.md).
- **Permissions.** The role is currently a line of text in the header; it hides
  and locks nothing.
- **Dark mode.** The tokens are already separated so it is reachable, but nobody
  has needed it.
- **Bundle splitting.** `dist` is 962 kB (307 kB gzipped), nearly all antd.
  Acceptable for internal software; split antd into `manualChunks` when it starts
  to feel slow.
