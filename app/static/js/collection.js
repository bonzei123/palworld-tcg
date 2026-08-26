function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
    ));
}

function euro(cents) {
    if (cents == null || cents === "") return "";
    return (Number(cents) / 100).toFixed(2) + " €";
}

async function saveQty(cardId, payload) {
    const res = await fetch("/api/collection/" + cardId, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    return res.json();
}

document.querySelectorAll("[data-notes]").forEach((panel) => {
    const btn = panel.querySelector("[data-save-notes]");
    if (!btn) return;
    btn.addEventListener("click", async () => {
        const id = panel.getAttribute("data-notes");
        const tags = [...panel.querySelectorAll("input[type=checkbox]:checked")].map((el) => el.value);
        const status = panel.querySelector("[data-notes-status]");
        const res = await fetch("/api/cards/" + id + "/notes", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ notes: panel.querySelector("[data-card-notes]").value, tags }),
        });
        if (status) status.textContent = res.ok ? "Gespeichert." : "Fehler.";
    });
});

const body = document.getElementById("coll-body");
if (body) {
    const url = new URLSearchParams(location.search);
    let status = url.get("status") || "";
    let locationFilter = url.get("location") || "";
    let conditionFilter = url.get("condition") || "";
    const summary = document.getElementById("summary-line");
    const conds = ["NM", "LP", "MP", "HP", "Played"];
    const locSel = document.getElementById("f-location");
    const condSel = document.getElementById("f-condition");

    if (condSel && conditionFilter) condSel.value = conditionFilter;
    document.querySelectorAll("#coll-tabs button").forEach((b) => {
        b.classList.toggle("is-active", (b.dataset.status || "") === status);
    });

    function syncCollUrl() {
        const u = new URLSearchParams();
        if (status) u.set("status", status);
        if (locationFilter) u.set("location", locationFilter);
        if (conditionFilter) u.set("condition", conditionFilter);
        const qs = u.toString();
        history.replaceState(null, "", qs ? ("/sammlung?" + qs) : "/sammlung");
    }

    function renderSummary(s) {
        if (!summary || !s) return;
        summary.textContent = `${s.have} im Besitz · ${s.owned} Exemplare · ${s.missing} fehlend · ${s.wanted} gewünscht`;
    }

    function fillLocations(locations) {
        if (!locSel) return;
        const current = locationFilter;
        locSel.innerHTML = `<option value="">Alle</option>` + (locations || []).map((loc) => (
            `<option value="${esc(loc)}"${loc === current ? " selected" : ""}>${esc(loc)}</option>`
        )).join("");
    }

    function renderValue(value) {
        const amount = document.getElementById("value-chip-amount");
        const line = document.getElementById("value-line");
        const cents = Number(value?.cents || 0);
        if (amount) amount.textContent = cents ? euro(cents) : "0.00 €";
        if (line) {
            line.textContent = cents
                ? `Sammelwert: ${euro(cents)} · ${value.priced || 0} Karten mit Preis`
                : "Sammelwert erscheint, sobald Preise hinterlegt sind.";
        }
    }

    async function loadProgress() {
        const res = await fetch("/api/collection/progress");
        if (!res.ok) return;
        const data = await res.json();
        renderValue(data.value || {});
        const syncLine = document.getElementById("sync-line");
        if (syncLine) {
            const info = data.prices_sync || {};
            syncLine.textContent = data.prices_synced_at
                ? `Letzter Preisabgleich: ${data.prices_synced_at}`
                    + (info.updated != null ? ` · ${info.updated} aktualisiert, ${info.skipped || 0} ohne Treffer` : "")
                : "Noch kein Preisabgleich.";
        }
        const syncBtn = document.getElementById("sync-prices");
        if (syncBtn) syncBtn.hidden = !data.is_admin;
        const list = document.getElementById("progress-list");
        if (list) {
            list.innerHTML = (data.sets || []).map((ed) => `
                <li>
                    <a class="progress-link" href="/?edition=${encodeURIComponent(ed.code)}&have=missing">
                        <strong>${esc(ed.code)}</strong>
                        <span>${ed.have}/${ed.total}${ed.copies ? " (" + ed.copies + ")" : ""}</span>
                        <span class="muted">${ed.missing ? "von " + esc(ed.code) + " fehlen noch " + ed.missing : "vollständig"}</span>
                        <div class="bar"><i style="width:${ed.total ? Math.round(100 * ed.have / ed.total) : 0}%"></i></div>
                    </a>
                </li>
            `).join("") || "<li class='muted'>Keine Editionen.</li>";
        }
        const gaps = document.getElementById("gap-list");
        if (gaps) {
            gaps.innerHTML = (data.gaps || []).map((c) => `
                <li class="gap-row">
                    <a href="/card/${c.id}">${esc(c.card_code)} · ${esc(c.name)}</a>
                    <span class="gap-have">nicht im Besitz</span>
                    <span class="gap-price">${euro(c.price_cents)}</span>
                </li>
            `).join("") || "<li class='muted'>Keine Preise — Lücken ohne Wertung.</li>";
        }
    }

    document.getElementById("sync-prices")?.addEventListener("click", async () => {
        const statusEl = document.getElementById("sync-status");
        if (statusEl) statusEl.textContent = "Preise werden geholt…";
        const res = await fetch("/api/admin/prices/sync", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            if (statusEl) statusEl.textContent = data.detail || "Abgleich fehlgeschlagen (Admin-Sitzung nötig).";
            return;
        }
        if (statusEl) {
            statusEl.textContent = `Aktualisiert: ${data.updated || 0} · übersprungen: ${data.skipped || 0} · offiziell: ${data.official || 0}`;
        }
        loadProgress();
    });

    async function loadPulls() {
        const res = await fetch("/api/pulls");
        if (!res.ok) return;
        const data = await res.json();
        const list = document.getElementById("pull-list");
        if (!list) return;
        list.innerHTML = (data.items || []).map((p) => `
            <li>${esc(p.qty)}× <a href="/card/${p.card_id}">${esc(p.card_code)} ${esc(p.name)}</a>
                ${p.foil ? ' <span class="badge foil">Foil</span>' : ""}
                · ${esc(p.source)} <span class="muted">${esc(p.created_at || "")}</span></li>
        `).join("") || "<li class='muted'>Noch keine Pulls.</li>";
    }

    async function loadCollection() {
        const u = new URLSearchParams();
        if (status) u.set("status", status);
        if (locationFilter) u.set("location", locationFilter);
        if (conditionFilter) u.set("condition", conditionFilter);
        const res = await fetch("/api/collection?" + u.toString());
        if (res.status === 401) {
            location.href = "/konto?next=/sammlung";
            return;
        }
        const data = await res.json();
        renderSummary(data.summary);
        fillLocations(data.locations || []);
        body.innerHTML = data.items.map((c) => `
            <tr data-id="${c.id}" data-card-id="${c.id}" data-hover="${esc(c.image_url || "")}">
                <td data-label="">${c.image_url ? `<img src="${esc(c.image_url)}" alt="" width="36"${c.landscape ? ' class="landscape"' : ""}>` : ""}</td>
                <td data-label="Karte"><a href="/card/${c.id}" data-card-id="${c.id}" data-hover="${esc(c.image_url || "")}"><strong>${esc(c.name)}</strong></a><br><code>${esc(c.card_code)}</code> · ${esc(c.rarity)}${c.foil ? ' <span class="badge foil">Foil</span>' : ""}${c.banned ? ' <span class="badge ban">Ban</span>' : ""}${c.has_errata ? ' <span class="badge errata">Errata</span>' : ""}</td>
                <td data-label="Habe"><input type="number" min="0" max="99" value="${c.owned || 0}" data-owned></td>
                <td data-label="Brauche"><input type="number" min="0" max="99" value="${c.wanted || 0}" data-wanted></td>
                <td data-label="Zustand"><select data-condition>${conds.map((x) => `<option${(c.condition || "NM") === x ? " selected" : ""}>${x}</option>`).join("")}</select></td>
                <td data-label="Ort"><input type="text" value="${esc(c.location || "")}" data-location></td>
                <td data-label="Tausch"><input type="checkbox" data-trade ${c.for_trade ? "checked" : ""}></td>
                <td data-label=""><button type="button" class="ghost" data-save>OK</button></td>
            </tr>
        `).join("") || `<tr><td colspan="8">Keine Einträge. Code oben eintragen oder im Katalog Besitz setzen.</td></tr>`;
    }

    document.getElementById("coll-tabs")?.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-status]");
        if (!btn) return;
        status = btn.dataset.status;
        document.querySelectorAll("#coll-tabs button").forEach((b) => b.classList.toggle("is-active", b === btn));
        syncCollUrl();
        loadCollection();
    });
    locSel?.addEventListener("change", () => {
        locationFilter = locSel.value;
        syncCollUrl();
        loadCollection();
    });
    condSel?.addEventListener("change", () => {
        conditionFilter = condSel.value;
        syncCollUrl();
        loadCollection();
    });

    body.addEventListener("click", async (e) => {
        const btn = e.target.closest("[data-save]");
        if (!btn) return;
        const tr = btn.closest("tr");
        await saveQty(tr.dataset.id, {
            owned: Number(tr.querySelector("[data-owned]").value || 0),
            wanted: Number(tr.querySelector("[data-wanted]").value || 0),
            condition: tr.querySelector("[data-condition]").value,
            location: tr.querySelector("[data-location]").value,
            for_trade: tr.querySelector("[data-trade]").checked,
        });
        loadCollection();
        loadProgress();
    });

    const addForm = document.getElementById("add-code");
    const pickGrid = document.getElementById("pick-grid");
    const addStatus = document.getElementById("add-status");

    async function addCode(payload) {
        const res = await fetch("/api/collection/add-code", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (res.status === 404) {
            addStatus.textContent = "Keine Karte zu diesem Code.";
            return;
        }
        if (data.need_pick) {
            pickGrid.hidden = false;
            pickGrid.innerHTML = data.items.map((c) => `
                <button type="button" class="pick-card" data-pick="${c.id}">
                    ${c.image_url ? `<img src="${esc(c.image_url)}" alt="">` : `<div class="missing">Kein Bild</div>`}
                    <span>${esc(c.card_code)} · ${esc(c.rarity)}</span>
                    <strong>${esc(c.name)}</strong>
                </button>
            `).join("");
            addStatus.textContent = "Mehrere Drucke — bitte auswählen.";
            pickGrid.dataset.code = payload.code;
            pickGrid.dataset.owned = payload.owned;
            pickGrid.dataset.source = payload.source || "";
            return;
        }
        pickGrid.hidden = true;
        pickGrid.innerHTML = "";
        addStatus.textContent = data.ok ? "Hinzugefügt." : (data.detail || "Fehler.");
        loadCollection();
        loadProgress();
        loadPulls();
    }

    addForm?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(addForm);
        await addCode({
            code: String(fd.get("code") || "").trim(),
            owned: Number(fd.get("owned") || 1),
            source: String(fd.get("source") || "").trim(),
        });
    });

    pickGrid?.addEventListener("click", async (e) => {
        const btn = e.target.closest("[data-pick]");
        if (!btn) return;
        await addCode({
            code: pickGrid.dataset.code,
            owned: Number(pickGrid.dataset.owned || 1),
            source: pickGrid.dataset.source || "",
            card_id: Number(btn.dataset.pick),
        });
    });

    loadCollection();
    loadProgress();
    loadPulls();
}
