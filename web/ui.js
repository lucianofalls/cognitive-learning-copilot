// Secondary UI chrome -- 2026-08-13, replaces web/tabs.js entirely.
// The sidebar+tabs model tabs.js managed (four tabs + a collapsible
// action group, plus a whole cross-tab toast/alert system to work around
// content being hidden behind whichever tab wasn't active) is gone: the
// two-zone layout (conversation | assistant, see styles.css) keeps the
// conversation and the response feed both on screen at once, so there's
// no more "the thing I need is in a tab I'm not looking at" problem to
// route around. What's left here is smaller and different in kind: the
// Language Coach drawer, the topbar's ••• overflow menu, and the context
// actions bar's own ••• overflow -- three independent open/close popovers,
// not a navigation system.

function openLanguageCoachDrawer() {
  document.getElementById("language-coach-drawer")?.classList.remove("hidden");
  document.getElementById("language-coach-drawer")?.setAttribute("aria-hidden", "false");
  document.getElementById("drawer-backdrop")?.classList.remove("hidden");
}

function closeLanguageCoachDrawer() {
  document.getElementById("language-coach-drawer")?.classList.add("hidden");
  document.getElementById("language-coach-drawer")?.setAttribute("aria-hidden", "true");
  document.getElementById("drawer-backdrop")?.classList.add("hidden");
}

function wireLanguageCoachDrawer() {
  const toggle = document.getElementById("language-coach-drawer-toggle");
  const closeBtn = document.getElementById("language-coach-drawer-close");
  const backdrop = document.getElementById("drawer-backdrop");
  if (!toggle) return;
  toggle.addEventListener("click", () => {
    closeOverflowMenu();
    openLanguageCoachDrawer();
  });
  closeBtn?.addEventListener("click", closeLanguageCoachDrawer);
  backdrop?.addEventListener("click", closeLanguageCoachDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !document.getElementById("language-coach-drawer")?.classList.contains("hidden")) {
      closeLanguageCoachDrawer();
    }
  });
}

// -- topbar ••• overflow menu (Preparar reunião, Language Coach entry
// point, microfone, status técnico, apagar sessão) ------------------------

function closeOverflowMenu() {
  document.getElementById("overflow-menu")?.classList.add("hidden");
  document.getElementById("menu-toggle")?.setAttribute("aria-expanded", "false");
}

function wireOverflowMenu() {
  const toggle = document.getElementById("menu-toggle");
  const menu = document.getElementById("overflow-menu");
  if (!toggle || !menu) return;

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    const opening = menu.classList.contains("hidden");
    menu.classList.toggle("hidden", !opening);
    toggle.setAttribute("aria-expanded", String(opening));
  });

  // Any actual action inside the menu (Preparar reunião, Apagar sessão,
  // the Language Coach toggle) closes it too -- wireLanguageCoachDrawer's
  // own listener already calls closeOverflowMenu(), these cover the rest.
  document.getElementById("prepare-meeting-btn")?.addEventListener("click", closeOverflowMenu);
  document.getElementById("delete-btn")?.addEventListener("click", closeOverflowMenu);

  document.addEventListener("click", (event) => {
    if (!menu.classList.contains("hidden") && !menu.contains(event.target) && event.target !== toggle) {
      closeOverflowMenu();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeOverflowMenu();
  });
}

// -- context actions bar's own ••• (Contexto / Confirmar / Aprender esta
// frase -- the three least-frequent of the seven actions) -----------------

function closeMoreActionsMenu() {
  document.getElementById("more-actions-menu")?.classList.add("hidden");
  document.getElementById("more-actions-toggle")?.setAttribute("aria-expanded", "false");
}

function wireMoreActionsMenu() {
  const toggle = document.getElementById("more-actions-toggle");
  const menu = document.getElementById("more-actions-menu");
  if (!toggle || !menu) return;

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    const opening = menu.classList.contains("hidden");
    menu.classList.toggle("hidden", !opening);
    toggle.setAttribute("aria-expanded", String(opening));
  });
  // Clicking any action inside closes the menu -- app.js's own delegated
  // `.action-btn` listener (wireStaticControls) still fires independently
  // for the actual runAction() call, this only handles the menu chrome.
  menu.addEventListener("click", (event) => {
    if (event.target.closest(".action-btn")) closeMoreActionsMenu();
  });
  document.addEventListener("click", (event) => {
    if (!menu.classList.contains("hidden") && !menu.contains(event.target) && event.target !== toggle) {
      closeMoreActionsMenu();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMoreActionsMenu();
  });
}

wireLanguageCoachDrawer();
wireOverflowMenu();
wireMoreActionsMenu();
