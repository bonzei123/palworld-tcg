(function () {
    const chatRoot = document.getElementById("chat-root");
    const chatPanel = document.getElementById("chat-panel");
    const chatToggle = document.getElementById("chat-toggle");
    const tabChat = document.getElementById("tab-chat");

    function setChatOpen(open) {
        document.documentElement.classList.toggle("chat-open", open);
        if (chatRoot) chatRoot.dataset.open = open ? "true" : "false";
        if (tabChat) tabChat.classList.toggle("is-active", open);
    }

    function isChatOpen() {
        return chatPanel && !chatPanel.hidden;
    }

    if (tabChat && chatToggle) {
        tabChat.addEventListener("click", () => chatToggle.click());
    }

    if (chatToggle) {
        const orig = chatToggle.onclick;
        chatToggle.addEventListener("click", () => {
            requestAnimationFrame(() => setChatOpen(isChatOpen()));
        });
        void orig;
    }

    const closeBtn = document.getElementById("chat-close");
    if (closeBtn) {
        closeBtn.addEventListener("click", () => setChatOpen(false));
    }

    const filterToggle = document.getElementById("filter-toggle");
    const filters = document.getElementById("filters");
    const filterCount = document.getElementById("filter-count");
    if (filterToggle && filters) {
        filterToggle.addEventListener("click", () => {
            const open = filters.classList.toggle("is-open");
            filterToggle.setAttribute("aria-expanded", String(open));
        });
        const updateCount = () => {
            if (!filterCount) return;
            const n = [...filters.querySelectorAll("select")].filter((s) => s.value).length;
            filterCount.textContent = n ? `(${n})` : "";
        };
        filters.addEventListener("change", updateCount);
        updateCount();
    }

    const vv = window.visualViewport;
    if (vv) {
        const syncKb = () => {
            const kb = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
            document.documentElement.style.setProperty("--kb", kb + "px");
        };
        vv.addEventListener("resize", syncKb);
        vv.addEventListener("scroll", syncKb);
        syncKb();
    }

    const hover = document.getElementById("card-hover");
    const hoverImg = hover?.querySelector("img");
    const loupe = document.getElementById("card-loupe");
    const modal = document.getElementById("card-view-modal");
    const modalTitle = document.getElementById("card-view-title");
    const modalBody = document.getElementById("card-view-body");
    const modalBack = document.getElementById("card-view-back");
    const imgCache = new Map();
    const cardStack = [];

    function esc(s) {
        return String(s ?? "").replace(/[&<>"']/g, (ch) => (
            { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
        ));
    }

    function colorClass(color) {
        const n = String(color || "").trim().toLowerCase();
        if (!n || n === "colorless" || n === "farblos") return "colorless";
        return n.replace(/[^a-z0-9]+/g, "");
    }

    function hoverNode(el) {
        if (el.closest?.(".kw, .kw-tip, .detail-art, .card-loupe, .qty-panel")) return null;
        return el.closest("[data-hover], [data-card-id], a[href^='/card/'], .card-tile, [data-add], img[src*='/images/']");
    }

    function cardIdFrom(el) {
        if (!el) return "";
        if (el.dataset?.cardId) return el.dataset.cardId;
        if (el.dataset?.add) return el.dataset.add;
        const href = el.getAttribute?.("href") || "";
        const m = href.match(/\/card\/(\d+)/);
        if (m) return m[1];
        const nested = el.querySelector?.("a[href^='/card/']");
        const nm = nested?.getAttribute("href")?.match(/\/card\/(\d+)/);
        return nm ? nm[1] : "";
    }

    function imageFrom(el) {
        if (!el) return "";
        if (el.dataset?.hover) return el.dataset.hover;
        if (el.matches?.("img[src*='/images/']")) return el.currentSrc || el.src;
        const pic = el.querySelector?.("img[src*='/images/']");
        if (pic) return pic.currentSrc || pic.src;
        return "";
    }

    async function resolveImage(el) {
        const direct = imageFrom(el);
        if (direct) return direct;
        const id = cardIdFrom(el);
        if (!id) return "";
        if (imgCache.has(id)) return imgCache.get(id);
        const res = await fetch("/api/cards/" + id);
        if (!res.ok) return "";
        const card = await res.json();
        const url = card.image_url || "";
        imgCache.set(id, url);
        return url;
    }

    function hideHover() {
        if (hover) hover.hidden = true;
    }

    function hideLoupe() {
        if (loupe) loupe.hidden = true;
    }

    function distTouches(a, b) {
        const dx = a.clientX - b.clientX;
        const dy = a.clientY - b.clientY;
        return Math.hypot(dx, dy);
    }

    function enablePinch(wrap) {
        if (!wrap || wrap.dataset.pinchBound) return;
        const img = wrap.querySelector("img");
        if (!img) return;
        wrap.dataset.pinchBound = "1";
        let scale = 1;
        let lastDist = 0;
        wrap.addEventListener("touchstart", (e) => {
            if (e.touches.length === 2) {
                lastDist = distTouches(e.touches[0], e.touches[1]);
            }
        }, { passive: true });
        wrap.addEventListener("touchmove", (e) => {
            if (e.touches.length !== 2) return;
            e.preventDefault();
            hideLoupe();
            const d = distTouches(e.touches[0], e.touches[1]);
            if (lastDist) {
                scale = Math.min(4, Math.max(1, scale * (d / lastDist)));
                img.style.transform = `scale(${scale})`;
            }
            lastDist = d;
        }, { passive: false });
        wrap.addEventListener("touchend", (e) => {
            if (e.touches.length < 2) lastDist = 0;
            if (e.touches.length === 0 && scale <= 1.05) {
                scale = 1;
                img.style.transform = "";
            }
        });
    }

    function bindArtZoom(root) {
        (root || document).querySelectorAll?.(".detail-art")?.forEach(enablePinch);
    }

    function artImg(el) {
        if (!el || typeof el.closest !== "function") return null;
        const wrap = el.closest(".detail-art");
        if (!wrap) return null;
        return wrap.querySelector("img");
    }

    function showLoupe(e, img) {
        if (!loupe || !img) return;
        const rect = img.getBoundingClientRect();
        if (rect.width < 48 || rect.height < 48) return;
        const zoom = 2.6;
        const size = Math.min(176, Math.round(Math.min(window.innerWidth, window.innerHeight) * 0.38));
        const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
        const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
        const bw = rect.width * zoom;
        const bh = rect.height * zoom;
        loupe.hidden = false;
        loupe.style.width = size + "px";
        loupe.style.height = size + "px";
        loupe.style.backgroundImage = `url("${img.currentSrc || img.src}")`;
        loupe.style.backgroundRepeat = "no-repeat";
        loupe.style.backgroundSize = `${bw}px ${bh}px`;
        loupe.style.backgroundPosition = `${size / 2 - x * bw}px ${size / 2 - y * bh}px`;
        let left = e.clientX + 16;
        let top = e.clientY - size / 2;
        if (left + size > window.innerWidth - 8) left = e.clientX - size - 16;
        if (top < 8) top = 8;
        if (top + size > window.innerHeight - 8) top = window.innerHeight - size - 8;
        loupe.style.left = left + "px";
        loupe.style.top = top + "px";
    }

    function placeHover(e) {
        if (!hover || hover.hidden) return;
        const w = hover.offsetWidth || 220;
        const h = hover.offsetHeight || 308;
        let x = e.clientX + 18;
        let y = e.clientY + 18;
        if (x + w > window.innerWidth - 8) x = e.clientX - w - 12;
        if (y + h > window.innerHeight - 8) y = Math.max(8, window.innerHeight - h - 8);
        hover.style.left = x + "px";
        hover.style.top = y + "px";
    }

    let hoverLock = null;
    document.addEventListener("pointerover", async (e) => {
        if (e.pointerType === "touch") return;
        if (artImg(e.target)) {
            hideHover();
            return;
        }
        hideLoupe();
        if (modal && !modal.hidden) return;
        if (e.target.closest("input, textarea, select, button:not([data-add])")) return;
        const el = hoverNode(e.target);
        if (!el || el.closest("#card-view-modal, .card-hover, .card-loupe")) return;
        hoverLock = el;
        const url = await resolveImage(el);
        if (hoverLock !== el || !url || !hover || !hoverImg) return;
        hoverImg.src = url;
        hover.hidden = false;
        placeHover(e);
    });
    document.addEventListener("pointerout", (e) => {
        if (artImg(e.target) && !artImg(e.relatedTarget)) hideLoupe();
        const el = hoverNode(e.target);
        if (!el) return;
        if (el.contains(e.relatedTarget)) return;
        if (hoverLock === el) hoverLock = null;
        hideHover();
    });
    document.addEventListener("pointermove", (e) => {
        if (e.pointerType === "touch") return;
        const img = artImg(e.target);
        if (img) {
            hideHover();
            showLoupe(e, img);
            return;
        }
        hideLoupe();
        placeHover(e);
    });

    function setModalLandscape(on) {
        const yes = !!on;
        modal?.querySelector(".card-view")?.classList.toggle("landscape", yes);
        modal?.querySelector(".card-view-layout")?.classList.toggle("landscape", yes);
        modal?.querySelector("figure.detail-art")?.classList.toggle("landscape", yes);
    }

    function closeCardView() {
        if (!modal) return;
        cardStack.length = 0;
        if (modalBack) modalBack.hidden = true;
        modal.hidden = true;
        document.body.classList.remove("modal-open");
        setModalLandscape(false);
        hideLoupe();
    }

    function syncBackBtn() {
        if (modalBack) modalBack.hidden = cardStack.length < 2;
    }

    const AUTH = document.body?.dataset.auth === "1";
    const CONDITIONS = ["NM", "LP", "MP", "HP", "Played"];

    function haveText(n, f) {
        n = Number(n) || 0;
        f = Number(f) || 0;
        if (n + f <= 0) return "Noch nicht in der Sammlung.";
        return `Im Besitz: ${n + f} (${n} normal, ${f} Foil)`;
    }

    function qtyMarkup(card) {
        if (!AUTH) {
            return `<p class="muted"><a href="/konto?next=/card/${card.id}">Anmelden</a>, um Besitz zu speichern und Karten hinzuzufügen.</p>`;
        }
        const n = Number(card.owned_normal || 0);
        const f = Number(card.owned_foil || 0);
        const w = Number(card.wanted || 0);
        const cond = card.condition || "NM";
        const opts = CONDITIONS.map((c) => `<option${c === cond ? " selected" : ""}>${c}</option>`).join("");
        return `
            <section class="qty-panel" data-collection="${card.id}">
                <div class="qty-head">
                    <h2>Sammlung</h2>
                    <p class="have-line" data-have-line>${esc(haveText(n, f))}</p>
                </div>
                <div class="qty-row">
                    <label>Habe ich <input type="number" min="0" max="99" value="${n}" data-owned></label>
                    <button type="button" class="ghost" data-add-copy="0">+1</button>
                    <label>Foil <input type="number" min="0" max="99" value="${f}" data-owned-foil></label>
                    <button type="button" class="ghost" data-add-copy="1">+1 Foil</button>
                    <label>Brauche ich <input type="number" min="0" max="99" value="${w}" data-wanted></label>
                    <label>Zustand <select data-condition>${opts}</select></label>
                    <label>Lagerort <input type="text" value="${esc(card.location || "")}" data-location placeholder="Binder A"></label>
                    <label class="check"><input type="checkbox" data-trade ${card.for_trade ? "checked" : ""}> Tausch</label>
                    <button type="button" data-save-qty>Speichern</button>
                </div>
                <p class="muted" data-qty-status></p>
            </section>`;
    }

    async function putCollection(cardId, payload) {
        const res = await fetch("/api/collection/" + cardId, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        return res.json();
    }

    function payloadFromPanel(panel, foil, ownedOverride) {
        const foilN = foil ? 1 : 0;
        let owned = ownedOverride;
        if (owned == null) {
            owned = foilN
                ? Number(panel.querySelector("[data-owned-foil]")?.value || 0)
                : Number(panel.querySelector("[data-owned]")?.value || 0);
        }
        return {
            owned,
            wanted: foilN ? 0 : Number(panel.querySelector("[data-wanted]")?.value || 0),
            condition: panel.querySelector("[data-condition]")?.value,
            location: panel.querySelector("[data-location]")?.value,
            for_trade: panel.querySelector("[data-trade]")?.checked || false,
            foil: foilN,
        };
    }

    function applyHave(panel, rec) {
        const n = rec.owned_normal ?? Number(panel.querySelector("[data-owned]")?.value || 0);
        const f = rec.owned_foil ?? Number(panel.querySelector("[data-owned-foil]")?.value || 0);
        const ownedInput = panel.querySelector("[data-owned]");
        const foilInput = panel.querySelector("[data-owned-foil]");
        if (ownedInput && rec.owned_normal != null) ownedInput.value = rec.owned_normal;
        if (foilInput && rec.owned_foil != null) foilInput.value = rec.owned_foil;
        const line = panel.querySelector("[data-have-line]");
        if (line) line.textContent = haveText(n, f);
        const id = panel.getAttribute("data-collection");
        document.querySelectorAll("[data-have-chip]").forEach((chip) => {
            if (chip.getAttribute("data-card-id") && chip.getAttribute("data-card-id") !== id) return;
            chip.textContent = n + f > 0
                ? `${n + f}× in der Sammlung${f ? " · " + f + " Foil" : ""}`
                : "Nicht in der Sammlung";
        });
    }

    async function savePanel(panel) {
        const id = panel.getAttribute("data-collection");
        const status = panel.querySelector("[data-qty-status]");
        const foilBox = panel.querySelector("[data-foil]");
        const foilInput = panel.querySelector("[data-owned-foil]");
        let foilQty = Number(foilInput?.value || 0);
        if (foilBox && foilBox.checked && foilQty < 1) foilQty = 1;
        if (foilBox && !foilBox.checked) foilQty = 0;
        if (foilInput) foilInput.value = foilQty;
        await putCollection(id, payloadFromPanel(panel, false));
        const rec = await putCollection(id, payloadFromPanel(panel, true, foilQty));
        if (status) status.textContent = rec.ok ? "Gespeichert." : (rec.detail || "Fehler.");
        if (rec && rec.ok) applyHave(panel, rec);
        return rec;
    }

    document.addEventListener("click", async (e) => {
        const add = e.target.closest("[data-add-copy]");
        if (add) {
            const panel = add.closest("[data-collection]");
            if (!panel) return;
            const foil = add.getAttribute("data-add-copy") === "1";
            const input = panel.querySelector(foil ? "[data-owned-foil]" : "[data-owned]");
            const next = Math.min(99, Number(input?.value || 0) + 1);
            if (input) input.value = next;
            const foilBox = panel.querySelector("[data-foil]");
            if (foil && foilBox) foilBox.checked = next > 0;
            const rec = await putCollection(panel.getAttribute("data-collection"), payloadFromPanel(panel, foil, next));
            const status = panel.querySelector("[data-qty-status]");
            if (status) status.textContent = rec.ok ? (foil ? "Foil hinzugefügt." : "Karte hinzugefügt.") : (rec.detail || "Fehler.");
            if (rec && rec.ok) applyHave(panel, rec);
            return;
        }
        const save = e.target.closest("[data-save-qty]");
        if (!save) return;
        const panel = save.closest("[data-collection]");
        if (panel) savePanel(panel);
    });

    function priceBlock(card) {
        const parts = [];
        if (card.price_cents != null) parts.push(`Aktuell ${(Number(card.price_cents) / 100).toFixed(2)} €`);
        if (card.price_7d_cents != null) parts.push(`7 Tage ${(Number(card.price_7d_cents) / 100).toFixed(2)} €`);
        if (card.price_30d_cents != null) parts.push(`30 Tage ${(Number(card.price_30d_cents) / 100).toFixed(2)} €`);
        const swing = card.price_7d_swing ?? card.price_daily_swing;
        if (swing != null && swing !== "") {
            const n = Number(swing);
            if (!Number.isNaN(n)) parts.push(`Swing ${n.toFixed(1)}%`);
        }
        if (card.active_listing_count) parts.push(`${Number(card.active_listing_count)} Angebote`);
        if (!parts.length) return "";
        return `<p class="price-line">${parts.join(" · ")}</p>`;
    }

    function openCardView(card) {
        if (!modal || !modalBody) return;
        hideHover();
        hideLoupe();
        const landscapeGuess = !!card.landscape;
        const img = card.image_url
            ? `<img src="${esc(card.image_url)}" alt="${esc(card.name)}">`
            : `<div class="missing">Kein Bild</div>`;
        const pills = [
            card.card_type, card.subtype, card.color, ...(card.attributes || []),
        ].filter(Boolean).map((p) => {
            const cls = p === card.color ? ` class="color-${colorClass(p)}"` : "";
            return `<li${cls}>${esc(p)}</li>`;
        }).join("");
        const apts = (card.aptitudes || []).map((a) => `<li class="apt">≪${esc(a)}≫</li>`).join("");
        const stats = [
            card.cost != null ? ["Cost", card.cost] : null,
            card.power != null ? ["Power", card.power] : null,
            card.strike != null ? ["Strike", card.strike] : null,
            card.edition_code ? ["Edition", card.edition_code] : null,
            card.copy_limit ? ["Kopien", "max. " + card.copy_limit] : null,
        ].filter(Boolean).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("");
        const n = Number(card.owned_normal || 0);
        const f = Number(card.owned_foil || 0);
        const chip = AUTH
            ? `<p class="have-chip" data-have-chip data-card-id="${card.id}">${esc(n + f > 0 ? `${n + f}× in der Sammlung${f ? " · " + f + " Foil" : ""}` : "Nicht in der Sammlung")}</p>`
            : "";
        const flags = [
            card.banned ? `<span class="badge ban">Ban</span>` : "",
            card.has_errata ? `<span class="badge errata">Errata</span>` : "",
        ].join("");
        const family = (card.family || []).filter((v) => v.id !== card.id);
        const familyHtml = family.length
            ? `<section class="related">
                <h3>Pal-Linie / Drucke</h3>
                <div class="variant-row">${family.map((v) => `
                    <a class="variant${v.landscape ? " landscape" : ""}" href="/card/${v.id}" data-card-id="${v.id}">
                        ${v.image_url ? `<img src="${esc(v.image_url)}" alt="">` : ""}
                        <span>${esc(v.card_code || "")} · ${esc(v.rarity || "")}</span>
                    </a>`).join("")}
                </div>
               </section>`
            : "";
        const errataHtml = card.has_errata && card.errata_excerpt
            ? `<aside class="errata-excerpt"><strong>Errata</strong><pre>${esc(card.errata_excerpt)}</pre></aside>`
            : "";
        if (modalTitle) modalTitle.textContent = card.name || "Karte";
        modalBody.innerHTML = `
            <div class="card-view-layout${landscapeGuess ? " landscape" : ""}">
                <figure class="detail-art${landscapeGuess ? " landscape" : ""}">${img}</figure>
                <div>
                    <p class="card-code">${esc(card.card_code || "")} · ${esc(card.rarity || "—")} ${flags}</p>
                    ${chip}
                    ${priceBlock(card)}
                    <ul class="stat-pills">${pills}${apts}</ul>
                    ${stats ? `<dl class="stat-grid">${stats}</dl>` : ""}
                    ${card.effect_html || card.effect ? `<section class="effect"><h3>Effekt</h3><pre>${card.effect_html || esc(card.effect)}</pre>${errataHtml}</section>` : errataHtml}
                    ${qtyMarkup(card)}
                    ${familyHtml}
                    <p class="muted"><a class="js-full-card" href="/card/${card.id}">Kartenseite öffnen</a></p>
                </div>
            </div>
        `;
        setModalLandscape(landscapeGuess);
        const art = modalBody.querySelector(".detail-art img");
        if (art) {
            const applyFromNatural = () => {
                if (art.naturalWidth > 0 && art.naturalHeight > 0) {
                    setModalLandscape(art.naturalWidth > art.naturalHeight);
                }
            };
            if (art.complete) applyFromNatural();
            else art.addEventListener("load", applyFromNatural, { once: true });
        }
        bindArtZoom(modalBody);
        modal.hidden = false;
        document.body.classList.add("modal-open");
        syncBackBtn();
    }

    async function showCard(id, opts = {}) {
        const nid = String(id);
        const res = await fetch("/api/cards/" + nid);
        if (!res.ok) return;
        const card = await res.json();
        if (!opts.fromBack && cardStack[cardStack.length - 1] !== nid) {
            cardStack.push(nid);
        }
        openCardView(card);
    }

    async function showCardByCode(code) {
        const res = await fetch("/api/lookup?q=" + encodeURIComponent(code || ""));
        if (!res.ok) return;
        const data = await res.json();
        const item = (data.items || [])[0];
        if (item?.id) showCard(item.id);
    }

    function backCard() {
        if (cardStack.length < 2) {
            closeCardView();
            return;
        }
        cardStack.pop();
        const prev = cardStack[cardStack.length - 1];
        showCard(prev, { fromBack: true });
    }

    document.getElementById("card-view-close")?.addEventListener("click", closeCardView);
    modalBack?.addEventListener("click", (e) => {
        e.preventDefault();
        backCard();
    });
    modal?.addEventListener("click", (e) => {
        if (e.target === modal) closeCardView();
    });
    document.addEventListener("keydown", (e) => {
        hideLoupe();
        if (e.key === "Escape") closeCardView();
    });

    document.addEventListener("click", (e) => {
        const codeBtn = e.target.closest("[data-card-code]");
        if (codeBtn) {
            e.preventDefault();
            e.stopPropagation();
            showCardByCode(codeBtn.getAttribute("data-card-code"));
            return;
        }
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button) return;
        if (e.target.closest("input, textarea, select, [data-add], [data-qty], [data-add-copy], [data-save-qty], [data-tile-add], .tile-actions, .js-full-card, .kw, .kw-tip, .qty-panel, [data-foil-toggle], [data-wish], #card-view-back, #card-view-close")) return;
        const el = e.target.closest("a[href^='/card/'], .card-tile[data-card-id]");
        if (!el) return;
        const id = cardIdFrom(el);
        if (!id) return;
        e.preventDefault();
        showCard(id);
    });

    bindArtZoom(document);
    window.PalTCG = { showCard, showCardByCode, openCardView, colorClass, esc };

    const kwTip = document.getElementById("kw-tip");
    const kwTitle = document.getElementById("kw-tip-title");
    const kwBody = document.getElementById("kw-tip-body");
    let kwTimer = 0;
    let kwOpen = null;

    function hideKwTip() {
        clearTimeout(kwTimer);
        kwTimer = 0;
        kwOpen = null;
        if (kwTip) kwTip.hidden = true;
    }

    function placeKwTip(anchor) {
        if (!kwTip || !anchor) return;
        const box = anchor.getBoundingClientRect();
        const tipW = Math.min(320, window.innerWidth - 16);
        kwTip.style.maxWidth = tipW + "px";
        kwTip.hidden = false;
        const h = kwTip.offsetHeight || 80;
        let x = box.left;
        let y = box.bottom + 8;
        if (x + tipW > window.innerWidth - 8) x = window.innerWidth - tipW - 8;
        if (x < 8) x = 8;
        if (y + h > window.innerHeight - 8) y = Math.max(8, box.top - h - 8);
        kwTip.style.left = x + "px";
        kwTip.style.top = y + "px";
    }

    function showKwTip(el) {
        if (!kwTip || !el) return;
        hideHover();
        const title = el.getAttribute("data-title") || el.getAttribute("data-kw") || "";
        const tip = el.getAttribute("data-tip") || "";
        if (!tip) return;
        if (kwTitle) kwTitle.textContent = title;
        if (kwBody) kwBody.textContent = tip;
        kwOpen = el;
        placeKwTip(el);
    }

    document.addEventListener("pointerover", (e) => {
        const el = e.target.closest?.(".kw");
        if (!el) return;
        hideHover();
        if (e.pointerType === "touch") return;
        clearTimeout(kwTimer);
        kwTimer = window.setTimeout(() => showKwTip(el), 450);
    });
    document.addEventListener("pointerout", (e) => {
        const el = e.target.closest?.(".kw");
        if (!el) return;
        if (el.contains(e.relatedTarget)) return;
        if (kwTip && kwTip.contains(e.relatedTarget)) return;
        clearTimeout(kwTimer);
        kwTimer = 0;
        if (e.pointerType !== "touch") hideKwTip();
    });
    document.addEventListener("click", (e) => {
        const el = e.target.closest?.(".kw");
        if (el) {
            e.preventDefault();
            e.stopPropagation();
            if (kwOpen === el && !kwTip?.hidden) hideKwTip();
            else showKwTip(el);
            return;
        }
        if (!e.target.closest?.(".kw-tip")) hideKwTip();
    }, true);
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") hideKwTip();
        const el = e.target.closest?.(".kw");
        if (!el) return;
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            if (kwOpen === el && !kwTip?.hidden) hideKwTip();
            else showKwTip(el);
        }
    });
    window.addEventListener("scroll", hideKwTip, true);
})();
