(function () {
const grid = document.getElementById("grid");
const meta = document.getElementById("result-meta");
const pager = document.getElementById("pager");
const form = document.getElementById("search-form");

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

function rarityClass(r) {
    return "rarity-chip rarity-" + String(r || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (ch) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
    ));
}

function cardCode(card) {
    return card.card_code || card.card_code || "";
}

function cardImage(card) {
    return card.image_url || card.image_url || "";
}

function tile(card) {
    const code = cardCode(card);
    const img = cardImage(card)
        ? `<img src="${esc(cardImage(card))}" alt="${esc(card.name)}" loading="lazy">`
        : `<div class="missing">Kein Bild</div>`;
    const badges = [
        card.banned ? `<span class="badge ban">Ban</span>` : "",
        card.has_errata ? `<span class="badge errata">Errata</span>` : "",
        card.price_cents ? `<span class="badge price">${(card.price_cents / 100).toFixed(2)} €</span>` : "",
    ].join("");
    return `<a class="card-tile${card.landscape ? " landscape" : ""}" href="/card/${card.id}">
        ${img}
        <div class="meta">
            <span>${esc(code)}</span>
            <strong>${esc(card.name)}</strong>
            <span class="${rarityClass(card.rarity)}">${esc(card.rarity || "")}</span>
            ${badges}
        </div>
    </a>`;
}

async function load() {
    if (!grid) return;
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

load();
})();
