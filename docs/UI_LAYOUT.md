# Companion interface — Orbital

Updated 2026-10-11 on `feat/wheel-ui-and-left-detection`.

The homepage uses white surfaces, teal/cyan accents, system sans-serif type and
quiet orbital detail. The wheel is the primary workspace; conversation partner,
Listen/Text and Default choices sit beside it. Shared words, the monochrome lens
preview and signal tools follow below. Phone layouts put the wheel first and keep
secondary tools behind More tools. The full-screen wheel and expanded trace remain.

Dark mode is available in the header on both the companion and Community pages.
The preference stays in this browser and synchronizes between tabs. A new browser
starts light. Speech remains a separate preference and resets off on refresh.

Appearance is in `frontend/theme.css`; `theme.js` applies the saved mode before
paint. Existing application, selection and sensor behavior remain in `app.js`.
No build step, external font, animation service or React dependency is required.
Choices do not rotate, and eye control still has no item highlighting. The fixed
preview shows the pending words before confirmation. State cues retain their
colours (wait amber, choose green, return blue, confirm purple, retry red, selected
teal, paused grey), with steady outlines instead of a flashing confirmation effect.
Reduced-motion preferences disable transitions and animations. OLED pixels remain
monochrome; appearance changes do not validate the physical display.

## Inspiration

[Animata](https://animata.design/components), [Motion](https://motion.dev/docs/react),
[Anime.js](https://animejs.com/), [Motion Sites](https://motionsites.ai/),
[Awwwards' immersion reference](https://www.awwwards.com/inspiration/3d-immersion-inside-kristallnacht),
[Motion Array's overview](https://motionarray.com/learn/motion-design/stop-motion-animation-websites/)
and [No Art](https://www.noartmusic.com/) informed the restrained layering,
typographic hierarchy and circular motif. Implementation uses native HTML/CSS/JS;
no third-party assets were copied. Naruko's page required client rendering and
some supplied Awwwards detail pages were unavailable through the research tool;
these are not claimed as fully reviewed visual references.

## Verification

268 tests run, 267 pass, one optional skip. The isolated EOG browser check passes:
light/dark mode, preference after refresh, Community synchronization, widths
320/390/768/1024/1440 without horizontal overflow, full-screen wheel, default choices,
ready/retry/return/confirmation UI, HUD and one mocked browser utterance. No paid
TTS was called. Screenshots were inspected for light/dark and phone layouts under
ignored `artifacts/browser-report/eog/`. An initial browser run hit a late guided
start timing failure; the rerun with explicit protocol/enabled assertions passed.
These checks do not measure sensor accuracy or physical phone/OLED readability.
