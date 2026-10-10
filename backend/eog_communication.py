"""Explicitly enabled experimental confirmation of a freshly gazed-at item.

Consumes detector events, never raw threshold crossings. Quiet signals alone do
not establish physical center; recovery remains the detector's responsibility.
"""
class EOGConfirmation:
    def __init__(self, pulse_mode=False):
        self.pulse_mode=pulse_mode
        self.clear()

    def clear(self):
        self.target = None
        self.ready_sample = None
        self.confirmation_quiet_since = None
        self.settle_after_sample = -1
        self.retry_pending = False
        self.message = 'Look at a choice, then return to center.'

    @staticmethod
    def identity(ring):
        item = ring.slots()[ring.selected]
        return (ring.screen, ring.contact, ring.selected, item['action'], item['value'], item['text'], item['enabled'])

    def focus(self, ring, sample):
        self.target = (self.identity(ring), sample)
        self.ready_sample = None
        self.confirmation_quiet_since = None
        self.settle_after_sample = -1
        self.retry_pending = False
        self.message = 'Return to center before double blinking.'

    @staticmethod
    def blink_match(event):
        """Allow amplitude variation only when class separation is stronger.

        Reused-recording engineering policy, not validated wearer accuracy.
        """
        distance=event.get('distance',1)
        margin=event.get('other_label_margin',0)
        horizontal=event.get('horizontal_fraction',1)
        return ((distance <= .08 and margin >= 1.5 and horizontal <= .25)
                or (distance <= .2 and margin >= 2.5 and horizontal <= .1))

    @staticmethod
    def pulse_match(event):
        # Two causal pulses plus a pulse-anchored template, not a late recovery tail.
        return (event.get('pulse_pair_valid') is True
                and (event.get('waveform_label') in ('blink','double_blink') or event.get('distance',1)<=.08)
                and event.get('distance',1)<=.08
                and event.get('direction_margin',0)>=2
                and event.get('horizontal_fraction',1)<=.15)

    def update(self, ring, detector, event=None):
        if self.pulse_mode and event and event.get('label')=='double_blink' and event.get('source')!='pulse_stream':
            event=None  # Legacy window labels cannot confirm while pulse mode is active.
        double = event and event.get('label') == 'double_blink' and event.get('reason') == 'blink'
        if double:event['confirmation_result']='no_pending_choice'
        if detector.phase in ('retry', 'signal_lost', 'centering'):
            self.clear()
            self.message = 'Look center / Retry. Choose again when Ready.'
            return False
        if self.target is None:
            if self.message.startswith("Look center / Retry"):
                self.message = "Ready. Look at a choice, then return to center."
            return False
        identity, sample = self.target
        if identity != self.identity(ring) or detector.raw_index - sample > 2500:
            self.clear()
            self.message = 'Choice expired or changed. Look at a choice again.'
            return False
        if (event and event.get('label')=='return' and self.ready_sample is not None
                and event.get('onset_sample',-1)>=self.ready_sample):
            self.clear()
            self.message='Movement changed. Look at the choice again.'
            return False
        # Arm after an observed opposite return plus a short settling period.
        # Once armed, vertical blink activity must not restart that period.
        observed_return = (detector.phase == 'recovery'
            and getattr(detector,'return_sample',None) is not None)
        if observed_return and self.ready_sample is not None:
            settled = True
        elif observed_return:
            horizontal_quiet = abs(detector.horizontal) <= 400
            vertical_quiet = abs(getattr(detector,'vertical',0)) <= 400
            quiet = horizontal_quiet and (getattr(detector,'direction',None) in ('left','right') or vertical_quiet or self.ready_sample is not None)
            if quiet:
                if self.confirmation_quiet_since is None:
                    self.confirmation_quiet_since = detector.raw_index
            else:
                self.confirmation_quiet_since = None
                self.ready_sample = None
                if not horizontal_quiet:self.settle_after_sample = detector.raw_index
            # Classification arrives ~1 s after onset. Use the buffered signal
            # to establish when the return actually settled, not when its label
            # finally arrived. This prevents requiring a second settling wait.
            if self.ready_sample is None and horizontal_quiet:
                run = 0
                for index,h,v in getattr(detector,'recent_frames',()):
                    if index < max(detector.return_sample,self.settle_after_sample):continue
                    quiet_frame = abs(h)<=400 and (getattr(detector,'direction',None) in ('left','right') or abs(v)<=400)
                    run = run+1 if quiet_frame else 0
                    if run>=13:
                        self.ready_sample=index
                        break
            settled = (self.ready_sample is not None or
                       self.confirmation_quiet_since is not None and detector.raw_index-self.confirmation_quiet_since >= 63)
        else:
            settled = detector.phase == 'ready'
        if not settled:
            if double:event['confirmation_result']='return_to_center_first'
            return False
        if self.ready_sample is None:
            self.ready_sample = detector.raw_index
        self.message = ('Blink unclear. Keep looking center and double blink again.' if self.retry_pending
                        else f"Double blink to choose {ring.slots()[ring.selected]['label']}.")
        if not event or event.get('label') != 'double_blink' or event.get('reason') != 'blink':
            return False
        event['confirmation_armed_sample']=self.ready_sample
        if (event.get('onset_sample', -1) < self.ready_sample
                or not (self.pulse_match(event) if self.pulse_mode else self.blink_match(event))):
            event['confirmation_result']='early_blink' if event.get('onset_sample',-1)<self.ready_sample else 'uncertain_blink_match'
            if self.pulse_mode and event['confirmation_result']=='uncertain_blink_match':
                self.retry_pending = True
                self.message = 'Blink unclear. Keep looking center and double blink again.'
            else:
                self.clear()
                self.message = 'Uncertain double blink. Look at the choice again.'
            return False
        event['confirmation_result']='selected'
        self.clear()  # Consume before dispatch: never repeat on the same choice.
        ring.action('select', 'eog-communication')
        self.message = 'Selected. Look at another choice to continue.'
        return True
