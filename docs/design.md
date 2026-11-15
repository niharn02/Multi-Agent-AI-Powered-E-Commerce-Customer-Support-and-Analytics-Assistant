# DESIGN.md — EcomAssist frontend

## Audit summary

The existing file is a single-page HTML/CSS/JavaScript chatbot. Its integration contract is deliberately kept intact: `POST /ask` sends `{ question }`, `POST /reset` resets the Flask session, responses use `answer` and optionally `chart_spec` / `chart_rows`, and Chart.js renders analytics. The refactor does not introduce a framework, new endpoint, or new response schema.

### Shortcomings addressed

- The original light lavender glass-panel treatment relied on layered ambient shapes, large radii, blur, and shadows; it read as decorative rather than operational.
- The header and conversation workspace were capped at 940px, which left wide screens underused.
- Assistant and user messages used similar container styling; analytics cards were offset with hard-coded margins and could feel nested or misaligned.
- At narrow widths, message widths and chart cards had fixed offsets that competed with the conversation gutter.
- The mobile CSS contained a stray `p` after a declaration.
- The composer had a focus state but no clear visual distinction between active typing, generation, and failure.
- Some interaction context was exposed visually only; the refactor adds clearer labels/status semantics and keeps focus-visible rings.

## Direction: Sleek dark-mode minimalism

A customer-support tool should feel calm, legible, and dependable. The visual signature is a restrained violet signal against ink-dark surfaces: no decorative floating orbs, no heavy glass effect, and no nested card stack around every message.

### Token palette

| Token | Hex | Use |
|---|---|---|
| Ink | `#101116` | Page background |
| Panel | `#171920` | Chat workspace and composer |
| Raised | `#1D2029` | Topic chips and secondary surfaces |
| Rule | `#303341` | Dividers and quiet outlines |
| Violet | `#B6A1FF` | Focus, brand and interactive emphasis |
| Error | `#FFB5C3` | Error text on a dark red-violet surface |

### Typography

- **Display / headings:** Space Grotesk, used for brand and conversational hierarchy.
- **Body / message copy:** Manrope, for readable, human-scale support content.
- **Utility / technical values:** DM Mono, reserved for small labels and code.
- Type scale is fluid for the welcome headline, with compact utility text and a relaxed 1.65 body line-height.

External Google Fonts are progressive enhancement; system sans-serif fallbacks remain available if the font service is blocked.

### Layout concept

```text
┌──────────────────────────────────────────────────────────┐
│  mark  EcomAssist / AI Customer Support             Exit  │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  assistant response                                      │
│                                     user question        │
│  assistant response / analytics charts                   │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  message textarea                               Send     │
│  Enter to send · Shift+Enter for a new line              │
└──────────────────────────────────────────────────────────┘
```

- One main conversation surface; assistant messages remain unboxed to reduce visual nesting.
- User messages are right-aligned and use a single quiet tinted surface.
- Analytics cards are placed in a responsive grid, becoming one column on mobile.
- Content gutters scale from narrow phones through desktop and larger displays.
- Message text wraps at word boundaries when possible and breaks long tokens safely.

### Signature element

The brand's violet mark is the only high-saturation accent. Its job is to connect the welcome state, assistant avatar, and focused composer without adding decorative noise.

## Implementation notes

- Preserves the original vanilla HTML/CSS/JS architecture and Chart.js integration.
- Keeps the current Markdown rendering and `/ask` + `/reset` request contracts.
- Honors `prefers-reduced-motion`.
- Fonts load from Google Fonts; if offline, fallback stacks are used.
