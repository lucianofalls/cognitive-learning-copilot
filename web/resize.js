// Arraste-para-redimensionar -- adicionado 2026-08-12, ajustado 2026-08-13
// para o redesign de duas zonas (Conversa ao vivo | Assistente, ver
// styles.css): a proporção 65/35 padrão nem sempre serve -- em alguns
// dias o assistente precisa de mais espaço, em outros é a conversa.
// Reaproveita o mesmo mecanismo genérico de handle arrastável (proporção
// de flex-grow entre dois elementos) de antes; só sobrou UM handle real
// agora que o layout não é mais cinco painéis/abas, é duas colunas.
//
// A proporção do handle fica salva em localStorage (não há estado de
// usuário no backend -- sem banco, sessão única em memória, por
// design -- então localStorage é o único lugar onde uma preferência
// de layout como essa pode viver entre recarregamentos).

// 0 de propósito: o pedido explícito foi poder encolher um painel até
// sumir de vez ("minimizar a ponto de não aparecer"), não só até um
// mínimo confortável. Isso não prende o usuário -- o próprio handle
// (`.resize-handle-row`/`-column`) tem largura/altura FIXA por CSS
// (`flex: 0 0 auto`), então mesmo com o painel vizinho em 0px o handle
// continua ali, do mesmo tamanho, pronto pra ser arrastado de volta.
const RESIZE_MIN_PX = 0;

function makeResizable(handle, prevEl, nextEl, axis) {
  const storageKey = `panelResize:${handle.id}`;
  const posProp = axis === "column" ? "clientX" : "clientY";
  const sizeProp = axis === "column" ? "width" : "height";

  function applyGrow(prevGrow, nextGrow) {
    prevEl.style.flexGrow = String(prevGrow);
    nextEl.style.flexGrow = String(nextGrow);
  }

  function restore() {
    const saved = localStorage.getItem(storageKey);
    if (saved === null) return;
    const ratio = parseFloat(saved);
    if (Number.isNaN(ratio)) return;
    applyGrow(ratio, 1 - ratio);
  }

  function reset() {
    localStorage.removeItem(storageKey);
    prevEl.style.flexGrow = "";
    nextEl.style.flexGrow = "";
  }

  let startPos = 0;
  let startPrevSize = 0;
  let startNextSize = 0;

  function onPointerDown(event) {
    startPos = event[posProp];
    startPrevSize = prevEl.getBoundingClientRect()[sizeProp];
    startNextSize = nextEl.getBoundingClientRect()[sizeProp];
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add(axis === "column" ? "is-resizing-col" : "is-resizing-row");
  }

  function onPointerMove(event) {
    if (!handle.hasPointerCapture(event.pointerId)) return;
    const delta = event[posProp] - startPos;
    const total = startPrevSize + startNextSize;
    if (total <= 0) return;
    let newPrevSize = startPrevSize + delta;
    newPrevSize = Math.max(RESIZE_MIN_PX, Math.min(total - RESIZE_MIN_PX, newPrevSize));
    applyGrow(newPrevSize / total, (total - newPrevSize) / total);
  }

  function onPointerUp(event) {
    if (!handle.hasPointerCapture(event.pointerId)) return;
    handle.releasePointerCapture(event.pointerId);
    document.body.classList.remove("is-resizing-col", "is-resizing-row");
    localStorage.setItem(storageKey, prevEl.style.flexGrow || "0.5");
  }

  handle.addEventListener("pointerdown", onPointerDown);
  handle.addEventListener("pointermove", onPointerMove);
  handle.addEventListener("pointerup", onPointerUp);
  handle.addEventListener("pointercancel", onPointerUp);
  // Duplo clique num handle devolve o par ao split padrão -- sem isso,
  // um arrasto ruim (painel quase invisível) não teria como ser desfeito
  // a não ser achando o handle certo às cegas e arrastando de volta.
  handle.addEventListener("dblclick", reset);

  restore();

  // Minimizar/maximizar um painel (wirePanelCollapseToggles em app.js)
  // alterna a classe `.minimized`, que tem seu próprio `flex: 0 0 auto`
  // em styles.css -- mas essa regra do stylesheet não consegue vencer um
  // flex-grow inline que este arrasto acabou de aplicar. Suspende a
  // proporção customizada enquanto qualquer um dos dois lados deste
  // handle estiver minimizado, e restaura assim que os dois voltarem a
  // ficar abertos, pra esses dois sistemas não brigarem pelo mesmo
  // style inline.
  const observer = new MutationObserver(() => {
    const eitherMinimized =
      prevEl.classList.contains("minimized") || nextEl.classList.contains("minimized");
    if (eitherMinimized) {
      prevEl.style.flexGrow = "";
      nextEl.style.flexGrow = "";
    } else {
      restore();
    }
  });
  observer.observe(prevEl, { attributes: true, attributeFilter: ["class"] });
  observer.observe(nextEl, { attributes: true, attributeFilter: ["class"] });
}

function wireResizeHandles() {
  // 2026-08-13: the sidebar/tabs redesign's per-tab handles (transcript
  // vs. translation, Ouvido vs. Traduzido) are gone along with the tabs
  // themselves -- transcript+translation are one paired timeline now
  // (no internal split to drag), and the PT-live output is a small
  // fixed-height compact section, not a full column. Just the one
  // handle left: the workspace's Conversa ao vivo | Assistente split.
  const pairs = [["resize-handle-workspace", "column"]];
  pairs.forEach(([handleId, axis]) => {
    const handle = document.getElementById(handleId);
    if (!handle) return;
    const prevEl = handle.previousElementSibling;
    const nextEl = handle.nextElementSibling;
    if (!prevEl || !nextEl) return;
    makeResizable(handle, prevEl, nextEl, axis);
  });
}

wireResizeHandles();
