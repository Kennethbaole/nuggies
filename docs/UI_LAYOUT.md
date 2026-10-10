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
- Mobile: wheel and confirmation preview first; context and tools follow.
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
