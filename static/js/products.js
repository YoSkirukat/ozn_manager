/** Синхронизация товаров с Ozon и модалка комиссий FBO/FBS */

let productCommissionModal = null;
let productCommissionRequestSeq = 0;

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function formatMoneyAmount(value) {
    const text = Number(value).toLocaleString("ru-RU", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
    return text.replace(/\u00A0|\u202F/g, " ");
}

function formatMoney(value) {
    return `${formatMoneyAmount(value)} ₽`;
}

function formatMoneyText(text) {
    const raw = String(text ?? "").trim();
    if (!raw) return "—";
    for (const sep of ["–", "-", "—"]) {
        if (!raw.includes(sep)) continue;
        const parts = raw.split(sep).map((part) => part.trim());
        if (parts.length === 2) {
            return `${formatMoneyAmount(parts[0])} – ${formatMoneyAmount(parts[1])} ₽`;
        }
    }
    return formatMoney(raw);
}

function resetProductCommissionModal() {
    if (productCommissionModal) {
        try {
            productCommissionModal.hide();
            productCommissionModal.dispose();
        } catch {
            /* modal removed from DOM */
        }
    }
    productCommissionModal = null;
}

function renderProductCommissionModal(data) {
    const titleEl = document.getElementById("productCommissionModalLabel");
    const metaEl = document.getElementById("product-commission-modal-meta");
    const bodyEl = document.getElementById("product-commission-modal-body");
    const header = data.header || {};
    const schemeLabel = data.scheme_label || (data.scheme === "fbo" ? "FBO" : "FBS");
    const schemeClass = data.scheme === "fbo" ? "fbo" : "fbs";

    if (titleEl) {
        titleEl.textContent = `Комиссия ${schemeLabel}`;
    }
    if (metaEl) {
        const offer = escapeHtml(header.offer_id || "—");
        const name = escapeHtml(header.name || "—");
        const price = header.price != null ? formatMoney(header.price) : "—";
        metaEl.innerHTML =
            `<span class="ozon-scheme ozon-scheme-${schemeClass}">${escapeHtml(schemeLabel)}</span>` +
            ` &middot; <span class="font-monospace">${offer}</span> &middot; ${name}` +
            ` &middot; цена: ${price}`;
    }

    const rows = data.rows || [];
    let html = "";
    if (rows.length) {
        html = `<div class="table-responsive">
            <table class="table table-sm product-commission-table align-middle mb-0">
                <thead><tr>
                    <th>Составляющая</th>
                    <th class="text-end">Сумма</th>
                </tr></thead><tbody>`;
        html += rows.map((row) => {
            const hint = row.hint
                ? `<div class="small text-muted">${escapeHtml(row.hint)}</div>`
                : "";
            const percent = row.percent != null
                ? `<span class="text-muted small ms-1">(${escapeHtml(String(row.percent))}%)</span>`
                : "";
            const amountCell = row.amount_display
                ? formatMoneyText(row.amount_display)
                : formatMoney(row.amount);
            return `<tr>
                <td>
                    <div>${escapeHtml(row.label)}${percent}</div>
                    ${hint}
                </td>
                <td class="text-end text-nowrap fw-semibold">${amountCell}</td>
            </tr>`;
        }).join("");
        const totalCell = data.total_display
            ? formatMoneyText(data.total_display)
            : formatMoney(data.total_max ?? data.total ?? 0);
        html += `<tr class="product-commission-total-row">
                <td class="fw-semibold">
                    <div>Итого</div>
                    <div class="product-commission-total-note">Без учёта возвратов</div>
                </td>
                <td class="text-end text-nowrap fw-bold">${totalCell}</td>
            </tr>`;
        html += "</tbody></table></div>";
    } else {
        html = '<p class="text-muted mb-0">Нет данных для расшифровки.</p>';
    }

    if (bodyEl) bodyEl.innerHTML = html;
}

async function openProductCommission(productId, scheme, salePrice) {
    const modalEl = document.getElementById("product-commission-modal");
    const bodyEl = document.getElementById("product-commission-modal-body");
    if (!modalEl || !productId || !scheme) return;

    const seq = ++productCommissionRequestSeq;
    productCommissionModal = bootstrap.Modal.getOrCreateInstance(modalEl);

    if (bodyEl) {
        bodyEl.innerHTML = '<div class="text-center text-muted py-4">Загрузка…</div>';
    }
    productCommissionModal.show();

    try {
        let url = `/api/products/${encodeURIComponent(productId)}/commission?scheme=${encodeURIComponent(scheme)}`;
        if (salePrice != null && salePrice !== "") {
            url += `&sale_price=${encodeURIComponent(salePrice)}`;
        }
        const res = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
        const data = await res.json();
        if (seq !== productCommissionRequestSeq) return;

        if (!data.ok) {
            const err = escapeHtml(data.error || "Не удалось загрузить комиссию");
            if (bodyEl) {
                bodyEl.innerHTML = `<div class="alert alert-warning mb-0">${err}</div>`;
            }
            return;
        }
        renderProductCommissionModal(data);
    } catch (err) {
        if (seq !== productCommissionRequestSeq) return;
        if (bodyEl) {
            bodyEl.innerHTML =
                `<div class="alert alert-danger mb-0">${escapeHtml(err.message)}</div>`;
        }
    }
}

function bindProductCommissionButtons(root) {
    const scope = root || document;
    scope.querySelectorAll(".product-commission-btn").forEach((btn) => {
        if (btn.dataset.bound === "1") return;
        btn.dataset.bound = "1";
        btn.addEventListener("click", () => {
            const productId = btn.dataset.productId;
            const scheme = btn.dataset.scheme;
            const salePrice = btn.dataset.salePrice;
            openProductCommission(productId, scheme, salePrice);
        });
    });
}

function initProductsPage() {
    const btn = document.getElementById("btn-sync-ozon");
    if (btn && btn.dataset.bound !== "1") {
        btn.dataset.bound = "1";
        btn.addEventListener("click", async () => {
            const spinner = document.getElementById("sync-spinner");
            const msgEl = document.getElementById("products-sync-message");
            btn.disabled = true;
            if (spinner) spinner.classList.remove("d-none");

            try {
                const res = await fetch("/api/products/sync", {
                    method: "POST",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                });
                const data = await res.json();
                const variant = data.ok ? "success" : "danger";
                const text = data.message || data.error || "Ошибка синхронизации";
                if (msgEl) {
                    msgEl.innerHTML = `<div class="alert alert-${variant} py-2">${text}</div>`;
                }
                if (typeof showToast === "function") {
                    showToast(text, variant);
                }
                if (data.ok && typeof loadPage === "function") {
                    loadPage("/products", false);
                }
            } catch (err) {
                const text = `Ошибка: ${err.message}`;
                if (msgEl) {
                    msgEl.innerHTML = `<div class="alert alert-danger py-2">${text}</div>`;
                }
                if (typeof showToast === "function") {
                    showToast(text, "danger");
                }
            } finally {
                if (btn.dataset.hasOzon === "1") {
                    btn.disabled = false;
                }
                if (spinner) spinner.classList.add("d-none");
            }
        });
    }

    bindProductCommissionButtons(document);

    const commissionModalEl = document.getElementById("product-commission-modal");
    if (commissionModalEl && commissionModalEl.dataset.bound !== "1") {
        commissionModalEl.dataset.bound = "1";
        commissionModalEl.addEventListener("hidden.bs.modal", resetProductCommissionModal);
    }
}

document.addEventListener("DOMContentLoaded", initProductsPage);
document.addEventListener("page:loaded", (e) => {
    if (e.detail?.path === "/products") {
        initProductsPage();
    }
});
