/** Страница «Заказы FBS»: период, синхронизация из Ozon, детали заказа. */

let fbsOrdersDatePicker = null;

function getFbsOrdersPeriodFromDom() {
    const input = document.getElementById("fbs-orders-date-range");
    if (!input) return { from: "", to: "" };

    const dates = fbsOrdersDatePicker?.selectedDates || [];
    if (dates.length === 2) {
        return { from: formatApiDate(dates[0]), to: formatApiDate(dates[1]) };
    }
    return { from: input.dataset.dateFrom || "", to: input.dataset.dateTo || "" };
}

function buildFbsOrdersUrl(from, to) {
    const params = new URLSearchParams();
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    const query = params.toString();
    return query ? `/fbs-orders?${query}` : "/fbs-orders";
}

function initFbsOrdersDatePicker() {
    const input = document.getElementById("fbs-orders-date-range");
    if (!input || input.disabled || typeof flatpickr === "undefined") return;

    const defaultDates = [];
    const from = parseIsoDate(input.dataset.dateFrom);
    const to = parseIsoDate(input.dataset.dateTo);
    if (from && to) defaultDates.push(from, to);

    if (fbsOrdersDatePicker) {
        fbsOrdersDatePicker.destroy();
        fbsOrdersDatePicker = null;
    }

    fbsOrdersDatePicker = flatpickr(input, {
        mode: "range",
        dateFormat: "d.m.Y",
        locale: "ru",
        maxDate: "today",
        allowInput: false,
        defaultDate: defaultDates.length === 2 ? defaultDates : undefined,
    });
}

function showFbsOrdersFromDatabase() {
    const { from, to } = getFbsOrdersPeriodFromDom();
    if (!from || !to) {
        if (typeof showToast === "function") showToast("Выберите период заказов.", "warning");
        return;
    }
    if (typeof loadPage === "function") loadPage(buildFbsOrdersUrl(from, to), true);
}

async function syncFbsOrdersFromOzon() {
    const msgEl = document.getElementById("fbs-orders-message");
    const syncBtn = document.getElementById("btn-fbs-orders-sync");
    const spinner = document.getElementById("fbs-orders-sync-spinner");
    const { from, to } = getFbsOrdersPeriodFromDom();

    if (!from || !to) {
        if (typeof showToast === "function") showToast("Выберите период заказов.", "warning");
        return;
    }

    if (syncBtn) syncBtn.disabled = true;
    if (spinner) spinner.classList.remove("d-none");
    if (msgEl) msgEl.innerHTML = "";

    try {
        const res = await fetch("/api/orders/load", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify({
                date_from: from,
                date_to: to,
                refresh_financials_batch: false,
            }),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Не удалось загрузить заказы из Ozon.");

        const message = [
            `Загружено заказов: ${data.total ?? 0}`,
            `(FBS ${data.fbs ?? 0}, FBO ${data.fbo ?? 0};`,
            `новых ${data.created ?? 0}, обновлено ${data.updated ?? 0}).`,
        ].join(" ");
        if (typeof showToast === "function") showToast(message, "success");
        if (typeof loadPage === "function") loadPage(buildFbsOrdersUrl(from, to), true);
    } catch (err) {
        const text = `Ошибка: ${err.message}`;
        if (msgEl) msgEl.innerHTML = `<div class="alert alert-danger py-2 mb-3">${text}</div>`;
        if (typeof showToast === "function") showToast(text, "danger");
    } finally {
        if (syncBtn && syncBtn.dataset.hasOzon === "1") syncBtn.disabled = false;
        if (spinner) spinner.classList.add("d-none");
    }
}

function initFbsOrdersPage() {
    initFbsOrdersDatePicker();

    const showBtn = document.getElementById("btn-fbs-orders-show");
    const syncBtn = document.getElementById("btn-fbs-orders-sync");

    if (showBtn && showBtn.dataset.bound !== "1") {
        showBtn.dataset.bound = "1";
        showBtn.addEventListener("click", showFbsOrdersFromDatabase);
    }
    if (syncBtn && syncBtn.dataset.bound !== "1") {
        syncBtn.dataset.bound = "1";
        syncBtn.addEventListener("click", syncFbsOrdersFromOzon);
    }

    // Карточка заказа открывается общей модалкой страницы «Заказы».
    if (typeof initOrderDetailLinks === "function") initOrderDetailLinks();
}

function onFbsOrdersPageReady() {
    if (typeof resetOrderDetailModal === "function") resetOrderDetailModal();
    if (typeof orderDetailRequestSeq === "number") orderDetailRequestSeq += 1;
    initFbsOrdersPage();
}

document.addEventListener("DOMContentLoaded", () => {
    if (window.location.pathname.split("?")[0] !== "/fbs-orders") return;
    onFbsOrdersPageReady();
});

document.addEventListener("page:loaded", (e) => {
    const path = (e.detail?.path || "").split("?")[0];
    if (path !== "/fbs-orders") return;
    onFbsOrdersPageReady();
});
