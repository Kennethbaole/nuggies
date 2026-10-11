# Glint companion interface

Updated 2026-10-11 on `feat/wheel-ui-and-left-detection`.

The project is now named **Glint**. The homepage tagline is intentionally blank.
The interface uses soft white surfaces, blue/violet accents, editorial serif headings
and dark mode. The wheel spans the workspace and sits in the center, up to 720 px
wide on desktop; conversation partner, Listen/Text and Default choices follow below. Shared words, the monochrome lens
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
violet, paused grey). A strong viewport frame, tinted center and solid colored
status banner make stages visible without flashing or moving choices.
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

271 tests run, 270 pass, one optional skip. The isolated EOG browser check passes:
light/dark mode, preference after refresh, Community synchronization, widths
320/390/768/1024/1440 without horizontal overflow, full-screen wheel, default choices,
ready/retry/return/confirmation UI, HUD and one mocked browser utterance. No paid
TTS was called. Screenshots were inspected for light/dark and phone layouts under
ignored `artifacts/browser-report/eog/`. An initial browser run hit a late guided
start timing failure; the rerun with explicit protocol/enabled assertions passed.
These checks do not measure sensor accuracy or physical phone/OLED readability.

## Project and people views

The project board provides a dated development snapshot, not a live issue tracker.
The people tab includes Kenneth Bao Le, Kat Dayaon, Bella Le and Anthony Terry.
Leaving the wheel stops active eye control before changing views. Keyboard input
on other views cannot select a hidden wheel choice. Returning does not auto-start
communication. Community remains the separate conversation-partner editor.

Rheostat's local frontend informed the blue/indigo palette, editorial type and
soft page transitions. Native View Transitions and CSS provide chapter changes,
card hover motion and a decorative botanical scroll accent; reduced-motion
preferences disable these. Eye-control choices remain stationary. Public portions
of the supplied Loom and Frolick Pinterest boards informed botanical shapes and
poster-like typography; login obscured parts of the boards. No assets were copied.

The guided recording button stays enabled across state polls while eye control is
on; starting a recording still stops eye control first. The state API reports
wheel control as sensor actions, so the UI must distinguish it from legacy sensor
control when deciding whether recording can start. No detection threshold changed.

## Wheel controls follow-up (2026-10-11)

Listen, Text, Default choices and the contact picker now replace the manual
Glance/Confirm bar. The compact conversation toolbar sits above the circle,
with the preview, so it is reachable without scrolling below the wheel and never
covers an option. The typing form expands
in place; connection diagnostics remain below. Manual gesture buttons and their
keyboard hint are removed; existing keyboard shortcuts still work on the wheel.
Eye-control choices are larger (28 px desktop), closer to center (30% radius),
with separate mobile dimensions to prevent collisions. The initial eight-slot
manual layout also uses larger labels, with more spacing than the four-slot layout.

## Team portraits (2026-10-11)

The people cards feature the four photos supplied by Kenneth: Kat (image 1),
AJ / Anthony Terry (image 2), Ken / Kenneth Bao Le (image 3), Bella (image 4).
Original assets are stored in `frontend/team/`, with consistent 4:5 CSS frames,
individual focal positions and accessible names. The originals are unaltered;
CSS controls only their display framing. No generated portraits are used.

Team roles are now Software Engineer for all four members; Ken’s displayed name
is Kenneth Le (2026-10-11). Photo assignments and other team names are unchanged.
