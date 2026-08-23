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
})();
