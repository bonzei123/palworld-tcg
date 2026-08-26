(function () {
const root = document.querySelector(".deck-builder");
if (!root) return;
const deckId = root.dataset.deckId;
const searchBox = document.getElementById("deck-q");
const hits = document.getElementById("deck-search");
const list = document.getElementById("deck-cards");
const soulsList = document.getElementById("deck-souls");
const curveEl = document.getElementById("curve");
const colorsEl = document.getElementById("colors");
const warnEl = document.getElementById("warnings");
const illegalEl = document.getElementById("illegal");
const missingEl = document.getElementById("missing");
const partnerEl = document.getElementById("partner-check");
const totalEl = document.getElementById("deck-total");
const banner = document.getElementById("build-banner");

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
    ));
}

function colorClass(color) {
    const n = String(color || "").trim().toLowerCase();
    if (!n || n === "colorless" || n === "farblos") return "colorless";
    return n.replace(/[^a-z0-9]+/g, "");
}

function isSoul(card) {
    const kind = String(card.card_type || "").toLowerCase();
    const name = String(card.name || "").toLowerCase();
    return kind === "soul" || name === "soul" || card.is_soul;
}

function cardRow(c) {
    const color = colorClass(c.color);
    return `
        <li class="${c.illegal ? "is-illegal" : ""} ${c.can_play === false ? "is-missing" : ""} ${c.foil ? "is-foil" : ""}"
            data-card-id="${c.id}" data-hover="${esc(c.image_url || "")}" draggable="true">
            <a href="/card/${c.id}">${esc(c.card_code)} · ${esc(c.name)}</a>
            <span><span class="color-${color}">${esc(c.color || "Colorless")}</span> · Cost ${c.cost ?? "—"} · habe ${c.owned_base ?? c.owned ?? 0}${c.banned ? " · Ban" : ""}${c.foil ? ' · <span class="badge foil">Foil</span>' : ""}</span>
            <input type="number" min="0" max="${c.copy_limit || 4}" value="${c.qty}" data-qty="${c.id}">
        </li>
    `;
}

function render(deck) {
    const a = deck.analysis || {};
    totalEl.textContent = `${a.total || 0} / 50 · Soul ${a.souls || 0} / 10`;
    if (banner) {
        if (a.can_build) banner.textContent = "Dieses Deck kannst du aus der Sammlung bauen.";
        else if ((a.missing || []).length) banner.textContent = "Für dieses Deck fehlen noch Karten in der Sammlung.";
        else banner.textContent = "";
        banner.classList.toggle("ok", !!a.can_build);
        banner.classList.toggle("warn", !a.can_build && ((a.total || 0) > 0 || (a.souls || 0) > 0));
    }
    const cards = deck.cards || [];
    const main = cards.filter((c) => !isSoul(c));
    const souls = cards.filter(isSoul);
    list.innerHTML = main.map(cardRow).join("") || "<li>Noch keine Karten.</li>";
    if (soulsList) {
        soulsList.innerHTML = souls.map(cardRow).join("") || "<li>Keine Souls — 10 erwartet.</li>";
    }
    const max = Math.max(1, ...(a.curve || []).map((x) => x.count));
    curveEl.innerHTML = (a.curve || []).map((b) => `
        <div class="curve-bar" title="${b.cost}: ${b.count}">
            <div style="height:${Math.round(80 * b.count / max)}%"></div>
            <span>${b.cost === 10 ? "10+" : b.cost}</span>
        </div>
    `).join("");
    colorsEl.innerHTML = (a.colors || []).map((c) => {
        const cls = colorClass(c.color);
        const extra = cls === "colorless" ? " · immer erlaubt" : "";
        return `<li><span class="color-${cls}">${esc(c.color)}</span>: ${c.count} (${c.share}%)${extra}</li>`;
    }).join("") || "<li>Keine Farben.</li>";
    if (a.color_ok === false) {
        colorsEl.insertAdjacentHTML("beforeend", `<li class="warn">Maximal zwei Farben plus Colorless.</li>`);
    }
    warnEl.innerHTML = (a.warnings || []).map((w) => `<li>${esc(w)}</li>`).join("");
    illegalEl.innerHTML = (a.illegal || []).map((w) => `<li>${esc(w)}</li>`).join("");
    const missing = a.missing || [];
    missingEl.innerHTML = missing.map((m) => `
        <li>
            ${esc(m.card_code)} · noch ${m.need} (habe ${m.have})
            <button type="button" class="ghost" data-wish="${m.card_id}" data-want="${(m.have || 0) + (m.need || 0)}">Auf Wunschliste</button>
        </li>
    `).join("") || (a.can_build ? "<li>Alle Karten vorhanden.</li>" : "");
    const wishAll = document.getElementById("wish-all");
    if (wishAll) wishAll.hidden = !missing.length;
    const lucky = (a.lucky_pals || []).join(", ") || "—";
    partnerEl.innerHTML = `<li>Soul-Stack: ${a.souls || 0} / 10</li><li>Lucky/Partner: ${esc(lucky)}</li>`;
}

async function refresh() {
    const res = await fetch("/api/decks/" + deckId);
    render(await res.json());
}

async function setQty(cardId, qty) {
    const res = await fetch(`/api/decks/${deckId}/cards/${cardId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ qty: Number(qty) }),
    });
    render(await res.json());
}

async function addWish(cardId, wanted) {
    await fetch("/api/collection/" + cardId, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ wanted: Number(wanted) }),
    });
}

let t;
searchBox.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(async () => {
        const q = searchBox.value.trim();
        if (q.length < 2) {
            hits.innerHTML = "";
            return;
        }
        const res = await fetch("/api/cards?limit=12&q=" + encodeURIComponent(q));
        const data = await res.json();
        hits.innerHTML = data.items.map((c) => `
            <button type="button" draggable="true" data-add="${c.id}" data-card-id="${c.id}" data-hover="${esc(c.image_url || "")}">${esc(c.card_code)} · ${esc(c.name)} · ${esc(c.rarity)}${c.banned ? " · Ban" : ""}</button>
        `).join("");
    }, 200);
});

hits.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-add]");
    if (!btn) return;
    const input = document.querySelector(`[data-qty="${btn.dataset.add}"]`);
    const qty = input ? Number(input.value || 0) + 1 : 1;
    setQty(btn.dataset.add, qty);
});

hits.addEventListener("dragstart", (e) => {
    const btn = e.target.closest("[data-add]");
    if (!btn) return;
    e.dataTransfer.setData("text/plain", btn.dataset.add);
    e.dataTransfer.effectAllowed = "copy";
});

function bindDrop(el) {
    if (!el) return;
    el.addEventListener("dragover", (e) => {
        e.preventDefault();
        el.classList.add("is-drop");
    });
    el.addEventListener("dragleave", () => el.classList.remove("is-drop"));
    el.addEventListener("drop", (e) => {
        e.preventDefault();
        el.classList.remove("is-drop");
        const id = e.dataTransfer.getData("text/plain");
        if (!id || !/^\d+$/.test(id)) return;
        const input = document.querySelector(`[data-qty="${id}"]`);
        const qty = input ? Number(input.value || 0) + 1 : 1;
        setQty(id, qty);
    });
}
bindDrop(list);
bindDrop(soulsList);
bindDrop(hits);

function onListChange(e) {
    const input = e.target.closest("[data-qty]");
    if (input && input.tagName === "INPUT") setQty(input.dataset.qty, input.value);
}

function onListClick(e) {
    const wish = e.target.closest("[data-wish]");
    if (wish) {
        addWish(wish.dataset.wish, wish.dataset.want).then(() => {
            wish.textContent = "Gesetzt";
            wish.disabled = true;
        });
    }
}

list.addEventListener("change", onListChange);
soulsList?.addEventListener("change", onListChange);
list.addEventListener("click", onListClick);
soulsList?.addEventListener("click", onListClick);
missingEl?.addEventListener("click", onListClick);

document.getElementById("wish-all")?.addEventListener("click", async () => {
    const btns = [...(missingEl?.querySelectorAll("[data-wish]") || [])];
    for (const btn of btns) {
        await addWish(btn.dataset.wish, btn.dataset.want);
        btn.textContent = "Gesetzt";
        btn.disabled = true;
    }
});

document.getElementById("rename-deck")?.addEventListener("click", async () => {
    const name = document.getElementById("deck-name").value.trim();
    if (!name) return;
    await fetch("/api/decks/" + deckId, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
    });
});

document.getElementById("import-deck")?.addEventListener("click", async () => {
    const statusEl = document.getElementById("import-status");
    const text = document.getElementById("import-text").value;
    const res = await fetch("/api/decks/" + deckId + "/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
    });
    if (!res.ok) {
        if (statusEl) statusEl.textContent = "Import fehlgeschlagen.";
        return;
    }
    render(await res.json());
    if (statusEl) statusEl.textContent = "Importiert.";
});

refresh();
})();
