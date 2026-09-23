/** Ручная загрузка файла с закупочными ценами на странице профиля */

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function initProfileExternalUpload() {
    const btn = document.getElementById("btn-upload-purchase-prices");
    const fileInput = document.getElementById("purchase-prices-file-input");
    const msgEl = document.getElementById("purchase-prices-upload-message");
    if (!btn || !fileInput || btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";

    btn.addEventListener("click", () => {
        fileInput.click();
    });

    fileInput.addEventListener("change", async () => {
        const file = fileInput.files && fileInput.files[0];
        fileInput.value = "";
        if (!file) return;

        btn.disabled = true;
        if (msgEl) {
            msgEl.innerHTML = '<div class="text-muted small">Загрузка файла…</div>';
        }

        try {
            const formData = new FormData();
            formData.append("file", file);
            const res = await fetch("/api/products/purchase-prices/upload", {
                method: "POST",
                headers: { "X-Requested-With": "XMLHttpRequest" },
                body: formData,
            });
            const data = await res.json();
            const variant = data.ok ? "success" : "danger";
            const text = data.message || data.error || "Ошибка загрузки";
            if (msgEl) {
                msgEl.innerHTML = `<div class="alert alert-${variant} py-2 mb-0">${escapeHtml(text)}</div>`;
            }
            if (typeof showToast === "function") {
                showToast(text, variant);
            }
        } catch (err) {
            const text = `Ошибка: ${err.message}`;
            if (msgEl) {
                msgEl.innerHTML = `<div class="alert alert-danger py-2 mb-0">${text}</div>`;
            }
            if (typeof showToast === "function") {
                showToast(text, "danger");
            }
        } finally {
            btn.disabled = false;
        }
    });
}

/** Профиль: остатки FBS по складам (добавление и удаление строк) */

function syncFbsStockSourceRow(row) {
    if (!row) return;
    const select = row.querySelector(".fbs-stock-source-select");
    if (!select) return;

    const nameInput = row.querySelector(".fbs-stock-source-name");
    if (nameInput) {
        const option = select.selectedOptions && select.selectedOptions[0];
        nameInput.value = option ? option.dataset.warehouseName || "" : "";
    }

    const urlWrap = row.querySelector(".fbs-stock-source-url-field");
    const urlInput = row.querySelector(".fbs-stock-source-url");
    if (urlWrap) {
        // Пока склад не выбран, поле ссылки у новой строки скрыто.
        const hasUrl = Boolean(urlInput && urlInput.value.trim());
        urlWrap.classList.toggle("is-hidden", !select.value && !hasUrl);
    }
}

function refreshFbsWarehouseOptions() {
    const container = document.getElementById("fbs-stock-sources");
    if (!container) return;

    const selects = Array.from(container.querySelectorAll(".fbs-stock-source-select"));
    const used = new Set(selects.map((select) => select.value).filter(Boolean));

    selects.forEach((select) => {
        Array.from(select.options).forEach((option) => {
            if (!option.value) {
                option.disabled = false;
                return;
            }
            option.disabled = used.has(option.value) && option.value !== select.value;
        });
    });
}

function initFbsStockSources() {
    const container = document.getElementById("fbs-stock-sources");
    const addBtn = document.getElementById("btn-add-fbs-warehouse");
    const template = document.getElementById("fbs-stock-source-template");
    if (!container || !addBtn || !template || addBtn.dataset.bound === "1") return;
    addBtn.dataset.bound = "1";

    addBtn.addEventListener("click", () => {
        const row = template.content.firstElementChild.cloneNode(true);
        container.appendChild(row);
        syncFbsStockSourceRow(row);
        refreshFbsWarehouseOptions();
        const select = row.querySelector(".fbs-stock-source-select");
        if (select) select.focus();
    });

    container.addEventListener("change", (event) => {
        const select = event.target.closest(".fbs-stock-source-select");
        if (!select) return;
        syncFbsStockSourceRow(select.closest(".fbs-stock-source-row"));
        refreshFbsWarehouseOptions();
    });

    container.addEventListener("click", (event) => {
        const btn = event.target.closest(".fbs-stock-source-remove");
        if (!btn) return;
        const row = btn.closest(".fbs-stock-source-row");
        if (!row) return;
        row.remove();
        refreshFbsWarehouseOptions();
    });

    container.querySelectorAll(".fbs-stock-source-row").forEach(syncFbsStockSourceRow);
    refreshFbsWarehouseOptions();
}

document.addEventListener("DOMContentLoaded", () => {
    initProfileExternalUpload();
    initFbsStockSources();
});
