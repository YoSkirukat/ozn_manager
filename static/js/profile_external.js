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

document.addEventListener("DOMContentLoaded", initProfileExternalUpload);
