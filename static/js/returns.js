/** Страница «Возвраты». */

let returnsDatePicker = null;

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

function buildReturnsPageUrl(from, to, refresh = false) {
    const params = new URLSearchParams();
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    if (refresh) params.set("refresh", "1");
    const query = params.toString();
    return query ? `/reports/returns?${query}` : "/reports/returns";
}

function initReturnsDatePicker() {
    const input = document.getElementById("returns-date-range");
    if (!input || input.disabled || typeof flatpickr === "undefined") return;

    const from = input.dataset.dateFrom || "";
    const to = input.dataset.dateTo || "";
    const defaultDates = [];
    const fromDate = parseIsoDate(from);
    const toDate = parseIsoDate(to);
    if (fromDate && toDate) {
        defaultDates.push(fromDate, toDate);
    }

    if (returnsDatePicker) {
        returnsDatePicker.destroy();
        returnsDatePicker = null;
    }

    returnsDatePicker = flatpickr(input, {
        mode: "range",
        locale: "ru",
        dateFormat: "d.m.Y",
        defaultDate: defaultDates.length === 2 ? defaultDates : undefined,
        onClose(selectedDates) {
            if (selectedDates.length === 2) {
                input.dataset.dateFrom = formatApiDate(selectedDates[0]);
                input.dataset.dateTo = formatApiDate(selectedDates[1]);
            }
        },
    });
}

function loadReturnsPage(from, to, refresh = false) {
    const url = buildReturnsPageUrl(from, to, refresh);
    if (typeof loadPage === "function") {
        loadPage(url, false);
        return;
    }
    window.location.href = url;
}

function initReturnsPage() {
    initReturnsDatePicker();

    const loadBtn = document.getElementById("btn-load-returns");
    if (loadBtn && loadBtn.dataset.bound !== "1") {
        loadBtn.dataset.bound = "1";
        loadBtn.addEventListener("click", () => {
            const input = document.getElementById("returns-date-range");
            const from = input?.dataset.dateFrom || "";
            const to = input?.dataset.dateTo || "";
            if (!from || !to) return;
            loadReturnsPage(from, to, true);
        });
    }

    const refreshBtn = document.getElementById("btn-refresh-returns");
    if (refreshBtn && refreshBtn.dataset.bound !== "1") {
        refreshBtn.dataset.bound = "1";
        refreshBtn.addEventListener("click", () => {
            const toolbar = document.getElementById("returns-toolbar");
            const spinner = document.getElementById("returns-refresh-spinner");
            const from = toolbar?.dataset.dateFrom || "";
            const to = toolbar?.dataset.dateTo || "";
            refreshBtn.disabled = true;
            if (spinner) spinner.classList.remove("d-none");
            loadReturnsPage(from, to, true);
        });
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const path = window.location.pathname.split("?")[0];
    if (path === "/reports/returns") initReturnsPage();
});

document.addEventListener("page:loaded", (e) => {
    const path = (e.detail?.path || "").split("?")[0];
    if (path !== "/reports/returns") return;

    const loadBtn = document.getElementById("btn-load-returns");
    const refreshBtn = document.getElementById("btn-refresh-returns");
    const spinner = document.getElementById("returns-refresh-spinner");
    if (loadBtn) loadBtn.dataset.bound = "";
    if (refreshBtn) {
        refreshBtn.dataset.bound = "";
        refreshBtn.disabled = false;
    }
    if (spinner) spinner.classList.add("d-none");
    if (returnsDatePicker) {
        returnsDatePicker.destroy();
        returnsDatePicker = null;
    }
    initReturnsPage();
});
