window.petitNudge.read().then((event) => {
  document.getElementById('title').textContent = event.title;
  document.getElementById('body').textContent = event.body;
});
document.getElementById('open').onclick = () => window.petitNudge.open();
document.getElementById('dismiss').onclick = () => window.petitNudge.dismiss();
document.body.addEventListener('mouseenter', () => window.petitNudge.hover(true));
document.body.addEventListener('mouseleave', () => window.petitNudge.hover(false));
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') window.petitNudge.dismiss(); });
