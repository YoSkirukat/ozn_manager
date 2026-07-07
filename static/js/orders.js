/** Загрузка и отображение заказов за период */
let ordersDatePicker = null;
let ordersFinancialsConfirmModal = null;

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

function getOrdersFiltersFromDom() {
    const status = [...document.querySelectorAll(".orders-filter-status:checked")].map((el) => el.value);
    const scheme = [...document.querySelectorAll(".orders-filter-scheme:checked")].map((el) => el.value);
    const delivery = document.querySelector(".orders-filter-delivery:checked")?.value || "";
    return { status, scheme, delivery };
}

function filterCheckboxLabel(input) {
    const text = input.closest(".orders-filter-item")?.textContent?.trim() || "";
    return text.replace(/\s+/g, " ").trim();
}

function buildOrdersPageUrl(from, to, filters = null) {
    const f = filters || getOrdersFiltersFromDom();
    const params = new URLSearchParams();
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    if (from && to) {
        params.set("status", (f.status || []).join(","));
        params.set("scheme", (f.scheme || []).join(","));
        params.set("delivery", f.delivery || "");
    }
    const query = params.toString();
    return query ? `/orders?${query}` : "/orders";
}

function setFilterControlState(kind, checkedCount, labelText) {
    const labelEl = document.getElementById(`orders-filter-${kind}-label`);
    const clearBtn = document.getElementById(`orders-filter-${kind}-clear`);
    const toggleBtn = document.getElementById(`orders-filter-${kind}-btn`);
    const active = checkedCount > 0;

    if (labelEl) labelEl.textContent = labelText;
    if (clearBtn) clearBtn.classList.toggle("d-none", !active);
    if (toggleBtn) toggleBtn.classList.toggle("orders-filter-btn--active", active);
}

function updateOrdersFilterButtons() {
    const statusChecked = [...document.querySelectorAll(".orders-filter-status:checked")];
    let statusLabel = "Все статусы";
    if (statusChecked.length === 1) {
        statusLabel = filterCheckboxLabel(statusChecked[0]) || statusChecked[0].value;
    } else if (statusChecked.length > 1) {
        statusLabel = `Статусы (${statusChecked.length})`;
    }
    setFilterControlState("status", statusChecked.length, statusLabel);

    const schemeChecked = [...document.querySelectorAll(".orders-filter-scheme:checked")];
    let schemeLabel = "Все схемы";
    if (schemeChecked.length === 1) {
        schemeLabel = filterCheckboxLabel(schemeChecked[0]) || schemeChecked[0].value;
    } else if (schemeChecked.length > 1) {
        schemeLabel = `Схемы (${schemeChecked.length})`;
    }
    setFilterControlState("scheme", schemeChecked.length, schemeLabel);

    const deliveryValue = document.querySelector(".orders-filter-delivery:checked")?.value || "";
    let deliveryLabel = "Все заказы";
    if (deliveryValue === "local") {
        deliveryLabel = "Локальные";
    } else if (deliveryValue === "international") {
        deliveryLabel = "Международные";
    }
    setFilterControlState("delivery", deliveryValue ? 1 : 0, deliveryLabel);
}

function resetOrdersFilter(kind) {
    if (kind === "delivery") {
        const allRadio = document.querySelector('.orders-filter-delivery[value=""]');
        if (allRadio) allRadio.checked = true;
    } else {
        document.querySelectorAll(`.orders-filter-${kind}`).forEach((input) => {
            input.checked = false;
        });
    }
    updateOrdersFilterButtons();
    applyOrdersFilters();
}

function getOrdersPeriodForUrl() {
    const urlPeriod = getUrlPeriod();
    if (urlPeriod.from && urlPeriod.to) {
        return urlPeriod;
    }
    const input = document.getElementById("orders-date-range");
    if (!input) return { from: null, to: null };
    return {
        from: input.dataset.dateFrom || null,
        to: input.dataset.dateTo || null,
    };
}

function applyOrdersFilters() {
    const { from, to } = getOrdersPeriodForUrl();
    if (!from || !to || typeof loadPage !== "function") return;
    loadPage(buildOrdersPageUrl(from, to, getOrdersFiltersFromDom()), true);
}

function downloadOrdersExport(exportType) {
    const { from, to } = getOrdersPeriodForUrl();
    if (!from || !to) {
        window.alert("Выберите период на странице заказов.");
        return;
    }
    const filters = getOrdersFiltersFromDom();
    const params = new URLSearchParams({
        type: exportType,
        from,
        to,
        status: (filters.status || []).join(","),
        scheme: (filters.scheme || []).join(","),
        delivery: filters.delivery || "",
    });
    window.location.assign(`/api/orders/export?${params}`);
}

function initOrdersExport() {
    const root = document.getElementById("orders-export-dropdown");
    if (!root || root.dataset.bound === "1") return;
    root.dataset.bound = "1";
    root.querySelectorAll("[data-export-type]").forEach((btn) => {
        btn.addEventListener("click", () => {
            downloadOrdersExport(btn.dataset.exportType);
        });
    });
}

function resizeOrdersDateInput() {
    const input = document.getElementById("orders-date-range");
    if (!input) return;
    const text = input.value || input.placeholder || "";
    const chars = Math.max(text.length, 12);
    input.style.width = `${Math.min(20, Math.max(11, chars * 0.62))}rem`;
}

/** Синхронизирует URL с периодом и фильтрами с сервера, без повторной загрузки. */
function syncOrdersUrlFromToolbar() {
    const params = new URLSearchParams(window.location.search);
    const hasPeriod = params.has("from") && params.has("to");
    const hasFilters = params.has("status") && params.has("scheme") && params.has("delivery");
    if (hasPeriod && hasFilters) return;

    const toolbar = document.getElementById("orders-toolbar");
    if (!toolbar) return;

    const from = toolbar.dataset.dateFrom;
    const to = toolbar.dataset.dateTo;
    if (!from || !to) return;

    const status = (toolbar.dataset.status || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    const scheme = (toolbar.dataset.scheme || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    const delivery = toolbar.dataset.delivery || "";

    history.replaceState(
        history.state,
        "",
        buildOrdersPageUrl(from, to, { status, scheme, delivery }),
    );
}

function initOrdersFilters() {
    const statusMenu = document.getElementById("orders-filter-status-menu");
    const schemeMenu = document.getElementById("orders-filter-scheme-menu");
    const deliveryMenu = document.getElementById("orders-filter-delivery-menu");
    [statusMenu, schemeMenu, deliveryMenu].forEach((menu) => {
        if (!menu || menu.dataset.bound === "1") return;
        menu.dataset.bound = "1";
        menu.addEventListener("click", (e) => e.stopPropagation());
    });

    document.querySelectorAll(".orders-filter-status, .orders-filter-scheme").forEach((input) => {
        if (input.dataset.bound === "1") return;
        input.dataset.bound = "1";
        input.addEventListener("change", () => {
            updateOrdersFilterButtons();
            applyOrdersFilters();
        });
    });

    document.querySelectorAll(".orders-filter-delivery").forEach((input) => {
        if (input.dataset.bound === "1") return;
        input.dataset.bound = "1";
        input.addEventListener("change", () => {
            updateOrdersFilterButtons();
            applyOrdersFilters();
        });
    });

    document.querySelectorAll(".orders-filter-clear").forEach((el) => {
        if (el.dataset.bound === "1") return;
        el.dataset.bound = "1";
        el.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            const kind = el.dataset.filterKind;
            if (kind) resetOrdersFilter(kind);
        });
        el.addEventListener("mousedown", (e) => e.stopPropagation());
    });

    updateOrdersFilterButtons();
}

function initOrdersDatePicker() {
    const input = document.getElementById("orders-date-range");
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

    if (ordersDatePicker) {
        ordersDatePicker.destroy();
        ordersDatePicker = null;
    }

    ordersDatePicker = flatpickr(input, {
        mode: "range",
        dateFormat: "d.m.Y",
        locale: "ru",
        maxDate: "today",
        allowInput: false,
        defaultDate: defaultDates.length === 2 ? defaultDates : undefined,
        onChange() {
            resizeOrdersDateInput();
        },
        onReady() {
            resizeOrdersDateInput();
        },
    });
    resizeOrdersDateInput();
}

let orderDetailModal = null;
let orderDetailRequestSeq = 0;

function resetOrderDetailModal() {
    if (orderDetailModal) {
        try {
            orderDetailModal.hide();
            orderDetailModal.dispose();
        } catch {
            /* modal already removed from DOM */
        }
    }
    orderDetailModal = null;
}

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function currencySymbol(code) {
    const normalized = String(code || "RUB").toUpperCase();
    const symbols = {
        RUB: "₽",
        BYN: "BYN",
        KZT: "₸",
        USD: "$",
        EUR: "€",
    };
    return symbols[normalized] || normalized;
}

function formatMoney(value, currencyCode = "RUB") {
    const symbol = currencySymbol(currencyCode);
    return `${Number(value).toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${symbol}`;
}

function renderProductCell(p) {
    const offerId = escapeHtml(p.offer_id || "—");
    const name = escapeHtml(p.name || "—");
    const barcode = escapeHtml(p.barcode || "—");
    return `<td>
        <div class="order-modal-product-offer font-monospace fw-semibold">${offerId}</div>
        <div class="order-modal-product-meta">${name}</div>
        <div class="order-modal-product-meta">${barcode}</div>
    </td>`;
}

function renderOrderPromotionsBlock(products) {
    const titles = [];
    (products || []).forEach((p) => {
        const promoTitles = Array.isArray(p.promotion_titles) ? p.promotion_titles : [];
        if (!p.in_promotion || !promoTitles.length) {
            return;
        }
        promoTitles.forEach((title) => {
            const text = String(title || "").trim();
            if (text && !titles.includes(text)) {
                titles.push(text);
            }
        });
    });
    if (!titles.length) {
        return "";
    }

    let html = '<div class="order-modal-promotions mb-4">';
    html += '<h6 class="mb-2">Акции</h6><div class="order-modal-promotions-list">';
    titles.forEach((title) => {
        const safeTitle = escapeHtml(title);
        html += `<div class="product-promo-tag order-modal-promo-item" title="${safeTitle}">
            <span class="product-promo-mark" aria-hidden="true">А</span>
            <span class="product-promo-name">${safeTitle}</span>
        </div>`;
    });
    html += "</div></div>";
    return html;
}

function renderClustersBlock(clusters) {
    if (!clusters || (!clusters.cluster_from && !clusters.cluster_to)) {
        return "";
    }
    let html = '<div class="order-modal-clusters mb-4">';
    if (clusters.cluster_from) {
        html += `<div class="order-modal-cluster-row">
            <span class="order-modal-cluster-label">Кластер отправления</span>
            <span class="order-modal-cluster-value">${escapeHtml(clusters.cluster_from)}</span>
        </div>`;
    }
    if (clusters.cluster_to) {
        html += `<div class="order-modal-cluster-row">
            <span class="order-modal-cluster-label">Кластер доставки</span>
            <span class="order-modal-cluster-value">${escapeHtml(clusters.cluster_to)}</span>
        </div>`;
    }
    html += "</div>";
    return html;
}

function renderOrderModal(data) {
    const header = data.header || {};
    const numberEl = document.getElementById("order-modal-number");
    const metaEl = document.getElementById("order-modal-meta");
    const bodyEl = document.getElementById("order-modal-body");

    if (numberEl) numberEl.textContent = header.posting_number || "—";
    if (metaEl) {
        const scheme = header.scheme || "";
        const schemeClass = header.scheme_class || "fbs";
        const returnMark = header.has_post_delivery_return
            ? ' <span class="product-return-mark product-return-mark--inline" title="Возврат после доставки" aria-label="Возврат после доставки">В</span>'
            : "";
        metaEl.innerHTML = `${escapeHtml(header.order_date || "—")} &middot; ` +
            `<span class="ozon-scheme ozon-scheme-${schemeClass}">${escapeHtml(scheme)}</span>` +
            (header.status ? ` &middot; ${escapeHtml(header.status)}${returnMark}` : "") +
            (header.delivery_country ? ` &middot; ${escapeHtml(header.delivery_country)}` : "") +
            (header.is_international ? ' &middot; <span class="text-warning-emphasis">Международный заказ</span>' : "");
    }

    const hideMargin = Boolean(header.has_post_delivery_return);

    const products = data.products || [];
    let productsHtml = "";
    if (products.length) {
        productsHtml = `<div class="table-responsive mb-4">
            <table class="table table-sm order-modal-products-table align-middle mb-0">
                <thead><tr>
                    <th>Фото</th><th>Товар</th><th class="text-end">Цена</th>
                    <th class="text-end">Цена закуп.</th><th class="text-end">Маржа</th>
                    <th class="text-end">Цена покупки (валюта оплаты)</th>
                    <th class="text-end">Цена покупки в руб.</th>
                </tr></thead><tbody>`;
        productsHtml += products.map((p) => {
            const thumb = p.thumbnail_url
                ? `<img src="${escapeHtml(p.thumbnail_url)}" alt="" class="order-modal-thumb" loading="lazy" referrerpolicy="no-referrer">`
                : `<div class="order-modal-thumb-empty"></div>`;
            return `<tr>
                <td class="text-center">${thumb}</td>
                ${renderProductCell(p)}
                <td class="text-end text-nowrap">${formatMoney(p.price, p.currency_code || "RUB")}</td>
                <td class="text-end text-nowrap">${
                    p.purchase_price != null ? formatMoney(p.purchase_price) : "—"
                }</td>
                <td class="text-end text-nowrap">${hideMargin ? '<span class="text-muted">—</span>' : renderMarginCell(p.margin)}</td>
                <td class="text-end text-nowrap">${
                    p.customer_price != null
                        ? formatMoney(p.customer_price, p.customer_currency_code || p.currency_code || "RUB")
                        : "—"
                }</td>
                <td class="text-end text-nowrap">${
                    p.customer_price_rub != null ? formatMoney(p.customer_price_rub, "RUB") : "—"
                }</td>
            </tr>`;
        }).join("");
        productsHtml += "</tbody></table></div>";
        productsHtml += renderOrderPromotionsBlock(products);
    } else {
        productsHtml = `<p class="text-muted">Нет данных о товарах.</p>`;
    }

    const clustersHtml = renderClustersBlock(data.clusters);
    const accrualsHtml = renderAccrualsBlock(data);
    if (bodyEl) {
        bodyEl.innerHTML = productsHtml + clustersHtml + accrualsHtml;
        initAccrualToggles(bodyEl);
    }
}

function renderAccrualAmount(row) {
    const cls = row.negative ? "order-accrual-negative" : "";
    const sign = row.negative ? "−" : "";
    return `<span class="${cls}">${sign}${formatMoney(row.amount)}</span>`;
}

function renderMarginCell(value) {
    if (value == null) {
        return '<span class="text-muted">—</span>';
    }
    const amount = Number(value);
    const cls = amount < 0 ? "order-accrual-negative" : "";
    const sign = amount < 0 ? "−" : "";
    return `<span class="${cls}">${sign}${formatMoney(Math.abs(amount))}</span>`;
}

function renderAccrualsBlock(data) {
    const accruals = data.accruals || [];
    const marginHint = data.header?.is_international
        ? '<div class="small text-muted mb-2">Для международного заказа маржа считается как: цена покупки в RUB − цена закуп.</div>'
        : "";
    let html = `<h6 class="mb-3">Начисления</h6>
        ${marginHint}
        <table class="table table-sm order-accruals-table mb-0">
        <thead><tr>
            <th>Дата</th><th>Тип операции</th><th class="text-end">Сумма</th>
        </tr></thead><tbody>`;

    accruals.forEach((row, idx) => {
        if (row.type === "group") {
            const groupId = `accrual-group-${idx}`;
            const expanded = row.expanded !== false;
            html += `<tr class="order-accrual-group-header">
                <td class="text-muted small">${escapeHtml(row.date || "—")}</td>
                <td>
                    <button type="button" class="order-accrual-toggle btn btn-link p-0"
                            data-group="${groupId}" aria-expanded="${expanded}">
                        <span class="order-accrual-chevron">${expanded ? "▾" : "▸"}</span>
                        ${escapeHtml(row.label)}
                    </button>
                </td>
                <td class="text-end text-nowrap">${renderAccrualAmount(row)}</td>
            </tr>`;
            (row.items || []).forEach((item) => {
                html += `<tr class="order-accrual-detail${expanded ? "" : " d-none"}"
                    data-group="${groupId}">
                    <td></td>
                    <td class="order-accrual-detail-label">${escapeHtml(item.label)}</td>
                    <td class="text-end text-nowrap">${renderAccrualAmount(item)}</td>
                </tr>`;
            });
            return;
        }
        html += `<tr>
            <td class="text-muted small">${escapeHtml(row.date || "—")}</td>
            <td>${escapeHtml(row.label)}</td>
            <td class="text-end text-nowrap">${renderAccrualAmount(row)}</td>
        </tr>`;
    });

    html += `<tr class="order-accrual-total">
        <td colspan="2">Итого начислено</td>
        <td class="text-end text-nowrap">${formatMoney(data.total_accrued || 0)}</td>
    </tr>`;
    html += "</tbody></table>";
    return html;
}

function initAccrualToggles(root) {
    if (!root) return;
    root.querySelectorAll(".order-accrual-toggle").forEach((btn) => {
        if (btn.dataset.bound === "1") return;
        btn.dataset.bound = "1";
        btn.addEventListener("click", () => {
            const groupId = btn.dataset.group;
            const expanded = btn.getAttribute("aria-expanded") === "true";
            const next = !expanded;
            btn.setAttribute("aria-expanded", next ? "true" : "false");
            const chevron = btn.querySelector(".order-accrual-chevron");
            if (chevron) chevron.textContent = next ? "▾" : "▸";
            root.querySelectorAll(`tr.order-accrual-detail[data-group="${groupId}"]`).forEach((tr) => {
                tr.classList.toggle("d-none", !next);
            });
        });
    });
}

async function openOrderDetail(postingNumber) {
    const modalEl = document.getElementById("order-detail-modal");
    const bodyEl = document.getElementById("order-modal-body");
    if (!modalEl || !postingNumber) return;

    const seq = ++orderDetailRequestSeq;
    orderDetailModal = bootstrap.Modal.getOrCreateInstance(modalEl);

    if (bodyEl) {
        bodyEl.innerHTML = '<div class="text-center text-muted py-4">Загрузка...</div>';
    }
    orderDetailModal.show();

    try {
        const url = `/api/orders/detail?posting_number=${encodeURIComponent(postingNumber)}&refresh=0`;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000);
        const res = await fetch(url, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
            signal: controller.signal,
        });
        clearTimeout(timeoutId);
        const data = await res.json();
        if (seq !== orderDetailRequestSeq) return;
        if (!data.ok) {
            if (bodyEl) {
                bodyEl.innerHTML = `<div class="alert alert-danger py-2 mb-0">${escapeHtml(data.error || "Ошибка загрузки")}</div>`;
            }
            return;
        }
        renderOrderModal(data);
    } catch (err) {
        if (seq !== orderDetailRequestSeq) return;
        if (bodyEl) {
            const message = err.name === "AbortError"
                ? "Превышено время ожидания. Попробуйте ещё раз."
                : err.message;
            bodyEl.innerHTML = `<div class="alert alert-danger py-2 mb-0">${escapeHtml(message)}</div>`;
        }
    }
}

function initOrderDetailLinks() {
    const root = document.getElementById("main-content");
    if (!root || root.dataset.orderLinksBound === "1") return;
    root.dataset.orderLinksBound = "1";
    root.addEventListener("click", (e) => {
        const btn = e.target.closest(".ozon-posting-link");
        if (!btn) return;
        e.preventDefault();
        const posting = btn.dataset.postingNumber;
        if (posting) openOrderDetail(posting);
    });
}

function initOrdersPage() {
    initOrdersDatePicker();
    initOrderDetailLinks();

    const fastBtn = document.getElementById("btn-load-orders");
    const fullBtn = document.getElementById("btn-load-orders-financials");
    if (!fastBtn || !fullBtn) return;
    if (fastBtn.dataset.bound === "1" && fullBtn.dataset.bound === "1") return;

    function getSelectedPeriod() {
        const dates = ordersDatePicker?.selectedDates || [];
        if (dates.length < 2) {
            return null;
        }
        return {
            dateFrom: formatApiDate(dates[0]),
            dateTo: formatApiDate(dates[1]),
        };
    }

    function showOrdersFromDatabase() {
        const msgEl = document.getElementById("orders-load-message");
        const period = getSelectedPeriod();
        if (!period) {
            const text = "Выберите период: дату начала и окончания.";
            if (msgEl) {
                msgEl.innerHTML = `<div class="alert alert-warning py-2">${text}</div>`;
            }
            if (typeof showToast === "function") showToast(text, "warning");
            return;
        }

        const text = `Показаны заказы из базы за ${period.dateFrom} — ${period.dateTo}.`;
        if (msgEl) {
            msgEl.innerHTML = `<div class="alert alert-info py-2">${text}</div>`;
        }
        if (typeof showToast === "function") showToast(text, "info");
        if (typeof loadPage === "function") {
            loadPage(
                buildOrdersPageUrl(period.dateFrom, period.dateTo, getOrdersFiltersFromDom()),
                true,
            );
        }
    }

    async function syncOrdersFromOzon() {
        const fullSpinner = document.getElementById("orders-load-financials-spinner");
        const msgEl = document.getElementById("orders-load-message");
        const period = getSelectedPeriod();
        if (!period) {
            const text = "Выберите период: дату начала и окончания.";
            if (msgEl) {
                msgEl.innerHTML = `<div class="alert alert-warning py-2">${text}</div>`;
            }
            if (typeof showToast === "function") showToast(text, "warning");
            return;
        }

        fastBtn.disabled = true;
        fullBtn.disabled = true;
        if (fullSpinner) fullSpinner.classList.remove("d-none");

        try {
            const res = await fetch("/api/orders/load", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify({
                    date_from: period.dateFrom,
                    date_to: period.dateTo,
                    refresh_financials_batch: true,
                }),
            });
            const data = await res.json();
            const variant = data.ok ? "success" : "danger";
            const text = data.message || data.error || "Ошибка загрузки";
            if (msgEl) {
                msgEl.innerHTML = `<div class="alert alert-${variant} py-2">${text}</div>`;
            }
            if (typeof showToast === "function") showToast(text, variant);
            if (data.ok && typeof loadPage === "function") {
                loadPage(
                    buildOrdersPageUrl(period.dateFrom, period.dateTo, getOrdersFiltersFromDom()),
                    true,
                );
            }
        } catch (err) {
            const text = `Ошибка: ${err.message}`;
            if (msgEl) {
                msgEl.innerHTML = `<div class="alert alert-danger py-2">${text}</div>`;
            }
            if (typeof showToast === "function") showToast(text, "danger");
        } finally {
            if (fastBtn.dataset.hasOzon === "1") {
                fastBtn.disabled = false;
                fullBtn.disabled = false;
            }
            if (fullSpinner) fullSpinner.classList.add("d-none");
        }
    }

    async function confirmOrdersFinancialsSync() {
        const modalEl = document.getElementById("orders-financials-confirm-modal");
        const okBtn = document.getElementById("orders-financials-confirm-ok");
        if (!modalEl || !okBtn || typeof bootstrap === "undefined") {
            return true;
        }

        if (!ordersFinancialsConfirmModal) {
            ordersFinancialsConfirmModal = bootstrap.Modal.getOrCreateInstance(modalEl);
        }

        return new Promise((resolve) => {
            let resolved = false;
            const finish = (value) => {
                if (resolved) return;
                resolved = true;
                modalEl.removeEventListener("hidden.bs.modal", onHidden);
                okBtn.removeEventListener("click", onOk);
                resolve(value);
            };
            const onHidden = () => finish(false);
            const onOk = () => {
                finish(true);
                ordersFinancialsConfirmModal.hide();
            };

            modalEl.addEventListener("hidden.bs.modal", onHidden);
            okBtn.addEventListener("click", onOk);
            ordersFinancialsConfirmModal.show();
        });
    }

    if (fastBtn.dataset.bound !== "1") {
        fastBtn.dataset.bound = "1";
        fastBtn.addEventListener("click", showOrdersFromDatabase);
    }
    if (fullBtn.dataset.bound !== "1") {
        fullBtn.dataset.bound = "1";
        fullBtn.addEventListener("click", async () => {
            const confirmed = await confirmOrdersFinancialsSync();
            if (!confirmed) return;
            await syncOrdersFromOzon();
        });
    }
}

function onOrdersPageReady() {
    syncOrdersUrlFromToolbar();
    const btn = document.getElementById("btn-load-orders");
    const finBtn = document.getElementById("btn-load-orders-financials");
    const exportRoot = document.getElementById("orders-export-dropdown");
    if (btn) btn.dataset.bound = "";
    if (finBtn) finBtn.dataset.bound = "";
    if (exportRoot) exportRoot.dataset.bound = "";
    initOrdersFilters();
    initOrdersExport();
    initOrdersPage();
    openOrderFromUrlParam();
}

function openOrderFromUrlParam() {
    const posting = new URLSearchParams(window.location.search).get("posting");
    if (posting) openOrderDetail(posting);
}

document.addEventListener("DOMContentLoaded", () => {
    const path = window.location.pathname.split("?")[0];
    if (path !== "/orders") return;
    onOrdersPageReady();
});

document.addEventListener("page:loaded", (e) => {
    const path = (e.detail?.path || "").split("?")[0];
    if (path !== "/orders") return;

    resetOrderDetailModal();
    orderDetailRequestSeq += 1;
    onOrdersPageReady();
});
