/** Остатки товаров по складам и товарам */
let warehouseStockModal = null;
let productStockModal = null;
let warehouseStockRequestSeq = 0;
let productStockRequestSeq = 0;

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function resetWarehouseStockModal() {
    if (warehouseStockModal) {
        try {
            warehouseStockModal.hide();
            warehouseStockModal.dispose();
        } catch {
            /* ignore */
        }
    }
    warehouseStockModal = null;
}

function resetProductStockModal() {
    if (productStockModal) {
        try {
            productStockModal.hide();
            productStockModal.dispose();
        } catch {
            /* ignore */
        }
    }
    productStockModal = null;
}

function renderProductCell(p) {
    const offerId = escapeHtml(p.offer_id || "—");
    const name = escapeHtml(p.name || "—");
    const barcode = escapeHtml(p.barcode || "—");
    return `<td class="products-col-product">
        <div class="product-cell-title">${name}</div>
        <div class="product-cell-meta font-monospace">${offerId}</div>
        <div class="product-cell-meta font-monospace">${barcode}</div>
    </td>`;
}

function renderWarehouseModal(data) {
    const header = data.header || {};
    const titleEl = document.getElementById("warehouse-modal-title");
    const metaEl = document.getElementById("warehouse-modal-meta");
    const bodyEl = document.getElementById("warehouse-modal-body");

    if (titleEl) titleEl.textContent = header.warehouse_name || "—";
    if (metaEl) {
        metaEl.textContent = `Позиций: ${header.sku_count ?? 0} · Всего шт.: ${header.total_quantity ?? 0}`;
    }

    const products = data.products || [];
    let html = "";
    if (products.length) {
        html = `<div class="table-responsive">
            <table class="table table-sm order-modal-products-table align-middle mb-0">
                <thead><tr>
                    <th>Фото</th><th>Товар</th>
                    <th class="text-end">Доступно</th>
                    <th class="text-end">Резерв</th>
                    <th class="text-end">Всего</th>
                </tr></thead><tbody>`;
        html += products.map((p) => {
            const thumb = p.thumbnail_url
                ? `<img src="${escapeHtml(p.thumbnail_url)}" alt="" class="product-thumb" loading="lazy" referrerpolicy="no-referrer">`
                : `<span class="text-muted small">—</span>`;
            return `<tr>
                <td class="text-center">${thumb}</td>
                ${renderProductCell(p)}
                <td class="text-end text-nowrap">${p.free_to_sell}</td>
                <td class="text-end text-nowrap">${p.reserved}</td>
                <td class="text-end text-nowrap fw-semibold">${p.quantity}</td>
            </tr>`;
        }).join("");
        html += "</tbody></table></div>";
    } else {
        html = `<p class="text-muted mb-0">Нет товаров на складе.</p>`;
    }

    if (bodyEl) bodyEl.innerHTML = html;
}

function renderProductModal(data) {
    const header = data.header || {};
    const titleEl = document.getElementById("product-modal-title");
    const metaEl = document.getElementById("product-modal-meta");
    const thumbWrap = document.getElementById("product-modal-thumb-wrap");
    const bodyEl = document.getElementById("product-modal-body");

    if (titleEl) titleEl.textContent = header.name || "—";
    if (metaEl) {
        const parts = [
            header.offer_id && header.offer_id !== "—" ? `Артикул: ${header.offer_id}` : null,
            header.barcode && header.barcode !== "—" ? `Баркод: ${header.barcode}` : null,
            `Складов: ${header.warehouse_count ?? 0}`,
            `Всего шт.: ${header.total_quantity ?? 0}`,
        ].filter(Boolean);
        metaEl.textContent = parts.join(" · ");
    }
    if (thumbWrap) {
        if (header.thumbnail_url) {
            thumbWrap.classList.remove("d-none");
            thumbWrap.innerHTML = `<img src="${escapeHtml(header.thumbnail_url)}" alt="" class="product-thumb" loading="lazy" referrerpolicy="no-referrer">`;
        } else {
            thumbWrap.classList.add("d-none");
            thumbWrap.innerHTML = "";
        }
    }

    const warehouses = data.warehouses || [];
    let html = "";
    if (warehouses.length) {
        html = `<div class="table-responsive">
            <table class="table table-sm order-modal-products-table align-middle mb-0">
                <thead><tr>
                    <th>Склад</th>
                    <th class="text-end">Доступно</th>
                    <th class="text-end">Резерв</th>
                    <th class="text-end">Всего</th>
                </tr></thead><tbody>`;
        html += warehouses.map((w) => `<tr>
            <td>${escapeHtml(w.warehouse_name || "—")}</td>
            <td class="text-end text-nowrap">${w.free_to_sell}</td>
            <td class="text-end text-nowrap">${w.reserved}</td>
            <td class="text-end text-nowrap fw-semibold">${w.quantity}</td>
        </tr>`).join("");
        html += "</tbody></table></div>";
    } else {
        html = `<p class="text-muted mb-0">Нет остатков на складах.</p>`;
    }

    if (bodyEl) bodyEl.innerHTML = html;
}

async function openWarehouseStock(warehouseName) {
    const modalEl = document.getElementById("warehouse-stock-modal");
    const bodyEl = document.getElementById("warehouse-modal-body");
    if (!modalEl || !warehouseName) return;

    const seq = ++warehouseStockRequestSeq;
    warehouseStockModal = bootstrap.Modal.getOrCreateInstance(modalEl);

    if (bodyEl) {
        bodyEl.innerHTML = '<div class="text-center text-muted py-4">Загрузка...</div>';
    }
    warehouseStockModal.show();

    try {
        const url = `/api/reports/stocks/warehouse?warehouse_name=${encodeURIComponent(warehouseName)}`;
        const res = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
        const data = await res.json();
        if (seq !== warehouseStockRequestSeq) return;
        if (!data.ok) {
            if (bodyEl) {
                bodyEl.innerHTML = `<div class="alert alert-danger py-2 mb-0">${escapeHtml(data.error || "Ошибка")}</div>`;
            }
            return;
        }
        renderWarehouseModal(data);
    } catch (err) {
        if (seq !== warehouseStockRequestSeq) return;
        if (bodyEl) {
            bodyEl.innerHTML = `<div class="alert alert-danger py-2 mb-0">${escapeHtml(err.message)}</div>`;
        }
    }
}

async function openProductStock(productKey) {
    const modalEl = document.getElementById("product-stock-modal");
    const bodyEl = document.getElementById("product-modal-body");
    if (!modalEl || !productKey) return;

    const seq = ++productStockRequestSeq;
    productStockModal = bootstrap.Modal.getOrCreateInstance(modalEl);

    if (bodyEl) {
        bodyEl.innerHTML = '<div class="text-center text-muted py-4">Загрузка...</div>';
    }
    const thumbWrap = document.getElementById("product-modal-thumb-wrap");
    if (thumbWrap) {
        thumbWrap.classList.add("d-none");
        thumbWrap.innerHTML = "";
    }
    productStockModal.show();

    try {
        const url = `/api/reports/stocks/product?product_key=${encodeURIComponent(productKey)}`;
        const res = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
        const data = await res.json();
        if (seq !== productStockRequestSeq) return;
        if (!data.ok) {
            if (bodyEl) {
                bodyEl.innerHTML = `<div class="alert alert-danger py-2 mb-0">${escapeHtml(data.error || "Ошибка")}</div>`;
            }
            return;
        }
        renderProductModal(data);
    } catch (err) {
        if (seq !== productStockRequestSeq) return;
        if (bodyEl) {
            bodyEl.innerHTML = `<div class="alert alert-danger py-2 mb-0">${escapeHtml(err.message)}</div>`;
        }
    }
}

function initStockLinks() {
    const root = document.getElementById("main-content");
    if (!root || root.dataset.stockLinksBound === "1") return;
    root.dataset.stockLinksBound = "1";
    root.addEventListener("click", (e) => {
        const warehouseBtn = e.target.closest("[data-warehouse-name]");
        if (warehouseBtn && warehouseBtn.classList.contains("ozon-posting-link")) {
            e.preventDefault();
            const name = warehouseBtn.dataset.warehouseName;
            if (name) openWarehouseStock(name);
            return;
        }

        const productBtn = e.target.closest("[data-product-key]");
        if (productBtn && productBtn.classList.contains("stock-product-link")) {
            e.preventDefault();
            const key = productBtn.dataset.productKey;
            if (key) openProductStock(key);
        }
    });
}

function initStocksPage() {
    initStockLinks();

    const btn = document.getElementById("btn-load-stocks");
    if (!btn || btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";

    btn.addEventListener("click", async () => {
        const spinner = document.getElementById("stocks-load-spinner");
        const msgEl = document.getElementById("stocks-load-message");

        btn.disabled = true;
        if (spinner) spinner.classList.remove("d-none");

        try {
            const res = await fetch("/api/reports/stocks/load", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: "{}",
            });
            const contentType = res.headers.get("content-type") || "";
            if (!contentType.includes("application/json")) {
                throw new Error(
                    res.ok
                        ? "Сервер вернул неожиданный ответ"
                        : `Ошибка сервера (${res.status})`
                );
            }
            const data = await res.json();
            const variant = data.ok ? "success" : "danger";
            const text = data.message || data.error || "Ошибка загрузки";
            if (msgEl) {
                msgEl.innerHTML = `<div class="alert alert-${variant} py-2">${escapeHtml(text)}</div>`;
            }
            if (typeof showToast === "function") showToast(text, variant);
            if (data.ok && typeof loadPage === "function") {
                loadPage("/reports/stock", false);
            }
        } catch (err) {
            const text = `Ошибка: ${err.message}`;
            if (msgEl) {
                msgEl.innerHTML = `<div class="alert alert-danger py-2">${escapeHtml(text)}</div>`;
            }
            if (typeof showToast === "function") showToast(text, "danger");
        } finally {
            if (btn.dataset.hasOzon === "1") btn.disabled = false;
            if (spinner) spinner.classList.add("d-none");
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    const path = window.location.pathname.split("?")[0];
    if (path === "/reports/stock") initStocksPage();
});

document.addEventListener("page:loaded", (e) => {
    const path = (e.detail?.path || "").split("?")[0];
    if (path !== "/reports/stock") return;

    resetWarehouseStockModal();
    resetProductStockModal();
    warehouseStockRequestSeq += 1;
    productStockRequestSeq += 1;

    const root = document.getElementById("main-content");
    if (root) root.dataset.stockLinksBound = "";
    const btn = document.getElementById("btn-load-stocks");
    if (btn) btn.dataset.bound = "";
    initStocksPage();
});
