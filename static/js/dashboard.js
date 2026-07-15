/** Дашборд: статистика и график заказов */
let dashboardChart = null;
let dashboardChartPicker = null;
let dashboardChartRequestSeq = 0;
let dashboardDailyStats = [];

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

function getDashboardChartPeriod() {
    const block = document.getElementById("dashboard-orders-chart-block");
    const input = document.getElementById("dashboard-chart-range");
    const dates = dashboardChartPicker?.selectedDates || [];
    if (dates.length >= 2) {
        return { from: formatApiDate(dates[0]), to: formatApiDate(dates[1]) };
    }
    const from = input?.dataset.dateFrom || block?.dataset.dateFrom;
    const to = input?.dataset.dateTo || block?.dataset.dateTo;
    if (from && to) return { from, to };
    return { from: null, to: null };
}

function getDashboardChartMetric() {
    const checked = document.querySelector('input[name="chart-metric"]:checked');
    return checked?.value === "amount" ? "amount" : "count";
}

function isDashboardChartCompare() {
    return document.getElementById("chart-compare-period")?.checked === true;
}

function formatChartValue(value, metric) {
    if (metric === "amount") {
        return `${Number(value).toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽`;
    }
    return formatOrdersCount(value);
}

function formatOrdersCount(value) {
    const n = Math.round(Number(value));
    const mod10 = n % 10;
    const mod100 = n % 100;
    let word = "заказов";
    if (mod100 < 11 || mod100 > 14) {
        if (mod10 === 1) word = "заказ";
        else if (mod10 >= 2 && mod10 <= 4) word = "заказа";
    }
    return `${n} ${word}`;
}

function buildChartTooltipCallbacks() {
    return {
        title(tooltipItems) {
            const idx = tooltipItems[0]?.dataIndex;
            const row = dashboardDailyStats[idx];
            return row?.label || tooltipItems[0]?.label || "";
        },
        label() {
            return null;
        },
        afterBody(tooltipItems) {
            const idx = tooltipItems[0]?.dataIndex;
            const row = dashboardDailyStats[idx];
            if (!row) return [];

            return [
                `Заказов: ${formatOrdersCount(row.count)}`,
                `Сумма: ${formatSummaryAmount(row.amount)}`,
                `${row.week_ago_label} (неделю назад)`,
                `Заказов: ${formatOrdersCount(row.week_ago_count)}`,
                `Сумма: ${formatSummaryAmount(row.week_ago_amount)}`,
            ];
        },
    };
}

function destroyDashboardChart() {
    if (dashboardChart) {
        dashboardChart.destroy();
        dashboardChart = null;
    }
}

function formatSummaryCount(value) {
    return Number(value).toLocaleString("ru-RU", { maximumFractionDigits: 0 });
}

function formatSummaryAmount(value) {
    return `${Number(value).toLocaleString("ru-RU", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })} ₽`;
}

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function renderDashboardWarehouses(rows) {
    const body = document.getElementById("dashboard-warehouses-body");
    const wrap = document.getElementById("dashboard-warehouses-wrap");
    const emptyEl = document.getElementById("dashboard-warehouses-empty");
    if (!body) return;

    const items = Array.isArray(rows) ? rows : [];
    const hasData = items.length > 0;

    if (wrap) wrap.classList.toggle("d-none", !hasData);
    if (emptyEl) emptyEl.classList.toggle("d-none", hasData);

    if (!hasData) {
        body.innerHTML = "";
        return;
    }

    body.innerHTML = items.map((row) => `
        <tr>
            <td>${escapeHtml(row.name || "—")}</td>
            <td class="text-end">${Number(row.quantity || 0).toLocaleString("ru-RU")}</td>
        </tr>
    `).join("");
}

function renderDashboardTopProducts(rows) {
    const body = document.getElementById("dashboard-top-products-body");
    const wrap = document.getElementById("dashboard-top-products-wrap");
    const emptyEl = document.getElementById("dashboard-top-products-empty");
    if (!body) return;

    const items = Array.isArray(rows) ? rows : [];
    const hasData = items.length > 0;

    if (wrap) wrap.classList.toggle("d-none", !hasData);
    if (emptyEl) emptyEl.classList.toggle("d-none", hasData);

    if (!hasData) {
        body.innerHTML = "";
        return;
    }

    body.innerHTML = items.map((row) => {
        const offerId = escapeHtml(row.offer_id || "—");
        const name = escapeHtml(row.name || "—");
        const barcode = escapeHtml(row.barcode || "—");
        const thumb = row.thumbnail_url
            ? `<img src="${escapeHtml(row.thumbnail_url)}" alt="" class="product-thumb" loading="lazy" referrerpolicy="no-referrer">`
            : '<span class="text-muted small">—</span>';
        return `
        <tr>
            <td class="text-center">${thumb}</td>
            <td class="products-col-product">
                <div class="product-cell-title" title="${name}">${name}</div>
                <div class="product-cell-meta font-monospace">${offerId}</div>
                <div class="product-cell-meta font-monospace">${barcode}</div>
            </td>
            <td class="text-end">${Number(row.quantity || 0).toLocaleString("ru-RU")}</td>
            <td class="text-end">${Number(row.stock || 0).toLocaleString("ru-RU")}</td>
        </tr>`;
    }).join("");
}

function renderDashboardInsights(data) {
    renderDashboardWarehouses(data?.warehouses);
    renderDashboardTopProducts(data?.top_products);
}

function formatSummaryDelta(delta, kind) {
    const num = Number(delta);
    const sign = num > 0 ? "+" : "";
    if (kind === "amount") {
        return `${sign}${num.toLocaleString("ru-RU", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        })} ₽`;
    }
    return `${sign}${num.toLocaleString("ru-RU", { maximumFractionDigits: 0 })}`;
}

function renderSummaryCompareLine(container, cmp, label, kind) {
    if (!container) return;
    if (!cmp) {
        container.innerHTML = "";
        return;
    }

    const direction = cmp.direction || "neutral";
    const deltaText = formatSummaryDelta(cmp.delta, kind);
    let arrowHtml = "";
    if (direction === "up") {
        arrowHtml = '<span class="dashboard-summary-arrow dashboard-summary-arrow--up" aria-hidden="true">▲</span>';
    } else if (direction === "down") {
        arrowHtml = '<span class="dashboard-summary-arrow dashboard-summary-arrow--down" aria-hidden="true">▼</span>';
    }

    container.innerHTML = `${arrowHtml}<span class="dashboard-summary-delta-value">${deltaText}</span>`
        + `<span class="dashboard-summary-delta-label">${label}</span>`;
}

function renderTodaySummary(summary) {
    const root = document.getElementById("dashboard-today-summary");
    if (!root) return;

    if (!summary) {
        root.classList.add("d-none");
        return;
    }
    root.classList.remove("d-none");

    const count = summary.count || {};
    const amount = summary.amount || {};

    const countValue = document.getElementById("summary-count-value");
    if (countValue) countValue.textContent = formatSummaryCount(count.value ?? 0);

    renderSummaryCompareLine(
        document.getElementById("summary-count-day"),
        count.vs_yesterday,
        "за день",
        "count",
    );
    renderSummaryCompareLine(
        document.getElementById("summary-count-week"),
        count.vs_last_week,
        "от прошлой недели",
        "count",
    );

    const amountValue = document.getElementById("summary-amount-value");
    if (amountValue) amountValue.textContent = formatSummaryAmount(amount.value ?? 0);

    renderSummaryCompareLine(
        document.getElementById("summary-amount-day"),
        amount.vs_yesterday,
        "за день",
        "amount",
    );
    renderSummaryCompareLine(
        document.getElementById("summary-amount-week"),
        amount.vs_last_week,
        "от прошлой недели",
        "amount",
    );
}

function renderDashboardChart(data) {
    const canvas = document.getElementById("dashboard-orders-chart");
    const emptyEl = document.getElementById("dashboard-chart-empty");
    if (!canvas || typeof Chart === "undefined") return;

    dashboardDailyStats = data.daily_stats || [];
    const metric = data.metric || "count";
    const hasValues = (data.current || []).some((v) => Number(v) > 0)
        || (data.previous || []).some((v) => Number(v) > 0);

    if (!hasValues) {
        destroyDashboardChart();
        canvas.classList.add("d-none");
        if (emptyEl) emptyEl.classList.remove("d-none");
        return;
    }

    canvas.classList.remove("d-none");
    if (emptyEl) emptyEl.classList.add("d-none");

    destroyDashboardChart();

    const datasets = [
        {
            label: data.current_label || "Текущий период",
            data: data.current || [],
            borderColor: "#2563eb",
            backgroundColor: "rgba(37, 99, 235, 0.12)",
            borderWidth: 2,
            pointRadius: 2,
            pointHoverRadius: 4,
            tension: 0.25,
            fill: true,
        },
    ];

    if (data.compare && data.previous) {
        datasets.push({
            label: data.previous_label || "Неделю назад",
            data: data.previous,
            borderColor: "#9ca3af",
            backgroundColor: "rgba(156, 163, 175, 0.08)",
            borderWidth: 2,
            borderDash: [6, 4],
            pointRadius: 2,
            pointHoverRadius: 4,
            tension: 0.25,
            fill: false,
        });
    }

    dashboardChart = new Chart(canvas, {
        type: "line",
        data: {
            labels: data.labels || [],
            datasets,
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: {
                    display: datasets.length > 1,
                    position: "bottom",
                    labels: { boxWidth: 12, padding: 16 },
                },
                tooltip: {
                    displayColors: false,
                    callbacks: buildChartTooltipCallbacks(),
                },
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 14 },
                },
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback(value) {
                            if (metric === "amount") {
                                return Number(value).toLocaleString("ru-RU", { maximumFractionDigits: 0 });
                            }
                            return Number.isInteger(value) ? value : Math.round(value);
                        },
                    },
                },
            },
        },
    });
}

async function loadDashboardOrdersChart() {
    const loadingEl = document.getElementById("dashboard-chart-loading");
    const period = getDashboardChartPeriod();
    if (!period.from || !period.to) return;

    const seq = ++dashboardChartRequestSeq;
    if (loadingEl) loadingEl.classList.remove("d-none");

    const params = new URLSearchParams({
        from: period.from,
        to: period.to,
        metric: getDashboardChartMetric(),
        compare: isDashboardChartCompare() ? "1" : "0",
    });

    try {
        const res = await fetch(`/api/dashboard/orders-chart?${params}`);
        const data = await res.json();
        if (seq !== dashboardChartRequestSeq) return;
        if (!data.ok) {
            destroyDashboardChart();
            renderTodaySummary(null);
            renderDashboardInsights(null);
            return;
        }
        renderTodaySummary(data.today_summary);
        renderDashboardChart(data);
        renderDashboardInsights(data);
    } catch (err) {
        if (seq !== dashboardChartRequestSeq) return;
        console.error("Orders chart:", err);
    } finally {
        if (seq === dashboardChartRequestSeq && loadingEl) {
            loadingEl.classList.add("d-none");
        }
    }
}

function initDashboardChartPicker() {
    const input = document.getElementById("dashboard-chart-range");
    if (!input || input.disabled || typeof flatpickr === "undefined") return;

    const from = input.dataset.dateFrom;
    const to = input.dataset.dateTo;
    const defaultDates = [];
    const d1 = parseIsoDate(from);
    const d2 = parseIsoDate(to);
    if (d1 && d2) defaultDates.push(d1, d2);

    if (dashboardChartPicker) {
        dashboardChartPicker.destroy();
        dashboardChartPicker = null;
    }

    dashboardChartPicker = flatpickr(input, {
        mode: "range",
        dateFormat: "d.m.Y",
        locale: "ru",
        maxDate: "today",
        allowInput: false,
        defaultDate: defaultDates.length === 2 ? defaultDates : undefined,
        onChange(selectedDates) {
            if (selectedDates.length < 2) return;
            const block = document.getElementById("dashboard-orders-chart-block");
            if (block) {
                block.dataset.dateFrom = formatApiDate(selectedDates[0]);
                block.dataset.dateTo = formatApiDate(selectedDates[1]);
            }
            loadDashboardOrdersChart();
        },
    });
}

function applyDashboardChartPrefsFromBlock() {
    const block = document.getElementById("dashboard-orders-chart-block");
    if (!block) return;

    const metric = block.dataset.metric === "amount" ? "amount" : "count";
    document.querySelectorAll('input[name="chart-metric"]').forEach((el) => {
        el.checked = el.value === metric;
    });

    const compareEl = document.getElementById("chart-compare-period");
    if (compareEl) compareEl.checked = block.dataset.compare === "1";
}

function initDashboardChartControls() {
    const block = document.getElementById("dashboard-orders-chart-block");
    if (!block || block.dataset.chartBound === "1") return;
    block.dataset.chartBound = "1";

    applyDashboardChartPrefsFromBlock();
    initDashboardChartPicker();

    document.querySelectorAll('input[name="chart-metric"]').forEach((el) => {
        el.addEventListener("change", () => loadDashboardOrdersChart());
    });

    const compareEl = document.getElementById("chart-compare-period");
    if (compareEl) {
        compareEl.addEventListener("change", () => loadDashboardOrdersChart());
    }
}

function initDashboardPage() {
    initDashboardChartControls();
    loadDashboardOrdersChart();
}

async function loadDashboardStats() {
    const stats = [
        { key: "returns_at_pickup", id: "stat-returns-at-pickup", periodId: "stat-returns-at-pickup-period" },
        { key: "orders", id: "stat-orders", periodId: "stat-orders-period" },
        { key: "shipments", id: "stat-shipments", periodId: "stat-shipments-period" },
        { key: "products_in_promotions", id: "stat-products-in-promotions" },
    ];
    try {
        const res = await fetch("/api/dashboard/stats");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        stats.forEach(({ key, id, periodId }) => {
            const el = document.getElementById(id);
            if (el) el.textContent = data[key] ?? 0;
            if (periodId) {
                const periodEl = document.getElementById(periodId);
                if (!periodEl) return;
                if (key === "returns_at_pickup") {
                    periodEl.textContent = data.returns_at_pickup_label || "В пункте выдачи";
                    return;
                }
                const label = data[`${key}_period`];
                periodEl.textContent = label || "";
            }
        });

        const ordersLink = document.getElementById("stat-orders-link");
        if (ordersLink && data.orders_period_from && data.orders_period_to) {
            const href = `/orders?from=${encodeURIComponent(data.orders_period_from)}&to=${encodeURIComponent(data.orders_period_to)}`;
            ordersLink.href = href;
            ordersLink.dataset.nav = href;
        }

        const shipmentsLink = document.getElementById("stat-shipments-link");
        if (shipmentsLink && data.shipments_period_from && data.shipments_period_to) {
            const href = `/shipments?from=${encodeURIComponent(data.shipments_period_from)}&to=${encodeURIComponent(data.shipments_period_to)}`;
            shipmentsLink.href = href;
            shipmentsLink.dataset.nav = href;
        }
    } catch (err) {
        console.error("Dashboard stats:", err);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const path = window.location.pathname.split("?")[0];
    if (path !== "/") return;
    loadDashboardStats();
    initDashboardPage();
});

document.addEventListener("page:loaded", (e) => {
    const path = (e.detail?.path || "").split("?")[0];
    if (path !== "/") return;

    destroyDashboardChart();
    dashboardChartRequestSeq += 1;
    if (dashboardChartPicker) {
        dashboardChartPicker.destroy();
        dashboardChartPicker = null;
    }
    const block = document.getElementById("dashboard-orders-chart-block");
    if (block) block.dataset.chartBound = "";

    loadDashboardStats();
    initDashboardPage();
});
