/* Decorative motion only: never moves a choice, filters a signal or issues an action. */
const flower = document.querySelector('.welcome-flower');
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
let queued = false;
function update() {
  queued = false;
  if (!flower) return;
  if (reduced.matches || document.body.classList.contains('communication-active')) {
    flower.style.transform = '';
    return;
  }
  const progress = Math.min(1, Math.max(0, scrollY / 500));
  flower.style.transform = `translateY(${-progress * 20}px) rotate(${12 + progress * 24}deg)`;
}
function schedule() {
  if (!queued) { queued = true; requestAnimationFrame(update); }
}
addEventListener('scroll', schedule, {passive: true});
reduced.addEventListener('change', update);
if (flower) new MutationObserver(schedule).observe(document.body, {attributes: true, attributeFilter: ['class']});
update();
