# UX-CONTRACT.md — EcomAssist interaction and accessibility contract

## Non-negotiable integration contract

1. Submit a question with `POST /ask`, JSON content type, and body `{ "question": question }`.
2. Expect a JSON response containing a non-empty string `answer`.
3. If present and valid, render analytics from `chart_spec.show_chart`, `chart_spec` metadata, and `chart_rows`.
4. Reset with `POST /reset`; only clear the visible conversation after the reset succeeds.
5. Keep Enter-to-send and Shift+Enter-for-newline behavior.
6. Preserve safe text rendering for user messages and escape assistant Markdown before rendering supported formatting.
7. Keep technical error details in the console, not in customer-facing copy.

## Interaction states

| State | Trigger | Required behavior |
|---|---|---|
| Idle | No request and empty input | Send disabled; helper text visible |
| Focused | Composer receives keyboard or pointer focus | Violet focus ring and clear keyboard focus indicator |
| Typing | Input contains non-whitespace text | Composer receives `is-typing`; Send becomes available |
| Generating | `/ask` request or response typing is active | Send disabled; composer receives `is-generating`; busy state announced |
| Error / dropout | Network, HTTP, JSON, or empty-answer failure | Remove thinking indicator, show a concise error message, expose recovery guidance, allow retry |
| Resetting | Exit selected | Do not clear UI until `/reset` succeeds; retain existing failure alert if reset fails |

## Conversation and content rules

- User messages align to the end; assistant messages align to the start.
- Messages must shrink within their flex container (`min-width: 0`) and wrap long URLs/IDs without forcing page-level horizontal scrolling.
- The conversation region scrolls independently from the composer.
- Analytics must remain within the conversation width. Two columns are used when space permits; narrow viewports use one column.
- Chart canvases retain accessible labels. Chart data and chart type selection continue to be governed by the backend chart specification and existing layout logic.
- Do not display raw backend exception details to customers.

## Accessibility requirements

- Use semantic `header`, `main`, `section`, `form`, headings, and list elements.
- Give the conversation region an accessible name and keyboard focusability.
- Label the message textarea and associate it with the composer helper/status text.
- Announce conversation additions politely; use `aria-busy` during generation.
- Keep visible `:focus-visible` outlines with adequate contrast.
- Respect `prefers-reduced-motion`.
- Maintain meaningful button labels even when the visual Send text is hidden on mobile.
- Keep decorative SVGs hidden from assistive technology.

## Responsive acceptance checks

- **320–360px:** no page-level horizontal scroll; textarea and send control remain usable; user and assistant messages retain readable gutters.
- **375–640px:** composer fits safe-area padding; charts collapse to one column.
- **Tablet / laptop:** conversation uses a comfortable readable measure without excessive card nesting.
- **Large desktop / 4K:** content area expands to a 1200px maximum rather than stretching messages across the whole viewport.
- **Keyboard only:** focus is visible on the textarea, send button, Exit button, and focusable conversation region.
- **Reduced motion:** no persistent typing or ambient motion animation is required to understand state.

## Scope boundaries

- No backend changes, endpoint renames, request payload changes, response schema changes, authentication assumptions, or framework migration.
- No promise of cancellation of an in-flight network request; the existing behavior remains.
- The legacy `addAnalyticsCharts` helper remains in the file for compatibility, while the current response path continues to call `addDynamicAnalyticsChart`.
