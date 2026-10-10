// Same canonical state as the companion; renderer does not decide navigation.
export function drawHUD(canvas, state, monochrome = true) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h);
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  const cx = w / 2, cy = h / 2, rx = w * .37, ry = h * .35;
  ctx.strokeStyle = '#303030'; ctx.lineWidth = Math.max(1, w / 512);
  ctx.beginPath(); ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2); ctx.stroke();
  state.slots.forEach((slot, index) => {
    const angle = index * Math.PI / 4 - Math.PI / 2;
    const x = cx + Math.cos(angle) * rx, y = cy + Math.sin(angle) * ry;
    ctx.font = `${Math.max(5, Math.round(w / 32))}px monospace`;
    const label = slot.label.slice(0, 9);
    const boxW = Math.max(ctx.measureText(label).width + w / 45, w / 10);
    const boxH = h / 11;
    ctx.fillStyle = !state.wheel_test && index === state.selected ? '#fff' : '#000';
    ctx.fillRect(x - boxW / 2, y - boxH / 2, boxW, boxH);
    ctx.fillStyle = !state.wheel_test && index === state.selected ? '#000' : slot.enabled ? '#fff' : '#555';
    ctx.fillText(label, x, y);
  });
  ctx.fillStyle = '#fff'; ctx.font = `${Math.max(5, Math.round(w / 38))}px monospace`;
  const testText = state.wheel_test ? (state.gaze_hover?.message || state.wheel_message || 'Eye test') : null;
  const text = testText || (state.screen === 'spell' ? state.draft || 'Choose letters' : state.confirmed || 'Your words, at your pace.');
  const limit = w * .4, lines = [];
  let current = '';
  for (const word of text.split(/\s+/)) {
    const candidate = current ? current + ' ' + word : word;
    if (ctx.measureText(candidate).width > limit && current) { lines.push(current); current = word; }
    else current = candidate;
  }
  if (current) lines.push(current);
  const shown = lines.slice(0, 4);
  if (lines.length > 4) shown[3] = shown[3].slice(0, -2) + '…';
  shown.forEach((line, i) => ctx.fillText(line, cx, cy + (i - (shown.length - 1) / 2) * h / 13, limit));
}

export function downloadFrame(state) {
  const canvas = document.createElement('canvas'); canvas.width = 128; canvas.height = 64;
  drawHUD(canvas, state);
  const link = document.createElement('a'); link.download = 'nuggies-hud-128x64.png';
  link.href = canvas.toDataURL('image/png'); link.click();
}
