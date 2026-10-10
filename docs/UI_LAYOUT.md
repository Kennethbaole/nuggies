# Companion readability update

Updated 2026-10-10. The homepage retains its dark green, sage and peach palette
and serif headings. Larger text, buttons, spacing and a clearer hierarchy improve
reading while the wearer is using eye input.

- Main area: communication controls, fixed detected-choice preview, wheel, manual
  confirmation controls. The wheel center shows the chosen label and confirmation
  readiness without restoring gaze highlighting.
- Left: conversation partner, listening/text context, connection.
- Right: confirmed words in the companion view, lens preview, recent words.
- Below: grouped signal diagnostics and recording tools, with a larger trace and
  the existing full-screen workspace. Diagnostic checks remain separate from
  communication mode.
- Mobile (760 px and below), arranged for a caregiver tapping phrases: wheel and
  confirmation preview first, with Glance left/Confirm/Glance right pinned to the
  bottom of the screen while the wheel is in view. Speaking-with (Listen/Text) and
  recent words follow. Connection, companion mirror, lens preview and signal tools
  sit behind a "More tools" button. Keyboard hints are hidden on touchscreens.
- Wheel center text shrinks to fit the circle (down to 13 px) instead of scrolling.
  Below 360 px the small label above it is dropped first. Only very long spelled
  drafts still scroll.
- Browser HUD: pending choice and confirmation readiness replace diagnostic-only
  speech-off text in communication mode. This is not physical OLED validation.

Homepage styling is isolated in frontend/homepage.css; contacts retain their
existing layout. Behavior remains in the shared application.

Verification: navigation/spelling/Back/phone/HUD/speech browser acceptance passed;
EOG browser simulation passed with pending-choice preview before confirmation.
Layout checks at widths 1440, 1024, 768, 390 and 320 pixels found no horizontal
overflow. Expanded trace sizing was checked. Screenshots are private artifacts
under artifacts/ui-refresh and artifacts/browser-report/eog. These checks do not
measure biological detection accuracy.

Mobile pass (2026-10-10): checked in headless Chromium at 390x844 and 320x640.
There's no horizontal overflow, the full wheel and confirm bar fit on the first
390x844 screen, and home-page controls are at least 40 px tall. "More tools"
expands and collapses. The /hud page on a phone no longer renders the companion
page underneath. Not yet checked on a physical phone.
