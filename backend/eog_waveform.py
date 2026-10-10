"""Frozen two-channel waveform matching with no ML/runtime dependencies."""
import json
import hashlib
import math
from pathlib import Path
from backend.blink_shape import blink_shape

DIRECTIONS = {'left': 6, 'right': 2, 'up': 0, 'down': 4}
LABELS = set(DIRECTIONS) | {'blink', 'double_blink'}


def haar(values, width=10):
    """Causal adjacent-window contrast; width is samples at 50 Hz, not a paper scale."""
    return [sum(values[i-width:i])/width-sum(values[i-2*width:i-width])/width
            for i in range(2*width, len(values)+1)]


class WaveformProfile:
    def __init__(self, profile):
        try:
            self.labels = profile['labels']
            self.waves = profile['waves']
            self.scale = tuple(profile['scale'])
            self.thresholds = (profile['threshold_h'], profile['threshold_v'])
            if (profile.get('version') != 1 or profile.get('capture_s') != 1
                    or not 1 <= len(self.labels) <= 256 or len(self.waves) != len(self.labels)
                    or not all(isinstance(label, str) and label in LABELS for label in self.labels)
                    or not set(DIRECTIONS).issubset(self.labels)
                    or not {'blink','double_blink'}.intersection(self.labels)
                    or len(self.scale) != 2
                    or not all(type(x) in (int,float) and math.isfinite(x) and x > 0
                               for x in (*self.scale,*self.thresholds))):
                raise ValueError('Invalid waveform profile settings')
            if any(len(wave) != 50 or any(len(frame) != 2 or
                   any(type(x) not in (int,float) or not math.isfinite(x) or abs(x)>2 for x in frame)
                   for frame in wave) for wave in self.waves):
                raise ValueError('Invalid waveform profile arrays')
        except (KeyError, TypeError) as error:
            raise ValueError('Invalid waveform profile') from error
        self.digest=hashlib.sha256(json.dumps(profile,sort_keys=True,allow_nan=False).encode()).hexdigest()
        self.haar = [haar([frame[1] for frame in wave]) for wave in self.waves]

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 2_000_000:
            raise ValueError('Waveform profile is too large')
        return cls(json.loads(path.read_text()))

    def classify(self, samples, haar_weight=0):
        if len(samples) != 50 or any(len(x) != 2 or not all(math.isfinite(y) for y in x) for x in samples):
            raise ValueError('Expected 50 finite two-channel frames')
        x = [tuple(max(-2,min(2,frame[i]/self.scale[i])) for i in (0,1)) for frame in samples]
        contrast = haar([frame[1] for frame in x])
        distances = []
        for wave, template in zip(self.waves,self.haar):
            distance = min(sum((wave[j+a][axis]-x[j+b][axis])**2
                              for j in range(50-abs(shift)) for axis in (0,1)) /
                           (2*(50-abs(shift)))
                           for shift in range(-4,5,2)
                           for a,b in [(max(0,shift),max(0,-shift))])
            if haar_weight:
                distance += haar_weight*sum((a-b)**2 for a,b in zip(contrast,template))/len(contrast)
            distances.append(distance)
        self.last_distances = list(distances)  # Observational: preserve every template score for private replay logs.
        best = min(range(len(distances)),key=distances.__getitem__)
        label = self.labels[best];distance = distances[best]
        blink = min(d for d,l in zip(distances,self.labels) if l not in DIRECTIONS)
        competing = min((d for d,l in zip(distances,self.labels) if l in DIRECTIONS and l!=label),default=math.inf)
        other = min((d for d,l in zip(distances,self.labels) if l != label), default=math.inf)
        energy=[sum(frame[i]**2 for frame in x) for i in (0,1)]
        horizontal_fraction=energy[0]/max(sum(energy),1e-9)
        return dict(**blink_shape(samples), other_label_margin=other/max(distance,1e-9),horizontal_fraction=horizontal_fraction,label=label, distance=distance, blink_margin=blink/max(distance,1e-9),
                    direction_margin=competing/max(distance,1e-9))
