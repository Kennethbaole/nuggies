import {drawHUD, downloadFrame} from './hud.js';

const $ = id => document.getElementById(id);
const isHUD = location.pathname === '/hud';
if (isHUD) { document.body.classList.add('hud-body'); $('hud-only').hidden = false; }
let state = null, seenSelection = null, session = null, audioEnabled = false;
let token = sessionStorage.getItem('nuggies-token') || '';
let queue = Promise.resolve(), audio = null, speechBusy = false, pollBusy = false;
const PROVIDER_LABELS = {gemini: 'Gemini reply suggestions', ollama: 'Local AI suggestions (offline)'};
const SETUP_HINT = 'Add GEMINI_API_KEY (or OLLAMA_MODEL for offline replies) to .env and restart to enable reply suggestions.';
const LISTEN_HINT = 'Set ASR_URL to the Qwen speech-to-text service in .env and restart to enable listening.';
let requestCounter = 0, recorder = null, recordTimer = null, suggesting = false;
const clientID = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
let lastConnected = null;
const slotButtons = [];
for (let i = 0; i < 8; i++) {
  const button = document.createElement('button'); button.className = 'slot'; button.dataset.slot = String(i);
  const angle = i * Math.PI / 4;
  button.style.left = `${50 + Math.sin(angle) * 38}%`;
  button.style.top = `${50 - Math.cos(angle) * 38}%`;
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
  if (!audioEnabled || isHUD || speechBusy || !snapshot.confirmed || snapshot.wheel_test || snapshot.source === 'eye-wheel-test') return;
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
    speakSelection({...state});
  }
  const contact = state.contacts.find(contact => contact.id === state.contact);
  if (!$('contact').options.length) {
    for (const item of state.contacts) {
      const option = document.createElement('option'); option.value = item.id; option.textContent = item.name;
      $('contact').append(option);
    }
  }
  $('contact').value = state.contact; $('avatar').textContent = contact.initials;
  $('avatar').dataset.tone = String(state.contacts.indexOf(contact) % 3);
  $('relationship').textContent = contact.relationship;
  $('phone-contact').textContent = `With ${contact.name}`;
  $('screen-name').textContent = state.screen === 'spell' ? 'SPELL YOUR WORDS' : state.screen === 'needs' ? 'EVERYDAY NEEDS' : 'CONVERSATION';
  $('page-info').textContent = state.screen === 'spell' ? 'Two groups, one letter at a time' : `Phrase set ${state.page + 1} · ${PROVIDER_LABELS[state.suggestions_provider] || 'curated demo'}`;
  state.slots.forEach((slot, index) => {
    const button = slotButtons[index];
    button.textContent = slot.label; button.disabled = !slot.enabled;
    button.classList.toggle('selected', state.selected === index);
    button.classList.toggle('gaze-hover', Boolean(state.wheel_test && state.gaze_hover?.slot === index));
    button.classList.toggle('utility', ['more', 'spell', 'back', 'space', 'delete', 'speak'].includes(slot.action));
    button.setAttribute('aria-pressed', String(state.selected === index));
    button.setAttribute('aria-label', `${slot.label}${slot.text ? ': ' + slot.text : ''}${state.selected === index ? ', highlighted' : ''}`);
  });
  const center = state.screen === 'spell' ? state.draft || 'Choose your letters.' : state.confirmed || 'Your words, at your pace.';
  $('center-text').textContent = center; $('phone-text').textContent = state.confirmed || 'Your words, at your pace.';
  $('center-label').textContent = state.screen === 'spell' ? 'YOUR DRAFT' : state.confirmed ? 'YOUR LAST SELECTION' : 'READY WHEN YOU ARE';
  $('preview-text').textContent = state.preview || `${state.slots[state.selected].label} — ${state.wheel_test ? 'hover only · click or Space to choose' : 'double blink to choose'}`;
  $('center-footer').textContent = state.screen === 'spell' ? 'Choose Speak when ready' : 'Double blink to choose';
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
  $('wheel-test-toggle').disabled = !state.wheel_test && (state.input_mode !== 'serial' || !state.connected || state.sensor_actions || state.guided?.status === 'running');
  $('wheel-test-stop').disabled = !state.wheel_test;
  const gaze = state.gaze_hover;
  $('wheel-test-status').textContent = state.wheel_test
    ? `${state.wheel_message}${gaze?.slot != null ? ' → ' + state.slots[gaze.slot].label : ''}` : 'Eye wheel control off';
  $('gaze-readings').textContent = state.wheel_test && gaze
    ? `EOG deviation · Horizontal ${gaze.horizontal} · Vertical ${gaze.vertical} ADC counts · ${gaze.phase}` : '';
  if (state.wheel_test && audioEnabled) {
    audioEnabled = false; audio?.pause();
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    $('audio-toggle').setAttribute('aria-pressed', 'false');
    $('audio-toggle').textContent = 'Enable speech';
  }
  $('audio-toggle').disabled = Boolean(state.wheel_test);
  $('trial-label').value = state.trial_label || 'unlabeled';
  $('recording-status').textContent = state.recording ? 'Recording locally' : 'Monitoring only · not recording';
  $('record-stop').disabled = !state.recording;
  const guided = state.guided || {status: 'idle'};
  const guidedRunning = guided.status === 'running';
  $('trial-label').disabled = guidedRunning;
  $('guided-protocol').disabled = guidedRunning;
  if (guidedRunning) $('guided-protocol').value = guided.protocol;
  $('guided-start').disabled = guidedRunning || !state.recording || !state.connected || state.sensor_actions;
  $('guided-stop').disabled = !guidedRunning;
  $('guided-cue').textContent = guided.cue || 'Live recording required to start a guided test.';
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
  $('hud-status').textContent = `${state.input_mode.toUpperCase()} · ${state.connected ? 'Connected' : 'Paused'} · ${state.screen}`;
  if (lastConnected === false) feedback('Session reconnected.');
  lastConnected = true;
}

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
    $('select').disabled = $('left').disabled = $('right').disabled = true;
  } finally {
    if (lastConnected) $('select').disabled = $('left').disabled = $('right').disabled = false;
    pollBusy = false;
  }
}

$('left').onclick = () => command('left'); $('right').onclick = () => command('right');
$('select').onclick = () => command('select'); $('reset').onclick = () => command('reset');
$('scenario').onclick = () => command('demo', !state?.demo_running);
$('contact').onchange = event => command('contact', event.target.value);
$('trial-label').onchange = event => command('label', event.target.value);
$('listen').onclick = toggleListen;
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
$('audio-toggle').onclick = () => {
  audioEnabled = !audioEnabled; $('audio-toggle').setAttribute('aria-pressed', String(audioEnabled));
  $('audio-toggle').textContent = audioEnabled ? 'Speech enabled' : 'Enable speech';
  if (!audioEnabled) { audio?.pause(); if ('speechSynthesis' in window) speechSynthesis.cancel(); }
  feedback(audioEnabled ? 'Speech enabled on this companion. Future selections will be spoken.' : 'Speech paused. Text stays visible.');
};
$('token-submit').onclick = () => { token = $('token-input').value; sessionStorage.setItem('nuggies-token', token); setTimeout(poll, 0); };
document.addEventListener('keydown', event => {
  if (isHUD || event.repeat || $('token-dialog').open || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) return;
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

$('guided-start').onclick = () => command('guided_start', $('guided-protocol').value);
$('guided-stop').onclick = () => command('guided_stop');

$('record-stop').onclick = () => command('record_stop');

$('wheel-test-toggle').onclick = () => command('wheel_test', !state?.wheel_test);
$('wheel-test-stop').onclick = () => command('wheel_test', false);
