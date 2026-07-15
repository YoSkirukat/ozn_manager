/** Загрузка и отображение поставок FBO за период */
let shipmentsDatePicker = null;

function formatApiDate(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

function parseIsoDate(value) {
    if (!value) return null;
    const parts = value.split("-");
    if (parts.length !== 3) return null;
    const y = Number(parts[0]);
    const m = Number(parts[1]) - 1;
    const d = Number(parts[2]);
    const date = new Date(y, m, d);
    return Number.isNaN(date.getTime()) ? null : date;
}

function getUrlPeriod() {
    const params = new URLSearchParams(window.location.search);
    const from = params.get("from");
    const to = params.get("to");
    if (from && to) {
        return { from, to };
    }
    return { from: null, to: null };
}

function shipmentsPageUrl(from, to) {
    return `/shipments?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`;
}

function resizeShipmentsDateInput() {
    const input = document.getElementById("shipments-date-range");
    if (!input) return;
    const text = input.value || input.placeholder || "";
    const chars = Math.max(text.length, 12);
    input.style.width = `${Math.min(20, Math.max(11, chars * 0.62))}rem`;
}

function initShipmentsDatePicker() {
    const input = document.getElementById("shipments-date-range");
    if (!input || input.disabled || typeof flatpickr === "undefined") return;

    const urlPeriod = getUrlPeriod();
    const fromAttr = input.dataset.dateFrom;
    const toAttr = input.dataset.dateTo;
    const from = fromAttr || urlPeriod.from;
    const to = toAttr || urlPeriod.to;

    const defaultDates = [];
    const d1 = parseIsoDate(from);
    const d2 = parseIsoDate(to);
    if (d1 && d2) {
        defaultDates.push(d1, d2);
    }

    if (shipmentsDatePicker) {
        shipmentsDatePicker.destroy();
        shipmentsDatePicker = null;
    }

    shipmentsDatePicker = flatpickr(input, {
        mode: "range",
        dateFormat: "d.m.Y",
        locale: "ru",
        // Ozon заявки на поставку могут быть на будущие даты,
        // поэтому разрешаем выбор вперёд (UI, не бизнес-ограничения).
        maxDate: new Date(Date.now() + 365 * 24 * 60 * 60 * 1000),
        allowInput: false,
        defaultDate: defaultDates.length === 2 ? defaultDates : undefined,
        onChange() {
            resizeShipmentsDateInput();
        },
        onReady() {
            resizeShipmentsDateInput();
        },
    });
    resizeShipmentsDateInput();
}

let supplyDetailModal = null;
let supplyDetailRequestSeq = 0;

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function resetSupplyDetailModal() {
    if (supplyDetailModal) {
        try {
            supplyDetailModal.hide();
            supplyDetailModal.dispose();
        } catch {
            /* modal removed from DOM */
        }
    }
    supplyDetailModal = null;
}

function renderSupplyProductCell(p) {
    const offerId = escapeHtml(p.offer_id || "—");
    const name = escapeHtml(p.name || "—");
    const barcode = escapeHtml(p.barcode || "—");
    return `<td>
        <div class="order-modal-product-offer font-monospace fw-semibold">${offerId}</div>
        <div class="order-modal-product-meta">${name}</div>
        <div class="order-modal-product-meta">${barcode}</div>
    </td>`;
}

function renderSupplyModal(data) {
    const header = data.header || {};
    const numberEl = document.getElementById("supply-modal-number");
    const metaEl = document.getElementById("supply-modal-meta");
    const bodyEl = document.getElementById("supply-modal-body");

    if (numberEl) numberEl.textContent = header.order_number || "—";
    if (metaEl) {
        const statusClass = header.status_class || "default";
        metaEl.innerHTML = `${escapeHtml(header.supply_date || "—")} &middot; ` +
            `<span class="ozon-status-badge ozon-status-${statusClass}">${escapeHtml(header.status || "")}</span>`;
    }

    let infoHtml = `<div class="supply-modal-info mb-4">
        <div class="row g-2 small">
            <div class="col-sm-6"><span class="text-muted">Склад назначения:</span> ${escapeHtml(header.warehouse_name)}</div>
            <div class="col-sm-6"><span class="text-muted">Точка отгрузки:</span> ${escapeHtml(header.dropoff_warehouse)}</div>
            <div class="col-sm-6"><span class="text-muted">Товаров:</span> ${header.items_count ?? 0}</div>
            <div class="col-sm-6"><span class="text-muted">Единиц:</span> ${header.total_quantity ?? 0}</div>
        </div>
    </div>`;

    const products = data.products || [];
    let productsHtml = "";
    if (products.length) {
        productsHtml = `<div class="table-responsive">
            <table class="table table-sm order-modal-products-table align-middle mb-0">
                <thead><tr>
                    <th>Фото</th><th>Товар</th><th class="text-end">Кол-во</th>
                </tr></thead><tbody>`;
        productsHtml += products.map((p) => {
            const thumb = p.thumbnail_url
                ? `<img src="${escapeHtml(p.thumbnail_url)}" alt="" class="order-modal-thumb" loading="lazy" referrerpolicy="no-referrer">`
                : `<div class="order-modal-thumb-empty"></div>`;
            return `<tr>
                <td class="text-center">${thumb}</td>
                ${renderSupplyProductCell(p)}
                <td class="text-end text-nowrap fw-semibold">${p.quantity}</td>
            </tr>`;
        }).join("");
        productsHtml += "</tbody></table></div>";
    } else {
        productsHtml = `<p class="text-muted mb-0">Нет данных о товарах в поставке.</p>`;
    }

    if (bodyEl) bodyEl.innerHTML = infoHtml + productsHtml;
}

async function openSupplyDetail(shipmentId) {
    const modalEl = document.getElementById("supply-detail-modal");
    const bodyEl = document.getElementById("supply-modal-body");
    if (!modalEl || !shipmentId) return;

    const seq = ++supplyDetailRequestSeq;
    supplyDetailModal = bootstrap.Modal.getOrCreateInstance(modalEl);

    if (bodyEl) {
        bodyEl.innerHTML = '<div class="text-center text-muted py-4">Загрузка...</div>';
    }
    supplyDetailModal.show();

    try {
        const url = `/api/shipments/detail?shipment_id=${encodeURIComponent(shipmentId)}`;
        const res = await fetch(url, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const data = await res.json();
        if (seq !== supplyDetailRequestSeq) return;
        if (!data.ok) {
            if (bodyEl) {
                bodyEl.innerHTML = `<div class="alert alert-danger py-2 mb-0">${escapeHtml(data.error || "Ошибка загрузки")}</div>`;
            }
            return;
        }
        renderSupplyModal(data);
        if (data.header) {
            applyShipmentTotalsUpdates([
                {
                    id: Number(shipmentId),
                    sku_count: data.header.items_count,
                    units_total: data.header.total_quantity,
                },
            ]);
        }
    } catch (err) {
        if (seq !== supplyDetailRequestSeq) return;
        if (bodyEl) {
            bodyEl.innerHTML = `<div class="alert alert-danger py-2 mb-0">${escapeHtml(err.message)}</div>`;
        }
    }
}

function collectShipmentIdsNeedingTotals() {
    const ids = [];
    document.querySelectorAll(".ozon-order-row[data-shipment-row-id]").forEach((row) => {
        const id = row.dataset.shipmentRowId;
        const skuCell = row.querySelector(".shipment-sku-count");
        if (!id || !skuCell) return;
        const text = skuCell.textContent.trim();
        if (text === "—" || text === "0") {
            ids.push(Number(id));
        }
    });
    return ids;
}

function applyShipmentTotalsUpdates(updates) {
    for (const item of updates || []) {
        const skuCell = document.querySelector(`.shipment-sku-count[data-shipment-id="${item.id}"]`);
        const unitsCell = document.querySelector(`.shipment-units-total[data-shipment-id="${item.id}"]`);
        if (skuCell && item.sku_count != null) skuCell.textContent = String(item.sku_count);
        if (unitsCell && item.units_total != null) unitsCell.textContent = String(item.units_total);
    }
}

let shipmentsTotalsRefreshSeq = 0;

async function refreshShipmentsTotalsInBackground() {
    const btn = document.getElementById("btn-load-shipments");
    if (!btn || btn.dataset.hasOzon !== "1") return;

    const seq = ++shipmentsTotalsRefreshSeq;
    let pendingIds = collectShipmentIdsNeedingTotals();
    if (!pendingIds.length) return;

    while (pendingIds.length) {
        if (seq !== shipmentsTotalsRefreshSeq) return;

        try {
            const res = await fetch("/api/shipments/refresh-totals", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify({ shipment_ids: pendingIds }),
            });
            const data = await res.json();
            if (seq !== shipmentsTotalsRefreshSeq || !data.ok) return;

            applyShipmentTotalsUpdates(data.updates);
            if (!data.has_more) break;
            if (!data.updates?.length) break;
            pendingIds = collectShipmentIdsNeedingTotals();
        } catch {
            return;
        }
    }
}

function initShipmentDetailLinks() {
    const root = document.getElementById("main-content");
    if (!root || root.dataset.shipmentLinksBound === "1") return;
    root.dataset.shipmentLinksBound = "1";
    root.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-shipment-id]");
        if (!btn || !btn.classList.contains("ozon-posting-link")) return;
        e.preventDefault();
        const shipmentId = btn.dataset.shipmentId;
        if (shipmentId) openSupplyDetail(shipmentId);
    });
}

function openShipmentFromUrlParam() {
    const shipmentId = new URLSearchParams(window.location.search).get("shipment_id");
    if (shipmentId) openSupplyDetail(shipmentId);
}

function initShipmentsPage() {
    onShipmentsPageReady();
}

function onShipmentsPageReady() {
    initShipmentsDatePicker();
    initShipmentDetailLinks();
    openShipmentFromUrlParam();
    refreshShipmentsTotalsInBackground();

    const btn = document.getElementById("btn-load-shipments");
    if (!btn || btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";

    btn.addEventListener("click", async () => {
        const spinner = document.getElementById("shipments-load-spinner");
        const msgEl = document.getElementById("shipments-load-message");

        const dates = shipmentsDatePicker?.selectedDates || [];
        if (dates.length < 2) {
            const text = "Выберите период: дату начала и окончания.";
            if (msgEl) {
                msgEl.innerHTML = `<div class="alert alert-warning py-2">${text}</div>`;
            }
            if (typeof showToast === "function") showToast(text, "warning");
            return;
        }

        const dateFrom = formatApiDate(dates[0]);
        const dateTo = formatApiDate(dates[1]);

        btn.disabled = true;
        if (spinner) spinner.classList.remove("d-none");

        try {
            const res = await fetch("/api/shipments/load", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify({ date_from: dateFrom, date_to: dateTo }),
            });
            const data = await res.json();
            const variant = data.ok ? "success" : "danger";
            const text = data.message || data.error || "Ошибка загрузки";
            if (msgEl) {
                msgEl.innerHTML = `<div class="alert alert-${variant} py-2">${text}</div>`;
            }
            if (typeof showToast === "function") showToast(text, variant);
            if (data.ok && typeof loadPage === "function") {
                loadPage(shipmentsPageUrl(dateFrom, dateTo), true);
            }
        } catch (err) {
            const text = `Ошибка: ${err.message}`;
            if (msgEl) {
                msgEl.innerHTML = `<div class="alert alert-danger py-2">${text}</div>`;
            }
            if (typeof showToast === "function") showToast(text, "danger");
        } finally {
            if (btn.dataset.hasOzon === "1") btn.disabled = false;
            if (spinner) spinner.classList.add("d-none");
        }
    });
}

function syncShipmentsUrlFromDefaults() {
    const urlPeriod = getUrlPeriod();
    if (urlPeriod.from) return;

    const input = document.getElementById("shipments-date-range");
    const from = input?.dataset.dateFrom;
    const to = input?.dataset.dateTo;
    if (!from || !to) return;

    history.replaceState(null, "", shipmentsPageUrl(from, to));
}

document.addEventListener("DOMContentLoaded", () => {
    const path = window.location.pathname.split("?")[0];
    if (path !== "/shipments") return;

    syncShipmentsUrlFromDefaults();
    initShipmentsPage();
});

document.addEventListener("page:loaded", (e) => {
    const path = (e.detail?.path || "").split("?")[0];
    if (path !== "/shipments") return;

    resetSupplyDetailModal();
    supplyDetailRequestSeq += 1;
    shipmentsTotalsRefreshSeq += 1;

    syncShipmentsUrlFromDefaults();

    const btn = document.getElementById("btn-load-shipments");
    if (btn) btn.dataset.bound = "";
    initShipmentsPage();
});
