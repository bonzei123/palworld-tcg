(function () {
const root = document.querySelector(".deck-builder");
if (!root) return;
const deckId = root.dataset.deckId;
const searchBox = document.getElementById("deck-q");
const hits = document.getElementById("deck-search");
const list = document.getElementById("deck-cards");
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

function render(deck) {
    const a = deck.analysis || {};
    totalEl.textContent = (a.total || 0) + " / 50";
    if (banner) {
        if (a.can_build) banner.textContent = "Dieses Deck kannst du aus der Sammlung bauen.";
        else if ((a.missing || []).length) banner.textContent = "Für dieses Deck fehlen noch Karten in der Sammlung.";
        else banner.textContent = "";
        banner.classList.toggle("ok", !!a.can_build);
        banner.classList.toggle("warn", !a.can_build && (a.total || 0) > 0);
    }
    list.innerHTML = (deck.cards || []).map((c) => `
        <li class="${c.illegal ? "is-illegal" : ""} ${c.can_play === false ? "is-missing" : ""}">
            <a href="/card/${c.id}">${esc(c.card_code)} · ${esc(c.name)}</a>
            <span>${esc(c.color || "")} · Cost ${c.cost ?? "—"} · habe ${c.owned_base ?? c.owned ?? 0}${c.banned ? " · Ban" : ""}</span>
            <input type="number" min="0" max="${c.copy_limit || 4}" value="${c.qty}" data-qty="${c.id}">
        </li>
    `).join("") || "<li>Noch keine Karten.</li>";
    const max = Math.max(1, ...(a.curve || []).map((x) => x.count));
    curveEl.innerHTML = (a.curve || []).map((b) => `
        <div class="curve-bar" title="${b.cost}: ${b.count}">
            <div style="height:${Math.round(80 * b.count / max)}%"></div>
            <span>${b.cost === 10 ? "10+" : b.cost}</span>
        </div>
    `).join("");
    colorsEl.innerHTML = (a.colors || []).map((c) => `<li>${esc(c.color)}: ${c.count} (${c.share}%)</li>`).join("");
    warnEl.innerHTML = (a.warnings || []).map((w) => `<li>${esc(w)}</li>`).join("");
    illegalEl.innerHTML = (a.illegal || []).map((w) => `<li>${esc(w)}</li>`).join("");
    missingEl.innerHTML = (a.missing || []).map((m) => `<li>${esc(m.card_code)} · noch ${m.need} (habe ${m.have})</li>`).join("")
        || (a.can_build ? "<li>Alle Karten vorhanden.</li>" : "");
    const lucky = (a.lucky_pals || []).join(", ") || "—";
    partnerEl.innerHTML = `<li>Soul: ${a.souls || 0} / 1</li><li>Lucky/Partner: ${esc(lucky)}</li>`;
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
            <button type="button" data-add="${c.id}">${esc(c.card_code)} · ${esc(c.name)} · ${esc(c.rarity)}${c.banned ? " · Ban" : ""}</button>
        `).join("");
    }, 200);
});

hits.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-add]");
    if (btn) setQty(btn.dataset.add, 1);
});

list.addEventListener("change", (e) => {
    const input = e.target.closest("[data-qty]");
    if (input) setQty(input.dataset.qty, input.value);
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
    const status = document.getElementById("import-status");
    const text = document.getElementById("import-text").value;
    const res = await fetch("/api/decks/" + deckId + "/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
    });
    if (!res.ok) {
        if (status) status.textContent = "Import fehlgeschlagen.";
        return;
    }
    render(await res.json());
    if (status) status.textContent = "Importiert.";
});

refresh();
})();
