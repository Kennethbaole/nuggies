"""Server-timed acquisition cues; labels indicate instructions, not detected events."""
import math
import secrets


def protocol(mode="horizontal"):
    if mode not in ("horizontal", "vertical", "double_blink", "diagnostic", "speed"):
        raise ValueError("Unknown guided protocol")
    steps = [(5, 'unlabeled', 'prepare', 'prepare', 'Get ready. Keep your head still and cables resting.')]
    if mode == 'speed':
        steps.append((5,'neutral','baseline','baseline','Look at CENTER. Wait for the direction cue.'))
        counts={label:0 for label in ('left','right','up','down')}
        for label in ('up','left','down','right','left','up','right','down','right','down','left','up'):
            counts[label]+=1;trial=f'{label}-{counts[label]}'
            steps.extend([(2,'neutral',trial,'prepare','Look at CENTER. Wait for the next cue.'),
                          (3,label,trial,'movement',f'Look {label.upper()} now.'),
                          (5,'neutral',trial,'return','Return to CENTER. Wait for Ready.')])
        return steps
    if mode == 'diagnostic':
        steps.append((10,'neutral','baseline','baseline','Look straight ahead. Blink naturally.'))
        for repeat in range(1,3):
            for label in ('left','right','up','down','blink','double_blink'):
                trial=f"{label.replace('_','-')}-{repeat}"
                cue=('BLINK once naturally.' if label=='blink' else 'BLINK TWICE naturally, about half a second apart.' if label=='double_blink' else f'Look {label.upper()} now and hold.')
                steps.extend([(3,'neutral',trial,'prepare','Look at CENTER. Wait for the instruction.'),
                              (2,label,trial,'movement',cue),
                              (6,'neutral',trial,'return','Return to CENTER and rest. Wait for Ready.')])
        steps.append((10,'neutral','final-baseline','baseline','Look straight ahead. Blink naturally.'))
        return steps
    if mode == 'double_blink':
        steps.append((10, 'neutral', 'baseline', 'baseline', 'Look straight ahead. Blink naturally.'))
        for repeat in range(1, 6):
            trial = f'double-blink-{repeat}'
            steps.extend([(3, 'neutral', trial, 'prepare', 'Look at the center. Get ready.'),
                          (3, 'double_blink', trial, 'movement', 'BLINK TWICE naturally, about half a second apart.'),
                          (4, 'neutral', trial, 'rest', 'Look at the center and rest.')])
        steps.append((10, 'neutral', 'final-baseline', 'baseline', 'Look straight ahead. Blink naturally.'))
        return steps
    steps.append((20, 'neutral', 'baseline', 'baseline', 'Look straight ahead. Blink naturally.'))
    for repeat in range(1, 6):
        for direction in (('left', 'right') if mode == 'horizontal' else ('up', 'down')):
            trial = f'{direction}-{repeat}'
            steps.extend([(3, 'neutral', trial, 'prepare', 'Look at the center. Get ready.'),
                          (2, direction, trial, 'movement', f'Look {direction.upper()} now and hold.'),
                          (4, 'neutral', trial, 'return', 'Return to CENTER and rest.')])
    for repeat in range(1, 6):
        trial = f'blink-{repeat}'
        steps.extend([(3, 'neutral', trial, 'prepare', 'Look at the center. Get ready.'),
                      (2, 'blink', trial, 'movement', 'BLINK once naturally. Do not squeeze.'),
                      (3, 'neutral', trial, 'rest', 'Look at the center and rest.')])
    if mode == 'vertical':
        for repeat in range(1, 6):
            trial = f'double-blink-{repeat}'
            steps.extend([(3, 'neutral', trial, 'prepare', 'Look at the center. Get ready.'),
                          (3, 'double_blink', trial, 'movement', 'BLINK TWICE naturally, about half a second apart.'),
                          (4, 'neutral', trial, 'rest', 'Look at the center and rest.')])
    steps.append((20, 'neutral', 'final-baseline', 'baseline', 'Look straight ahead. Blink naturally.'))
    return steps


class GuidedTrial:
    def __init__(self):
        self.started = None
        self.status = 'idle'
        self.run_id = ''
        self.mode = 'horizontal'
        self.steps = protocol()
        self.paused_at=None
        self.paused_total=0

    def start(self, now, mode="horizontal"):
        if self.status == 'running':
            raise ValueError('A guided test is already running')
        steps = protocol(mode)
        self.mode, self.steps = mode, steps
        self.started = now
        self.paused_at=None;self.paused_total=0
        self.run_id = secrets.token_hex(8)
        self.status = 'running'

    def pause(self,now,paused):
        if self.status!='running':return
        if paused and self.paused_at is None:self.paused_at=now
        elif not paused and self.paused_at is not None:
            self.paused_total+=max(0,now-self.paused_at);self.paused_at=None

    def stop(self):
        self.status = 'stopped'
        self.paused_at=None

    def snapshot(self, now):
        result = dict(status=self.status, run_id=self.run_id, protocol=self.mode, label='unlabeled', trial_id='', phase='',
                      cue='Start a guided test when ready.', remaining_s=0,paused=self.paused_at is not None)
        if self.status != 'running':
            if self.status == 'complete': result['cue'] = 'Test complete. Recording continues until stopped.'
            if self.status == 'stopped': result['cue'] = 'Test stopped. Recording continues.'
            return result
        elapsed = max(0, (self.paused_at if self.paused_at is not None else now) - self.started - self.paused_total)
        offset = 0
        for index, (duration, label, trial, phase, cue) in enumerate(self.steps):
            if elapsed < offset + duration:
                result.update(label=label, trial_id=trial, phase=phase, cue=cue,
                              remaining_s=math.ceil(offset + duration - elapsed),phase_elapsed_s=round(elapsed-offset,4),
                              step=index + 1, total_steps=len(self.steps))
                if self.paused_at is not None:result['cue']='Look center / Retry. Waiting for Ready before the next instruction.'
                return result
            offset += duration
        self.status = 'complete'
        return self.snapshot(now)
