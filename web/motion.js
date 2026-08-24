// Purposeful, restrained motion -- NOT decoration. Grounded in cognitive-
// accessibility research: ambient/continuous/unpredictable motion
// measurably increases cognitive load and distraction for ADHD users, a
// real and meaningful share of this app's intended audience, while
// brief, one-time, predictable transitions that signal a state change
// (something appeared, something collapsed) can *help* by making state
// changes easier to track with limited working memory. Every function
// here is a single, finite transition -- nothing loops, nothing is
// ambient, nothing auto-plays on a timer.
//
// Every function respects prefers-reduced-motion (WCAG 2.3.3, MDN) --
// checked once, not per-call, since it can't change without a page
// reload in any browser that matters here.
//
// Uses anime.js v4.5.0 (MIT, vendored locally at web/vendor/anime.umd.min.js
// -- no CDN, matches this app's local-first/offline-first posture) rather
// than hand-rolled CSS transitions specifically for the collapse/expand
// case: CSS can't transition to/from `height: auto`, only a JS animation
// library (or a measured-pixel-value CSS transition, which is what this
// effectively does under the hood) can animate a panel's *actual*
// content height smoothly instead of guessing a max-height.

const PREFERS_REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// New card fading/sliding into place, once, when it's inserted -- makes
// "something new just appeared" visually obvious without a jarring
// instant pop-in. ~220ms is short enough to not feel like a delay.
function animateCardIn(el) {
  if (PREFERS_REDUCED_MOTION || typeof anime === "undefined") return;
  anime.animate(el, {
    opacity: [0, 1],
    translateY: [8, 0],
    duration: 220,
    ease: "outQuad",
  });
}

// One-time gentle pulse (opacity/scale, not color-flashing or looping)
// to draw the eye to something that just became relevant -- e.g. the
// "possible direct question" badge. Never repeats on its own; call it
// again explicitly if genuinely needed.
function animatePulse(el) {
  if (PREFERS_REDUCED_MOTION || typeof anime === "undefined") return;
  anime.animate(el, {
    scale: [1, 1.06, 1],
    duration: 420,
    ease: "outQuad",
  });
}

// Smooth expand/collapse using the panel's real measured height, not a
// guessed max-height. `collapsing` is a bool; `contentEl` is the element
// whose height actually changes (the panel itself, since its children
// get hidden/shown by the .minimized CSS class already -- this animates
// the resulting height change instead of an instant jump).
function animateCollapse(panelEl, collapsing, onComplete) {
  if (PREFERS_REDUCED_MOTION || typeof anime === "undefined") {
    if (onComplete) onComplete();
    return;
  }
  const startHeight = panelEl.getBoundingClientRect().height;
  panelEl.classList.toggle("minimized", collapsing);
  const endHeight = panelEl.getBoundingClientRect().height;
  panelEl.style.overflow = "hidden";
  anime.animate(panelEl, {
    height: [startHeight, endHeight],
    duration: 220,
    ease: "outQuad",
    onComplete: () => {
      panelEl.style.height = "";
      panelEl.style.overflow = "";
      if (onComplete) onComplete();
    },
  });
}
