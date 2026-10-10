"""Server-timed acquisition cues; labels indicate instructions, not detected events."""
import math
import secrets


def protocol():
    steps = [(5, 'unlabeled', 'prepare', 'prepare', 'Get ready. Keep your head still and cables resting.')]
    steps.append((20, 'neutral', 'baseline', 'baseline', 'Look straight ahead. Blink naturally.'))
    for repeat in range(1, 6):
        for direction in ('left', 'right'):
            trial = f'{direction}-{repeat}'
            steps.extend([(3, 'neutral', trial, 'prepare', 'Look at the center. Get ready.'),
                          (2, direction, trial, 'movement', f'Look {direction.upper()} now and hold.'),
                          (4, 'neutral', trial, 'return', 'Return to CENTER and rest.')])
    for repeat in range(1, 6):
        trial = f'blink-{repeat}'
        steps.extend([(3, 'neutral', trial, 'prepare', 'Look at the center. Get ready.'),
                      (2, 'blink', trial, 'movement', 'BLINK once naturally. Do not squeeze.'),
                      (3, 'neutral', trial, 'rest', 'Look at the center and rest.')])
    steps.append((20, 'neutral', 'final-baseline', 'baseline', 'Look straight ahead. Blink naturally.'))
    return steps


class GuidedTrial:
    def __init__(self):
        self.started = None
        self.status = 'idle'
        self.run_id = ''
        self.steps = protocol()

    def start(self, now):
        if self.status == 'running':
            raise ValueError('A guided test is already running')
        self.started = now
        self.run_id = secrets.token_hex(8)
        self.status = 'running'

    def stop(self):
        self.status = 'stopped'

    def snapshot(self, now):
        result = dict(status=self.status, run_id=self.run_id, label='unlabeled', trial_id='', phase='',
                      cue='Start a guided test when ready.', remaining_s=0)
        if self.status != 'running':
            if self.status == 'complete': result['cue'] = 'Test complete. Recording continues until stopped.'
            if self.status == 'stopped': result['cue'] = 'Test stopped. Recording continues.'
            return result
        elapsed = max(0, now - self.started)
        offset = 0
        for index, (duration, label, trial, phase, cue) in enumerate(self.steps):
            if elapsed < offset + duration:
                result.update(label=label, trial_id=trial, phase=phase, cue=cue,
                              remaining_s=math.ceil(offset + duration - elapsed),
                              step=index + 1, total_steps=len(self.steps))
                return result
            offset += duration
        self.status = 'complete'
        return self.snapshot(now)
