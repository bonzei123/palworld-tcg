const q = document.getElementById("off-q");
const meta = document.getElementById("off-meta");
const grid = document.getElementById("off-grid");
let items = [];

function tile(card) {
    const img = card.image_url
        ? `<img src="${card.image_url}" alt="${card.name}" loading="lazy">`
        : `<div class="missing">Kein Bild</div>`;
    return `<a class="card-tile${card.landscape ? " landscape" : ""}" href="/card/${card.id}">
        ${img}
        <div class="meta"><span>${card.card_code}</span><strong>${card.name}</strong><span>${card.rarity || ""}</span></div>
    </a>`;
}

function draw() {
    const term = (q.value || "").trim().toLowerCase();
    const shown = term
        ? items.filter((c) => `${c.name} ${c.card_code} ${(c.aptitudes || []).join(" ")}`.toLowerCase().includes(term))
        : items;
    meta.textContent = shown.length + " Karten im Offline-Katalog";
    grid.innerHTML = shown.slice(0, 200).map(tile).join("") || "<p class='empty'>Kein Cache. Einmal online den Katalog öffnen.</p>";
}

async function boot() {
    try {
        const res = await fetch("/api/catalog.json");
        const data = await res.json();
        items = data.items || [];
        localStorage.setItem("pwtcg-catalog", JSON.stringify(items));
    } catch {
        try {
            items = JSON.parse(localStorage.getItem("pwtcg-catalog") || "[]");
        } catch {
            items = [];
        }
    }
    draw();
}

q.addEventListener("input", draw);
boot();
