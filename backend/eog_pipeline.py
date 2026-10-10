"""Transport-free EOG contract: numeric samples and choices in, state/events out."""
from dataclasses import asdict
from copy import deepcopy
from .guided_eog import GuidedConfig, GuidedEOGTest
from .eog_communication import EOGConfirmation

SCHEMA_VERSION = 1
SLOTS = {'up': 0, 'right': 2, 'down': 4, 'left': 6}
EVENT_TYPES = {'gaze_candidate','gaze_accepted','return','blink','double_blink','selection','fault','reset'}


def validate_event(event):
    if event.get('schema_version')!=SCHEMA_VERSION or event.get('type') not in EVENT_TYPES:
        raise ValueError('Unsupported EOG event contract')
    if type(event.get('sample_index')) is not int or not isinstance(event.get('event_id'),int):
        raise ValueError('Integer sample index and event ID required')
    if event['type']=='selection' and (event.get('slot') not in SLOTS.values() or 'choice_id' not in event):
        raise ValueError('Selection must identify the confirmed cardinal choice')
    return event


class EOGPipeline:
    """No HTTP, ring, browser, serial, filesystem, or speech dependencies.

    The adapter supplies current choice identities and a selected slot; identities
    must change with text/contact/context. The adapter alone executes selections.
    """
    def __init__(self, profile, config=GuidedConfig(), detector=None, confirmation=None):
        self.detector=detector or GuidedEOGTest(profile,config)
        self.confirmation=confirmation or EOGConfirmation(pulse_mode=config.pulse_confirmation)
        self.choices={};self.selected=None;self.sequence=0;self.pending_events=[]
        self.communication=False
        self.input_index=-1

    def set_choices(self, choices, selected):
        self.choices={int(slot):dict(choice) for slot,choice in choices.items()}
        self.selected=selected
        choice=self.choices.get(selected,{})
        if self.confirmation.target and self.confirmation.target[0]!=choice.get('id'):
            self.confirmation.clear()

    def _emit(self, kind, **data):
        self.sequence+=1
        offset=self.input_index-self.detector.raw_index
        data=deepcopy(data)
        if 'onset_sample' in data:data['onset_sample']+=offset
        if 'decision' in data:
            for key in ('onset_sample','emitted_sample','confirmation_armed_sample'):
                if key in data['decision']:data['decision'][key]+=offset
            pair=data['decision'].get('pulse_pair')
            if pair:
                for pulse in (pair['first'],pair['second']):
                    for key in ('onset_sample','peak_sample','end_sample'):pulse[key]+=offset
        event=dict(schema_version=SCHEMA_VERSION,type=kind,event_id=self.sequence,
                   sample_index=self.input_index,**data)
        validate_event(event);self.pending_events.append(event)
        return event

    def reset(self, cause='manual'):
        self.detector.reset(cause=cause);self.confirmation.clear()
        self._emit('reset',cause=cause)

    def fault(self, reason):
        self.detector.fault(reason);self.confirmation.clear()
        self._emit('fault',reason=reason)

    def state(self):
        offset=self.input_index-self.detector.raw_index
        return dict(schema_version=SCHEMA_VERSION,sample_index=self.input_index,
                    phase=self.detector.phase,reason=self.detector.reason,
                    pending=self.confirmation.target is not None,
                    armed=self.confirmation.ready_sample is not None,
                    armed_sample=self.confirmation.ready_sample+offset if self.confirmation.ready_sample is not None else None,
                    expires_sample=self.confirmation.target[1]+2500+offset if self.confirmation.target else None,
                    confirmation=self.confirmation.message,selected_slot=self.selected,
                    horizontal=self.detector.horizontal,vertical=self.detector.vertical,
                    units='filtered_adc_counts',sample_rate_hz=250,filtered_rate_hz=50,
                    profile_sha256=self.detector.profile.digest,settings=asdict(self.detector.config))

    def process(self,h,v,timestamp_ms=None,*,sample_index=None,communication=None):
        if communication is not None:self.communication=bool(communication)
        self.input_index=self.input_index+1 if sample_index is None else sample_index
        prior=self.detector.last_result;prior_pair=self.detector.last_blink_result
        faults=self.detector.totals['faults']
        slot=self.detector.process(h,v,timestamp_ms)
        if self.detector.totals['faults']!=faults:self._emit('fault',reason=getattr(self.detector,'last_fault_reason',self.detector.reason))
        event=self.detector.last_result if self.detector.last_result is not prior or slot is not None else None
        if event:
            label=event['label']
            kind='gaze_accepted' if slot is not None else label if label in ('return','blink','double_blink') else 'gaze_candidate'
            self._emit(kind,decision=dict(event),slot=slot)
        if slot is not None:
            self.confirmation.clear()
            choice=self.choices.get(slot)
            if choice and choice.get('enabled',True):
                self.selected=slot
                if self.communication:self.confirmation.focus_choice(choice['id'],self.detector.raw_index)
        pair=self.detector.last_blink_result
        fresh_pair=pair is not None and pair is not prior_pair
        if fresh_pair:self._emit('double_blink',decision=dict(pair),slot=None)
        choice=self.choices.get(self.selected,{})
        if self.communication:
            for candidate in ([event,pair] if fresh_pair else [event]):
                if self.confirmation.update_choice(choice.get('id'),choice.get('label','choice'),self.detector,candidate):
                    candidate['communication_selected']=True
                    self._emit('selection',slot=self.selected,choice_id=choice['id'],
                               onset_sample=candidate['onset_sample'],confirmation='double_blink')
        else:self.confirmation.clear()
        result=dict(state=self.state(),events=self.pending_events)
        self.pending_events=[]
        return result
