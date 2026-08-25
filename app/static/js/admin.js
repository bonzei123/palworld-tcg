function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
    ));
}

const geminiForm = document.getElementById("gemini-form");
const importForm = document.getElementById("import-form");
const rulesForm = document.getElementById("rules-form");
const logEl = document.getElementById("import-log");
const modal = document.getElementById("card-modal");
const cardForm = document.getElementById("card-form");

document.getElementById("admin-tabs").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-tab]");
    if (!btn) return;
    document.querySelectorAll("#admin-tabs button").forEach((b) => b.classList.toggle("is-active", b === btn));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("is-active", p.dataset.panel === btn.dataset.tab));
});

geminiForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(geminiForm);
    const body = { gemini_model: fd.get("gemini_model") };
    const key = String(fd.get("gemini_api_key") || "").trim();
    if (key) body.gemini_api_key = key;
    const status = document.getElementById("gemini-status");
    const res = await fetch("/api/admin/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    status.textContent = res.ok ? "Gespeichert." : "Fehler beim Speichern.";
});

const banlistForm = document.getElementById("banlist-form");
if (banlistForm) {
    banlistForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const status = document.getElementById("banlist-status");
        const res = await fetch("/api/admin/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ banned_codes: banlistForm.banned_codes.value }),
        });
        status.textContent = res.ok ? "Banlist gespeichert." : "Fehler.";
    });
}

const clearBtn = document.getElementById("clear-key");
if (clearBtn) {
    clearBtn.addEventListener("click", async () => {
        await fetch("/api/admin/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ clear_key: true, gemini_api_key: "" }),
        });
        location.reload();
    });
}

rulesForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const status = document.getElementById("rules-status");
    const data = new FormData(rulesForm);
    status.textContent = "Lade hoch…";
    const res = await fetch("/api/admin/rules", { method: "POST", body: data });
    const json = await res.json().catch(() => ({}));
    status.textContent = res.ok ? `Gespeichert (${json.chars || 0} Zeichen).` : json.detail || "Fehler";
    if (res.ok) setTimeout(() => location.reload(), 600);
});

const errataForm = document.getElementById("errata-form");
if (errataForm) {
    errataForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const status = document.getElementById("errata-status");
        status.textContent = "Lade hoch…";
        const res = await fetch("/api/admin/errata", { method: "POST", body: new FormData(errataForm) });
        const json = await res.json().catch(() => ({}));
        status.textContent = res.ok ? `Gespeichert (${json.chars || 0} Zeichen).` : json.detail || "Fehler";
        if (res.ok) setTimeout(() => location.reload(), 600);
    });
}

importForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    logEl.hidden = false;
    logEl.textContent = "Import läuft…\n";
    const data = new FormData(importForm);
    const res = await fetch("/api/admin/import", { method: "POST", body: data });
    if (!res.ok || !res.body) {
        logEl.textContent += "Import fehlgeschlagen.\n";
        return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop();
        for (const line of lines) {
            if (!line.trim()) continue;
            try {
                const ev = JSON.parse(line);
                if (ev.stage === "parse") logEl.textContent += `${ev.count} Karten erkannt.\n`;
                else if (ev.stage === "save") logEl.textContent += `DB ${ev.done}/${ev.total}\n`;
                else if (ev.stage === "image") logEl.textContent += `Bild ${ev.done}/${ev.total} ${ev.name || ""}\n`;
                else if (ev.stage === "done") {
                    logEl.textContent += `Fertig: ${ev.inserted} neu, ${ev.updated} aktualisiert`;
                    if (ev.images_ok) logEl.textContent += `, ${ev.images_ok} Bilder aus ZIP`;
                    if (ev.images_unmatched) logEl.textContent += `, ${ev.images_unmatched} Dateien ohne Treffer`;
                    logEl.textContent += ".\n";
                } else if (ev.stage === "error" || ev.error) logEl.textContent += `Fehler: ${ev.error}\n`;
            } catch {
                logEl.textContent += line + "\n";
            }
            logEl.scrollTop = logEl.scrollHeight;
        }
    }
});

document.getElementById("save-editions").addEventListener("click", async () => {
    const status = document.getElementById("edition-status");
    for (const input of document.querySelectorAll(".edition-name")) {
        await fetch("/api/admin/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                edition_rename: { code: input.dataset.edition, name: input.value },
            }),
        });
    }
    status.textContent = "Namen gespeichert.";
});

document.getElementById("edition-list").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-delete-edition]");
    if (!btn) return;
    const code = btn.dataset.deleteEdition;
    if (!confirm(`Edition ${code} inkl. aller Karten löschen?`)) return;
    const res = await fetch("/api/admin/editions/" + encodeURIComponent(code), { method: "DELETE" });
    document.getElementById("edition-status").textContent = res.ok ? `${code} gelöscht.` : "Löschen fehlgeschlagen.";
    if (res.ok) setTimeout(() => location.reload(), 400);
});

document.getElementById("wipe-btn").addEventListener("click", async () => {
    const status = document.getElementById("wipe-status");
    const confirmText = document.getElementById("wipe-confirm").value.trim();
    const res = await fetch("/api/admin/wipe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: confirmText }),
    });
    status.textContent = res.ok ? "Datenbank geleert." : "Bestätigung falsch oder Fehler.";
    if (res.ok) setTimeout(() => location.reload(), 500);
});

let dbPage = 1;
async function loadDb() {
    const q = document.getElementById("db-q").value.trim();
    const u = new URLSearchParams({ page: dbPage, limit: 40 });
    if (q) u.set("q", q);
    const res = await fetch("/api/cards?" + u.toString());
    const data = await res.json();
    document.getElementById("db-meta").textContent = data.total + " Karten";
    const body = document.getElementById("db-body");
    body.innerHTML = data.items.map((c) => `
        <tr>
            <td data-label="">${c.image_url ? `<img src="${esc(c.image_url)}" alt=""${c.landscape ? ' class="landscape"' : ""}>` : ""}</td>
            <td data-label="Code"><code>${esc(c.card_code)}</code></td>
            <td data-label="Name">${esc(c.name)}</td>
            <td data-label="Seltenheit">${esc(c.rarity)}</td>
            <td data-label="Typ">${esc(c.card_type)}</td>
            <td data-label="Edition">${esc(c.edition_code)}</td>
            <td data-label=""><button type="button" class="ghost" data-edit="${c.id}">Bearbeiten</button></td>
        </tr>
    `).join("") || `<tr><td colspan="7">Keine Karten. HTML unter „Import“ hochladen.</td></tr>`;
    const pages = Math.max(1, Math.ceil(data.total / data.limit));
    document.getElementById("db-pager").innerHTML = `
        <button type="button" ${dbPage <= 1 ? "disabled" : ""} data-to="${dbPage - 1}">Zurück</button>
        <span>${dbPage} / ${pages}</span>
        <button type="button" ${dbPage >= pages ? "disabled" : ""} data-to="${dbPage + 1}">Weiter</button>
    `;
}

document.getElementById("db-q").addEventListener("input", () => {
    dbPage = 1;
    loadDb();
});
document.getElementById("db-pager").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-to]");
    if (!btn || btn.disabled) return;
    dbPage = Number(btn.dataset.to);
    loadDb();
});
document.getElementById("db-body").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-edit]");
    if (btn) openCard(Number(btn.dataset.edit));
});
document.getElementById("db-new").addEventListener("click", () => openCard(null));
document.getElementById("modal-close").addEventListener("click", () => { modal.hidden = true; });
modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.hidden = true;
});

function fillForm(card) {
    const f = cardForm;
    f.id.value = card?.id || "";
    f.card_code.value = card?.card_code || "";
    f.name.value = card?.name || "";
    f.rarity.value = card?.rarity || "";
    f.card_type.value = card?.card_type || "";
    f.subtype.value = card?.subtype || "";
    f.color.value = card?.color || "";
    f.attributes.value = (card?.attributes || []).join(", ");
    f.aptitudes.value = (card?.aptitudes || []).join(", ");
    f.cost.value = card?.cost ?? "";
    f.power.value = card?.power ?? "";
    f.strike.value = card?.strike ?? "";
    f.edition_code.value = card?.edition_code || "";
    f.official_id.value = card?.official_id ?? "";
    f.effect.value = card?.effect || "";
    if (f.price_euros) {
        f.price_euros.value = card?.price_cents != null ? (Number(card.price_cents) / 100).toFixed(2) : "";
    }
    if (f.banned) f.banned.checked = !!card?.banned;
    f.image.value = "";
    document.getElementById("card-delete").hidden = !card?.id;
    document.getElementById("modal-title").textContent = card?.id ? card.name : "Neue Karte";
    document.getElementById("modal-image").textContent = card?.image_url ? "Aktuelles Bild vorhanden." : "Kein Bild.";
    document.getElementById("card-status").textContent = "";
}

async function openCard(id) {
    if (!id) {
        fillForm(null);
        modal.hidden = false;
        return;
    }
    const res = await fetch("/api/cards/" + id);
    if (!res.ok) return;
    fillForm(await res.json());
    modal.hidden = false;
}

function formPayload() {
    const f = cardForm;
    return {
        card_code: f.card_code.value.trim(),
        name: f.name.value.trim(),
        rarity: f.rarity.value.trim(),
        card_type: f.card_type.value.trim(),
        subtype: f.subtype.value.trim(),
        color: f.color.value.trim(),
        attributes: f.attributes.value,
        aptitudes: f.aptitudes.value,
        cost: f.cost.value,
        power: f.power.value,
        strike: f.strike.value,
        edition_code: f.edition_code.value.trim(),
        official_id: f.official_id.value,
        effect: f.effect.value,
        banned: !!f.banned?.checked,
        price_euros: f.price_euros?.value || "",
    };
}

cardForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = cardForm.id.value;
    const status = document.getElementById("card-status");
    const res = await fetch(id ? "/api/admin/cards/" + id : "/api/admin/cards", {
        method: id ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formPayload()),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
        status.textContent = json.detail || "Speichern fehlgeschlagen.";
        return;
    }
    const cardId = json.card?.id || id;
    const img = cardForm.image.files[0];
    if (img && cardId) {
        const fd = new FormData();
        fd.append("file", img);
        await fetch("/api/admin/cards/" + cardId + "/image", { method: "POST", body: fd });
    }
    status.textContent = "Gespeichert.";
    loadDb();
    setTimeout(() => { modal.hidden = true; }, 400);
});

document.getElementById("card-delete").addEventListener("click", async () => {
    const id = cardForm.id.value;
    if (!id || !confirm("Diese Karte löschen?")) return;
    const res = await fetch("/api/admin/cards/" + id, { method: "DELETE" });
    document.getElementById("card-status").textContent = res.ok ? "Gelöscht." : "Löschen fehlgeschlagen.";
    if (res.ok) {
        loadDb();
        setTimeout(() => { modal.hidden = true; }, 300);
    }
});

loadDb();

const pwForm = document.getElementById("palworldcard-form");
if (pwForm) {
    pwForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(pwForm);
        const body = {};
        const ident = String(fd.get("palworldcard_identity") || "").trim();
        const pwd = String(fd.get("palworldcard_password") || "");
        if (ident) body.palworldcard_identity = ident;
        if (pwd.trim()) body.palworldcard_password = pwd;
        const status = document.getElementById("palworldcard-status");
        if (!ident && !pwd.trim()) {
            status.textContent = "Nichts zu speichern.";
            return;
        }
        const res = await fetch("/api/admin/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        status.textContent = res.ok ? "Gespeichert." : "Fehler beim Speichern.";
    });
}
document.getElementById("clear-palworldcard")?.addEventListener("click", async () => {
    await fetch("/api/admin/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clear_palworldcard: true }),
    });
    location.reload();
});
