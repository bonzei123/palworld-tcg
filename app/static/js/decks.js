(function () {
const form = document.getElementById("new-deck");
const list = document.getElementById("deck-list");

form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = form.name.value.trim() || "Neues Deck";
    const res = await fetch("/api/decks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (data.id) location.href = "/decks/" + data.id;
});

list?.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-del]");
    if (!btn) return;
    if (!confirm("Deck löschen?")) return;
    await fetch("/api/decks/" + btn.dataset.del, { method: "DELETE" });
    location.reload();
});
})();
