(function () {
const grid = document.getElementById("grid");
const meta = document.getElementById("result-meta");
const pager = document.getElementById("pager");
const form = document.getElementById("search-form");
const AUTH = document.body?.dataset.auth === "1";

let page = 1;
const PAGE_SIZE = 96;

function val(id) {
    return document.getElementById(id)?.value?.trim() || "";
}

function params() {
    const u = new URLSearchParams({ page: String(page), limit: String(PAGE_SIZE) });
    const q = val("q");
    const type = val("f-type");
    const color = val("f-color");
    const rarity = val("f-rarity");
    const edition = val("f-edition");
    const attribute = val("f-attribute");
    const aptitude = val("f-aptitude");
    const have = val("f-have");
    const sort = val("f-sort");
    if (q) u.set("q", q);
    if (type) u.set("type", type);
    if (color) u.set("color", color);
    if (rarity) u.set("rarity", rarity);
    if (edition) u.set("edition", edition);
    if (attribute) u.set("attribute", attribute);
    if (aptitude) u.set("aptitude", aptitude);
    if (have) u.set("have", have);
    if (sort) u.set("sort", sort);
    return u;
}

function syncUrl() {
    const u = params();
    u.delete("limit");
    if (page === 1) u.delete("page");
    const qs = u.toString();
    const next = qs ? ("/?" + qs) : "/";
    if (location.pathname === "/" && location.search.replace(/^\?/, "") !== qs) {
        history.replaceState(null, "", next);
    }
}

function applyUrl() {
    const u = new URLSearchParams(location.search);
    const map = {
        q: "q",
        type: "f-type",
        color: "f-color",
        rarity: "f-rarity",
        edition: "f-edition",
        attribute: "f-attribute",
        aptitude: "f-aptitude",
        have: "f-have",
        sort: "f-sort",
    };
    for (const [key, id] of Object.entries(map)) {
        const el = document.getElementById(id);
        if (el && u.has(key)) el.value = u.get(key);
    }
    page = Math.max(1, Number(u.get("page") || 1) || 1);
    const filters = document.getElementById("filters");
    const toggle = document.getElementById("filter-toggle");
    if (filters && [...filters.querySelectorAll("select")].some((s) => s.value)) {
        filters.classList.add("is-open");
        toggle?.setAttribute("aria-expanded", "true");
    }
}

function rarityClass(r) {
    return "rarity-chip rarity-" + String(r || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (ch) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
    ));
}

function cardCode(card) {
    return card.card_code || "";
}

function cardImage(card) {
    return card.image_url || "";
}

function haveMark(n, f) {
    const t = (Number(n) || 0) + (Number(f) || 0);
    if (!t) return "";
    return `<span class="have-badge">${t}×${f ? " · " + f + "F" : ""}</span>`;
}

function tile(card) {
    const code = cardCode(card);
    const src = cardImage(card);
    const img = src
        ? `<img src="${esc(src)}" alt="${esc(card.name)}" loading="lazy">`
        : `<div class="missing">Kein Bild</div>`;
    const badges = [
        card.banned ? `<span class="badge ban">Ban</span>` : "",
        card.has_errata ? `<span class="badge errata">Errata</span>` : "",
        card.price_cents ? `<span class="badge price"${card.price_chart_cents && String(card.price_chart_cents).split(",").length >= 2 ? ` data-price-cents="${esc(card.price_chart_cents)}" data-price-labels="${esc(card.price_chart_labels || "")}"` : ""}>${(card.price_cents / 100).toFixed(2)} €</span>` : "",
    ].join("");
    const n = Number(card.owned_normal || 0);
    const f = Number(card.owned_foil || 0);
    const actions = AUTH
        ? `<div class="tile-actions">
            <button type="button" data-tile-add="0">+1</button>
            <button type="button" data-tile-add="1">+1 Foil</button>
           </div>`
        : "";
    return `<article class="card-tile${card.landscape ? " landscape" : ""}" tabindex="0"
        data-card-id="${card.id}"
        data-hover="${esc(src)}"
        data-owned-normal="${n}"
        data-owned-foil="${f}"
        data-copy-limit="${card.copy_limit || 4}">
        ${haveMark(n, f)}
        ${img}
        <div class="meta">
            <span>${esc(code)}</span>
            <strong>${esc(card.name)}</strong>
            <span class="${rarityClass(card.rarity)}">${esc(card.rarity || "")}</span>
            ${badges}
        </div>
        ${actions}
    </article>`;
}

function refreshTileHave(tileEl, n, f) {
    tileEl.dataset.ownedNormal = String(n);
    tileEl.dataset.ownedFoil = String(f);
    let badge = tileEl.querySelector(".have-badge");
    const html = haveMark(n, f);
    if (html) {
        const tmp = document.createElement("div");
        tmp.innerHTML = html;
        const next = tmp.firstElementChild;
        if (badge) badge.replaceWith(next);
        else tileEl.insertAdjacentElement("afterbegin", next);
    } else if (badge) {
        badge.remove();
    }
}

async function addCopy(tileEl, foil) {
    if (!AUTH || !tileEl) return;
    const id = tileEl.dataset.cardId;
    const key = foil ? "ownedFoil" : "ownedNormal";
    const prevN = Number(tileEl.dataset.ownedNormal || 0);
    const prevF = Number(tileEl.dataset.ownedFoil || 0);
    const next = (foil ? prevF : prevN) + 1;
    refreshTileHave(tileEl, foil ? prevN : next, foil ? next : prevF);
    try {
        const res = await fetch("/api/collection/" + id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ owned: next, foil: foil ? 1 : 0 }),
        });
        const rec = await res.json();
        if (!res.ok || !rec.ok) throw new Error(rec.detail || "Fehler");
        refreshTileHave(
            tileEl,
            rec.owned_normal != null ? rec.owned_normal : (foil ? prevN : next),
            rec.owned_foil != null ? rec.owned_foil : (foil ? next : prevF),
        );
    } catch {
        refreshTileHave(tileEl, prevN, prevF);
    }
}

async function load() {
    if (!grid) return;
    syncUrl();
    grid.innerHTML = `<p class="empty">Lade Karten…</p>`;
    try {
        const res = await fetch("/api/cards?" + params().toString());
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || "API-Fehler " + res.status);
        const list = Array.isArray(data.items) ? data.items : [];
        const total = Number(data.total || 0);
        const limit = Number(data.limit || PAGE_SIZE) || PAGE_SIZE;
        if (meta) {
            const q = val("q");
            meta.textContent = q
                ? `${total} Treffer`
                : `${total} Karten`;
        }
        if (!list.length) {
            grid.innerHTML = `<p class="empty">${total ? "Antwort ohne Kartenliste." : "Keine Karten. Unter Admin eine HTML-Liste importieren."}</p>`;
            if (pager) pager.innerHTML = "";
            return;
        }
        grid.innerHTML = list.map(tile).join("");
        const pages = Math.max(1, Math.ceil(total / limit));
        if (pager) {
            pager.innerHTML = `
                <button type="button" ${page <= 1 ? "disabled" : ""} data-to="${page - 1}">Zurück</button>
                <span>${page} / ${pages}</span>
                <button type="button" ${page >= pages ? "disabled" : ""} data-to="${page + 1}">Weiter</button>
            `;
        }
    } catch (err) {
        grid.innerHTML = `<p class="empty">Katalog konnte nicht geladen werden. ${esc(err.message || err)}</p>`;
        if (pager) pager.innerHTML = "";
    }
}

grid?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-tile-add]");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    addCopy(btn.closest(".card-tile"), btn.getAttribute("data-tile-add") === "1");
});

function tiles() {
    return [...(grid?.querySelectorAll(".card-tile") || [])];
}

function gridColumns() {
    const items = tiles();
    if (items.length < 2) return 1;
    const y0 = items[0].offsetTop;
    let n = 1;
    for (let i = 1; i < items.length; i++) {
        if (items[i].offsetTop !== y0) break;
        n++;
    }
    return n;
}

function inField(el) {
    return el?.closest?.("input, textarea, select");
}

document.addEventListener("keydown", (e) => {
    if (!grid || document.body.classList.contains("modal-open")) return;
    if (inField(e.target) || inField(document.activeElement)) return;
    const items = tiles();
    if (!items.length) return;
    const current = e.target.closest?.(".card-tile") || document.activeElement?.closest?.(".card-tile");
    let idx = items.indexOf(current);
    if (e.key === "ArrowRight" || e.key === "ArrowLeft" || e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const cols = gridColumns();
        if (idx < 0) idx = 0;
        else if (e.key === "ArrowRight") idx = Math.min(items.length - 1, idx + 1);
        else if (e.key === "ArrowLeft") idx = Math.max(0, idx - 1);
        else if (e.key === "ArrowDown") idx = Math.min(items.length - 1, idx + cols);
        else if (e.key === "ArrowUp") idx = Math.max(0, idx - cols);
        items[idx].focus();
        return;
    }
    if (idx < 0) return;
    if (e.key === "Enter") {
        e.preventDefault();
        const id = items[idx].dataset.cardId;
        if (id && window.PalTCG?.showCard) window.PalTCG.showCard(id);
        else if (id) items[idx].click();
        return;
    }
    if (e.key === "+" || e.key === "=") {
        e.preventDefault();
        addCopy(items[idx], false);
    }
});

form?.addEventListener("submit", (e) => {
    e.preventDefault();
    page = 1;
    load();
});
["f-type", "f-color", "f-rarity", "f-edition", "f-attribute", "f-aptitude", "f-have", "f-sort"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", () => {
        page = 1;
        load();
    });
});
let t;
document.getElementById("q")?.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => {
        page = 1;
        load();
    }, 160);
});
pager?.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-to]");
    if (!btn || btn.disabled) return;
    page = Number(btn.dataset.to);
    load();
    window.scrollTo({ top: 0, behavior: "smooth" });
});

applyUrl();
load();
})();
