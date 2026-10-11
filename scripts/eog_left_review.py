"""Summarize private Left decisions without assigning intent or touching hardware."""
import argparse
from collections import Counter
import json
from pathlib import Path

from backend.eog_waveform import WaveformProfile


def review(log_path, profile_path):
    rows = [json.loads(line) for line in Path(log_path).read_text().splitlines() if line.strip()]
    session = next(row for row in rows if row['kind'] == 'session')
    profile = WaveformProfile.load(profile_path)
    if profile.digest != session['profile_sha256']:
        raise ValueError('Profile does not match the recorded decisions')
    decisions = [row for row in rows if row['kind'] == 'decision' and 'classification' in row]
    left = [row for row in decisions if row['event'].get('candidate') == 'left']
    cases = []
    for row in left:
        event = row['event']
        result = profile.classify(row['classification']['window'])
        if result['label'] != 'left' or round(result['distance'], 6) != round(event['distance'], 6):
            raise ValueError(f"Saved classification does not reproduce at {row['sample_index']}")
        scores = row['classification']['best_distances']
        competitor = min((label for label in scores if label not in ('left','blink','double_blink')), key=scores.get)
        cases.append(dict(sample_index=row['sample_index'], reason=event['reason'],
                          distance=event['distance'], blink_margin=event['blink_margin'],
                          direction_margin=event['direction_margin'],
                          horizontal_fraction=event['horizontal_fraction'],
                          competing_direction=competitor,
                          best_distances=scores))
    return dict(evidence='Unlabelled live windows; these counts are not hits or accuracy.',
                profile_sha256=profile.digest, settings=session['settings'],
                candidate_reasons=dict(Counter(row['event']['reason'] for row in left)),
                cases=cases, intended_misses=None, false_confirmations=None,
                limits=['Returns are intentionally consumed; logs do not establish physical intention.',
                        'Saved-window reproduction checks classification, not full-stream state.',
                        'No inference about deliberate versus natural blinks is possible.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('events');parser.add_argument('--profile', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if not output.is_relative_to(Path('recordings').resolve()):
        parser.error('Private report must be under recordings/')
    result = review(args.events, args.profile)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False))
    print(json.dumps({key: result[key] for key in ('evidence','candidate_reasons','intended_misses','false_confirmations')}))


if __name__ == '__main__':
    main()
