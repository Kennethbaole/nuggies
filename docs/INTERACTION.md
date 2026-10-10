# Phrase selection

`RingState` is the sole authority for navigation, drafts, confirmation and
history. The wheel has eight fixed slots: five phrases at 0,1,2,3,5; Back at 4,
More at 6 and Spell at 7. Index 0 is top, increasing clockwise. Only the
highlight moves; disabled slots are skipped. Highlighting never speaks.

Left/right changes focus. Select confirms a phrase or invokes a utility.
Home Back opens Needs and confirms “Give me a moment.” Needs Back returns Home.
More advances through finite nonrepeating pages and disables at exhaustion.
Contacts provide conversation metadata; the curated phrase bank is shared.

Spell recursively splits letters into two groups and offers local completions,
Space, Delete and Speak. Drafts are bounded to 280 characters. Back rewinds a
letter group before leaving spelling. Speak confirms the draft. Confirmed text
has a monotonically increasing selection ID and bounded history.

The ring currently uses curated phrases. Live suggestion providers are not
implemented. The visual interface is a separate component.
