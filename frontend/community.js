// Community page: add members and give each a short notes file that guides reply suggestions.
const $ = id => document.getElementById(id);
const token = sessionStorage.getItem('nuggies-token') || '';
const MAX_FILE_BYTES = 32_000;
const NOTES_PREVIEW_CHARS = 220;
const TONES = 6;  // Profile colours in styles.css (.avatar[data-tone]).
let community = null, busy = false;

async function api(path, payload, timeout = 30000) {
  const headers = {'Authorization': `Bearer ${token}`};
  if (payload !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {method: payload === undefined ? 'GET' : 'POST', headers,
    body: payload === undefined ? undefined : JSON.stringify(payload), signal: AbortSignal.timeout(timeout)});
  if (response.status === 401) throw new Error('Open the companion page and enter the session token first.');
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || `Request failed (${response.status})`);
  }
  return response.json();
}

const command = (action, extra = {}, timeout) =>
  api('/api/community', {session_id: community.session_id, action, ...extra}, timeout);

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer); let text = '';
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(text);
}

function updated(seconds) {
  if (!seconds) return '';
  return new Date(seconds * 1000).toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'});
}

function pageStatus(message) { $('page-status').textContent = message; }

function showNotes(card, member) {
  const notes = member.notes, text = card.querySelector('.notes-text'), more = card.querySelector('.notes-more');
  const badge = card.querySelector('.member-badge');
  badge.textContent = notes ? 'Notes added' : 'Default style';
  badge.classList.toggle('active', Boolean(notes));
  card.classList.toggle('has-notes', Boolean(notes));
  card.querySelector('.notes-saved').hidden = !notes;
  card.querySelector('.notes-actions').hidden = !notes;
  card.querySelector('.notes-drop').hidden = Boolean(notes);
  if (!notes) return;
  const long = notes.text.length > NOTES_PREVIEW_CHARS;
  let expanded = false;
  const draw = () => {
    text.textContent = long && !expanded ? `${notes.text.slice(0, NOTES_PREVIEW_CHARS).trimEnd()}…` : notes.text;
    more.textContent = expanded ? 'Show less' : 'Show all';
  };
  more.hidden = !long;
  more.onclick = () => { expanded = !expanded; draw(); };
  draw();
  card.querySelector('.notes-meta').textContent =
    [notes.source, updated(notes.updated) && `updated ${updated(notes.updated)}`].filter(Boolean).join(' · ');
}

// The avatar and the label tag share the member's colour.
function paintTone(card, tone) {
  card.querySelector('.avatar').dataset.tone = card.querySelector('.member-tags').dataset.tone = String(tone);
}

// Profile editing: each field is a row of common choices plus a box for anything else.
function editor(card, member, index) {
  const form = card.querySelector('.edit-form'), toggle = card.querySelector('.edit-button');
  const open = shown => {
    form.hidden = !shown; toggle.setAttribute('aria-expanded', String(shown)); card.classList.toggle('editing', shown);
    form.querySelector('.edit-error').textContent = '';
    if (shown) fill();
  };
  let tone = null;
  function fill() {
    for (const choice of form.querySelectorAll('.choice[data-field]')) {
      const input = choice.querySelector('input'), chips = choice.querySelector('.chips');
      const mark = () => {
        for (const chip of chips.children) {
          const value = chip.dataset.value;
          chip.setAttribute('aria-pressed', String(value.toLowerCase() === input.value.trim().toLowerCase()));
        }
      };
      input.value = member[choice.dataset.field] || '';
      chips.textContent = '';
      for (const option of choice.dataset.options.split('|')) {
        const chip = document.createElement('button');
        chip.type = 'button'; chip.className = 'chip'; chip.textContent = option;
        chip.dataset.value = option === 'Not set' ? '' : option;
        chip.onclick = () => { input.value = chip.dataset.value; mark(); };
        chips.append(chip);
      }
      input.oninput = mark; mark();
    }
    tone = member.tone ?? null;
    const swatches = form.querySelector('.swatches'); swatches.textContent = '';
    for (const value of [null, ...Array.from({length: TONES}, (_, i) => i)]) {
      const swatch = document.createElement('button');
      swatch.type = 'button'; swatch.setAttribute('role', 'radio');
      swatch.className = value === null ? 'swatch auto' : 'swatch';
      swatch.dataset.tone = String(value ?? index % TONES);
      swatch.setAttribute('aria-label', value === null ? 'Automatic colour' : `Colour ${value + 1}`);
      swatch.title = value === null ? 'Automatic' : '';
      if (value === null) swatch.textContent = 'A';
      swatch.onclick = () => {
        tone = value;
        for (const other of swatches.children) other.setAttribute('aria-checked', String(other === swatch));
        paintTone(card, swatch.dataset.tone);
      };
      swatch.setAttribute('aria-checked', String(value === tone));
      swatches.append(swatch);
    }
  }
  toggle.onclick = () => open(form.hidden);
  card.querySelector('.edit-cancel').onclick = () => {
    paintTone(card, member.tone ?? index % TONES);
    open(false);
  };
  form.onsubmit = async event => {
    event.preventDefault();
    if (busy) return;
    const value = field => form.querySelector(`.choice[data-field="${field}"] input`).value;
    const save = form.querySelector('.save-button'), error = form.querySelector('.edit-error');
    busy = true; save.disabled = true; save.textContent = 'Saving…'; error.textContent = '';
    try {
      const next = await command('update_member', {member_id: member.id, relationship: value('relationship'),
        gender: value('gender'), pronouns: value('pronouns'), tone});
      open(false);
      render(next);
      pageStatus(`Saved ${member.name}’s profile.`);
    } catch (failure) {
      // A page newer than the running server: the server does not know this action yet.
      error.textContent = /Unknown community action/.test(failure.message)
        ? 'The app needs a restart before profile changes can be saved.' : failure.message;
    } finally { busy = false; save.disabled = false; save.textContent = 'Save changes'; }
  };
}

function memberCard(member, index) {
  const card = $('member-template').content.firstElementChild.cloneNode(true);
  const status = message => { card.querySelector('.card-status').textContent = message; };
  const first = member.name.split(' ')[0];
  card.querySelector('.avatar').textContent = member.initials;
  paintTone(card, member.tone ?? index % TONES);
  card.querySelector('.member-name').textContent = member.name;
  const tags = card.querySelector('.member-tags');
  [[member.relationship, 'label'], [member.pronouns], [member.gender]].forEach(([text, kind]) => {
    if (!text) return;
    const tag = document.createElement('span');
    tag.className = kind ? `tag ${kind}` : 'tag'; tag.textContent = text; tags.append(tag);
  });
  showNotes(card, member);
  editor(card, member, index);

  async function upload(file) {
    if (!file || busy) return;
    if (!/\.txt$/i.test(file.name) && file.type !== 'text/plain') { status('Notes need to be a plain .txt file.'); return; }
    if (file.size > MAX_FILE_BYTES) { status('That file is too long. Notes work best as a paragraph or two.'); return; }
    busy = true; card.classList.add('working'); status('Saving notes…');
    try {
      const replacing = Boolean(member.notes);
      render(await command('save_notes', {member_id: member.id, filename: file.name, file_b64: toBase64(await file.arrayBuffer())}));
      pageStatus(`${replacing ? 'Updated' : 'Saved'} notes for ${member.name}. Replies to ${first} now follow them.`);
    } catch (error) { status(error.message); }
    finally { busy = false; card.classList.remove('working'); }
  }
  for (const input of card.querySelectorAll('.notes-input')) {
    input.onchange = () => { const file = input.files[0]; input.value = ''; upload(file); };
  }
  card.ondragover = event => {
    if (![...event.dataTransfer.types].includes('Files')) return;
    event.preventDefault(); card.classList.add('dragging');
  };
  card.ondragleave = event => { if (!card.contains(event.relatedTarget)) card.classList.remove('dragging'); };
  card.ondrop = event => { event.preventDefault(); card.classList.remove('dragging'); upload(event.dataTransfer.files[0]); };

  card.querySelector('.remove-button').onclick = async () => {
    if (busy || !confirm(`Remove the notes for ${member.name}? Replies to ${first} will use your default style. Your original file is not affected.`)) return;
    busy = true;
    try { render(await command('remove_notes', {member_id: member.id})); pageStatus(`Removed the notes for ${member.name}.`); }
    catch (error) { status(error.message); }
    finally { busy = false; }
  };

  const form = card.querySelector('.try-form'), input = card.querySelector('.try-input');
  const results = card.querySelector('.try-results'), caption = card.querySelector('.try-caption');
  card.querySelector('.try-label').textContent = `Something ${first} might say`;
  input.placeholder = 'Do you want to get dinner later?';
  input.disabled = !community.suggest_available;
  form.querySelector('button').disabled = !community.suggest_available;
  caption.textContent = community.suggest_available ? ''
    : 'Reply suggestions are not set up on this computer (OLLAMA_MODEL), so previews are unavailable.';
  form.onsubmit = async event => {
    event.preventDefault();
    const heard = input.value.trim();
    if (!heard || form.classList.contains('loading')) return;
    form.classList.add('loading'); results.textContent = ''; status('');
    caption.textContent = member.notes ? `Writing replies with ${first}’s notes…` : 'Writing replies in your default style…';
    try {
      const preview = await command('preview', {member_id: member.id, heard}, 90000);
      for (const text of preview.suggestions) {
        const item = document.createElement('li'); item.textContent = text; results.append(item);
      }
      caption.textContent = `${preview.used_notes ? `Shaped by ${first}’s notes` : 'Default speaking style; add notes to personalise'} · ${(preview.latency_ms / 1000).toFixed(1)} s`;
    } catch (error) { caption.textContent = ''; status(error.message); }
    finally { form.classList.remove('loading'); }
  };
  return card;
}

function render(next) {
  const open = new Set([...document.querySelectorAll('.member-card details[open]')].map(d => d.closest('.member-card').dataset.id));
  community = next;
  const list = $('member-list'); list.textContent = '';
  community.members.forEach((member, index) => {
    const card = memberCard(member, index);
    card.dataset.id = member.id;
    card.querySelector('details').open = open.has(member.id);
    list.append(card);
  });
  const withNotes = community.members.filter(member => member.notes).length;
  $('member-count').textContent = `${community.members.length} ${community.members.length === 1 ? 'person' : 'people'} · ${withNotes} with notes`;
}

$('add-form').onsubmit = async event => {
  event.preventDefault();
  if (busy || !community) return;
  busy = true;
  try {
    const name = $('add-name').value.trim();
    render(await command('add_member', {name, relationship: $('add-relationship').value}));
    $('add-form').reset();
    pageStatus(`Added ${name}. They now appear in the companion's “speaking with” list. Upload notes on their card to personalise replies.`);
    $('member-list').lastElementChild?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  } catch (error) { pageStatus(error.message); }
  finally { busy = false; }
};

$('example-download').onclick = () => {
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([`${$('example-text').textContent}\n`], {type: 'text/plain'}));
  link.download = 'maya-notes.txt'; link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
};

api('/api/community').then(render).catch(error => pageStatus(error.message));
