"""Explicitly enabled experimental confirmation of a freshly gazed-at item.

Consumes detector events, never raw threshold crossings. Quiet signals alone do
not establish physical center; recovery remains the detector's responsibility.
"""
class EOGConfirmation:
    def __init__(self):
        self.clear()

    def clear(self):
        self.target = None
        self.ready_sample = None
        self.message = 'Look at a choice, then return to center.'

    @staticmethod
    def identity(ring):
        item = ring.slots()[ring.selected]
        return (ring.screen, ring.contact, ring.selected, item['action'], item['value'], item['text'], item['enabled'])

    def focus(self, ring, sample):
        self.target = (self.identity(ring), sample)
        self.ready_sample = None
        self.message = 'Return to center before double blinking.'

    def update(self, ring, detector, event=None):
        if detector.phase in ('retry', 'signal_lost', 'centering'):
            self.clear()
            self.message = 'Look center / Retry. Choose again when Ready.'
            return False
        if self.target is None:
            return False
        identity, sample = self.target
        if identity != self.identity(ring) or detector.raw_index - sample > 2500:
            self.clear()
            self.message = 'Choice expired or changed. Look at a choice again.'
            return False
        if detector.phase != 'ready':
            return False
        if self.ready_sample is None:
            self.ready_sample = detector.raw_index
            self.message = f"Double blink to choose {ring.slots()[ring.selected]['label']}."
        if not event or event.get('label') != 'double_blink' or event.get('reason') != 'blink':
            return False
        if (event.get('onset_sample', -1) < self.ready_sample
                or event.get('distance', 1) > .08
                or event.get('other_label_margin', 0) < 1.5
                or event.get('horizontal_fraction', 1) > .25):
            self.clear()
            self.message = 'Uncertain double blink. Look at the choice again.'
            return False
        self.clear()  # Consume before dispatch: never repeat on the same choice.
        ring.action('select', 'eog-communication')
        self.message = 'Selected. Look at another choice to continue.'
        return True
