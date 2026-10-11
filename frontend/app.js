import {drawHUD, downloadFrame} from './hud.js';

const $ = id => document.getElementById(id);
const isHUD = location.pathname === '/hud';
if (isHUD) { document.body.classList.add('hud-body'); $('hud-only').hidden = false; }
let state = null, seenSelection = null, session = null, audioEnabled = false;
let selectedFlashUntil = 0;
let workspaceView = 'wheel', workspaceSwitchBusy = false;
let token = sessionStorage.getItem('nuggies-token') || '';
let queue = Promise.resolve(), audio = null, speechBusy = false, pollBusy = false;
const PROVIDER_LABELS = {'quick-replies': 'Direct reply choices', ollama: 'On-device AI reply suggestions', preset: 'Default choices'};
const SETUP_HINT = 'Set OLLAMA_MODEL in .env (with Ollama running) and restart to enable reply suggestions.';
const LISTEN_HINT = 'Set ASR_URL to the Qwen speech-to-text service in .env and restart to enable listening.';
let requestCounter = 0, recorder = null, recordTimer = null, suggesting = false;
const clientID = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
let lastConnected = null;
const slotButtons = [];
for (let i = 0; i < 8; i++) {
  const button = document.createElement('button'); button.className = 'slot'; button.dataset.slot = String(i);
  const angle = i * Math.PI / 4;
  // Unit direction; CSS sets the radius so eye-control mode can pull choices toward the centre.
  button.style.setProperty('--sx', Math.sin(angle).toFixed(4));
  button.style.setProperty('--sy', (-Math.cos(angle)).toFixed(4));
  button.addEventListener('click', () => command('focus', i));
  $('slots').append(button); slotButtons.push(button);
}

async function api(path, payload) {
  const headers = {'Authorization': `Bearer ${token}`};
  if (payload !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {method: payload === undefined ? 'GET' : 'POST', headers,
    body: payload === undefined ? undefined : JSON.stringify(payload), signal: AbortSignal.timeout(18000)});
  if (response.status === 401) {
    if (!$('token-dialog').open) $('token-dialog').showModal();
    throw new Error('A session token is needed to connect.');
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const exception = new Error(error.error || `Request failed (${response.status})`);
    exception.status = response.status;
    throw exception;
  }
  return response;
}

function feedback(text) { $('feedback').textContent = text; }
function command(action, value) {
  if (isHUD) return Promise.resolve();
  queue = queue.then(async () => {
    const response = await api('/api/action', {action, value, event_id: `${clientID}-${++requestCounter}`});
    render(await response.json());
    if (action === 'blink') feedback('Blink sent. A second blink within the test window selects.');
  }).catch(error => feedback(error.message));
  return queue;
}

function browserSpeak(text) {
  if (!('speechSynthesis' in window)) { feedback('Speech is unavailable on this browser. Your sentence is still displayed.'); return; }
  speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text); utterance.rate = 1;
  utterance.onerror = () => feedback('Browser speech could not play. Your sentence remains visible.');
  speechSynthesis.speak(utterance);
}

async function speakSelection(snapshot) {
  if (!audioEnabled || isHUD || speechBusy || !snapshot.confirmed || (snapshot.wheel_test && !snapshot.eog_communication) || snapshot.source === 'eye-wheel-test') return;
  speechBusy = true;
  try {
    const response = await api('/api/speech', {selection_id: snapshot.selection_id, session_id: snapshot.session_id});
    if (!audioEnabled) return;
    if (response.headers.get('content-type')?.includes('audio')) {
      if (audio) audio.pause();
      const url = URL.createObjectURL(await response.blob());
      audio = new Audio(url); audio.onended = audio.onerror = () => URL.revokeObjectURL(url);
      try { await audio.play(); feedback('Speaking with your configured voice.'); }
      catch { URL.revokeObjectURL(url); browserSpeak(snapshot.confirmed); feedback('Cloud audio could not play; using browser speech.'); }
    } else { browserSpeak(snapshot.confirmed); feedback('Speaking with browser voice.'); }
  } catch (error) {
    if (error.status === 409) feedback('Another companion already claimed this utterance.');
    else if (error.status === 503 && audioEnabled) { browserSpeak(snapshot.confirmed); feedback('Cloud speech unavailable; using browser voice.'); }
    else feedback(error.message);
  } finally { speechBusy = false; }
}

function render(next) {
  if (state && next.session_id === state.session_id && next.revision < state.revision) return;
  state = next;
  if (session !== state.session_id) {
    session = state.session_id; seenSelection = state.selection_id;
  }
  if (state.selection_id > seenSelection) {
    seenSelection = state.selection_id;
    feedback(`Selected: ${state.confirmed}`);
    selectedFlashUntil = Date.now() + 1500;
    speakSelection({...state});
  }
  const contact = state.contacts.find(contact => contact.id === state.contact);
  if ($('contact').options.length !== state.contacts.length) {  // Members can be added on /community.
    $('contact').textContent = '';
    for (const item of state.contacts) {
      const option = document.createElement('option'); option.value = item.id; option.textContent = item.name;
      $('contact').append(option);
    }
  }
  $('contact').value = state.contact; $('avatar').textContent = contact.initials;
  $('avatar').dataset.tone = String(contact.tone ?? state.contacts.indexOf(contact) % 6);
  $('relationship').textContent = [contact.relationship, contact.pronouns, state.has_notes && 'notes'].filter(Boolean).join(' · ');
  $('phone-contact').textContent = `With ${contact.name}`;
  $('screen-name').textContent = state.screen === 'spell' ? 'SPELL YOUR WORDS' : state.screen === 'needs' ? 'EVERYDAY NEEDS' : 'CONVERSATION';
  $('page-info').textContent = state.screen === 'spell' ? 'Two groups, one letter at a time' : `Phrase set ${state.page + 1} · ${PROVIDER_LABELS[state.suggestions_provider] || 'curated demo'}`;
  state.slots.forEach((slot, index) => {
    const button = slotButtons[index];
    button.textContent = slot.label; button.disabled = !slot.enabled;
    button.style.visibility = slot.action === 'none' ? 'hidden' : '';  // e.g. the removed Spell position
    button.classList.toggle('selected', !state.wheel_test && state.selected === index);
    button.classList.toggle('utility', ['more', 'spell', 'back', 'space', 'delete', 'speak'].includes(slot.action));
    button.setAttribute('aria-pressed', String(!state.wheel_test && state.selected === index));
    button.setAttribute('aria-label', `${slot.label}${slot.text ? ': ' + slot.text : ''}${!state.wheel_test && state.selected === index ? ', highlighted' : ''}`);
  });
  const center = state.screen === 'spell' ? state.draft || 'Choose your letters.' : state.confirmed || 'Your words, at your pace.';
  $('center-text').textContent = center; $('phone-text').textContent = state.confirmed || 'Your words, at your pace.';
  $('center-label').textContent = state.screen === 'spell' ? 'YOUR DRAFT' : state.confirmed ? 'YOUR LAST SELECTION' : 'READY WHEN YOU ARE';
  $('preview-label').textContent = state.wheel_test ? 'EYE TEST' : 'HIGHLIGHTED';
  $('preview-text').textContent = state.preview || `${state.slots[state.selected].label} — ${state.wheel_test ? 'direction test · speech off' : 'double blink to choose'}`;
  $('center-footer').textContent = state.wheel_test ? 'Read direction in test status' : state.screen === 'spell' ? 'Choose Speak when ready' : 'Double blink to choose';
  const synthetic = state.input_mode === 'demo';
  $('source-name').textContent = synthetic ? (state.demo_running ? 'Synthetic signal scenario' : 'Keyboard demonstration') : state.input_mode === 'serial' ? 'Nano USB · raw ADC' : 'Recorded ADC replay';
  $('input-detail').textContent = state.wheel_test ? 'Experimental eye wheel control active. Speech disabled.' : synthetic ? 'No glasses or electrodes needed.' : state.sensor_actions ? 'Calibrated navigation enabled. Blink detection pending.' : 'Monitoring only. Sensor navigation is disabled.';
  $('scenario').disabled = !synthetic;
  $('scenario').textContent = state.demo_running ? 'Stop signal scenario' : 'Run signal scenario';
  $('scenario').classList.toggle('running', state.demo_running);
  $('connection').textContent = state.connected ? (synthetic ? 'Demo session' : 'Input connected') : 'Input paused';
  $('connection').classList.toggle('disconnected', !state.connected);
  $('phone-live').textContent = state.connected ? '● Connected' : '○ Input paused';
  $('input-error').textContent = state.input_error;
  $('wheel-test-toggle').textContent = state.wheel_test ? 'Stop eye wheel test' : 'Start experimental eye wheel test';
  $('wheel-test-toggle').setAttribute('aria-pressed', String(Boolean(state.wheel_test)));
  $('wheel-test-toggle').disabled = !state.wheel_test && ((state.input_mode !== 'serial' && !(state.input_mode === 'replay' && state.eog_engine === 'waveform')) || !state.connected || state.sensor_actions || state.guided?.status === 'running');
  $('wheel-test-stop').disabled = !state.wheel_test;
  const gaze = state.gaze_hover;
  $('wheel-test-status').textContent = state.wheel_test
    ? `${state.wheel_message}${gaze?.slot != null ? ' → ' + state.slots[gaze.slot].label : ''}` : 'Eye wheel control off';
  $('gaze-readings').textContent = state.wheel_test && gaze
    ? `EOG deviation · Horizontal ${gaze.horizontal} · Vertical ${gaze.vertical} ADC counts · ${gaze.phase}` : '';
  const guidedEOG = state.eog_engine === 'waveform';
  $('eog-guidance').hidden = !guidedEOG;
  $('speed-test-start').hidden = !guidedEOG;
  $('speed-test-start').disabled = !state.connected || !state.recording || Boolean(state.pending_eog_check) || state.guided?.status === 'running';
  const speedAttempts = state.speed_results || [];
  const lastSpeed = [...speedAttempts].reverse().find(x => x.detected);
  $('speed-test-results').textContent = state.pending_eog_check ? 'Centering before the speed check…'
    : speedAttempts.length ? `${speedAttempts.filter(x => x.complete).length}/12 attempts complete · ${speedAttempts.filter(x => x.correct).length} matched${lastSpeed ? ` · Last: ${lastSpeed.cue_to_detection_ms} ms cue-to-response${lastSpeed.early_candidate ? ' (started before cue)' : ''}` : ''}${state.speed_median_ms != null ? ` · Median ${state.speed_median_ms} ms (includes reaction time)` : ''}` : '';

  if (state.wheel_test && guidedEOG) {
    const cueActive = ['diagnostic', 'speed'].includes(state.guided?.protocol) && state.guided?.status === 'running';
    const title = gaze?.phase === 'retry' ? 'Look center / Retry' : gaze?.phase === 'centering' ? 'Look straight ahead'
      : gaze?.phase === 'signal_lost' ? 'Signal interrupted' : gaze?.direction ? `${gaze.direction.toUpperCase()} detected` : 'Ready';
    $('center-label').textContent = cueActive ? 'LIVE EYE SIGNAL CHECK' : 'EYE SIGNAL TEST';
    $('center-text').textContent = gaze?.needs_retry ? title : cueActive ? state.guided.cue : title;
    $('center-footer').textContent = gaze?.phase === 'ready' ? 'One direction, then center · speech off'
      : gaze?.phase === 'recovery' ? 'Return to center · wait for Ready' : `${Math.round((gaze?.progress || 0) * 100)}% clean rest`;
    $('preview-text').textContent = gaze?.direction ? `${gaze.direction.toUpperCase()} → ${state.slots[gaze.slot].label}`
      : gaze?.last_event ? `Last reading: ${gaze.last_event.label} · ${gaze.last_event.reason.replaceAll('_', ' ')}` : title;
  }
  if (state.wheel_test && state.guided?.protocol === 'speed' && gaze?.direction && lastSpeed) {
    $('preview-text').textContent += ` · ${(lastSpeed.cue_to_detection_ms / 1000).toFixed(2)}s response`;
  }
  $('eog-communication-toggle').textContent = state.eog_communication ? 'Stop gaze + double-blink communication' : 'Start gaze + double-blink communication';
  $('eog-communication-toggle').setAttribute('aria-pressed', String(Boolean(state.eog_communication)));
  $('eog-communication-toggle').disabled = !state.eog_communication && (!state.connected || !guidedEOG || state.input_mode !== 'serial' || state.guided?.status === 'running');
  document.body.classList.toggle('communication-active', Boolean(state.eog_communication));
  if (!state.eog_communication) document.querySelector('.preview').classList.remove('confirmation-ready');
  $('eog-mode-help').textContent = state.eog_communication ? 'Communication is on: choose a reply, return to Ready, then double blink to confirm.' : 'In navigation checks, blinks are observed without selection or speech.';
  $('eog-communication-status').textContent = state.eog_communication ? state.eog_confirmation : 'Experimental: gaze chooses; return to center, then double blink confirms. Single blinks do nothing.';
  if (state.eog_communication) {
    $('center-label').textContent = 'GAZE + DOUBLE BLINK';
    const choice = state.slots[state.selected];
    const pending = Boolean(state.eog_choice_pending);
    $('center-text').textContent = pending ? choice.label : gaze?.phase === 'ready' ? 'Choose a reply' : gaze?.needs_retry ? 'Look center / Retry' : 'Look straight ahead';
    $('center-footer').textContent = state.eog_confirmation_ready ? 'Ready to confirm · double blink' : pending ? 'Detected · return to center' : gaze?.phase === 'ready' ? 'Look left or right for a reply' : `${Math.round((gaze?.progress || 0) * 100)}% clean rest`;
    if (state.eog_paused) { $('center-text').textContent = 'Paused'; $('center-footer').textContent = 'Look around · double blink at center to resume'; }
    $('preview-label').textContent = pending ? 'DETECTED CHOICE · NOT YET SELECTED' : 'NO PENDING CHOICE';
    $('preview-text').textContent = pending ? choice.text || choice.label : 'Look at an option. Your detected choice will appear here before you confirm.';
    document.querySelector('.preview').classList.toggle('confirmation-ready', Boolean(state.eog_confirmation_ready));
    $('wheel-test-status').textContent = gaze?.phase === 'ready' ? state.eog_confirmation : gaze?.message;
    $('input-detail').textContent = audioEnabled ? 'Experimental gaze and double-blink communication. Confirmed replies are spoken.' : 'Experimental gaze and double-blink communication. Speech is off; Enable speech to hear confirmed replies.';
    $('page-info').textContent = 'Two replies · More · Back';
  }
  // One peripheral-vision colour per interaction state; text alone is unreadable while gazing elsewhere.
  const eogCue = !state.wheel_test || !guidedEOG || !state.connected ? ''
    : Date.now() < selectedFlashUntil ? 'selected'
    : state.eog_paused ? 'paused'
    : gaze?.phase === 'retry' ? 'retry'
    : gaze?.phase !== 'ready' && gaze?.phase !== 'recovery' ? 'wait'
    : state.eog_confirmation_ready ? 'confirm'
    : state.eog_choice_pending || gaze?.phase === 'recovery' ? 'detected' : 'ready';
  if (eogCue) document.body.dataset.eogCue = eogCue; else delete document.body.dataset.eogCue;
  $('eog-cue-legend').hidden = !eogCue;
  $('eog-recenter').disabled = !state.wheel_test || !state.connected;
  $('eog-progress').value = state.wheel_test ? (gaze?.progress || 0) : 0;
  const lastEOG = gaze?.last_event;
  $('eog-event').textContent = state.wheel_test && lastEOG
    ? `Last reading: ${lastEOG.label} · ${lastEOG.reason.replaceAll('_', ' ')}` : '';
  $('eog-quality').textContent = state.wheel_test && gaze?.totals
    ? `Directions ${gaze.totals.accepted} · Retries ${gaze.totals.rejected} · Blink events ${gaze.totals.blinks} · Signal interruptions ${gaze.totals.faults}${gaze.waiting_too_long ? ' · Check electrode contact or recenter' : ''}` : '';
  if (state.wheel_test && !state.eog_communication && audioEnabled) {
    audioEnabled = false; audio?.pause();
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    $('audio-toggle').setAttribute('aria-pressed', 'false');
    $('audio-toggle').textContent = 'Enable speech';
  }
  $('audio-toggle').disabled = Boolean(state.wheel_test && !state.eog_communication);
  $('trial-label').value = state.trial_label || 'unlabeled';
  $('recording-status').textContent = state.recording ? 'Recording locally' : 'Monitoring only · not recording';
  $('record-stop').disabled = !state.recording;
  const guided = state.guided || {status: 'idle'};
  const guidedRunning = guided.status === 'running';
  $('trial-label').disabled = guidedRunning;
  $('guided-protocol').disabled = guidedRunning;
  if (guidedRunning) $('guided-protocol').value = guided.protocol;
  $('guided-protocol').querySelector('option[value="diagnostic"]').disabled = !guidedEOG;
  if (!guidedEOG && ['diagnostic', 'speed'].includes($('guided-protocol').value)) $('guided-protocol').value = 'horizontal';
  $('guided-protocol').querySelector('option[value="speed"]').disabled = !guidedEOG;
  const diagnosticCheck = ['diagnostic', 'speed'].includes($('guided-protocol').value);
  $('guided-start').disabled = guidedRunning || !state.recording || !state.connected || (diagnosticCheck
    ? !guidedEOG || !state.wheel_test || gaze?.phase !== 'ready' : state.sensor_actions && !state.wheel_test);
  $('guided-stop').disabled = !guidedRunning;
  $('guided-why').textContent = guidedRunning ? '' : !state.connected ? 'Start is off: the Nano is not connected.'
    : !state.recording ? 'Start is off: recording has stopped. Restart the server to record again.'
    : diagnosticCheck && (!state.wheel_test || gaze?.phase !== 'ready') ? 'This check needs eye control on and showing Ready. For up/down or left/right recordings, pick one of the recording tests instead.'
    : !diagnosticCheck && state.wheel_test ? 'Starting this recording will switch eye control off first.' : '';
  $('guided-cue').textContent = guided.cue || 'Live recording required to start a guided test.';
  if (guidedRunning && !state.wheel_test) {  // Acquisition cues must be readable from the wheel, not a side panel.
    $('center-label').textContent = 'GUIDED RECORDING';
    $('center-text').textContent = guided.cue;
    $('center-footer').textContent = `${guided.remaining_s}s · step ${guided.step}/${guided.total_steps}`;
    fitCenterText();
  }
  $('guided-progress').textContent = guidedRunning ? `${guided.remaining_s}s · Step ${guided.step}/${guided.total_steps} · ${guided.trial_id}` : guided.status;

  $('signal-info').textContent = `${state.samples.length} recent samples · raw ADC counts${state.calibrated ? ' · calibration loaded' : ''}`;
  $('suggest-source').textContent = PROVIDER_LABELS[state.suggestions_provider] || 'Local sample phrases';
  $('heard').textContent = state.heard ? `Heard: “${state.heard}”` : '';
  $('suggest-clear').hidden = state.suggestions_provider === 'curated-demo';
  $('listen').disabled = suggesting; $('text-send').disabled = suggesting;
  $('history-count').textContent = state.history.length;
  const oldHistory = $('history').dataset.selection;
  if (oldHistory !== String(state.selection_id)) {
    $('history').replaceChildren();
    for (const item of state.history) { const li = document.createElement('li'); li.textContent = item.text; $('history').append(li); }
    $('history').dataset.selection = String(state.selection_id);
  }
  drawTrace(); drawHUD($('hud-preview'), state); drawHUD($('hud-full'), state);
  fitCenterText();
  $('hud-status').textContent = `${state.input_mode.toUpperCase()} · ${state.connected ? 'Connected' : 'Paused'} · ${state.screen}`;
  if (lastConnected === false) feedback('Session reconnected.');
  lastConnected = true;
}

// Shrink long center text to fit the circle rather than scroll it; very long spelled drafts still scroll at 13px.
let fittedCenter = '';
function fitCenterText() {
  const text = $('center-text'), key = `${text.textContent}|${$('wheel').clientWidth}`;
  if (key === fittedCenter) return;
  fittedCenter = key;
  const shrink = () => {
    text.style.fontSize = '';
    let size = Math.round(parseFloat(getComputedStyle(text).fontSize));
    const floor = Math.min(size, 13);
    while (text.scrollHeight > text.clientHeight + 1 && size > floor) text.style.fontSize = `${--size}px`;
    return text.scrollHeight <= text.clientHeight + 1;
  };
  // On the smallest phones, drop the decorative label before resorting to scroll.
  $('wheel').classList.remove('center-compact');
  if (!shrink()) { $('wheel').classList.add('center-compact'); shrink(); }
}
addEventListener('resize', fitCenterText);

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer); let text = '';
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(text);
}

async function suggest(payload) {
  if (isHUD || suggesting || !state) return false;
  const listening = Boolean(payload.audio_b64);
  if (!listening && !state.suggest_available) { feedback(SETUP_HINT); return false; }
  suggesting = true; $('listen').disabled = $('text-send').disabled = true;
  feedback(listening ? 'Transcribing with Qwen…' : 'Thinking of replies…');
  try {
    render(await (await api('/api/suggest', {session_id: state.session_id, ...payload})).json());
    feedback(state.suggest_available ? 'New reply suggestions. Nothing is spoken until you choose one.'
      : `Transcribed with Qwen: “${state.heard}”`); return true;
  } catch (error) { feedback(`${error.message} Sample phrases remain available.`); return false; }
  finally { suggesting = false; $('listen').disabled = $('text-send').disabled = false; }
}

async function toggleListen() {
  if (recorder) { recorder.stop(); return; }
  if (!state?.transcribe_available) { feedback(LISTEN_HINT); return; }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { feedback('Microphone recording is not available in this browser.'); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({audio: true}); }
  catch { feedback('Microphone permission was denied.'); return; }
  const chunks = [];
  const active = recorder = new MediaRecorder(stream);
  active.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
  active.onstop = async () => {
    clearTimeout(recordTimer); stream.getTracks().forEach(track => track.stop());
    const type = active.mimeType || 'audio/webm'; recorder = null;
    $('listen-label').textContent = 'Listen'; $('listen').classList.remove('running');
    const blob = new Blob(chunks, {type});
    if (blob.size < 1500) { feedback('Nothing was heard. Try again.'); return; }
    suggest({mime_type: type, audio_b64: toBase64(await blob.arrayBuffer())});
  };
  active.start(); $('listen-label').textContent = 'Stop'; $('listen').classList.add('running');
  feedback('Listening… press again when they finish (stops after 12 seconds).');
  recordTimer = setTimeout(() => recorder?.stop(), 12000);
}

function drawTrace() {
  const canvas = $('trace'), ctx = canvas.getContext('2d');
  const {width: w, height: h} = canvas;
  ctx.fillStyle = '#0b1717'; ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = '#25382e';
  for (let y = 0; y < 4; y++) { ctx.beginPath(); ctx.moveTo(0, y * h / 3); ctx.lineTo(w, y * h / 3); ctx.stroke(); }
  if (!state.samples.length) return;
  const values = state.samples.flatMap(sample => [sample.horizontal, sample.vertical]);
  const min = Math.min(...values) - 100, max = Math.max(...values) + 100;
  for (const [channel, color] of [['horizontal', '#b5d3c1'], ['vertical', '#e4ad8f']]) {
    ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 2;
    state.samples.forEach((sample, index) => {
      const x = index * w / Math.max(1, state.samples.length - 1), y = h - (sample[channel] - min) / (max - min) * h;
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }); ctx.stroke();
  }
}

async function poll() {
  if (pollBusy) return;
  pollBusy = true;
  try { render(await (await api('/api/state')).json()); }
  catch (error) {
    $('connection').textContent = 'Disconnected'; $('connection').classList.add('disconnected');
    $('hud-status').textContent = 'Disconnected — last frame retained';
    $('phone-live').textContent = '○ Disconnected';
    if (lastConnected !== false) feedback(error.message);
    lastConnected = false;
  } finally {
    pollBusy = false;
  }
}

$('reset').onclick = () => command('reset');
$('scenario').onclick = () => command('demo', !state?.demo_running);
$('contact').onchange = event => command('contact', event.target.value);
$('trial-label').onchange = event => command('label', event.target.value);
$('listen').onclick = toggleListen;
$('default-choices').onclick = () => command('default_choices').then(() => {
  if (state?.suggestions_provider === 'preset') feedback('Default choices restored. Look at a choice, then confirm when ready.');
});
$('suggest-clear').onclick = () => command('suggestions_clear');
$('text-toggle').onclick = () => {
  const open = $('text-panel').hidden;
  $('text-panel').hidden = !open; $('text-toggle').setAttribute('aria-expanded', String(open));
  $('text-toggle').classList.toggle('running', open);
  if (open) $('heard-input').focus();
};
$('text-panel').onsubmit = event => {
  event.preventDefault();
  const text = $('heard-input').value.trim();
  if (text) suggest({heard_text: text}).then(ok => { if (ok) $('heard-input').value = ''; });
};
$('download-hud').onclick = () => state && downloadFrame(state);
$('mobile-tools-toggle').onclick = () => {
  const open = document.body.classList.toggle('mobile-tools-open');
  $('mobile-tools-toggle').setAttribute('aria-expanded', String(open));
  $('mobile-tools-toggle').textContent = open ? 'Hide tools' : 'More tools';
};
function setAudio(enabled) {
  audioEnabled = enabled; $('audio-toggle').setAttribute('aria-pressed', String(audioEnabled));
  $('audio-toggle').textContent = audioEnabled ? 'Speech enabled' : 'Enable speech';
  if (!audioEnabled) { audio?.pause(); if ('speechSynthesis' in window) speechSynthesis.cancel(); }
  feedback(audioEnabled ? 'Speech enabled on this companion. Future selections will be spoken.' : 'Speech paused. Text stays visible.');
}
$('audio-toggle').onclick = () => setAudio(!audioEnabled);
$('token-submit').onclick = () => { token = $('token-input').value; sessionStorage.setItem('nuggies-token', token); setTimeout(poll, 0); };
document.addEventListener('keydown', event => {
  if (isHUD || workspaceView !== 'wheel' || event.repeat || $('token-dialog').open || /INPUT|TEXTAREA|SELECT|BUTTON|A|SUMMARY/.test(event.target.tagName)) return;
  if (event.key === 'Escape' && document.querySelector('.signal-details').classList.contains('signal-expanded')) return;
  const actions = {ArrowLeft: 'left', a: 'left', ArrowRight: 'right', d: 'right', ' ': 'select', Enter: 'select', b: 'blink', Escape: 'back'};
  const action = actions[event.key] || actions[event.key.toLowerCase()];
  if (action) { event.preventDefault(); command(action); }
});
function transformHUD() {
  $('hud-full').style.transform = `scale(${$('mirror-x').checked ? -1 : 1},${$('mirror-y').checked ? -1 : 1})`;
  $('hud-full').style.width = `${$('hud-scale').value}vw`;
}
for (const id of ['mirror-x', 'mirror-y', 'hud-scale']) $(id).oninput = transformHUD;
poll(); setInterval(poll, 250);

// Full-screen wheel: the wheel panel covers the page so only the choices and confirm controls show.
// In-page rather than the Fullscreen API, which iPhone Safari lacks and which would take Esc away from Back.
$('wheel-focus').onclick = () => {
  const focused = document.body.classList.toggle('wheel-focus-open');
  $('wheel-focus').setAttribute('aria-pressed', String(focused));
  $('wheel-focus').setAttribute('aria-label', focused ? 'Exit full screen' : 'Show the wheel full screen');
  $('wheel-focus').title = focused ? 'Exit full screen' : 'Full screen';
  fitCenterText();
};

// Expand the existing workspace without opening another serial connection.
const signalWorkspace = document.querySelector('.signal-details');
function setSignalExpanded(expanded) {
  signalWorkspace.classList.toggle('signal-expanded', expanded);
  document.body.classList.toggle('signal-expanded-open', expanded);
  $('expand-signal').setAttribute('aria-pressed', String(expanded));
  $('expand-signal').textContent = expanded ? 'Close expanded view (Esc)' : 'Expand signal workspace';
  if (expanded) signalWorkspace.open = true;
  drawTrace();
}
$('expand-signal').addEventListener('click', () => setSignalExpanded(!signalWorkspace.classList.contains('signal-expanded')));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && signalWorkspace.classList.contains('signal-expanded')) {
    setSignalExpanded(false);
    $('expand-signal').focus();
  }
});
signalWorkspace.addEventListener('toggle', () => {
  if (!signalWorkspace.open) setSignalExpanded(false);
});

$('guided-start').onclick = () => {
  const protocol = $('guided-protocol').value;
  // Recording protocols are refused while eye control runs; stop it rather than leave a dead button.
  if (!['diagnostic', 'speed'].includes(protocol) && state?.wheel_test) command('wheel_test', false);
  command('guided_start', protocol);
};
$('guided-stop').onclick = () => command('guided_stop');

$('record-stop').onclick = () => command('record_stop');

$('speed-test-start').onclick = () => command('speed_test');
$('eog-communication-toggle').onclick = () => {
  const starting = !state?.eog_communication;
  // This click is the user gesture browsers require before audio; double-blink confirmations then speak.
  if (starting && !isHUD && !audioEnabled) setAudio(true);
  command('eog_communication', starting);
};
$('wheel-test-toggle').onclick = () => command('wheel_test', !state?.wheel_test);
$('eog-recenter').onclick = () => command('eog_recenter');
$('wheel-test-stop').onclick = () => command('wheel_test', false);

// Project and team views share the app shell, but keyboard/gaze commands belong
// to the visible wheel. Stop eye control before hiding it; returning is explicit.
async function openWorkspace(view) {
  if (isHUD || workspaceSwitchBusy || !['wheel', 'project', 'team'].includes(view)) return;
  workspaceSwitchBusy = true;
  try {
    if (view !== 'wheel' && state?.wheel_test) {
      await command(state.eog_communication ? 'eog_communication' : 'wheel_test', false);
      if (state?.wheel_test) return; // Keep the wheel visible if stopping failed.
    }
    const show = () => {
      workspaceView = view;
      $('companion').hidden = view !== 'wheel';
      $('project-view').hidden = view !== 'project';
      $('team-view').hidden = view !== 'team';
      for (const button of document.querySelectorAll('[data-workspace]')) {
        if (button.dataset.workspace === view) button.setAttribute('aria-current', 'page');
        else button.removeAttribute('aria-current');
      }
      if (view === 'wheel') fitCenterText();
      else $(view + '-title').focus({preventScroll: true});
    };
    if (document.startViewTransition && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      const transition = document.startViewTransition(show);
      transition.finished.catch(() => {});
      await transition.updateCallbackDone.catch(() => {});
    } else {
      show();
    }
    window.scrollTo({top: 0, behavior: 'instant'});
  } finally { workspaceSwitchBusy = false; }
}
for (const button of document.querySelectorAll('[data-workspace]')) {
  button.addEventListener('click', () => openWorkspace(button.dataset.workspace));
}
