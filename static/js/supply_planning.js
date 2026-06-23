/** Планирование поставки: форма склада и периода */
let supplyPlanningDatePicker = null;

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

function formatApiDate(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

function getSupplyPlanningUrlParams() {
    const params = new URLSearchParams(window.location.search);
    return {
        warehouse: params.get("warehouse") || "",
        from: params.get("from"),
        to: params.get("to"),
    };
}

function buildSupplyPlanningPageUrl(warehouse, from, to) {
    const params = new URLSearchParams();
    if (warehouse) params.set("warehouse", warehouse);
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    const query = params.toString();
    return query ? `/analytics/supply-planning?${query}` : "/analytics/supply-planning";
}

function resizeSupplyPlanningDateInput() {
    const input = document.getElementById("supply-planning-date-range");
    if (!input) return;
    const text = input.value || input.placeholder || "";
    const chars = Math.max(text.length, 12);
    input.style.width = `${Math.min(20, Math.max(11, chars * 0.62))}rem`;
}

function initSupplyPlanningDatePicker() {
    const input = document.getElementById("supply-planning-date-range");
    if (!input || input.disabled || typeof flatpickr === "undefined") return;

    const urlPeriod = getSupplyPlanningUrlParams();
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

    if (supplyPlanningDatePicker) {
        supplyPlanningDatePicker.destroy();
        supplyPlanningDatePicker = null;
    }

    supplyPlanningDatePicker = flatpickr(input, {
        mode: "range",
        dateFormat: "d.m.Y",
        locale: "ru",
        maxDate: "today",
        allowInput: false,
        defaultDate: defaultDates.length === 2 ? defaultDates : undefined,
        onChange() {
            resizeSupplyPlanningDateInput();
        },
        onReady() {
            resizeSupplyPlanningDateInput();
        },
    });
}

function getSupplyPlanningPeriod() {
    const input = document.getElementById("supply-planning-date-range");
    if (!input) return { from: null, to: null };

    if (supplyPlanningDatePicker && supplyPlanningDatePicker.selectedDates.length === 2) {
        const [from, to] = supplyPlanningDatePicker.selectedDates;
        return { from: formatApiDate(from), to: formatApiDate(to) };
    }

    const from = input.dataset.dateFrom;
    const to = input.dataset.dateTo;
    return { from: from || null, to: to || null };
}

function bindSupplyPlanningForm() {
    const form = document.getElementById("supply-planning-form");
    if (!form || form.dataset.bound === "1") return;
    form.dataset.bound = "1";

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        const warehouseEl = document.getElementById("supply-planning-warehouse");
        const warehouse = warehouseEl ? warehouseEl.value.trim() : "";
        const period = getSupplyPlanningPeriod();
        const spinner = document.getElementById("supply-planning-spinner");
        const submitBtn = document.getElementById("btn-supply-planning-submit");

        if (!warehouse) {
            if (typeof showToast === "function") {
                showToast("Выберите склад.", "warning");
            }
            return;
        }
        if (!period.from || !period.to) {
            if (typeof showToast === "function") {
                showToast("Выберите период.", "warning");
            }
            return;
        }

        if (spinner) spinner.classList.remove("d-none");
        if (submitBtn) submitBtn.disabled = true;

        const url = buildSupplyPlanningPageUrl(warehouse, period.from, period.to);
        if (typeof loadPage === "function") {
            loadPage(url).finally(() => {
                if (spinner) spinner.classList.add("d-none");
                if (submitBtn) submitBtn.disabled = false;
            });
        } else {
            window.location.href = url;
        }
    });
}

function normalizeSendQuantityInput(input) {
    if (!input) return;
    const raw = String(input.value || "").trim();
    if (!raw) {
        input.value = "";
        return;
    }
    const value = Math.max(0, Math.floor(Number(raw)));
    input.value = Number.isFinite(value) ? String(value) : "";
}

function collectSupplyPlanningSendItems(exportType) {
    const items = [];
    document.querySelectorAll(".supply-planning-send-input").forEach((input) => {
        const raw = String(input.value || "").trim();
        if (!raw) return;
        const quantity = Math.max(0, Math.floor(Number(raw)));
        if (!Number.isFinite(quantity) || quantity <= 0) return;

        if (exportType === "ozon") {
            const offerId = String(input.dataset.offerId || "").trim();
            if (!offerId || offerId === "—") return;
            items.push({
                offer_id: offerId,
                name: String(input.dataset.name || "").trim(),
                quantity,
            });
            return;
        }

        const barcode = String(input.dataset.barcode || "").trim();
        if (!barcode || barcode === "—") return;
        items.push({ barcode, quantity });
    });
    return items;
}

function parseContentDispositionFilename(header) {
    if (!header) return null;
    const utfMatch = header.match(/filename\*=UTF-8''([^;]+)/i);
    if (utfMatch) {
        try {
            return decodeURIComponent(utfMatch[1]);
        } catch {
            /* ignore */
        }
    }
    const match = header.match(/filename="?([^";]+)"?/i);
    return match ? match[1] : null;
}

async function exportSupplyPlanningSend(exportType) {
    const type = exportType === "ozon" ? "ozon" : "1c";
    const items = collectSupplyPlanningSendItems(type);
    if (!items.length) {
        if (typeof showToast === "function") {
            showToast("Укажите количество в колонке «Отправить» хотя бы для одного товара.", "warning");
        }
        return;
    }

    const dropdown = document.getElementById("supply-planning-export-dropdown");
    const toggleBtn = dropdown?.querySelector(".supply-planning-export-btn");
    if (toggleBtn) toggleBtn.disabled = true;

    const warehouseEl = document.getElementById("supply-planning-warehouse");
    const warehouse = (
        (warehouseEl && warehouseEl.value.trim())
        || (dropdown && dropdown.dataset.warehouse)
        || ""
    ).trim();

    try {
        const res = await fetch("/api/analytics/supply-planning/export", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ items, warehouse, type }),
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.error || `HTTP ${res.status}`);
        }
        const blob = await res.blob();
        const filename = parseContentDispositionFilename(res.headers.get("Content-Disposition"))
            || "supply_planning.xls";
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    } catch (err) {
        if (typeof showToast === "function") {
            showToast(`Ошибка экспорта: ${err.message}`, "danger");
        }
    } finally {
        if (toggleBtn) toggleBtn.disabled = false;
    }
}

function bindSupplyPlanningExport() {
    const root = document.getElementById("supply-planning-export-dropdown");
    if (!root || root.dataset.bound === "1") return;
    root.dataset.bound = "1";
    root.querySelectorAll("[data-export-type]").forEach((btn) => {
        btn.addEventListener("click", () => {
            exportSupplyPlanningSend(btn.dataset.exportType);
        });
    });
}

function bindSupplyPlanningSendInputs() {
    document.querySelectorAll(".supply-planning-send-input").forEach((input) => {
        if (input.dataset.bound === "1") return;
        input.dataset.bound = "1";
        input.addEventListener("input", () => normalizeSendQuantityInput(input));
        input.addEventListener("blur", () => normalizeSendQuantityInput(input));
    });
}

function initSupplyPlanningPage() {
    initSupplyPlanningDatePicker();
    bindSupplyPlanningForm();
    bindSupplyPlanningSendInputs();
    bindSupplyPlanningExport();
}

document.addEventListener("DOMContentLoaded", () => {
    if (window.location.pathname === "/analytics/supply-planning") {
        initSupplyPlanningPage();
    }
});

document.addEventListener("page:loaded", (event) => {
    if (event.detail?.path === "/analytics/supply-planning") {
        initSupplyPlanningPage();
    }
});
