"""TypeSafe Jev candidate ranking for self-hosted speech clips.

Candidate generation is deterministic; Jev only scores supplied transcript text.
No API key or transcript is written to logs. See docs/JEV_INTEGRATION_PLAN.md.
"""
import math
import os
import re

import httpx

from clip_selection import clip_count_targets, dedupe_overlapping

API_URL = 'https://api.typesafe.ai/v1/systemone'
RUBRIC = ['Very weak', 'Weak', 'Moderate', 'Strong', 'Excellent']
DIMENSIONS = {
    'hook': 'Does the opening quickly attract attention?',
    'standalone': 'Can the excerpt be understood without surrounding context?',
    'emotion': 'Does the excerpt have emotional impact?',
    'information': 'Does the excerpt convey useful information or insight?',
    'clarity': 'Is the transcript clear and coherent?',
    'boundaries': 'Does the excerpt start and end at natural complete thoughts?',
}


def selected():
    billing = os.getenv('BILLING_ENABLED', '').lower() in ('1', 'true', 'yes')
    return not billing and os.getenv('HIGHLIGHT_PROVIDER', '').strip().lower() == 'jev'


def configured():
    return selected() and bool(os.getenv('JEV_API_KEY', '').strip())


def model_name():
    return os.getenv('JEV_MODEL', 'jev-latest').strip() or 'jev-latest'


def describe():
    return {'provider': 'jev', 'model': model_name()} if configured() else None


def candidates(transcript, duration, min_seconds, max_seconds, limit=20):
    """Create bounded, overlapping speech windows across the entire source."""
    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0:
        return []
    words = []
    for segment in transcript.get('segments', []):
        for word in segment.get('words', []):
            try:
                start, end = float(word['start']), float(word['end'])
                text = str(word.get('word') or '')
            except (KeyError, TypeError, ValueError):
                continue
            if text.strip() and math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration:
                words.append((start, end, text))
    words.sort()
    if not words:
        return []
    span = min(max_seconds, max(min_seconds, 30.0), duration)
    step = max(span / 2, max(0.0, duration - span) / max(1, limit - 1))
    starts = [min(i * step, max(0.0, duration - span)) for i in range(limit)]
    starts = list(dict.fromkeys(round(s, 3) for s in starts))
    result = []
    for start in starts:
        end = min(duration, start + span)
        selected_words = [w for w in words if w[0] >= start and w[1] <= end]
        if not selected_words:
            continue
        text = ''.join(w[2] if w[2].startswith(' ') else ' ' + w[2] for w in selected_words).strip()
        if not text:
            continue
        # Cut at full word boundaries, within the requested duration.
        start, end = selected_words[0][0], selected_words[-1][1]
        if end - start < min_seconds and duration >= min_seconds:
            continue
        result.append({'id': f'candidate_{len(result)+1:03}', 'start': round(start, 3),
                       'end': round(end, 3), 'text': text})
    return result


def score_candidate(client, candidate, language):
    key = os.getenv('JEV_API_KEY', '').strip()
    if not key:
        raise ValueError('JEV_API_KEY is required for Jev highlight selection')
    payload = {'model': model_name(),
               'state': {'language': language, 'transcript': candidate['text'],
                         'duration_seconds': round(candidate['end'] - candidate['start'], 2)},
               'questions': {name: {'type': 'score', 'instructions': prompt, 'criteria': RUBRIC}
                             for name, prompt in DIMENSIONS.items()}}
    response = client.post(API_URL, headers={'Authorization': f'Bearer {key}'}, json=payload)
    # Avoid printing response bodies or credentials in failures.
    if response.status_code != 200:
        raise RuntimeError(f'Jev API request failed (HTTP {response.status_code})')
    data = response.json()
    answers = data.get('answers', {})
    scores = []
    for name in DIMENSIONS:
        answer = answers.get(name, {})
        try:
            score = float(answer['score'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f'Jev returned an invalid {name} score') from exc
        if answer.get('type') != 'score' or not math.isfinite(score) or not 0 <= score <= 4:
            raise ValueError(f'Jev returned an invalid {name} score')
        scores.append(score)
    return round(sum(scores) / len(scores) / 4 * 100)


def select(transcript, duration, min_seconds, max_seconds):
    if not configured():
        raise ValueError('Set HIGHLIGHT_PROVIDER=jev and JEV_API_KEY to use Jev')
    try:
        limit = min(100, max(1, int(os.getenv('JEV_MAX_CANDIDATES', '20'))))
    except ValueError:
        raise ValueError('JEV_MAX_CANDIDATES must be an integer') from None
    options = candidates(transcript, duration, min_seconds, max_seconds, limit)
    if not options:
        raise ValueError('Jev selection requires a transcript with word timestamps')
    print(f'Ranking {len(options)} transcript candidates with Jev; transcript text is sent to TypeSafe.', flush=True)
    clips = []
    with httpx.Client(timeout=60.0) as client:
        for candidate in options:
            score = score_candidate(client, candidate, transcript.get('language', 'unknown'))
            # Jev scores rather than writes copy; use source words as a neutral title.
            title = re.sub(r'\s+', ' ', candidate['text']).strip()[:100]
            clips.append({'start': candidate['start'], 'end': candidate['end'],
                          'source_window_id': candidate['id'], 'predicted_score': score,
                          'video_description_for_tiktok': title,
                          'video_description_for_instagram': title,
                          'video_title_for_youtube_short': title,
                          'viral_hook_text': '', 'why': 'Ranked from transcript by Jev.'})
    clips = dedupe_overlapping(clips)
    _, max_clips = clip_count_targets(len(options))
    selected_clips = sorted(sorted(clips, key=lambda c: -c['predicted_score'])[:max_clips], key=lambda c: c['start'])
    return {'shorts': selected_clips}
