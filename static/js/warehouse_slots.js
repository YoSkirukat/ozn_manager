/** Страница «Склады и слоты» */
let warehouseSlotsState = {
    draftId: null,
    clusterId: null,
    macrolocalClusterId: null,
    allClusters: false,
    openWarehouseKey: null,
    refreshCooldownUntil: 0,
    timeslotsCache: new Map(),
    warehousesByKey: {},
    watchKeys: new Set(),
    watchesByKey: new Map(),
};

const WAREHOUSE_SLOTS_UNAVAILABLE_MESSAGE =
    "Таймслоты для этого склада недоступны. Выберите склад со статусом «Доступен».";

const TIMESLOT_MONTH_NAMES = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

const TIMESLOT_MONTH_NAMES_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

const TIMESLOT_WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

const TIMESLOT_PERIOD_GROUPS = [
    { key: "night", label: "Ночь", range: "00:00 – 06:00", minHour: 0, maxHour: 6 },
    { key: "morning", label: "Утро", range: "06:00 – 12:00", minHour: 6, maxHour: 12 },
    { key: "day", label: "День", range: "12:00 – 18:00", minHour: 12, maxHour: 18 },
    { key: "evening", label: "Вечер", range: "18:00 – 00:00", minHour: 18, maxHour: 24 },
];

let timeslotPickerCounter = 0;
const timeslotPickers = new Map();

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function formatSlotTime(value) {
    if (!value) return "—";
    const text = String(value);
    if (text.length >= 16) {
        const datePart = text.slice(0, 10).split("-").reverse().join(".");
        const timePart = text.slice(11, 16);
        return `${datePart} ${timePart}`;
    }
    return text;
}

function formatSlotRange(fromValue, toValue) {
    const from = String(fromValue || "");
    const to = String(toValue || "");
    if (from.length >= 16 && to.length >= 16) {
        return `${from.slice(11, 16)} – ${to.slice(11, 16)}`;
    }
    return `${formatSlotTime(from)} – ${formatSlotTime(to)}`;
}

function parseIsoDateKey(value) {
    const text = String(value || "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return null;
    const [year, month, day] = text.split("-").map(Number);
    return { year, month, day, key: text };
}

function todayDateKey() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
}

function dateKeyFromParts(year, month, day) {
    return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function compareDateKeys(a, b) {
    return String(a).localeCompare(String(b));
}

function isDateInRange(dateKey, range) {
    if (!range?.from || !range?.to) return true;
    return compareDateKeys(dateKey, range.from) >= 0 && compareDateKeys(dateKey, range.to) <= 0;
}

function mondayFirstWeekday(year, month, day) {
    const weekday = new Date(year, month - 1, day).getDay();
    return weekday === 0 ? 6 : weekday - 1;
}

function buildDaysMap(days) {
    const map = new Map();
    for (const day of days || []) {
        const parsed = parseIsoDateKey(day?.date);
        if (!parsed) continue;
        map.set(parsed.key, day.timeslots || []);
    }
    return map;
}

function pickInitialSelectedDate(daysMap, range) {
    const sorted = [...daysMap.keys()].sort();
    if (!sorted.length) return range?.from || todayDateKey();
    const today = todayDateKey();
    if (daysMap.has(today)) return today;
    return sorted[0];
}

function slotStartHour(fromValue) {
    const text = String(fromValue || "");
    if (text.length >= 13) {
        const hour = Number(text.slice(11, 13));
        return Number.isFinite(hour) ? hour : 0;
    }
    return 0;
}

function groupSlotsByPeriod(timeslots) {
    const groups = Object.fromEntries(
        TIMESLOT_PERIOD_GROUPS.map((group) => [group.key, []]),
    );
    for (const slot of timeslots || []) {
        const hour = slotStartHour(slot.from);
        if (hour < 6) groups.night.push(slot);
        else if (hour < 12) groups.morning.push(slot);
        else if (hour < 18) groups.day.push(slot);
        else groups.evening.push(slot);
    }
    return groups;
}

function formatSelectedDayTitle(dateKey) {
    const parsed = parseIsoDateKey(dateKey);
    if (!parsed) return "—";
    return `${parsed.day} ${TIMESLOT_MONTH_NAMES_GENITIVE[parsed.month - 1]}`;
}

function renderTimeslotPeriodGroups(timeslots) {
    const groups = groupSlotsByPeriod(timeslots);
    const sections = TIMESLOT_PERIOD_GROUPS.map((group) => {
        const slots = groups[group.key] || [];
        if (!slots.length) return "";
        const pills = slots.map((slot) => `
            <span class="warehouse-slots-slot-pill">${escapeHtml(formatSlotRange(slot.from, slot.to))}</span>
        `).join("");
        return `
        <div class="warehouse-slots-period-block">
            <div class="warehouse-slots-period-title">
                <span>${group.label}</span>
                <span class="warehouse-slots-period-range">${group.range}</span>
            </div>
            <div class="warehouse-slots-slot-list">${pills}</div>
        </div>`;
    }).join("");
    return sections || '<div class="text-muted small">Нет слотов на выбранный день.</div>';
}

function canNavigateMonth(state, direction) {
    const { range, viewYear, viewMonth } = state;
    if (!range?.from || !range?.to) return false;
    const from = parseIsoDateKey(range.from);
    const to = parseIsoDateKey(range.to);
    if (!from || !to) return false;

    let year = viewYear;
    let month = viewMonth + direction;
    if (month < 1) {
        month = 12;
        year -= 1;
    } else if (month > 12) {
        month = 1;
        year += 1;
    }

    const monthStart = dateKeyFromParts(year, month, 1);
    const daysInMonth = new Date(year, month, 0).getDate();
    const monthEnd = dateKeyFromParts(year, month, daysInMonth);
    return compareDateKeys(monthEnd, range.from) >= 0 && compareDateKeys(monthStart, range.to) <= 0;
}

function renderTimeslotsCalendarGrid(state) {
    const { daysMap, range, selectedDate, viewYear, viewMonth } = state;
    const daysInMonth = new Date(viewYear, viewMonth, 0).getDate();
    const leadingEmpty = mondayFirstWeekday(viewYear, viewMonth, 1);
    const cells = [];

    for (let i = 0; i < leadingEmpty; i += 1) {
        cells.push('<div class="warehouse-slots-cal-day warehouse-slots-cal-day--empty" aria-hidden="true"></div>');
    }

    const today = todayDateKey();
    for (let day = 1; day <= daysInMonth; day += 1) {
        const dateKey = dateKeyFromParts(viewYear, viewMonth, day);
        const inRange = isDateInRange(dateKey, range);
        const hasSlots = daysMap.has(dateKey);
        const isSelected = dateKey === selectedDate;
        const isToday = dateKey === today;
        const weekday = mondayFirstWeekday(viewYear, viewMonth, day);
        const isWeekend = weekday >= 5;
        const classes = [
            "warehouse-slots-cal-day",
            hasSlots ? "warehouse-slots-cal-day--has-slots" : "",
            isSelected ? "warehouse-slots-cal-day--selected" : "",
            isToday ? "warehouse-slots-cal-day--today" : "",
            isWeekend ? "warehouse-slots-cal-day--weekend" : "",
            !inRange || !hasSlots ? "warehouse-slots-cal-day--disabled" : "",
        ].filter(Boolean).join(" ");

        if (!inRange || !hasSlots) {
            cells.push(`
            <div class="${classes}" aria-hidden="true">
                <span class="warehouse-slots-cal-day-num">${day}</span>
                ${hasSlots ? '<span class="warehouse-slots-cal-day-dot"></span>' : ""}
            </div>`);
        } else {
            cells.push(`
            <button type="button" class="${classes}" data-date="${dateKey}" aria-label="${formatSelectedDayTitle(dateKey)}">
                <span class="warehouse-slots-cal-day-num">${day}</span>
                <span class="warehouse-slots-cal-day-dot"></span>
            </button>`);
        }
    }

    return cells.join("");
}

function renderTimeslotsPicker(container) {
    const pickerId = container.dataset.pickerId;
    const state = timeslotPickers.get(pickerId);
    if (!state) return;

    const selectedSlots = state.daysMap.get(state.selectedDate) || [];
    const canPrev = canNavigateMonth(state, -1);
    const canNext = canNavigateMonth(state, 1);

    container.innerHTML = `
    <div class="warehouse-slots-picker">
        <div class="warehouse-slots-picker-calendar">
            <div class="warehouse-slots-cal-header">
                <button type="button" class="warehouse-slots-cal-nav" data-dir="prev" ${canPrev ? "" : "disabled"} aria-label="Предыдущий месяц">‹</button>
                <div class="warehouse-slots-cal-title">${TIMESLOT_MONTH_NAMES[state.viewMonth - 1]} ${state.viewYear}</div>
                <button type="button" class="warehouse-slots-cal-nav" data-dir="next" ${canNext ? "" : "disabled"} aria-label="Следующий месяц">›</button>
            </div>
            <div class="warehouse-slots-cal-weekdays">
                ${TIMESLOT_WEEKDAYS.map((label, index) => `
                    <div class="warehouse-slots-cal-weekday${index >= 5 ? " warehouse-slots-cal-weekday--weekend" : ""}">${label}</div>
                `).join("")}
            </div>
            <div class="warehouse-slots-cal-grid">
                ${renderTimeslotsCalendarGrid(state)}
            </div>
        </div>
        <div class="warehouse-slots-picker-slots">
            <div class="warehouse-slots-slots-date-title">${escapeHtml(formatSelectedDayTitle(state.selectedDate))}</div>
            <div class="warehouse-slots-slots-groups">
                ${renderTimeslotPeriodGroups(selectedSlots)}
            </div>
        </div>
    </div>`;
}

function handleTimeslotPickerClick(event) {
    const container = event.target.closest(".warehouse-slots-detail-content");
    if (!container?.dataset.pickerId) return;

    const state = timeslotPickers.get(container.dataset.pickerId);
    if (!state) return;

    const dayBtn = event.target.closest(".warehouse-slots-cal-day[data-date]");
    if (dayBtn) {
        state.selectedDate = dayBtn.dataset.date;
        renderTimeslotsPicker(container);
        return;
    }

    const navBtn = event.target.closest(".warehouse-slots-cal-nav");
    if (!navBtn || navBtn.disabled) return;

    const direction = navBtn.dataset.dir === "next" ? 1 : -1;
    if (!canNavigateMonth(state, direction)) return;

    let month = state.viewMonth + direction;
    let year = state.viewYear;
    if (month < 1) {
        month = 12;
        year -= 1;
    } else if (month > 12) {
        month = 1;
        year += 1;
    }
    state.viewMonth = month;
    state.viewYear = year;
    renderTimeslotsPicker(container);
}

function renderTimeslotsContent(container, data) {
    const days = data?.days || [];
    if (!days.length) {
        container.removeAttribute("data-picker-id");
        container.innerHTML = '<div class="text-muted small">Нет доступных таймслотов на выбранный период.</div>';
        return;
    }

    const daysMap = buildDaysMap(days);
    const range = {
        from: data.date_from || days[0]?.date,
        to: data.date_to || days[days.length - 1]?.date,
    };
    const selectedDate = pickInitialSelectedDate(daysMap, range);
    const parsed = parseIsoDateKey(selectedDate) || parseIsoDateKey(range.from);

    const pickerId = container.dataset.pickerId || `picker-${++timeslotPickerCounter}`;
    container.dataset.pickerId = pickerId;
    timeslotPickers.set(pickerId, {
        daysMap,
        range,
        selectedDate,
        viewYear: parsed?.year || new Date().getFullYear(),
        viewMonth: parsed?.month || new Date().getMonth() + 1,
    });
    renderTimeslotsPicker(container);
}

function availabilityBadgeClass(state) {
    if (state === "FULL_AVAILABLE") return "warehouse-slots-badge--available";
    if (state === "PARTIAL_AVAILABLE") return "warehouse-slots-badge--partial";
    return "warehouse-slots-badge--unavailable";
}

function showWarehouseSlotsMessage(text, variant = "danger") {
    const root = document.getElementById("warehouse-slots-message");
    if (!root) return;
    if (!text) {
        root.innerHTML = "";
        return;
    }
    root.innerHTML = `<div class="alert alert-${variant} py-2">${escapeHtml(text)}</div>`;
}

function getSelectedCluster() {
    const select = document.getElementById("warehouse-slots-cluster");
    if (!select) return null;
    const option = select.options[select.selectedIndex];
    const macrolocalClusterId = Number(select.value);
    if (!macrolocalClusterId) return null;
    return {
        macrolocal_cluster_id: macrolocalClusterId,
        cluster_id: Number(option?.dataset.clusterId || 0) || null,
        name: option?.textContent?.trim() || "",
    };
}

function warehouseRowKey(row) {
    const warehouseId = Number(row?.storage_warehouse_id || 0);
    const macrolocalId = Number(row?.macrolocal_cluster_id || 0);
    return `${macrolocalId}:${warehouseId}`;
}

function isWarehouseWatched(rowKey) {
    const keys = warehouseSlotsState.watchKeys;
    return keys instanceof Set && keys.has(rowKey);
}

function renderWarehouseWatchButton(rowKey, row) {
    const watched = isWarehouseWatched(rowKey);
    const title = watched
        ? "Прекратить отслеживание"
        : "Отслеживать доступность склада";
    const iconClass = watched ? "bi-bell-fill" : "bi-bell";
    const btnClass = watched
        ? "warehouse-slots-watch-btn warehouse-slots-watch-btn--active"
        : "warehouse-slots-watch-btn";
    return `
        <button type="button" class="btn btn-sm ${btnClass}"
                data-warehouse-key="${escapeHtml(rowKey)}"
                title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}"
                aria-pressed="${watched ? "true" : "false"}">
            <i class="bi ${iconClass}" aria-hidden="true"></i>
        </button>`;
}

async function loadWarehouseWatches() {
    const root = document.getElementById("warehouse-slots-watch-list");
    if (!root) return;

    try {
        const res = await fetch("/api/analytics/warehouse-slots/watches", {
            headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);

        warehouseSlotsState.watchKeys = new Set();
        warehouseSlotsState.watchesByKey = new Map();
        for (const watch of data.watches || []) {
            const key = watch.watch_key || `${watch.macrolocal_cluster_id}:${watch.storage_warehouse_id}`;
            warehouseSlotsState.watchKeys.add(key);
            warehouseSlotsState.watchesByKey.set(key, watch);
        }
        renderWarehouseWatchList();
        updateWarehouseWatchButtons();
    } catch (err) {
        root.innerHTML = `<div class="text-danger small">${escapeHtml(err.message)}</div>`;
    }
}

function renderWarehouseWatchList() {
    const root = document.getElementById("warehouse-slots-watch-list");
    if (!root) return;

    const watches = [...warehouseSlotsState.watchesByKey.values()];
    if (!watches.length) {
        root.innerHTML = '<div class="text-muted small">Склады для мониторинга не выбраны.</div>';
        return;
    }

    root.innerHTML = watches.map((watch) => {
        const key = watch.watch_key || `${watch.macrolocal_cluster_id}:${watch.storage_warehouse_id}`;
        const stateLabel = watch.last_availability_state === "FULL_AVAILABLE"
            ? "Доступен"
            : watch.last_availability_state === "NOT_AVAILABLE"
                ? "Недоступен"
                : "—";
        return `
            <div class="warehouse-slots-watch-item" data-watch-key="${escapeHtml(key)}">
                <div class="warehouse-slots-watch-item-main">
                    <div class="warehouse-slots-watch-item-title">${escapeHtml(watch.warehouse_name || "—")}</div>
                    <div class="warehouse-slots-watch-item-meta text-muted small">
                        ${escapeHtml(watch.cluster_name || "—")} · последний статус: ${escapeHtml(stateLabel)}
                    </div>
                </div>
                <button type="button" class="btn btn-sm btn-outline-danger warehouse-slots-watch-remove-btn"
                        data-watch-id="${watch.id}"
                        title="Убрать из мониторинга" aria-label="Убрать из мониторинга">
                    <i class="bi bi-x-lg" aria-hidden="true"></i>
                </button>
            </div>`;
    }).join("");
}

function updateWarehouseWatchButtons() {
    const body = document.getElementById("warehouse-slots-table-body");
    if (!body) return;

    body.querySelectorAll(".warehouse-slots-watch-btn").forEach((btn) => {
        const rowKey = btn.dataset.warehouseKey;
        const watched = rowKey && isWarehouseWatched(rowKey);
        btn.classList.toggle("warehouse-slots-watch-btn--active", Boolean(watched));
        btn.setAttribute("aria-pressed", watched ? "true" : "false");
        const icon = btn.querySelector("i");
        if (icon) {
            icon.classList.toggle("bi-bell-fill", Boolean(watched));
            icon.classList.toggle("bi-bell", !watched);
        }
        btn.title = watched ? "Прекратить отслеживание" : "Отслеживать доступность склада";
    });
}

async function toggleWarehouseWatch(rowKey) {
    const row = warehouseSlotsState.warehousesByKey?.[rowKey];
    if (!row) return;

    if (isWarehouseWatched(rowKey)) {
        const watch = warehouseSlotsState.watchesByKey.get(rowKey);
        if (!watch?.id) return;
        const res = await fetch(`/api/analytics/warehouse-slots/watches/${watch.id}`, {
            method: "DELETE",
            headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    } else {
        const res = await fetch("/api/analytics/warehouse-slots/watches", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify({
                macrolocal_cluster_id: row.macrolocal_cluster_id,
                cluster_id: row.cluster_id,
                storage_warehouse_id: row.storage_warehouse_id,
                warehouse_name: row.name,
                cluster_name: row.cluster_name,
                availability_state: row.availability_state,
            }),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    }

    await loadWarehouseWatches();
}

function renderWarehouseSlotsSummary(data) {
    const card = document.getElementById("warehouse-slots-summary-card");
    if (!card) return;
    card.classList.remove("d-none");

    const clusterEl = document.getElementById("warehouse-slots-summary-cluster");
    const totalEl = document.getElementById("warehouse-slots-summary-total");
    const availableEl = document.getElementById("warehouse-slots-summary-available");

    if (clusterEl) {
        clusterEl.textContent = data.cluster_name || "—";
    }
    if (totalEl) {
        const clustersCount = data.summary?.clusters;
        const total = data.summary?.total ?? 0;
        totalEl.textContent = data.all_clusters && clustersCount
            ? `${total} (${clustersCount} класт.)`
            : String(total);
    }
    if (availableEl) availableEl.textContent = String(data.summary?.available ?? 0);
}

function canLoadWarehouseTimeslots(row) {
    return row?.is_available === true || row?.availability_state === "FULL_AVAILABLE";
}

function renderWarehouseExpandCell(rowKey, row) {
    if (!canLoadWarehouseTimeslots(row)) {
        return `<span class="text-muted small" title="${escapeHtml(WAREHOUSE_SLOTS_UNAVAILABLE_MESSAGE)}">—</span>`;
    }
    return `
        <button type="button" class="btn btn-sm btn-outline-secondary warehouse-slots-expand-btn"
                data-warehouse-key="${escapeHtml(rowKey)}"
                title="Показать таймслоты" aria-label="Показать таймслоты">
            <span class="warehouse-slots-expand-icon">▸</span>
        </button>`;
}

function isUnavailableWarehouse(row) {
    return row?.availability_state === "NOT_AVAILABLE";
}

function renderWarehouseRowHtml(row, allClusters, colspan, { hidden = false } = {}) {
    const rowKey = warehouseRowKey(row);
    const warehouseId = Number(row.storage_warehouse_id || 0);
    const reason = row.invalid_reason_label
        ? `<div class="warehouse-slots-reason">${escapeHtml(row.invalid_reason_label)}</div>`
        : "";
    const address = escapeHtml(row.address || "—");
    const clusterCell = allClusters
        ? `<td class="warehouse-slots-col-cluster warehouse-slots-cluster-name">${escapeHtml(row.cluster_name || "—")}</td>`
        : "";
    const hiddenClass = hidden ? " warehouse-slots-row--unavailable d-none" : "";

    return `
        <tr class="warehouse-slots-row${hiddenClass}" data-warehouse-key="${escapeHtml(rowKey)}" data-warehouse-id="${warehouseId}">
            <td class="warehouse-slots-col-expand text-center">
                ${renderWarehouseExpandCell(rowKey, row)}
            </td>
            ${clusterCell}
            <td class="warehouse-slots-col-name">
                <div class="fw-semibold">${escapeHtml(row.name || "—")}</div>
            </td>
            <td class="warehouse-slots-col-address warehouse-slots-address" title="${address}">${address}</td>
            <td class="text-center warehouse-slots-col-availability">
                <span class="warehouse-slots-badge ${availabilityBadgeClass(row.availability_state)}">
                    ${escapeHtml(row.availability_label || "—")}
                </span>
                ${reason}
            </td>
            <td class="text-center text-nowrap warehouse-slots-col-rank">
                ${row.total_rank != null ? `#${escapeHtml(row.total_rank)}` : "—"}
            </td>
            <td class="text-center warehouse-slots-col-watch">
                ${renderWarehouseWatchButton(rowKey, row)}
            </td>
        </tr>
        <tr class="warehouse-slots-detail-row d-none${hidden ? " warehouse-slots-row--unavailable" : ""}" data-detail-for="${escapeHtml(rowKey)}">
            <td colspan="${colspan}" class="warehouse-slots-detail-cell">
                <div class="warehouse-slots-detail-loading text-muted small">Загрузка таймслотов…</div>
                <div class="warehouse-slots-detail-content d-none"></div>
            </td>
        </tr>`;
}

function renderUnavailableWarehousesToggle(count, colspan) {
    if (!count) return "";
    return `
        <tr class="warehouse-slots-unavailable-toggle-row">
            <td colspan="${colspan}" class="warehouse-slots-unavailable-toggle-cell">
                <button type="button" class="warehouse-slots-unavailable-toggle btn btn-link btn-sm p-0">
                    <span class="warehouse-slots-unavailable-toggle-icon" aria-hidden="true">▸</span>
                    Недоступные склады (${count})
                </button>
            </td>
        </tr>`;
}

function toggleUnavailableWarehouses() {
    const body = document.getElementById("warehouse-slots-table-body");
    if (!body) return;

    const isOpen = body.dataset.unavailableOpen === "1";
    const nextOpen = !isOpen;
    body.dataset.unavailableOpen = nextOpen ? "1" : "0";

    body.querySelectorAll("tr.warehouse-slots-row.warehouse-slots-row--unavailable").forEach((row) => {
        row.classList.toggle("d-none", !nextOpen);
    });

    const icon = body.querySelector(".warehouse-slots-unavailable-toggle-icon");
    if (icon) icon.textContent = nextOpen ? "▾" : "▸";
}

function renderWarehouseSlotsTable(rows, allClusters = false) {
    const wrap = document.getElementById("warehouse-slots-table-wrap");
    const body = document.getElementById("warehouse-slots-table-body");
    const clusterCol = document.getElementById("warehouse-slots-col-cluster");
    if (!wrap || !body) return;

    if (clusterCol) clusterCol.classList.toggle("d-none", !allClusters);

    const items = Array.isArray(rows) ? rows : [];
    if (!items.length) {
        wrap.classList.add("d-none");
        body.innerHTML = "";
        warehouseSlotsState.warehousesByKey = {};
        return;
    }

    wrap.classList.remove("d-none");

    warehouseSlotsState.warehousesByKey = Object.fromEntries(
        items.map((row) => [warehouseRowKey(row), row]),
    );

    const colspan = allClusters ? 7 : 6;

    const availableRows = items.filter((row) => !isUnavailableWarehouse(row));
    const unavailableRows = items.filter((row) => isUnavailableWarehouse(row));

    const parts = [];
    for (const row of availableRows) {
        parts.push(renderWarehouseRowHtml(row, allClusters, colspan));
    }
    if (unavailableRows.length) {
        parts.push(renderUnavailableWarehousesToggle(unavailableRows.length, colspan));
        for (const row of unavailableRows) {
            parts.push(renderWarehouseRowHtml(row, allClusters, colspan, { hidden: true }));
        }
    }

    body.dataset.unavailableOpen = "0";
    body.innerHTML = parts.join("");
}

async function loadWarehouseTimeslots(rowKey, detailRow) {
    const row = warehouseSlotsState.warehousesByKey?.[rowKey];
    if (!row) return;

    const draftId = row.draft_id || warehouseSlotsState.draftId;
    const clusterId = row.cluster_id || warehouseSlotsState.clusterId;
    const macrolocalClusterId = row.macrolocal_cluster_id || warehouseSlotsState.macrolocalClusterId;
    const warehouseId = Number(row.storage_warehouse_id || 0);
    if (!draftId || !clusterId || !macrolocalClusterId || !warehouseId) return;

    const cacheKey = `${draftId}:${warehouseId}`;
    const cached = warehouseSlotsState.timeslotsCache.get(cacheKey);

    const loadingEl = detailRow.querySelector(".warehouse-slots-detail-loading");
    const contentEl = detailRow.querySelector(".warehouse-slots-detail-content");
    if (!contentEl) return;

    if (cached) {
        if (loadingEl) loadingEl.classList.add("d-none");
        contentEl.classList.remove("d-none");
        renderTimeslotsContent(contentEl, cached);
        return;
    }

    if (loadingEl) loadingEl.classList.remove("d-none");
    contentEl.classList.add("d-none");
    contentEl.innerHTML = "";

    const params = new URLSearchParams({
        draft_id: String(draftId),
        macrolocal_cluster_id: String(macrolocalClusterId),
        cluster_id: String(clusterId),
        storage_warehouse_id: String(warehouseId),
    });

    try {
        await new Promise((resolve) => setTimeout(resolve, 600));
        const res = await fetch(`/api/analytics/warehouse-slots/timeslots?${params}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
        warehouseSlotsState.timeslotsCache.set(cacheKey, data);
        renderTimeslotsContent(contentEl, data);
    } catch (err) {
        contentEl.innerHTML = `<div class="text-danger small">${escapeHtml(err.message)}</div>`;
    } finally {
        if (loadingEl) loadingEl.classList.add("d-none");
        contentEl.classList.remove("d-none");
    }
}

function toggleWarehouseTimeslots(rowKey) {
    const row = warehouseSlotsState.warehousesByKey?.[rowKey];
    if (row && !canLoadWarehouseTimeslots(row)) {
        if (typeof showToast === "function") {
            showToast(WAREHOUSE_SLOTS_UNAVAILABLE_MESSAGE, "warning");
        }
        return;
    }

    const detailRow = document.querySelector(`tr.warehouse-slots-detail-row[data-detail-for="${rowKey}"]`);
    const mainRow = document.querySelector(`tr.warehouse-slots-row[data-warehouse-key="${rowKey}"]`);
    if (!detailRow || !mainRow) return;

    const icon = mainRow.querySelector(".warehouse-slots-expand-icon");
    const isOpen = !detailRow.classList.contains("d-none");

    document.querySelectorAll(".warehouse-slots-detail-row").forEach((row) => row.classList.add("d-none"));
    document.querySelectorAll(".warehouse-slots-expand-icon").forEach((el) => {
        el.textContent = "▸";
    });

    if (isOpen) {
        warehouseSlotsState.openWarehouseKey = null;
        return;
    }

    detailRow.classList.remove("d-none");
    if (icon) icon.textContent = "▾";
    warehouseSlotsState.openWarehouseKey = rowKey;
    loadWarehouseTimeslots(rowKey, detailRow);
}

function bindWarehouseSlotsTable() {
    const body = document.getElementById("warehouse-slots-table-body");
    if (!body || body.dataset.bound === "1") return;
    body.dataset.bound = "1";

    body.addEventListener("click", (event) => {
        const unavailableToggle = event.target.closest(".warehouse-slots-unavailable-toggle");
        if (unavailableToggle) {
            toggleUnavailableWarehouses();
            return;
        }

        const btn = event.target.closest(".warehouse-slots-expand-btn");
        if (btn) {
            const rowKey = btn.dataset.warehouseKey;
            if (!rowKey) return;
            toggleWarehouseTimeslots(rowKey);
            return;
        }

        const watchBtn = event.target.closest(".warehouse-slots-watch-btn");
        if (watchBtn) {
            const rowKey = watchBtn.dataset.warehouseKey;
            if (!rowKey) return;
            toggleWarehouseWatch(rowKey).catch((err) => {
                if (typeof showToast === "function") showToast(err.message, "danger");
            });
            return;
        }
        handleTimeslotPickerClick(event);
    });
}

async function refreshWarehouseSlots() {
    const cluster = getSelectedCluster();

    const now = Date.now();
    if (now < warehouseSlotsState.refreshCooldownUntil) {
        const sec = Math.ceil((warehouseSlotsState.refreshCooldownUntil - now) / 1000);
        showWarehouseSlotsMessage(
            `Подождите ${sec} сек. перед повторным запросом к Ozon.`,
            "warning",
        );
        return;
    }

    const btn = document.getElementById("btn-warehouse-slots-refresh");
    const spinner = document.getElementById("warehouse-slots-spinner");
    showWarehouseSlotsMessage("");
    if (btn) btn.disabled = true;
    if (spinner) spinner.classList.remove("d-none");

    const payload = { force: false };
    if (cluster) {
        payload.macrolocal_cluster_id = cluster.macrolocal_cluster_id;
        payload.cluster_id = cluster.cluster_id;
    }

    try {
        const res = await fetch("/api/analytics/warehouse-slots/refresh", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);

        const preservedWatchKeys = warehouseSlotsState.watchKeys || new Set();
        const preservedWatchesByKey = warehouseSlotsState.watchesByKey || new Map();

        warehouseSlotsState = {
            draftId: data.draft_id,
            clusterId: data.cluster_id,
            macrolocalClusterId: data.macrolocal_cluster_id,
            allClusters: Boolean(data.all_clusters),
            openWarehouseKey: null,
            refreshCooldownUntil: Date.now() + (data.all_clusters ? 90000 : 45000),
            timeslotsCache: new Map(),
            warehousesByKey: {},
            watchKeys: preservedWatchKeys,
            watchesByKey: preservedWatchesByKey,
        };

        renderWarehouseSlotsSummary(data);
        renderWarehouseSlotsTable(data.warehouses, Boolean(data.all_clusters));
        bindWarehouseSlotsTable();
        updateWarehouseWatchButtons();

        if (Array.isArray(data.warnings) && data.warnings.length && typeof showToast === "function") {
            showToast(
                `Загружены не все кластеры (${data.warnings.length} с ошибкой).`,
                "warning",
            );
        } else if (data.cached && typeof showToast === "function") {
            showToast("Показаны недавно загруженные данные. Повторный запрос к Ozon будет доступен через минуту.", "info");
        } else if (data.all_clusters && typeof showToast === "function") {
            showToast("Загружены склады по всем кластерам.", "success");
        }
    } catch (err) {
        showWarehouseSlotsMessage(err.message, "danger");
        if (String(err.message || "").includes("лимит запросов")) {
            warehouseSlotsState.refreshCooldownUntil = Date.now() + 60000;
        }
    } finally {
        if (btn) btn.disabled = false;
        if (spinner) spinner.classList.add("d-none");
    }
}

function bindWarehouseSlotsMonitor() {
    const list = document.getElementById("warehouse-slots-watch-list");
    if (!list || list.dataset.bound === "1") return;
    list.dataset.bound = "1";

    list.addEventListener("click", (event) => {
        const btn = event.target.closest(".warehouse-slots-watch-remove-btn");
        if (!btn) return;
        const watchId = Number(btn.dataset.watchId);
        if (!watchId) return;
        fetch(`/api/analytics/warehouse-slots/watches/${watchId}`, {
            method: "DELETE",
            headers: { "X-Requested-With": "XMLHttpRequest" },
        })
            .then((res) => res.json())
            .then((data) => {
                if (!data.ok) throw new Error(data.error || "Ошибка удаления");
                return loadWarehouseWatches();
            })
            .catch((err) => {
                if (typeof showToast === "function") showToast(err.message, "danger");
            });
    });
}

function bindWarehouseSlotsPage() {
    const refreshBtn = document.getElementById("btn-warehouse-slots-refresh");
    if (refreshBtn && refreshBtn.dataset.bound !== "1") {
        refreshBtn.dataset.bound = "1";
        refreshBtn.addEventListener("click", () => refreshWarehouseSlots());
    }
}

function initWarehouseSlotsPage() {
    bindWarehouseSlotsPage();
    bindWarehouseSlotsMonitor();
    loadWarehouseWatches();
}

document.addEventListener("DOMContentLoaded", () => {
    if (window.location.pathname === "/analytics/warehouse-slots") {
        initWarehouseSlotsPage();
    }
});

document.addEventListener("page:loaded", (event) => {
    if (event.detail?.path === "/analytics/warehouse-slots") {
        initWarehouseSlotsPage();
    }
});
