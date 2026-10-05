/* dota2coach — логика страницы.
   Словари интерфейса и справочные списки приходят в window.I18N: сервер
   вставляет их в <head> при отдаче index.html (см. web/app.py). */

(() => {
  "use strict";

  if (document.documentElement.dataset.directFile === "true") return;

  const CFG = window.I18N;
  const $ = (id) => document.getElementById(id);
  const form = $("form"), statusEl = $("status"), errorEl = $("error"),
        warnEl = $("warning"), resultEl = $("result"), promptEl = $("promptText"),
        workspaceEl = $("workspace"),
        submitBtn = $("submitBtn"), hintEl = $("hint"),
        roleSel = $("roleSelect"), focusNote = $("focusNote"), moreEl = $("more"),
        moreToggle = $("moreToggle"), roleFilter = $("roleFilter"),
        wStart = $("windowStart"), wEnd = $("windowEnd");

  const STORE = "dota2coach:prefs";
  // Версия формата настроек. Настройки прошлых версий игнорируем: например,
  // раньше глубина сохранялась всегда, и это молча отменяло дефолт модели.
  const PREFS_VERSION = 4;
  let lang = CFG.defaultLang;
  let theme = "dark";
  let mode = "match";           // match | game | profile
  const MODES = ["match", "game", "profile"];
  let heroOpen = false;          // раскрыто ли поле «имя моего героя»
  let currentFilename = "prompt.txt";
  let ticker = null;
  let focusNoteTimer = null;
  let phTimer = null;
  let phIndex = 0;
  let currentOverview = null;
  let chartSeries = "gold";
  // Сессия матча: тело запроса, по которому собран основной промпт, вместе со
  // скачанным браузером матчем. Промпт по отрезку отправляет его же, меняя
  // только окно и вопрос, — матч второй раз не качается.
  let session = null;
  // Промпты по отрезкам этой сессии, свежий первым: { window, prompt, note, open }.
  let followups = [];
  // Модель, под которую собран текущий промпт: на неё ведёт «открыть чат».
  let currentModel = null;
  // Контекст последнего разбора — он же контекст отзыва. account_id сюда
  // намеренно НЕ попадает: он опознаёт человека, а для оценки качества не нужен.
  let fbContext = null;
  let fbRating = 0;

  const t = (key, params) => {
    let s = (CFG.strings[lang] || {})[key];
    if (s === undefined) return key;
    if (params) for (const k in params) s = s.replaceAll("{" + k + "}", params[k]);
    return s;
  };

  /* ============================================================
     Настройки: язык, тема, режим, account_id и опции переживают перезагрузку
     ============================================================ */
  const readPrefs = () => {
    try {
      const p = JSON.parse(localStorage.getItem(STORE) || "{}");
      return p.v === PREFS_VERSION ? p : {};
    } catch { return {}; }
  };
  const savePrefs = () => {
    try {
      localStorage.setItem(STORE, JSON.stringify({
        v: PREFS_VERSION, lang, theme, mode,
        // Имя поля в localStorage менять незачем: блокировщики видят только
        // разметку, а переименование молча сбросило бы состояние блока у тех,
        // у кого он был раскрыт.
        advOpen: moreEl.dataset.open === "true",
        accountId: $("accountId").value.trim(),
        matches: $("matches").value.trim(),
        role: roleSel.value || null,
        roleFilter: roleFilter.value || null,
        focus: $("focus").value,
        model: $("model").value,
        mmr: $("mmr").value.trim(),
      }));
    } catch { /* приватный режим — просто не сохраняем */ }
  };

  /* ============================================================
     Тема
     ============================================================ */
  const SUN = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/>';
  const MOON = '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>';

  const applyTheme = () => {
    document.documentElement.dataset.theme = theme;
    // Иконка показывает, КУДА переключит клик, а не текущее состояние.
    $("themeIcon").innerHTML = theme === "dark" ? SUN : MOON;
  };

  /* Снимаем backdrop-filter на один кадр, чтобы композитор пересобрал слои:
     без этого стеклянные поверхности продолжают размывать прежний фон. */
  const repaintGlass = () => {
    const root = document.documentElement;
    root.classList.add("theme-swap");
    requestAnimationFrame(() => requestAnimationFrame(() => {
      root.classList.remove("theme-swap");
    }));
  };

  $("themeBtn").addEventListener("click", () => {
    theme = theme === "dark" ? "light" : "dark";
    applyTheme(); repaintGlass(); savePrefs();
  });

  /* ============================================================
     Режимы: показываем только поля выбранного режима
     ============================================================ */
  const applyMode = () => {
    // data-only — список режимов через пробел: ID матча нужен и разбору игрока,
    // и разбору игры целиком.
    for (const el of document.querySelectorAll("[data-only]")) {
      el.hidden = !el.dataset.only.split(" ").includes(mode);
    }
    // Положение скользящей шайбы задаётся атрибутом, а не инлайн-стилем:
    // анимацию описывает CSS, скрипт только сообщает состояние. Тем же
    // атрибутом на форме раскладка выбирает, какое поле первого ряда широкое.
    $("modes").dataset.mode = mode;
    form.dataset.mode = mode;
    // У поля героя есть своё состояние: оно раскрывается по ссылке «не знаю ID»,
    // и общий цикл по режимам не должен показывать его сам.
    $("heroField").hidden = mode !== "match" || !heroOpen;
    loadRecent();
    for (const btn of document.querySelectorAll(".mode")) {
      btn.setAttribute("aria-selected", String(btn.dataset.mode === mode));
    }
    $("groupBasicsText").textContent = t("group." + mode);
    // Перечень в свёрнутом виде должен называть поля ТЕКУЩЕГО режима: у разбора
    // игры целиком нет ни роли, ни фокуса.
    $("moreSummary").textContent = t("advanced.summary." + mode);
    $("footCmd").textContent = {
      match: "python -m dota2coach analyze <match_id> --me <account_id>",
      game: "python -m dota2coach analyze <match_id> --game",
      profile: "python -m dota2coach profile <account_id> -n 10",
    }[mode];
    setBusy(false);
  };

  for (const btn of document.querySelectorAll(".mode")) {
    btn.addEventListener("click", () => {
      if (mode === btn.dataset.mode) return;
      mode = btn.dataset.mode;
      // Результат предыдущего режима к новому отношения не имеет.
      hide(errorEl, warnEl, workspaceEl, resultEl);
      currentOverview = null;
      session = null;
      history.replaceState(null, "", location.pathname);
      closeHint();
      applyMode(); savePrefs();
    });
  }

  /* ============================================================
     Расширенные настройки
     ============================================================ */
  const setAdvanced = (open) => {
    moreEl.dataset.open = String(open);
    moreToggle.setAttribute("aria-expanded", String(open));
  };

  moreToggle.addEventListener("click", () => {
    setAdvanced(moreEl.dataset.open !== "true");
    savePrefs();
  });

  /* ============================================================
     Ползунок тайм-рейнджа
     ============================================================ */
  const MIN_SPAN = 1;   // окно в ноль минут смысла не имеет

  const syncRange = () => {
    let a = Number(wStart.value), b = Number(wEnd.value);
    if (b - a < MIN_SPAN) {
      // Раздвигаем ту ручку, которую НЕ держит пользователь, иначе она
      // «прилипает» и перетаскивание упирается в невидимую стену.
      if (document.activeElement === wStart) b = Math.min(Number(wEnd.max), a + MIN_SPAN);
      else a = Math.max(0, b - MIN_SPAN);
      wStart.value = a; wEnd.value = b;
    }
    const max = Number(wStart.max);

    // Ручка не доезжает до самых краёв дорожки — её центр гуляет в пределах
    // (ширина - ширина ручки). Без этой поправки и подпись, и активный трек
    // уползают от ручки на краях диапазона. Диаметр берём из CSS-переменной,
    // а не константой: размер ручки — решение оформления, и дублировать его
    // числом в скрипте значит однажды разъехаться с ним.
    const THUMB = parseFloat(
      getComputedStyle($("rangeFill").closest(".range")).getPropertyValue("--thumb")) || 20;
    const track = $("rangeFill").parentElement.clientWidth || 1;
    const at = (v) => THUMB / 2 + (track - THUMB) * (v / max);
    const posA = at(a), posB = at(b);

    // Заливка идёт от центра одной ручки до центра другой, без зазоров. Зазор
    // был данью форме слайдера M3, но с двумя ручками он резал полосу на три
    // отдельных куска; отделяет ручку теперь кольцо-хват внутри неё.
    $("rangeFill").style.left = posA + "px";
    $("rangeFill").style.width = Math.max(0, posB - posA) + "px";

    const one = $("bubbleStart"), two = $("bubbleEnd"), both = $("bubbleBoth");
    // Текст ставим ДО замеров: ширина зависит от него («100» шире «8»), а
    // решение о схлопывании — от ширины.
    one.textContent = a;
    two.textContent = b;
    both.textContent = a + "\u2013" + b;

    const halfA = one.offsetWidth / 2, halfB = two.offsetWidth / 2;
    // Две подписи рядом наезжают друг на друга. Порог — по их фактической
    // ширине плюс зазор, а не по угаданному числу.
    const merged = posB - posA < halfA + halfB + 8;

    one.classList.toggle("is-off", merged);
    two.classList.toggle("is-off", merged);
    both.classList.toggle("is-off", !merged);

    // Зажим по краям, чтобы подпись не вылезла за габарит дорожки на 0 и на
    // максимуме — там ручка стоит вплотную к краю, а подпись шире неё.
    const clamp = (x, half) => Math.min(Math.max(x, half), track - half);
    if (merged) {
      const halfBoth = both.offsetWidth / 2;
      both.style.left = clamp((posA + posB) / 2, halfBoth) + "px";
    } else {
      one.style.left = clamp(posA, halfA) + "px";
      two.style.left = clamp(posB, halfB) + "px";
    }
    $("windowValue").textContent = t("window.range", { start: a, end: b });
    $("followupBtn").disabled = !session || followupBusy;
  };

  /* Шкала ползунка — длина этого матча, а не условные 80 минут: иначе в
     короткой игре половина дорожки вела бы в пустоту. */
  const setRangeMax = (minutes) => {
    const max = Math.max(MIN_SPAN + 1, minutes);
    for (const input of [wStart, wEnd]) input.max = max;
    const step = max > 60 ? 20 : max > 30 ? 10 : 5;
    const ticks = $("rangeTicks");
    ticks.replaceChildren();
    for (let v = 0; v <= max; v += step) {
      if (max - v < step / 2 && v !== 0) continue;   // не слипаться с последней
      const tick = makeNode("span", "", v);
      tick.style.setProperty("--v", v / max);
      ticks.append(tick);
    }
    const last = makeNode("span", "", max);
    last.style.setProperty("--v", 1);
    ticks.append(last);
  };

  const setWindow = (start, end) => {
    const max = Number(wEnd.max);
    start = Math.max(0, Math.min(max - MIN_SPAN, Math.round(start)));
    end = Math.max(start + MIN_SPAN, Math.min(max, Math.round(end)));
    wStart.value = start;
    wEnd.value = end;
    syncRange();
    refreshExplorerWindow();
  };

  for (const input of [wStart, wEnd]) {
    input.addEventListener("input", () => {
      syncRange();
      refreshExplorerWindow();
    });
  }

  /* Пока ручку тащат, у заливки и подписей не должно быть ни одного перехода:
     нативная ручка идёт за курсором в том же кадре, а всё, что анимируется,
     догоняет её и выглядит как рассинхрон. Отпустили — переходы возвращаются,
     они нужны шагам с клавиатуры.

     pointerup слушаем на окне, а не на инпуте: палец или курсор почти всегда
     уходит за пределы ручки, и событие до неё уже не долетит. */
  const setDragging = (on) => {
    if (on) $("rangeWrap").dataset.dragging = "true";
    else delete $("rangeWrap").dataset.dragging;
  };
  for (const el of [wStart, wEnd]) {
    el.addEventListener("pointerdown", () => setDragging(true));
  }
  for (const ev of ["pointerup", "pointercancel"]) {
    window.addEventListener(ev, () => setDragging(false));
  }

  /* ============================================================
     Язык: перерисовываем подписи, плейсхолдеры и содержимое селектов
     ============================================================ */
  /* Иконки позиций. Нативный select остаётся источником истины: на нём висит
     вся логика role-aware фокусов, и дублировать её было бы способом
     рассинхронизировать. Кнопки лишь пишут в него значение и шлют change. */
  /* Иконки позиций. Читаемость важнее детализации: это ЗАЛИВНЫЕ силуэты, а не
     контурные рисунки — на 20px тонкая линия сливается в кашу. Нарисованы
     здесь же, никаких ассетов Valve.

     Метафоры выбраны так, чтобы силуэты не путались между собой: искра —
     «определить само»; меч — кери; молния — мид (темп); щит — оффлейн; глаз —
     soft support (вижн и роуминг); сердце — hard support (сейвы и лечение).
     Прежние «чаши ладоней» у 4 и 5 отличались друг от друга только начинкой и
     на таком размере сливались в одно пятно. */
  const ROLE_GLYPH = {
    // Искра: крупная четырёхлучевая звезда и маленькая рядом — «подберётся само».
    "": '<path d="M11 2.2 12.9 7.9 18.6 9.8 12.9 11.7 11 17.4 9.1 11.7 3.4 9.8 9.1 7.9z"/>'
      + '<path d="M18 14.2 18.9 16.9 21.6 17.8 18.9 18.7 18 21.4 17.1 18.7 14.4 17.8 17.1 16.9z"/>',
    // Меч: остриё вверх, широкая гарда, рукоять, навершие. Силуэт меча держится
    // на длинной оси и поперечной гарде — их и рисуем.
    "1": '<path d="M12 1.4 14.8 6.9v5.5H9.2V6.9z"/>'
       + '<path d="M5.6 12.4h12.8v2.7H5.6z"/>'
       + '<path d="M10.6 15.1h2.8v4.1h-2.8z"/>'
       + '<path d="M12 18.7a1.9 1.9 0 1 0 0 3.8 1.9 1.9 0 0 0 0-3.8z"/>',
    // Молния: темп, руны, ранний импакт.
    "2": '<path d="M13.6 1.8 5.2 13.2h5.2l-1 9 9.4-12h-5.6z"/>',
    // Щит: «принимаю удар на себя».
    "3": '<path d="M12 2.2 20.2 5.4v6.1c0 4.7-3.3 8.4-8.2 10.3C7.1 19.9 3.8 16.2 3.8 11.5V5.4z"/>',
    // Глаз: вижн и роуминг. Веко — кольцо через evenodd, зрачок — отдельный круг:
    // сплошной глаз без выреза читался бы как линза.
    "4": '<path fill-rule="evenodd" d="M12 4.6C7.2 4.6 3.1 8 1.4 12c1.7 4 5.8 7.4 10.6 7.4S20.9 16 22.6 12C20.9 8 16.8 4.6 12 4.6zm0 11.7a4.3 4.3 0 1 1 0-8.6 4.3 4.3 0 0 1 0 8.6z"/>'
       + '<circle cx="12" cy="12" r="2.2"/>',
    // Сердце: сейвы и лечение. Один сплошной силуэт — самый читаемый из всех.
    "5": '<path d="M12 21.4 3.9 13.3a5.1 5.1 0 0 1 7.3-7.1l.8.8.8-.8a5.1 5.1 0 0 1 7.3 7.1z"/>',
  };

  const roleCells = () => [...$("roleIcons").querySelectorAll(".seg-item")];

  const renderRoleIcons = () => {
    const host = $("roleIcons");
    // Шайба живёт вне цикла перерисовки подписей: пересоздавать её при смене
    // языка значило бы каждый раз проигрывать её поездку от нулевой позиции.
    host.innerHTML = '<span class="seg-thumb" aria-hidden="true"></span>';
    for (const code of ["", ...CFG.roles]) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "seg-item ripple";
      b.dataset.role = code;
      b.setAttribute("role", "radio");
      b.title = code === "" ? t("role.auto") : t("role." + code);
      b.innerHTML =
        `<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">${ROLE_GLYPH[code]}</svg>`
        + `<span>${code === "" ? t("role.auto.short") : code}</span>`;
      host.append(b);
    }
  };

  const syncRoleIcons = () => {
    const cells = roleCells();
    for (const cell of cells) {
      cell.setAttribute("aria-checked", String(cell.dataset.role === roleSel.value));
      // Roving tabindex: в радиогруппе Tab заходит на выбранный элемент, а
      // дальше переключение идёт стрелками — так это и ожидается с клавиатуры.
      cell.tabIndex = cell.dataset.role === roleSel.value ? 0 : -1;
    }
    // Раскладку считает CSS, скрипт сообщает только номер выбранной ячейки.
    const at = cells.findIndex((c) => c.dataset.role === roleSel.value);
    $("roleIcons").style.setProperty("--at", Math.max(at, 0));
  };

  const pickRole = (code) => {
    if (roleSel.value === code) return;
    roleSel.value = code;
    roleSel.dispatchEvent(new Event("change"));
    syncRoleIcons();
  };

  $("roleIcons").addEventListener("click", (e) => {
    const cell = e.target.closest(".seg-item");
    if (cell) pickRole(cell.dataset.role);
  });

  $("roleIcons").addEventListener("keydown", (e) => {
    const keys = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"];
    if (!keys.includes(e.key)) return;
    e.preventDefault();
    const cells = roleCells();
    const at = cells.findIndex((c) => c.dataset.role === roleSel.value);
    const step = (e.key === "ArrowRight" || e.key === "ArrowDown") ? 1 : -1;
    const next = cells[(at + step + cells.length) % cells.length];
    pickRole(next.dataset.role);
    next.focus();
  });

  const renderRoleOptions = () => {
    const keep = roleSel.value;
    roleSel.innerHTML = "";
    roleSel.append(new Option(t("role.auto"), ""));
    for (const code of CFG.roles) roleSel.append(new Option(t("role." + code), code));
    roleSel.value = CFG.roles.includes(keep) ? keep : "";

    const keepFilter = roleFilter.value;
    roleFilter.innerHTML = "";
    roleFilter.append(new Option(t("role.any"), ""));
    for (const code of CFG.roles) roleFilter.append(new Option(t("role." + code), code));
    roleFilter.value = CFG.roles.includes(keepFilter) ? keepFilter : "";
  };

  const renderFocusOptions = (notify = false) => {
    const focusSel = $("focus");
    const keep = focusSel.value;
    const allowed = roleSel.value && CFG.roleFocuses[roleSel.value]
      ? CFG.roleFocuses[roleSel.value]
      : CFG.focuses;
    focusSel.innerHTML = "";
    for (const code of allowed) focusSel.append(new Option(t("focus." + code), code));
    const preserved = allowed.includes(keep);
    focusSel.value = preserved ? keep : "full";

    clearTimeout(focusNoteTimer);
    focusNote.hidden = !(notify && keep && !preserved);
    if (!focusNote.hidden) {
      focusNote.textContent = t("focus.adjusted");
      focusNoteTimer = setTimeout(() => { focusNote.hidden = true; }, 5000);
    }
  };

  /* Плейсхолдер вопроса чередуется: один пример читается как «надо писать так»,
     несколько показывают, что спросить можно про что угодно. */
  const NOTE_PH = ["field.note.ph.1", "field.note.ph.2", "field.note.ph.3"];

  const rotateNotePlaceholder = () => {
    const el = $("note");
    // Пока в поле пишут, подсказку не трогаем — это отвлекает.
    if (document.activeElement !== el) {
      el.placeholder = t(NOTE_PH[phIndex % NOTE_PH.length]);
      phIndex += 1;
    }
  };

  const startPlaceholderRotation = () => {
    clearInterval(phTimer);
    rotateNotePlaceholder();
    phTimer = setInterval(rotateNotePlaceholder, 6500);
  };

  const applyLang = () => {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-ph]").forEach((el) => {
      el.placeholder = t(el.dataset.i18nPh);
    });
    document.querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.title = t(el.dataset.i18nTitle);
    });
    document.querySelectorAll("[data-i18n-aria]").forEach((el) => {
      el.setAttribute("aria-label", t(el.dataset.i18nAria));
    });

    renderRoleOptions();
    renderRoleIcons();
    syncRoleIcons();
    renderFocusOptions(false);
    applyMode();
    syncRange();
    startPlaceholderRotation();

    $("fbSend").textContent = t("feedback.send");
    $("copyBtn").textContent = t("result.copy");
    renderOpenChat();
    renderFollowups();
    renderRecent();
    if (!followupBusy) $("followupBtn").textContent = t("session.submit");
    renderChartTabs();
    $("downloadBtn").textContent = t("result.download");
    $("chipNote").textContent = t("result.with_note");
    if ($("chipRole").textContent && roleSel.value) {
      $("chipRole").textContent = t("result.role", { role: t("role." + roleSel.value) });
    }
    if (currentOverview) renderOverview(currentOverview);
    if (!hintEl.hidden) hintEl.hidden = true;
  };

  /* ============================================================
     Ripple: одна делегированная подписка на всю страницу
     ============================================================ */
  // Система просит меньше движения — волну не создаём вовсе. Обнулённая
  // длительность оставила бы после себя мусорные узлы в DOM.
  const calmMotion = matchMedia("(prefers-reduced-motion: reduce)");

  document.addEventListener("pointerdown", (e) => {
    if (calmMotion.matches) return;
    const host = e.target.closest(".ripple");
    if (!host || host.disabled) return;

    const r = host.getBoundingClientRect();
    // Радиус до самого дальнего угла: волна обязана накрыть поверхность
    // целиком, откуда бы ни начиналась.
    const dx = Math.max(e.clientX - r.left, r.right - e.clientX);
    const dy = Math.max(e.clientY - r.top, r.bottom - e.clientY);
    const radius = Math.hypot(dx, dy);

    const wave = document.createElement("span");
    wave.className = "ripple-wave";
    wave.style.width = wave.style.height = radius * 2 + "px";
    wave.style.left = (e.clientX - r.left - radius) + "px";
    wave.style.top = (e.clientY - r.top - radius) + "px";
    host.appendChild(wave);
    wave.addEventListener("animationend", () => wave.remove(), { once: true });
  });

  /* ============================================================
     Инфо-окно
     ============================================================ */
  const infoModal = $("infoModal");
  let infoOpener = null;

  const openInfo = () => {
    infoOpener = document.activeElement;
    infoModal.hidden = false;
    // Фон не должен уезжать под модалкой на мобильном.
    document.body.style.overflow = "hidden";
    $("infoClose").focus({ preventScroll: true });
  };

  const closeInfo = () => {
    if (infoModal.hidden) return;
    infoModal.hidden = true;
    document.body.style.overflow = "";
    // Возвращаем фокус туда, откуда открыли: иначе он улетает в начало страницы.
    if (infoOpener && infoOpener.focus) infoOpener.focus({ preventScroll: true });
    infoOpener = null;
  };

  $("infoBtn").addEventListener("click", openInfo);
  $("infoClose").addEventListener("click", closeInfo);
  // Клик мимо окна закрывает: сам backdrop и есть «мимо», внутренняя карточка —
  // отдельный элемент, и клики по ней сюда не долетают.
  infoModal.addEventListener("click", (e) => { if (e.target === infoModal) closeInfo(); });

  infoModal.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    // Ловушка фокуса: пока окно открыто, Tab не должен уводить на страницу за ним.
    const focusable = infoModal.querySelectorAll("button, [href], a");
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  });

  /* ============================================================
     Подсказки: по клику, а не по ховеру — ховер недоступен с клавиатуры
     ============================================================ */
  let openHintBtn = null;

  const closeHint = () => {
    hintEl.hidden = true;
    if (openHintBtn) openHintBtn.setAttribute("aria-expanded", "false");
    openHintBtn = null;
  };

  const openHint = (btn) => {
    hintEl.textContent = t(btn.dataset.hint);
    hintEl.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    openHintBtn = btn;

    // Позиционируем под значком и удерживаем в пределах окна.
    const r = btn.getBoundingClientRect();
    const w = Math.min(380, window.innerWidth - 32);
    hintEl.style.width = w + "px";
    let left = r.left + window.scrollX - 6;
    left = Math.min(left, window.scrollX + window.innerWidth - w - 16);
    hintEl.style.left = Math.max(window.scrollX + 16, left) + "px";
    hintEl.style.top = (r.bottom + window.scrollY + 8) + "px";
  };

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-hint]");
    if (btn) {
      e.preventDefault();
      if (openHintBtn === btn) closeHint(); else openHint(btn);
      return;
    }
    if (!e.target.closest("#hint")) closeHint();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    // Подсказка поверх модалки — закрываем сначала её, окно остаётся.
    if (!hintEl.hidden) closeHint(); else closeInfo();
  });
  window.addEventListener("resize", () => { closeHint(); syncRange(); });

  /* ============================================================
     Форма
     ============================================================ */
  roleSel.addEventListener("change", () => { renderFocusOptions(true); savePrefs(); });

  $("heroToggle").addEventListener("click", () => {
    heroOpen = !heroOpen;
    $("heroField").hidden = !heroOpen;
    if (heroOpen) $("hero").focus({ preventScroll: true });
  });

  /* Из ссылки на матч вытаскиваем номер: люди копируют именно ссылку. */
  const parseMatchId = (raw) => {
    const digits = String(raw).match(/\d{5,}/g);
    if (!digits) return null;
    const best = digits.sort((a, b) => b.length - a.length)[0];
    return Number(best);
  };

  const estimateTokens = (text) => {
    // Грубая оценка: у кириллицы токенов на символ заметно больше, чем у латиницы.
    const cyr = (text.match(/[Ѐ-ӿ]/g) || []).length / Math.max(text.length, 1);
    const perToken = 4 - 1.6 * cyr;
    const n = Math.round(text.length / perToken);
    return n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n);
  };

  /* ============================================================
     Загрузка и ошибки
     ============================================================ */
  // Разные режимы ждут по-разному: матч может уйти в парсинг, профиль тянет
  // матчи по одному. Тексты этапов у них поэтому свои.
  const STAGES = {
    match: [[0, "stage.0"], [6, "stage.6"], [14, "stage.14"], [40, "stage.40"]],
    profile: [[0, "pstage.0"], [4, "pstage.4"], [25, "pstage.25"], [90, "pstage.90"]],
  };

  const startTicker = () => {
    const t0 = Date.now();
    const stages = STAGES[mode === "profile" ? "profile" : "match"];
    const tick = () => {
      const sec = Math.round((Date.now() - t0) / 1000);
      let key = stages[0][1];
      for (const [at, k] of stages) if (sec >= at) key = k;
      statusEl.textContent = `${t(key)}  ${sec} ${t("stage.seconds")}`;
    };
    tick();
    ticker = setInterval(tick, 1000);
  };
  const stopTicker = () => { clearInterval(ticker); ticker = null; statusEl.textContent = ""; };

  function setBusy(busy) {
    const label = mode === "profile" ? "submit.profile" : "submit";
    const busyLabel = mode === "profile" ? "submit.busy.profile" : "submit.busy";
    submitBtn.disabled = busy;
    form.setAttribute("aria-busy", String(busy));
    submitBtn.innerHTML = busy
      ? '<span class="wave" aria-hidden="true"><i></i><i></i><i></i></span>' + t(busyLabel)
      : t(label);
  }

  function hide(...els) { els.forEach((el) => { el.hidden = true; }); }

  const showPanel = (el, title, text) => {
    el.innerHTML = "";
    if (title) { const b = document.createElement("strong"); b.textContent = title; el.appendChild(b); }
    el.appendChild(document.createTextNode(text));
    el.hidden = false;
  };

  const numOrNull = (v) => { const s = v.trim(); return s === "" ? null : Number(s); };

  const badAccount = (id) => id === null || !Number.isInteger(id) || id <= 0;

  /* ============================================================
     OpenDota напрямую из браузера
     ============================================================ */
  /* Почему страница ходит в OpenDota сама. Лимит OpenDota считается по IP:
     60 запросов в минуту и около 3000 в сутки. Бесплатный хостинг выходит в сеть
     через общие адреса, одни на множество чужих сервисов, и их суточный лимит
     выбирают другие — сервер получал 429 на первом же запросе. OpenDota разрешает
     CORS, поэтому матч забирает браузер, со своего IP и в пределах своего лимита,
     а серверу отдаёт готовый ответ. Сервер по-прежнему умеет сходить сам: если
     здесь что-то не получилось, просто отправляем запрос без данных. */
  const OPENDOTA = "https://api.opendota.com/api";
  const PARSE_WAIT_MS = 90000;
  const PARSE_POLL_MS = 5000;
  const PREFETCH_PARALLEL = 4;

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const odFetch = async (path, params, init) => {
    const url = new URL(OPENDOTA + path);
    for (const [key, value] of Object.entries(params || {})) {
      if (value !== null && value !== undefined) url.searchParams.set(key, value);
    }
    const res = await fetch(url, { headers: { Accept: "application/json" }, ...init });
    if (!res.ok) {
      const error = new Error(`OpenDota ${res.status}`);
      error.status = res.status;
      throw error;
    }
    return res.json().catch(() => null);
  };

  // OpenDota проставляет version, когда матч прошёл детальный парсинг.
  const isParsed = (raw) => raw && raw.version !== null && raw.version !== undefined;

  /* Заказать парсинг и дождаться его. Пока задача жива, /request/{job} отдаёт
     объект, по завершении — null. Не дождались — не беда: сервер получит то,
     что есть, и честно предупредит о неполных данных. */
  const waitForParse = async (matchId) => {
    const job = await odFetch(`/request/${matchId}`, null, { method: "POST" });
    const jobId = job && job.job && job.job.jobId;
    const deadline = Date.now() + PARSE_WAIT_MS;
    while (jobId && Date.now() < deadline) {
      await sleep(PARSE_POLL_MS);
      if (!(await odFetch(`/request/${jobId}`))) break;
    }
    return odFetch(`/matches/${matchId}`);
  };

  /* Результат: { raw } — матч скачан; { notFound: true } — такого матча нет, и
     спрашивать сервер бессмысленно; null — не вышло, пусть сервер попробует. */
  async function prefetchMatch(matchId) {
    try {
      let raw = await odFetch(`/matches/${matchId}`);
      if (!raw || raw.match_id === undefined || raw.match_id === null) return null;
      if (!isParsed(raw)) {
        try {
          const refreshed = await waitForParse(matchId);
          if (refreshed && refreshed.match_id) raw = refreshed;
        } catch { /* парсинг не заказался — идём с базовыми данными */ }
      }
      return { raw };
    } catch (error) {
      return error.status === 404 ? { notFound: true } : null;
    }
  }

  // Не больше PREFETCH_PARALLEL запросов одновременно: вежливо к API и укладывается
  // в минутный лимит даже для профиля на 40 матчей.
  const mapLimited = async (items, limit, worker) => {
    const results = new Array(items.length);
    let next = 0;
    const lane = async () => {
      while (next < items.length) {
        const index = next++;
        results[index] = await worker(items[index]);
      }
    };
    await Promise.all(Array.from({ length: Math.min(limit, items.length) }, lane));
    return results;
  };

  /* ============================================================
     Последние игры игрока
     ============================================================ */
  /* По сохранённому account_id страница сама подтягивает последние игры: ID
     матча больше не нужно копировать с Dotabuff. Запрос идёт со своего IP, как
     и сами матчи; имена героев — у сервера, его справочник уже прогрет. */
  const RECENT_LIMIT = 8;
  let heroNames = null;                       // Promise<{ hero_id: имя }>
  let recent = { account: null, rows: [] };
  let recentTimer = null;

  const loadHeroNames = () => {
    if (!heroNames) {
      heroNames = fetch("/api/heroes")
        .then((res) => (res.ok ? res.json() : {}))
        .catch(() => { heroNames = null; return {}; });
    }
    return heroNames;
  };

  async function loadRecent() {
    const id = numOrNull($("accountId").value);
    if (mode === "profile" || badAccount(id)) {
      recent = { account: null, rows: [] };
      renderRecent();
      return;
    }
    if (recent.account === id) { renderRecent(); return; }
    recent = { account: id, rows: [] };
    renderRecent();
    try {
      const [rows, names] = await Promise.all([
        odFetch(`/players/${id}/recentMatches`), loadHeroNames(),
      ]);
      if (recent.account !== id) return;       // пока грузили, ID поменяли
      recent.rows = (Array.isArray(rows) ? rows : []).slice(0, RECENT_LIMIT)
        .map((row) => ({ ...row, hero: names[row.hero_id] || null }));
    } catch {
      recent.rows = [];
    }
    renderRecent();
  }

  const timeAgo = (unixSeconds) => {
    const diff = Math.round(unixSeconds - Date.now() / 1000);
    const format = new Intl.RelativeTimeFormat(localeForLang(), { numeric: "auto" });
    const abs = Math.abs(diff);
    if (abs < 3600) return format.format(Math.round(diff / 60), "minute");
    if (abs < 86400) return format.format(Math.round(diff / 3600), "hour");
    return format.format(Math.round(diff / 86400), "day");
  };

  function renderRecent() {
    const host = $("recentList");
    host.replaceChildren();
    const rows = mode === "profile" ? [] : recent.rows;
    $("recent").hidden = !rows.length;
    const current = parseMatchId($("matchId").value);
    for (const row of rows) {
      // player_slot < 128 — Radiant.
      const win = (Number(row.player_slot) < 128) === Boolean(row.radiant_win);
      const item = makeNode("button", "recent-item ripple");
      item.type = "button";
      item.dataset.win = String(win);
      item.setAttribute("aria-pressed", String(row.match_id === current));
      item.title = t("recent.pick", { id: row.match_id });
      item.append(
        makeNode("span", "recent-hero", row.hero || `#${row.hero_id}`),
        makeNode("span", "recent-meta", [
          t(win ? "recent.win" : "recent.lose"),
          `${row.kills || 0}/${row.deaths || 0}/${row.assists || 0}`,
          timeAgo(Number(row.start_time || 0) + Number(row.duration || 0)),
        ].join(" · ")),
      );
      item.addEventListener("click", () => {
        $("matchId").value = row.match_id;
        renderRecent();
        submitBtn.focus({ preventScroll: true });
      });
      host.append(item);
    }
  }

  $("accountId").addEventListener("input", () => {
    clearTimeout(recentTimer);
    recentTimer = setTimeout(loadRecent, 700);
  });
  $("matchId").addEventListener("input", renderRecent);

  /* Для профиля: план запроса (hero_id и линию умеют вычислять только
     справочники сервера) → список матчей игрока → сами матчи. Ошибка плана —
     например, неопознанный герой — показывается сразу: сервер ответил бы тем же. */
  async function prefetchProfile(body) {
    // Пустое «сколько матчей» — это «по умолчанию»: параметр не передаём вовсе.
    const query = new URLSearchParams();
    if (body.matches) query.set("matches", body.matches);
    if (body.hero) query.set("hero", body.hero);
    if (body.role) query.set("role", body.role);
    const planRes = await fetch(`/api/profile/plan?${query}`);
    if (!planRes.ok) {
      return { error: { status: planRes.status, data: await planRes.json().catch(() => ({})) } };
    }
    const plan = await planRes.json();
    try {
      const rows = await odFetch(`/players/${body.account_id}/matches`, {
        limit: plan.limit, hero_id: plan.hero_id, lane_role: plan.lane_role,
        project: "hero_id",
      });
      const ids = (Array.isArray(rows) ? rows : []).map((row) => row && row.match_id).filter(Boolean);
      const raws = await mapLimited(ids, PREFETCH_PARALLEL,
        (id) => odFetch(`/matches/${id}`).catch(() => null));
      return { match_ids: ids, raw_matches: raws.filter(Boolean) };
    } catch {
      return null;
    }
  }

  /* Дополняет тело запроса тем, что удалось скачать. Возвращает false, если
     продолжать незачем — ошибка уже показана. */
  async function attachPrefetched(request) {
    if (request.url === "/api/analyze") {
      const got = await prefetchMatch(request.body.match_id);
      if (got && got.notFound) {
        showError(404, { detail: { kind: "not_found", message: "" } });
        return false;
      }
      if (got) request.body.raw_match = got.raw;
      return true;
    }
    const got = await prefetchProfile(request.body);
    if (got && got.error) { showError(got.error.status, got.error.data); return false; }
    if (got) Object.assign(request.body, got);
    return true;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    closeHint();
    hide(errorEl, warnEl, workspaceEl, resultEl);
    currentOverview = null;
    session = null;

    const accountId = numOrNull($("accountId").value);
    const request = mode === "profile"
      ? buildProfileRequest(accountId)
      : buildMatchRequest(accountId);
    if (!request) return;

    savePrefs();
    setBusy(true);
    startTicker();

    try {
      if (!(await attachPrefetched(request))) return;
      const res = await fetch(request.url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request.body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { showError(res.status, data); return; }
      if (request.url === "/api/analyze") session = { body: request.body, mode };
      showResult(data);
    } catch {
      showPanel(errorEl, t("err.offline"), t("err.offline.body"));
    } finally {
      stopTicker();
      setBusy(false);
    }
  });

  function buildMatchRequest(accountId) {
    const matchId = parseMatchId($("matchId").value);
    if (!matchId) { showPanel(errorEl, t("err.match"), t("err.match.body")); return null; }

    const note = $("note").value.trim() || null;
    // Разбор игры целиком: никого не ищем, роль и фокус не нужны. Глубину
    // не передаём вовсе — сервер возьмёт дефолт выбранной модели.
    if (mode === "game") {
      return {
        url: "/api/analyze",
        body: { match_id: matchId, whole_game: true, model: $("model").value,
                lang: lang, note: note },
      };
    }

    const hero = $("hero").value.trim();
    if (accountId === null && hero === "") {
      showPanel(errorEl, t("err.who"), t("err.who.body")); return null;
    }
    if (accountId !== null && badAccount(accountId)) {
      showPanel(errorEl, t("err.account"), t("err.account.body")); return null;
    }

    return {
      url: "/api/analyze",
      body: {
        match_id: matchId,
        account_id: accountId,
        hero: hero || null,
        role: roleSel.value || null,
        focus: $("focus").value,
        model: $("model").value,
        lang: lang,
        note: note,
        mmr: $("mmr").value.trim() || null,
      },
    };
  }

  function buildProfileRequest(accountId) {
    if (badAccount(accountId)) {
      showPanel(errorEl, t("err.account"), t("err.account.body")); return null;
    }
    const matches = numOrNull($("matches").value);
    return {
      url: "/api/profile",
      body: {
        account_id: accountId,
        // Пустое поле — это «сколько по умолчанию», а не ошибка ввода:
        // сервер сам подставит и провалидирует границы.
        matches: matches === null ? undefined : matches,
        hero: $("heroFilter").value.trim() || null,
        role: roleFilter.value || null,
        model: $("model").value,
        lang: lang,
        note: $("note").value.trim() || null,
        mmr: $("mmr").value.trim() || null,
      },
    };
  }

  /* ============================================================
     Match Explorer: факты OpenDota отдельно от coach-prompt
     ============================================================ */
  const localeForLang = () => ({ ru: "ru-RU", uk: "uk-UA", en: "en-US" })[lang] || "en-US";

  const formatNumber = (value, digits = 0) => {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return number.toLocaleString(localeForLang(), {
      maximumFractionDigits: digits,
      minimumFractionDigits: 0,
    });
  };

  const formatSigned = (value) => {
    const number = Number(value) || 0;
    return (number > 0 ? "+" : "") + formatNumber(number);
  };

  const formatClock = (seconds) => {
    const raw = Math.round(Number(seconds) || 0);
    const sign = raw < 0 ? "−" : "";
    const absolute = Math.abs(raw);
    return sign + Math.floor(absolute / 60) + ":" + String(absolute % 60).padStart(2, "0");
  };

  const formatDuration = (seconds) => {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    return Math.floor(total / 60) + ":" + String(total % 60).padStart(2, "0");
  };

  const makeNode = (tag, className, value) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined && value !== null) element.textContent = String(value);
    return element;
  };

  const emptyState = () => makeNode("div", "empty-state", t("explorer.empty"));

  const roleLabel = (role) => {
    const key = "role." + role;
    const value = t(key);
    if (value !== key) return value;
    if (role === "core") return "Core";
    if (role === "support") return "Support";
    return role || "—";
  };

  const isNeutral = (overview) => Boolean(overview && overview.perspective
                                          && overview.perspective.neutral);

  // Выбранный в панели уточнения отрезок, в минутах.
  const selectedWindow = () => ({ start: Number(wStart.value), end: Number(wEnd.value) });

  const fightInsideWindow = (fight, windowState) =>
    Number(fight.end) / 60 >= windowState.start && Number(fight.start) / 60 <= windowState.end;

  function renderOverviewCards(overview, me) {
    const host = $("overviewCards");
    host.replaceChildren();
    const perspective = overview.perspective || {};
    const metrics = [
      ["explorer.metric.kda", `${me.kills || 0} / ${me.deaths || 0} / ${me.assists || 0}`,
       t("explorer.metric.level", { level: me.level || 0 })],
      ["explorer.metric.kp", formatNumber(perspective.kill_participation_pct) + "%",
       t("explorer.metric.team_kills", { kills: perspective.team_kills || 0 })],
      ["explorer.metric.networth", formatNumber(me.net_worth), `GPM ${formatNumber(me.gpm)}`],
      ["explorer.metric.last_hits", `${formatNumber(me.last_hits)} / ${formatNumber(me.denies)}`,
       `XPM ${formatNumber(me.xpm)}`],
    ];
    for (const [label, value, context] of metrics) {
      const card = makeNode("div", "metric-card");
      card.append(
        makeNode("span", "metric-label", t(label)),
        makeNode("strong", "metric-value", value),
        makeNode("span", "metric-context", context),
      );
      host.append(card);
    }
  }

  function renderSignals(overview) {
    const host = $("signalList");
    host.replaceChildren();
    const signals = Array.isArray(overview.signals) ? overview.signals : [];
    $("signalsPanel").hidden = isNeutral(overview);
    if (!signals.length) {
      host.append(makeNode("div", "empty-state", t("explorer.signals.empty")));
      return;
    }
    for (const signal of signals) {
      const row = makeNode("div", "signal-row");
      row.dataset.kind = signal.kind || "inspect";
      const body = makeNode("div");
      const metricKey = "explorer.metric." + signal.metric;
      const translated = t(metricKey);
      const metric = translated === metricKey ? String(signal.metric || "").replaceAll("_", " ") : translated;
      body.append(
        makeNode("div", "signal-main", t("explorer.signal." + signal.kind)),
        makeNode("span", "signal-note", t("explorer.signal.percentile", {
          metric: metric,
          value: formatNumber(signal.raw, 1),
          percentile: formatNumber(signal.percentile),
        })),
      );
      row.append(makeNode("span", "signal-mark"), body);
      host.append(row);
    }
  }

  function renderScoreboard(overview) {
    const host = $("scoreboardBody");
    host.replaceChildren();
    for (const player of overview.players || []) {
      const row = document.createElement("tr");
      row.dataset.me = String(Boolean(player.is_me));

      const heroCell = document.createElement("td");
      const hero = makeNode("span", "hero-cell");
      hero.append(
        makeNode("span", "side-dot" + (player.is_radiant ? " radiant" : "")),
        makeNode("span", "", player.hero || "—"),
      );
      if (player.is_me) hero.append(makeNode("span", "me-mark", "★"));
      heroCell.append(hero);
      row.append(heroCell);

      const values = [
        roleLabel(player.role),
        `${player.kills || 0} / ${player.deaths || 0} / ${player.assists || 0}`,
        `${formatNumber(player.last_hits)} / ${formatNumber(player.denies)}`,
        `${formatNumber(player.gpm)} / ${formatNumber(player.xpm)}`,
        formatNumber(player.net_worth),
        formatNumber(player.hero_damage),
      ];
      for (const value of values) row.append(makeNode("td", "", value));
      host.append(row);
    }
  }

  function renderDraft(overview) {
    const host = $("draftList");
    host.replaceChildren();
    const rawDraft = overview.draft || {};
    const legacy = Array.isArray(rawDraft) ? rawDraft : null;
    const picks = legacy
      ? legacy.filter((action) => action.is_pick)
      : [...(rawDraft.picks || [])];
    const bans = legacy
      ? legacy.filter((action) => !action.is_pick)
      : [...(rawDraft.bans || [])];
    const chronological = legacy ? true : Boolean(rawDraft.chronological);

    function appendActions(actions, kind, preserveOrder) {
      const ordered = [...actions].sort((a, b) => Number(a.order) - Number(b.order));
      for (const [index, action] of ordered.entries()) {
        const row = makeNode("div", "event-row");
        const body = makeNode("div");
        const sideKey = "result.side." + action.side;
        const sideLabel = t(sideKey) === sideKey ? (action.side || "—") : t(sideKey);
        body.append(
          makeNode("div", "event-main", action.hero || "—"),
          makeNode("span", "event-note", sideLabel),
        );
        row.append(
          makeNode("span", "draft-side", t(kind === "pick" ? "explorer.draft.pick" : "explorer.draft.ban", {
            order: preserveOrder ? Number(action.order) + 1 : index + 1,
          })),
          body,
        );
        host.append(row);
      }
    }

    if (picks.length || bans.length) {
      if (chronological) {
        const actions = [
          ...picks.map((action) => ({ ...action, kind: "pick" })),
          ...bans.map((action) => ({ ...action, kind: "ban" })),
        ].sort((a, b) => Number(a.order) - Number(b.order));
        for (const action of actions) appendActions([action], action.kind, true);
      } else {
        if (picks.length) {
          const label = makeNode("div", "draft-group-label", t("explorer.draft.picks"));
          label.append(makeNode("span", "draft-group-note", " · " + t("explorer.draft.grouped_note")));
          host.append(label);
          appendActions(picks, "pick", false);
        }
        if (bans.length) {
          host.append(makeNode("div", "draft-group-label", t("explorer.draft.bans")));
          appendActions(bans, "ban", false);
        }
      }
      return;
    }

    for (const side of ["radiant", "dire"]) {
      const heroes = (overview.players || [])
        .filter((player) => Boolean(player.is_radiant) === (side === "radiant"))
        .map((player) => player.hero)
        .filter(Boolean);
      if (!heroes.length) continue;
      const row = makeNode("div", "event-row");
      const body = makeNode("div");
      body.append(
        makeNode("div", "event-main", heroes.join(" · ")),
        makeNode("span", "event-note", t("explorer.draft.final")),
      );
      row.append(makeNode("span", "draft-side", t("result.side." + side)), body);
      host.append(row);
    }
    if (!host.children.length) host.append(emptyState());
  }

  function renderBuilds(overview) {
    const host = $("buildList");
    host.replaceChildren();
    let itemCount = 0;
    for (const player of overview.players || []) {
      const items = (player.items || []).filter((item) => item.key);
      if (!items.length) continue;
      itemCount += items.length;
      const row = makeNode("div", "build-row");
      const hero = makeNode("div", "build-hero", (player.is_me ? "★ " : "") + (player.hero || "—"));
      const flow = makeNode("div", "item-flow");
      for (const item of items) {
        const chip = makeNode("span", "item-chip");
        chip.append(
          makeNode("time", "", formatClock(item.time)),
          makeNode("span", "", item.name || String(item.key).replaceAll("_", " ")),
        );
        flow.append(chip);
      }
      row.append(hero, flow);
      host.append(row);
    }
    if (!itemCount) host.append(makeNode("div", "empty-state", t("explorer.builds.empty")));
  }

  function renderObjectives(overview) {
    const host = $("objectiveList");
    host.replaceChildren();
    const objectives = (overview.objectives || [])
      .filter((objective) => !objective.minor)
      .sort((a, b) => Number(a.time) - Number(b.time));
    if (!objectives.length) { host.append(emptyState()); return; }

    for (const objective of objectives) {
      const row = makeNode("div", "event-row");
      const body = makeNode("div");
      const key = "explorer.objective." + objective.kind;
      const translated = t(key);
      const params = objective.params || {};
      const note = [];
      if (params.attacker || params.victim) note.push(`${params.attacker || "?"} → ${params.victim || "?"}`);
      if (params.team) note.push(params.team);
      if (params.short) note.push(params.short.replaceAll("_", " "));
      body.append(makeNode("div", "event-main", translated === key ? objective.kind : translated));
      if (note.length) body.append(makeNode("span", "event-note", note.join(" · ")));
      row.append(makeNode("span", "event-time", formatClock(objective.time)), body);
      host.append(row);
    }
  }

  /* Драки — главный способ выбрать момент: клик ставит отрезок вокруг драки
     с запасом в пару минут до и после, чтобы в окно попал и заход в бой. */
  function renderFights(overview) {
    const host = $("fightList");
    host.replaceChildren();
    const windowState = selectedWindow();
    const fights = [...(overview.teamfights || [])]
      .sort((a, b) => Number(a.start) - Number(b.start));
    if (!fights.length) { host.append(emptyState()); return; }
    const neutral = isNeutral(overview);
    const radiant = overview.perspective && overview.perspective.side === "radiant";
    for (const fight of fights) {
      const row = makeNode("button", "event-row event-action");
      row.type = "button";
      row.setAttribute("aria-pressed", String(fightInsideWindow(fight, windowState)));
      const body = makeNode("div");
      const range = `${formatClock(fight.start)}–${formatClock(fight.end)}`;
      row.setAttribute("aria-label", t("explorer.fight.open", { range }));
      const teamGold = radiant ? fight.radiant_gold_delta : fight.dire_gold_delta;
      body.append(
        makeNode("div", "event-main", t("explorer.fight.row", { index: fight.index, range })),
        makeNode("span", "event-note", t(neutral ? "explorer.fight.note.game" : "explorer.fight.note", {
          damage: formatNumber(fight.me && fight.me.damage),
          gold: formatSigned(teamGold),
          deaths: formatNumber(fight.deaths),
        })),
      );
      row.append(makeNode("span", "event-time", formatClock(fight.start)), body);
      row.addEventListener("click", () => {
        setWindow(Math.floor(Number(fight.start) / 60) - 2, Math.ceil(Number(fight.end) / 60) + 2);
      });
      host.append(row);
    }
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  const makeSvg = (tag, attrs, value) => {
    const element = document.createElementNS(SVG_NS, tag);
    for (const [name, attr] of Object.entries(attrs || {})) element.setAttribute(name, attr);
    if (value !== undefined) element.textContent = String(value);
    return element;
  };

  const formatAxis = (value) => {
    const absolute = Math.abs(value);
    if (absolute >= 1000) return (value / 1000).toLocaleString(localeForLang(), { maximumFractionDigits: 1 }) + "k";
    return formatNumber(Math.round(value));
  };

  /* График всегда показывает матч целиком, а выбранный отрезок — подсветкой
     поверх. Отрезок можно протянуть прямо по графику: так «выделить момент»
     и задумано, ползунок под ним — для точной подстройки. */
  const CHART = { left: 62, right: 18, top: 14, bottom: 34, width: 800 - 62 - 18, height: 250 - 14 - 34 };

  const chartValues = () => {
    const economy = (currentOverview && currentOverview.economy) || {};
    const raw = chartSeries === "xp" ? economy.team_xp_adv : economy.team_gold_adv;
    return (Array.isArray(raw) ? raw : []).map(Number).filter(Number.isFinite);
  };

  // Минута матча по точке на графике: ось X — минуты, по точке на минуту.
  const chartMinute = (event) => {
    const svg = $("overviewChart");
    const matrix = svg.getScreenCTM();
    if (!matrix) return 0;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    const span = Math.max(1, chartValues().length - 1);
    const ratio = (point.x - CHART.left) / CHART.width;
    return Math.max(0, Math.min(span, ratio * span));
  };

  function renderChartTabs() {
    const neutral = isNeutral(currentOverview);
    for (const tab of $("chartTabs").querySelectorAll("[data-series]")) {
      tab.textContent = t((neutral ? "game.chart." : "explorer.chart.") + tab.dataset.series);
    }
  }

  function renderChart() {
    if (!currentOverview) return;
    const svg = $("overviewChart");
    svg.replaceChildren();
    const values = chartValues();
    if (!values.length) {
      $("chartSummary").textContent = t("explorer.empty");
      svg.append(makeSvg("text", { x: 400, y: 125, "text-anchor": "middle", class: "chart-axis-label" }, t("explorer.empty")));
      return;
    }

    const { left, top, width, height } = CHART;
    const edge = Math.max(1, ...values.map(Math.abs));
    const min = -edge, max = edge;
    const xAt = (index) => left + width * index / Math.max(1, values.length - 1);
    const yAt = (value) => top + height * (max - value) / Math.max(1, max - min);

    for (let index = 0; index <= 4; index += 1) {
      const ratio = index / 4;
      const y = top + height * ratio;
      const value = max - (max - min) * ratio;
      svg.append(
        makeSvg("line", { x1: left, y1: y, x2: left + width, y2: y,
          class: index === 2 ? "chart-zero-line" : "chart-grid-line" }),
        makeSvg("text", { x: left - 10, y: y + 4, "text-anchor": "end", class: "chart-axis-label" }, formatAxis(value)),
      );
    }

    const windowState = selectedWindow();
    const last = values.length - 1;
    const from = Math.min(windowState.start, last), to = Math.min(windowState.end, last);
    svg.append(makeSvg("rect", {
      x: xAt(from), y: top, width: Math.max(2, xAt(to) - xAt(from)), height,
      class: "chart-window",
    }));

    const step = last > 60 ? 20 : last > 30 ? 10 : 5;
    for (let minute = 0; minute <= last; minute += step) {
      svg.append(makeSvg("text", { x: xAt(minute), y: 242, "text-anchor": "middle", class: "chart-axis-label" }, `${minute}m`));
    }

    const points = values.map((value, index) => [xAt(index), yAt(value)]);
    const line = points.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
    const baseline = yAt(0);
    const area = `${line} L${points.at(-1)[0].toFixed(2)},${baseline.toFixed(2)} L${points[0][0].toFixed(2)},${baseline.toFixed(2)} Z`;
    svg.append(
      makeSvg("path", { d: area, class: "chart-area" }),
      makeSvg("path", { d: line, class: "chart-path" }),
      makeSvg("circle", { cx: points.at(-1)[0], cy: points.at(-1)[1], r: 4, class: "chart-dot" }),
    );
    drawChartMarkers(svg, xAt, last);
    const inside = values.slice(from, to + 1);
    $("chartSummary").textContent = t("session.chart.summary", {
      start: windowState.start,
      end: windowState.end,
      from: formatSigned(inside[0]),
      to: formatSigned(inside.at(-1)),
    });
  }

  /* Метки моментов: драки — полосой у нижнего края, смерти моего героя и
     Рошан — точками у верхнего. Это ответ на «а какой момент выделять»: глаз
     сразу видит, где игра сгущалась. Подробности — во всплывающей подписи. */
  function drawChartMarkers(svg, xAt, last) {
    const { top, height } = CHART;
    const at = (seconds) => xAt(Math.max(0, Math.min(last, Number(seconds) / 60)));
    const titled = (node, text) => { node.append(makeSvg("title", {}, text)); return node; };

    for (const fight of currentOverview.teamfights || []) {
      const x1 = at(fight.start), x2 = at(fight.end);
      const range = `${formatClock(fight.start)}–${formatClock(fight.end)}`;
      svg.append(titled(makeSvg("rect", {
        x: x1, y: top + height - 7, width: Math.max(3, x2 - x1), height: 5, rx: 1.5,
        class: "chart-fight",
      }), t("explorer.fight.row", { index: fight.index, range })));
    }
    for (const objective of currentOverview.objectives || []) {
      if (objective.kind !== "roshan") continue;
      svg.append(titled(makeSvg("circle", {
        cx: at(objective.time), cy: top + 7, r: 4.5, class: "chart-roshan",
      }), t("chart.marker.roshan", { time: formatClock(objective.time) })));
    }
    const me = (currentOverview.players || []).find((player) => player.is_me);
    for (const seconds of (me && me.death_times) || []) {
      const x = at(seconds), y = top + 18;
      svg.append(titled(makeSvg("path", {
        d: `M${x - 4},${y - 4} L${x + 4},${y + 4} M${x + 4},${y - 4} L${x - 4},${y + 4}`,
        class: "chart-death",
      }), t("chart.marker.death", { time: formatClock(seconds) })));
    }
    $("legendDeath").hidden = !(me && (me.death_times || []).length);
  }

  // Протягивание по графику: нажали — начало отрезка, отпустили — конец.
  let chartDrag = null;
  $("overviewChart").addEventListener("pointerdown", (event) => {
    if (!currentOverview || event.button !== 0) return;
    event.preventDefault();
    chartDrag = chartMinute(event);
    $("overviewChart").setPointerCapture(event.pointerId);
  });
  $("overviewChart").addEventListener("pointermove", (event) => {
    if (chartDrag === null) return;
    const here = chartMinute(event);
    // Пока тянут меньше минуты, это ещё клик, а не выделение.
    if (Math.abs(here - chartDrag) < 1) return;
    setWindow(Math.floor(Math.min(here, chartDrag)), Math.ceil(Math.max(here, chartDrag)));
  });
  const endChartDrag = (event) => {
    if (chartDrag === null) return;
    const here = chartMinute(event);
    // Простой клик ставит отрезок ±2 минуты вокруг точки.
    if (Math.abs(here - chartDrag) < 1) setWindow(Math.round(here) - 2, Math.round(here) + 2);
    chartDrag = null;
  };
  $("overviewChart").addEventListener("pointerup", endChartDrag);
  $("overviewChart").addEventListener("pointercancel", () => { chartDrag = null; });

  function renderOverview(overview) {
    currentOverview = overview;
    const match = overview.match || {};
    const perspective = overview.perspective || {};
    const neutral = isNeutral(overview);
    const me = (overview.players || []).find((player) => player.is_me) || {};
    const winner = match.radiant_win ? "radiant" : "dire";
    $("workspaceTitle").textContent = neutral
      ? t("game.title", { match_id: match.match_id || "—" })
      : t("explorer.title", { hero: perspective.hero || me.hero || "—",
                              match_id: match.match_id || "—" });
    $("workspaceMeta").textContent = neutral
      ? t("game.meta", {
          winner: t("result.side." + winner),
          score: `${match.radiant_kills || 0}–${match.dire_kills || 0}`,
          duration: formatDuration(match.duration),
          patch: match.patch || "—",
        })
      : t("explorer.meta", {
          side: t("result.side." + (perspective.side || "radiant")),
          result: t(perspective.win ? "result.win" : "result.lose"),
          duration: formatDuration(match.duration),
          patch: match.patch || "—",
        });
    $("overviewCards").hidden = neutral;
    if (!neutral) renderOverviewCards(overview, me);
    renderSignals(overview);
    renderScoreboard(overview);
    renderDraft(overview);
    renderBuilds(overview);
    renderObjectives(overview);
    renderChartTabs();
    refreshExplorerWindow();
  }

  function refreshExplorerWindow() {
    if (!currentOverview) return;
    renderFights(currentOverview);
    renderChart();
  }

  /* Отрезок по умолчанию — первая драка: с неё чаще всего и начинают. Если
     драк нет, берём первые десять минут. */
  function initWindow(overview) {
    const minutes = Math.max(2, Math.ceil(Number((overview.match || {}).duration || 0) / 60));
    setRangeMax(minutes);
    const fights = [...(overview.teamfights || [])].sort((a, b) => Number(a.start) - Number(b.start));
    if (fights.length) {
      setWindow(Math.floor(Number(fights[0].start) / 60) - 2, Math.ceil(Number(fights[0].end) / 60) + 2);
    } else {
      setWindow(0, Math.min(10, minutes));
    }
  }

  $("chartTabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-series]");
    if (!button || button.dataset.series === chartSeries) return;
    chartSeries = button.dataset.series;
    for (const tab of $("chartTabs").querySelectorAll("[data-series]")) {
      tab.setAttribute("aria-pressed", String(tab === button));
    }
    renderChart();
  });

  function showResult(data) {
    currentFilename = data.filename || "prompt.txt";
    resetFeedback(data);
    promptEl.textContent = data.prompt;
    $("chipTokens").textContent = t("result.tokens", { n: estimateTokens(data.prompt) });

    const m = CFG.models.find((x) => x.code === data.model);
    $("chipModel").textContent = m ? m.label : data.model;
    currentModel = data.model;
    renderOpenChat();

    const isProfile = mode === "profile";
    const isGame = mode === "game";
    followups = [];
    renderFollowups();
    hide($("followupError"));
    // Адрес запоминает матч и режим: ссылкой можно поделиться, а после
    // перезагрузки ID матча уже стоит в поле.
    if (!isProfile && session) {
      const query = new URLSearchParams({ match: session.body.match_id });
      if (isGame) query.set("mode", "game");
      history.replaceState(null, "", "?" + query);
    }
    $("followupNote").value = "";
    $("resultHead").hidden = isProfile || !data.overview;
    // Сессия открывается сразу, а подробности — свёрнутыми: к ним приходят
    // за конкретной цифрой, а не читают подряд.
    $("matchDetails").open = false;
    if (!isProfile && data.overview) {
      // Сначала показываем секцию: шкала ползунка меряет ширину дорожки, а у
      // скрытого блока она нулевая.
      workspaceEl.hidden = false;
      renderOverview(data.overview);
      initWindow(data.overview);
    } else {
      currentOverview = null;
      workspaceEl.hidden = true;
    }
    // Сторона игрока — только у разбора игрока: у профиля сторон много, а у
    // игры целиком победитель уже назван в заголовке.
    const badge = $("sideBadge");
    badge.hidden = isProfile || isGame || !data.side;
    if (!badge.hidden) {
      resultEl.dataset.side = data.side;
      $("sideText").textContent = t("result.side." + data.side) + " · "
        + t(data.win ? "result.win" : "result.lose");
    } else {
      delete resultEl.dataset.side;
    }

    // Фокус показываем, только если он не общий: «focus: full» ничего не сообщает.
    $("chipFocus").hidden = isProfile || !data.focus || data.focus === "full";
    $("chipFocus").textContent = data.focus ? t("focus." + data.focus) : "";
    $("chipMatches").hidden = !isProfile;
    $("chipUnparsed").hidden = !(isProfile && data.unparsed);
    $("chipWinrate").hidden = !isProfile;

    if (isProfile) {
      $("chipMatches").textContent = t("result.matches", {
        analyzed: data.analyzed, requested: data.requested,
      });
      $("chipWinrate").textContent = t("result.winrate", { pct: data.winrate });
      if (data.unparsed) {
        $("chipUnparsed").textContent = t("result.unparsed", { n: data.unparsed });
      }
    }

    // Роль показываем, только если её выбрали: «роль: Auto» ничего не сообщает.
    const selectedRole = isGame ? null
      : data.role || (isProfile ? roleFilter.value : roleSel.value);
    $("chipRole").hidden = !selectedRole;
    $("chipRole").textContent = selectedRole
      ? t("result.role", { role: t("role." + selectedRole) }) : "";
    $("chipNote").hidden = !data.has_note;

    resultEl.hidden = false;
    if (data.warning) {
      const body = t("warn." + data.warning);
      showPanel(warnEl, t("err.warn_title"),
                body.startsWith("warn.") ? t("warn.unparsed") : body);
    }
    resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function showError(status, data, target = errorEl) {
    const detail = data && data.detail;
    const kind = detail && typeof detail === "object" ? detail.kind : null;
    const title = t("err." + status) !== "err." + status ? t("err." + status) : t("err.generic");

    let body = kind ? t("err.body." + kind) : null;
    if (!body || body.startsWith("err.body.")) {
      // Неизвестный вид сбоя (например, ошибка валидации pydantic) — показываем
      // то, что пришло с сервера, лишь бы пользователь не остался без объяснения.
      body = typeof detail === "string" ? detail
           : Array.isArray(detail) && detail[0] ? detail[0].msg
           : (detail && detail.message) || String(status);
    }
    // В сообщении про «кто из игроков» server присылает состав матча — он полезен.
    if (kind === "player_not_found" && detail.message.includes("\n")) {
      body += "\n" + t("err.roster") + detail.message.split("\n").slice(1).join("\n")
                                             .replace(/^[^:]*:/, "");
    }
    showPanel(target, title, body);
  }

  /* ============================================================
     Промпт по отрезку: короткое продолжение для того же чата
     ============================================================ */
  /* Уходит то же тело запроса, что и у основного промпта (с уже скачанным
     матчем), плюс окно и флаг followup. Сервер отвечает коротким текстом:
     без роли тренера, драфта и методики — модель их уже прочитала. */
  let followupBusy = false;

  const setFollowupBusy = (busy) => {
    followupBusy = busy;
    const btn = $("followupBtn");
    btn.disabled = busy || !session;
    btn.innerHTML = busy
      ? '<span class="wave" aria-hidden="true"><i></i><i></i><i></i></span>' + t("session.busy")
      : t("session.submit");
  };

  $("followupBtn").addEventListener("click", async () => {
    if (!session || followupBusy) return;
    const windowState = selectedWindow();
    hide($("followupError"));
    setFollowupBusy(true);
    try {
      const res = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...session.body,
          followup: true,
          lang: lang,
          // Вопрос основного разбора модель уже видела; здесь — свой, про отрезок.
          note: $("followupNote").value.trim() || null,
          window_start: windowState.start,
          window_end: windowState.end,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { showError(res.status, data, $("followupError")); return; }
      for (const item of followups) item.open = false;
      followups.unshift({ window: windowState, prompt: data.prompt,
                          note: $("followupNote").value.trim(), open: true });
      renderFollowups();
      $("followupList").firstElementChild
        .scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch {
      showPanel($("followupError"), t("err.offline"), t("err.offline.body"));
    } finally {
      setFollowupBusy(false);
    }
  });

  $("followupNote").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); $("followupBtn").click(); }
  });

  /* ============================================================
     Фидбэк: оценка отправляется сразу по клику, комментарий — опционально
     ============================================================ */
  const fbNote = $("fbNote"), fbForm = $("fbForm");

  function resetFeedback(data) {
    fbRating = 0;
    fbContext = {
      mode: mode,
      lang: lang,
      model: data.model || $("model").value,
      match_id: mode !== "profile" ? parseMatchId($("matchId").value) : null,
      role: mode === "match" ? (data.role || roleSel.value || null)
                             : mode === "profile" ? (roleFilter.value || null) : null,
      depth: mode !== "profile" ? (data.depth || null) : null,
      focus: mode !== "profile" ? (data.focus || null) : null,
      window: data.window || null,
      matches: mode === "profile" ? (data.analyzed || null) : null,
      prompt_bytes: data.size_bytes || null,
    };
    for (const btn of [$("fbUp"), $("fbDown")]) {
      btn.setAttribute("aria-pressed", "false");
      btn.disabled = false;
    }
    fbForm.hidden = true;
    fbNote.hidden = true;
    $("fbComment").value = "";
  }

  const postFeedback = async (payload) => {
    const res = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(String(res.status));
  };

  const showFbNote = (key, state) => {
    fbNote.textContent = t(key);
    fbNote.dataset.state = state || "ok";
    fbNote.hidden = false;
  };

  for (const btn of [$("fbUp"), $("fbDown")]) {
    btn.addEventListener("click", async () => {
      const rating = Number(btn.dataset.rating);
      if (!fbContext || fbRating === rating) return;
      fbRating = rating;
      // Оценку отправляем НЕМЕДЛЕННО: это главный сигнал, а комментарий пишут
      // единицы. Ждать «Отправить» значило бы терять голос при уходе со страницы.
      $("fbUp").setAttribute("aria-pressed", String(rating === 1));
      $("fbDown").setAttribute("aria-pressed", String(rating === -1));
      try {
        await postFeedback({ ...fbContext, rating: rating, followup: false });
        showFbNote("feedback.thanks");
        fbForm.hidden = false;
      } catch {
        showFbNote("feedback.error", "error");
      }
    });
  }

  $("fbSend").addEventListener("click", async (e) => {
    const comment = $("fbComment").value.trim();
    if (!comment || !fbContext) return;
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = t("feedback.sending");
    try {
      // followup=true: это дополнение к уже учтённой оценке. Без флага при
      // подсчёте голосов один человек считался бы дважды.
      await postFeedback({ ...fbContext, rating: fbRating || 1,
                           comment: comment, followup: true });
      fbForm.hidden = true;
      showFbNote("feedback.thanks_more");
    } catch {
      showFbNote("feedback.error", "error");
    } finally {
      btn.disabled = false;
      btn.textContent = t("feedback.send");
    }
  });

  /* ============================================================
     Копирование и скачивание
     ============================================================ */
  /* Короткое подтверждение: галочка + «кивок» кнопки. Действие невидимое
     (буфер, скачивание), и без отклика непонятно, случилось ли оно вообще. */
  const confirmAction = (btn, key, restore) => {
    btn.textContent = t(key) + " \u2713";
    btn.classList.add("done");
    setTimeout(() => {
      btn.classList.remove("done");
      btn.textContent = t(restore);
    }, 1800);
  };

  /* true — текст в буфере; false — буфер недоступен, и текст выделен, чтобы
     его можно было скопировать руками. */
  const copyPre = async (pre) => {
    try {
      await navigator.clipboard.writeText(pre.textContent);
      return true;
    } catch {
      const r = document.createRange();
      r.selectNodeContents(pre);
      const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
      return false;
    }
  };

  const copyFrom = (pre) => async (e) => {
    const btn = e.currentTarget;
    confirmAction(btn, (await copyPre(pre)) ? "result.copied" : "result.selected", "result.copy");
  };
  $("copyBtn").addEventListener("click", copyFrom(promptEl));

  /* «Копировать и открыть чат»: промпт в буфер, чат выбранной модели — в новой
     вкладке. Вкладку открываем после копирования: новая вкладка забирает фокус,
     а без фокуса страница писать в буфер не может. */
  const CHAT_URLS = {
    chatgpt: "https://chatgpt.com/",
    claude: "https://claude.ai/new",
    gemini: "https://gemini.google.com/app",
  };

  function renderOpenChat() {
    const btn = $("openChatBtn");
    const model = CFG.models.find((x) => x.code === currentModel);
    btn.hidden = !CHAT_URLS[currentModel];
    btn.textContent = t("result.open_chat", { model: model ? model.label : "" });
  }

  $("openChatBtn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const copied = await copyPre(promptEl);
    if (!copied) { confirmAction(btn, "result.selected", "result.copy"); return; }
    window.open(CHAT_URLS[currentModel], "_blank", "noopener");
    btn.textContent = t("result.copied") + " \u2713";
    btn.classList.add("done");
    setTimeout(() => { btn.classList.remove("done"); renderOpenChat(); }, 1800);
  });

  /* История промптов по отрезкам. Перерисовывается целиком: элементов единицы,
     а так язык интерфейса меняется без отдельного обхода подписей. */
  function renderFollowups() {
    const host = $("followupList");
    host.replaceChildren();
    for (const item of followups) {
      const card = makeNode("div", "followup-item");
      card.dataset.open = String(item.open);
      const bar = makeNode("div", "result-bar");
      const meta = makeNode("div", "meta");
      meta.append(
        makeNode("span", "chip chip-accent", t("window.range", item.window)),
        makeNode("span", "chip", t("result.tokens", { n: estimateTokens(item.prompt) })),
      );
      if (item.note) meta.append(makeNode("span", "followup-question", item.note));
      const actions = makeNode("div", "actions");
      const toggle = makeNode("button", "btn btn-ghost ripple",
                              t(item.open ? "session.hide" : "session.show"));
      toggle.type = "button";
      toggle.setAttribute("aria-expanded", String(item.open));
      toggle.addEventListener("click", () => { item.open = !item.open; renderFollowups(); });
      const copy = makeNode("button", "btn btn-ghost ripple", t("result.copy"));
      copy.type = "button";
      const pre = makeNode("pre", "prompt-text", item.prompt);
      pre.hidden = !item.open;
      copy.addEventListener("click", copyFrom(pre));
      actions.append(toggle, copy);
      bar.append(meta, actions);
      card.append(bar, pre);
      host.append(card);
    }
  }

  $("downloadBtn").addEventListener("click", (e) => {
    const blob = new Blob([promptEl.textContent], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = currentFilename; a.click();
    URL.revokeObjectURL(url);
    confirmAction(e.currentTarget, "result.download", "result.download");
  });

  form.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") form.requestSubmit();
  });

  /* ============================================================
     Старт
     ============================================================ */
  const langSel = $("langSelect");
  for (const l of CFG.languages) langSel.append(new Option(l.name, l.code));
  const modelSel = $("model");
  for (const m of CFG.models) modelSel.append(new Option(m.label, m.code));

  const prefs = readPrefs();
  const browserLang = (navigator.language || "").slice(0, 2);
  lang = prefs.lang || (CFG.strings[browserLang] ? browserLang : CFG.defaultLang);
  theme = prefs.theme === "light" ? "light" : "dark";
  mode = MODES.includes(prefs.mode) ? prefs.mode : "match";
  // Ссылка вида ?match=…&mode=game открывает страницу с этим матчем в поле.
  // Разбор сам не запускается: он тратит лимит OpenDota, и решать это игроку.
  const linked = new URLSearchParams(location.search);
  if (linked.get("mode") === "game") mode = "game";
  else if (linked.get("match") && mode === "profile") mode = "match";
  if (parseMatchId(linked.get("match") || "")) {
    $("matchId").value = parseMatchId(linked.get("match"));
  }
  setAdvanced(prefs.advOpen === true);
  if (prefs.accountId) $("accountId").value = prefs.accountId;
  if (prefs.matches) $("matches").value = prefs.matches;
  if (prefs.mmr) $("mmr").value = prefs.mmr;
  if (prefs.model && CFG.models.some((m) => m.code === prefs.model)) modelSel.value = prefs.model;

  langSel.value = lang;
  langSel.addEventListener("change", () => { lang = langSel.value; applyLang(); savePrefs(); });

  applyTheme();
  if (prefs.role && CFG.roles.includes(prefs.role)) roleSel.value = prefs.role;
  // syncRoleIcons вызовется внутри applyLang -> renderRoleIcons ниже.
  if (prefs.roleFilter && CFG.roles.includes(prefs.roleFilter)) roleFilter.value = prefs.roleFilter;
  applyLang();
  if (prefs.focus && [...$("focus").options].some((o) => o.value === prefs.focus)) {
    $("focus").value = prefs.focus;
  }
  ($("matchId").offsetParent ? $("matchId") : $("accountId")).focus({ preventScroll: true });
})();
