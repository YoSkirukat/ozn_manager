/** Страница «Товары в акциях». */

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function initPromotionsPage() {
    const btn = document.getElementById("btn-refresh-promotions");
    if (btn && btn.dataset.bound !== "1") {
        btn.dataset.bound = "1";
        btn.addEventListener("click", () => {
            const spinner = document.getElementById("promotions-refresh-spinner");
            btn.disabled = true;
            if (spinner) spinner.classList.remove("d-none");
            if (typeof loadPage === "function") {
                loadPage("/analytics/promotions", false);
                return;
            }
            window.location.reload();
        });
    }

    const root = document.getElementById("promotions-page-root");
    if (!root || root.dataset.removeBound === "1") return;
    root.dataset.removeBound = "1";

    root.addEventListener("click", (event) => {
        const removeBtn = event.target.closest(".promotion-remove-btn");
        if (removeBtn) {
            event.preventDefault();
            removeProductFromPromotion(removeBtn);
        }
    });
}

async function removeProductFromPromotion(btn) {
    const actionId = btn.dataset.actionId;
    const productId = btn.dataset.productId;
    const productName = btn.dataset.productName || "товар";

    if (!actionId || !productId) return;

    const confirmed = window.confirm(`Удалить «${productName}» из акции?`);
    if (!confirmed) return;

    const row = btn.closest("[data-promotion-row]");
    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';

    try {
        const res = await fetch("/api/analytics/promotions/remove", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify({
                action_id: actionId,
                product_id: productId,
            }),
        });
        const data = await res.json();
        const text = data.message || data.error || (data.ok ? "Готово" : "Ошибка");
        if (typeof showToast === "function") {
            showToast(text, data.ok ? "success" : "danger");
        }

        if (data.ok) {
            if (typeof loadPage === "function") {
                loadPage("/analytics/promotions", false);
            } else {
                window.location.reload();
            }
            return;
        }

        btn.disabled = false;
        btn.innerHTML = originalHtml;
    } catch (err) {
        if (typeof showToast === "function") showToast(err.message, "danger");
        btn.disabled = false;
        btn.innerHTML = originalHtml;
        if (row) row.classList.remove("opacity-50");
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const path = window.location.pathname.split("?")[0];
    if (path === "/analytics/promotions") initPromotionsPage();
});

document.addEventListener("page:loaded", (e) => {
    const path = (e.detail?.path || "").split("?")[0];
    if (path !== "/analytics/promotions") return;

    const btn = document.getElementById("btn-refresh-promotions");
    const spinner = document.getElementById("promotions-refresh-spinner");
    const root = document.getElementById("promotions-page-root");
    if (btn) {
        btn.dataset.bound = "";
        btn.disabled = false;
    }
    if (spinner) spinner.classList.add("d-none");
    if (root) root.dataset.removeBound = "";
    initPromotionsPage();
});
