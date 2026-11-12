# Render quality and project adaptation

Checked: 2026-11-09. [Playwright screenshots](https://playwright.dev/docs/screenshots) documents whole-page and element capture. These visual acceptance checks are local recommendations for the existing stack-diagram tools.

Use the existing HTML template and build/render scripts rather than inventing a second image renderer. Customize component labels, groups, edges, theme and output dimensions to the system being explained. The template's example services do not establish the project's actual topology.

Inspect the rendered PNG at its intended display size: no clipped nodes, crossed labels, missing brand assets, low-contrast text or arrows that imply the wrong direction. Check light and dark outputs when both are produced. Full-page captures are useful for the report; a `.canvas` element capture isolates the diagram.

Label unimplemented components as planned, and attach command/interval evidence to measured rates or latencies. Do not populate unknown values from assumptions. Keep HTML and image outputs tied to the same source revision. Observe the project's runtime restrictions even when the upstream skill's examples use a host environment; an unavailable renderer remains an explicit capture gap. Public gallery submission remains a separate authorized action.
