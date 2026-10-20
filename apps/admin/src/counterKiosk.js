// Kiosk helpers for the /counter screen on an Android tablet.
// - installCounterManifest: makes /counter installable as a full-screen app.
// - keepScreenAwake: Screen Wake Lock, re-acquired when the tab is visible again.
// - unlockAudio: probes whether the chime may play without a tap.
// - holdAction: press-and-hold so a stray tap cannot log the counter out.

export function installCounterManifest(doc = document) {
  const added = [];
  const ensure = (selector, make) => {
    if (doc.head.querySelector(selector)) return;
    const el = make(); doc.head.appendChild(el); added.push(el);
  };
  ensure('link[rel="manifest"]', () => Object.assign(doc.createElement('link'), { rel: 'manifest', href: '/counter/manifest.webmanifest' }));
  ensure('meta[name="mobile-web-app-capable"]', () => Object.assign(doc.createElement('meta'), { name: 'mobile-web-app-capable', content: 'yes' }));
  const theme = doc.head.querySelector('meta[name="theme-color"]');
  const previousTheme = theme?.getAttribute('content');
  theme?.setAttribute('content', '#0a0d14');
  return () => { added.forEach(el => el.remove()); if (theme && previousTheme != null) theme.setAttribute('content', previousTheme); };
}

export function keepScreenAwake({ nav = navigator, doc = document, onChange = () => {} } = {}) {
  if (!nav?.wakeLock?.request) { onChange('unsupported'); return () => {}; }
  let sentinel = null, stopped = false;
  async function acquire() {
    if (stopped || doc.visibilityState !== 'visible' || sentinel) return;
    try {
      sentinel = await nav.wakeLock.request('screen');
      onChange('on');
      sentinel.addEventListener?.('release', () => { sentinel = null; if (!stopped) onChange('off'); });
    } catch { onChange('off'); }
  }
  const onVisible = () => { if (doc.visibilityState === 'visible') acquire(); };
  doc.addEventListener('visibilitychange', onVisible);
  acquire();
  return () => { stopped = true; doc.removeEventListener('visibilitychange', onVisible); sentinel?.release?.().catch?.(() => {}); sentinel = null; };
}

/** Resolves true when the chime can play without a user gesture. */
export async function unlockAudio(audio) {
  if (!audio?.play) return false;
  const volume = audio.volume;
  try {
    // Muted playback is always allowed, so probe un-muted at volume 0: that
    // is what the autoplay policy actually blocks.
    audio.muted = false; audio.volume = 0;
    await audio.play();
    audio.pause(); audio.currentTime = 0;
    return true;
  } catch {
    return false;
  } finally {
    audio.muted = false; audio.volume = volume;
  }
}

export const LOGOUT_HOLD_MS = 1500;
