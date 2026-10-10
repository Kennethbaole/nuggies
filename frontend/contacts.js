// Contacts page: add people and give each a private profile built from a past conversation.
const $ = id => document.getElementById(id);
const token = sessionStorage.getItem('nuggies-token') || '';
const MAX_FILE_BYTES = 8_000_000;
let people = null, busy = false;

async function api(path, payload) {
  const headers = {'Authorization': `Bearer ${token}`};
  if (payload !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {method: payload === undefined ? 'GET' : 'POST', headers,
    body: payload === undefined ? undefined : JSON.stringify(payload), signal: AbortSignal.timeout(30000)});
  if (response.status === 401) throw new Error('Open the companion page and enter the session token first.');
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || `Request failed (${response.status})`);
  }
  return response.json();
}

const command = (action, extra = {}) => api('/api/persona', {session_id: people.session_id, action, ...extra});

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer); let text = '';
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(text);
}

function describe(card, person, isDefault) {
  const profile = person.profile, badge = card.querySelector('.person-badge'), detail = card.querySelector('.person-detail');
  badge.classList.toggle('active', Boolean(profile));
  detail.textContent = '';
  if (profile) {
    badge.textContent = 'Personalised';
    const count = document.createElement('strong');
    count.textContent = `${profile.exchanges} past ${profile.exchanges === 1 ? 'exchange' : 'exchanges'}`;
    detail.append(count, profile.source ? ` from ${profile.source}.` : '.', profile.note ? ` You write: ${profile.note}.` : '');
  } else if (isDefault) {
    badge.textContent = 'Not set';
    detail.textContent = 'Used for anyone without their own conversation. Add a file with your messages to several people.';
  } else {
    badge.textContent = people.default ? 'Default personality' : 'Sample phrases';
    detail.textContent = people.default ? 'Replies follow your default personality until you add a conversation with them.'
      : 'Replies use the sample phrases until you add a conversation with them.';
  }
  card.querySelector('.upload-label').textContent = profile ? 'Replace conversation' : 'Add a conversation';
  card.querySelector('.remove-button').hidden = !profile;
  card.querySelector('.try-form').hidden = !profile;
}

function personCard(person, isDefault = false) {
  const card = $('person-template').content.firstElementChild.cloneNode(true);
  const status = message => { card.querySelector('.card-status').textContent = message; };
  const whoForm = card.querySelector('.who-form'), upload = card.querySelector('.upload-input');
  let pending = null;
  card.classList.toggle('default-card', isDefault);
  card.querySelector('.avatar').textContent = person.initials;
  card.querySelector('.person-name').textContent = person.name;
  card.querySelector('.person-relationship').textContent = person.relationship;
  describe(card, person, isDefault);

  upload.onchange = async () => {
    const file = upload.files[0]; upload.value = '';
    if (!file || busy) return;
    if (file.size > MAX_FILE_BYTES) { status('That file is larger than 8 MB. Export a shorter period.'); return; }
    busy = true; status('Reading the conversation…');
    try {
      pending = {filename: file.name, file_b64: toBase64(await file.arrayBuffer())};
      const {names} = await command('inspect', {file_b64: pending.file_b64});
      const options = card.querySelector('.who-options'); options.textContent = '';
      names.forEach((entry, index) => {
        const label = document.createElement('label'), radio = document.createElement('input'), count = document.createElement('span');
        radio.type = 'radio'; radio.name = `who-${person.id}`; radio.value = entry.name; radio.required = true;
        radio.checked = index === 0 && names.length === 1;
        count.textContent = `${entry.messages} messages`;
        label.append(radio, entry.name, count); options.append(label);
      });
      whoForm.hidden = false; status('');
    } catch (error) { pending = null; status(error.message); }
    finally { busy = false; }
  };
  whoForm.onsubmit = async event => {
    event.preventDefault();
    const chosen = whoForm.querySelector('input:checked');
    if (!chosen || !pending || busy) return;
    busy = true; status('Building the profile…');
    try {
      render(await command('save', {contact_id: person.id, me: chosen.value, ...pending}));
      pageStatus(`Saved. Replies to ${isDefault ? 'everyone else' : person.name} now follow this conversation.`);
    } catch (error) { status(error.message); }
    finally { busy = false; }
  };
  card.querySelector('.who-cancel').onclick = () => { pending = null; whoForm.hidden = true; status(''); };
  card.querySelector('.remove-button').onclick = async () => {
    if (busy || !confirm(`Remove the saved conversation profile for ${person.name}? Your original file is not affected.`)) return;
    busy = true;
    try { render(await command('remove', {contact_id: person.id})); pageStatus('Profile removed.'); }
    catch (error) { status(error.message); }
    finally { busy = false; }
  };
  card.querySelector('.try-form').onsubmit = async event => {
    event.preventDefault();
    const heard = card.querySelector('.try-input').value.trim(), results = card.querySelector('.try-results');
    if (!heard) return;
    try {
      const {context} = await command('preview', {contact_id: person.id, heard});
      results.textContent = '';
      for (const pair of context?.examples || []) {
        const item = document.createElement('li'), them = document.createElement('div'), me = document.createElement('div');
        them.className = 'them'; them.textContent = `They said: ${pair.them}`; me.textContent = `You replied: ${pair.me}`;
        item.append(them, me); results.append(item);
      }
      status(results.children.length ? 'These past replies would guide the suggestions.' : 'No past replies to show.');
    } catch (error) { status(error.message); }
  };
  return card;
}

function pageStatus(message) { $('page-status').textContent = message; }

function render(next) {
  people = next;
  const list = $('people-list'); list.textContent = '';
  for (const person of people.contacts) list.append(personCard(person));
  list.append(personCard({id: 'default', name: 'Default personality', relationship: 'Everyone else', initials: '◌',
    profile: people.default}, true));
}

$('add-form').onsubmit = async event => {
  event.preventDefault();
  if (busy || !people) return;
  busy = true;
  try {
    render(await command('add_contact', {name: $('add-name').value, relationship: $('add-relationship').value}));
    $('add-form').reset(); pageStatus('Added. They now appear in the companion contact list.');
  } catch (error) { pageStatus(error.message); }
  finally { busy = false; }
};

api('/api/people').then(render).catch(error => pageStatus(error.message));
