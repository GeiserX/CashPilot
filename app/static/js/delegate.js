// ---------------------------------------------------------------------------
// Event delegation (CashPilot-guw)
//
// Its own file, loaded by EVERY page including the standalone templates
// that never load app.js. Living inside app.js meant the onboarding and
// login pages had buttons whose handlers were never registered — they
// rendered perfectly and did nothing. Only a browser could see that.
//
// Every button used to carry an inline onclick=. That forced
// script-src 'unsafe-inline' in the CSP, which means ANY markup an attacker can
// inject executes — and this UI renders provider-supplied strings.
//
// One delegated listener replaces all of them. Handlers are named in
// data-action and resolved against the CP namespace, so a typo fails loudly at
// click time in one place rather than silently doing nothing in fifty.
// ---------------------------------------------------------------------------
document.addEventListener('click', (event) => {
  const el = event.target.closest('[data-action]');
  if (!el) return;

  // Rows are themselves clickable, so a button inside one has to stop the row
  // from also firing. This replaces the inline event.stopPropagation() calls.
  if (el.dataset.stop === '1') event.stopPropagation();
  if (el.dataset.prevent === '1') event.preventDefault();
  if (el.hasAttribute('disabled')) return;

  const run = (name, args) => {
    if (!name) return;
    // CP first, then a page-local global: a few controls belong to one template
    // (the onboarding wizard, the fleet page) and have no business on the shared
    // namespace. Anything else is a typo, and it says so rather than doing
    // nothing — a silently dead button is the failure mode this refactor could
    // most easily introduce fifty times over.
    const ns = typeof CP !== 'undefined' ? CP : {};
    const fn = typeof ns[name] === 'function' ? ns[name] : window[name];
    if (typeof fn !== 'function') {
      console.error(`No handler named ${name} (checked CP and window)`);
      return;
    }
    fn(...args);
  };

  const args = [];
  for (let i = 1; i <= 3; i += 1) {
    const value = el.dataset[`a${i}`];
    if (value === undefined) break;
    args.push(value);
  }
  run(el.dataset.action, args);
  // A few controls did two things in one inline handler.
  run(el.dataset.then, []);
});

