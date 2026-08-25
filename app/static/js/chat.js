(function () {
const root = document.getElementById("chat-root");
const panel = document.getElementById("chat-panel");
const toggle = document.getElementById("chat-toggle");
const closeBtn = document.getElementById("chat-close");
const expandBtn = document.getElementById("chat-expand");
const log = document.getElementById("chat-log");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");

const history = [];

function openChat() {
    panel.hidden = false;
    root.dataset.open = "true";
    toggle.setAttribute("aria-expanded", "true");
    input.focus();
}
function closeChat() {
    panel.hidden = true;
    root.dataset.open = "false";
    root.classList.remove("is-wide");
    toggle.setAttribute("aria-expanded", "false");
}

toggle.addEventListener("click", () => {
    if (panel.hidden) openChat();
    else closeChat();
    document.documentElement.classList.toggle("chat-open", !panel.hidden);
});
closeBtn.addEventListener("click", () => {
    closeChat();
    document.documentElement.classList.remove("chat-open");
});
expandBtn.addEventListener("click", () => root.classList.toggle("is-wide"));

function escHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (ch) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
    ));
}

function renderMarkdown(src) {
    const escaped = escHtml(src).replace(/\r\n/g, "\n");
    const fences = [];
    let text = escaped.replace(/```([\s\S]*?)```/g, (_, code) => {
        const i = fences.length;
        fences.push(`<pre><code>${code.replace(/^\n/, "")}</code></pre>`);
        return `\u0000F${i}\u0000`;
    });
    text = text.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    text = text.replace(/^###### (.*)$/gm, "<h6>$1</h6>");
    text = text.replace(/^##### (.*)$/gm, "<h5>$1</h5>");
    text = text.replace(/^#### (.*)$/gm, "<h4>$1</h4>");
    text = text.replace(/^### (.*)$/gm, "<h3>$1</h3>");
    text = text.replace(/^## (.*)$/gm, "<h2>$1</h2>");
    text = text.replace(/^# (.*)$/gm, "<h2>$1</h2>");
    text = text.replace(/^> (.*)$/gm, "<blockquote>$1</blockquote>");
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/__([^_]+)__/g, "<strong>$1</strong>");
    text = text.replace(/(^|[^\*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
    text = text.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    text = text.replace(/((?:^[\t ]*[-*] .+(?:\n|$))+)/gm, (block) => {
        const items = block.trim().split("\n").map((l) => `<li>${l.replace(/^[\t ]*[-*] /, "")}</li>`).join("");
        return `<ul>${items}</ul>`;
    });
    text = text.replace(/((?:^[\t ]*\d+\. .+(?:\n|$))+)/gm, (block) => {
        const items = block.trim().split("\n").map((l) => `<li>${l.replace(/^[\t ]*\d+\. /, "")}</li>`).join("");
        return `<ol>${items}</ol>`;
    });
    text = text.split(/\n{2,}/).map((block) => {
        const t = block.trim();
        if (!t) return "";
        if (/^<(h\d|ul|ol|pre|blockquote)/.test(t)) return t.replace(/\n/g, "");
        return `<p>${t.replace(/\n/g, "<br>")}</p>`;
    }).join("");
    return text.replace(/\u0000F(\d+)\u0000/g, (_, i) => fences[Number(i)]);
}

function linkCardCodes(html) {
    return html.replace(/(^|>)([^<]+)/g, (full, prefix, text) => {
        const linked = text.replace(/\b([A-Z]{2,}\d{2}-\d{3}[A-Z]*)\b/gi, (code) => (
            `<button type="button" class="card-code-link" data-card-code="${code.toUpperCase()}">${code}</button>`
        ));
        return prefix + linked;
    });
}

function addMsg(role, text, asMarkdown) {
    const el = document.createElement("div");
    el.className = "msg " + role;
    if (role === "bot" && asMarkdown) {
        el.classList.add("md");
        el.innerHTML = linkCardCodes(renderMarkdown(text));
    } else {
        el.textContent = text;
    }
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
}

form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    addMsg("user", message, false);
    history.push({ role: "user", content: message });
    const send = document.getElementById("chat-send");
    send.disabled = true;
    const pending = addMsg("bot", "Denke nach…", false);
    try {
        const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message, history: history.slice(0, -1) }),
        });
        const data = await res.json();
        if (!data.ok) {
            pending.classList.add("err");
            pending.textContent = data.error || "Fehler";
            history.pop();
        } else {
            let body = data.text || "";
            if (data.cached) body += "\n\n*(Cache — kein Tokenverbrauch)*";
            pending.classList.add("md");
            pending.innerHTML = linkCardCodes(renderMarkdown(body));
            history.push({ role: "model", content: data.text });
        }
    } catch (err) {
        pending.classList.add("err");
        pending.textContent = "Netzwerkfehler";
        history.pop();
    } finally {
        send.disabled = false;
        log.scrollTop = log.scrollHeight;
    }
});

input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        form.requestSubmit();
    }
});
})();
