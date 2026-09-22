/** Страница «Заказы FBS»: сборка заказа и карточка заказа по клику на номер. */

async function assembleFbsOrder(btn) {
    const postingNumber = btn.dataset.postingNumber;
    if (!postingNumber) return;

    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';

    try {
        const res = await fetch("/api/orders/fbs/assemble", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify({ posting_number: postingNumber }),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Не удалось собрать заказ.");

        if (typeof showToast === "function") {
            showToast(data.message || "Заказ собран: статус «Ожидает отгрузки».", "success");
        }
        if (typeof loadPage === "function") {
            await loadPage("/fbs-orders", false);
        }
    } catch (err) {
        btn.disabled = false;
        btn.innerHTML = originalHtml;
        if (typeof showToast === "function") showToast(`Ошибка: ${err.message}`, "danger");
    }
}

async function downloadFbsLabel(btn) {
    const postingNumber = btn.dataset.postingNumber;
    if (!postingNumber) return;

    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';

    try {
        const url = `/api/orders/fbs/label?posting_number=${encodeURIComponent(postingNumber)}`;
        const res = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
        const contentType = res.headers.get("content-type") || "";

        if (contentType.includes("application/json")) {
            const data = await res.json();
            throw new Error(data.error || "Не удалось получить этикетку.");
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const blob = await res.blob();
        const blobUrl = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = blobUrl;
        link.download = `label-${postingNumber}.pdf`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(blobUrl);

        if (typeof showToast === "function") {
            showToast(`Этикетка ${postingNumber} загружена.`, "success");
        }
    } catch (err) {
        if (typeof showToast === "function") showToast(`Ошибка: ${err.message}`, "danger");
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalHtml;
    }
}

async function refreshFbsOrdersList() {
    const btn = document.getElementById("btn-fbs-orders-refresh");
    if (!btn || btn.disabled) return;

    const dateFrom = btn.dataset.dateFrom || "";
    const dateTo = btn.dataset.dateTo || "";
    const spinner = document.getElementById("fbs-orders-refresh-spinner");
    const icon = document.getElementById("fbs-orders-refresh-icon");

    btn.disabled = true;
    if (spinner) spinner.classList.remove("d-none");
    if (icon) icon.classList.add("d-none");

    try {
        const res = await fetch("/api/orders/fbs/refresh", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify({ date_from: dateFrom, date_to: dateTo }),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Не удалось обновить заказы.");

        if (typeof showToast === "function") {
            showToast(data.message || "Список заказов обновлён.", "success");
        }

        // Перерисовываем только содержимое страницы — без перезагрузки браузера.
        if (typeof loadPage === "function") {
            const query = dateFrom && dateTo
                ? `?from=${encodeURIComponent(dateFrom)}&to=${encodeURIComponent(dateTo)}`
                : "";
            await loadPage(`/fbs-orders${query}`, false);
        }
    } catch (err) {
        if (typeof showToast === "function") showToast(`Ошибка: ${err.message}`, "danger");
    } finally {
        // DOM мог быть перерисован — берём актуальные элементы.
        const freshBtn = document.getElementById("btn-fbs-orders-refresh");
        const freshSpinner = document.getElementById("fbs-orders-refresh-spinner");
        const freshIcon = document.getElementById("fbs-orders-refresh-icon");
        if (freshBtn) freshBtn.disabled = false;
        if (freshSpinner) freshSpinner.classList.add("d-none");
        if (freshIcon) freshIcon.classList.remove("d-none");
    }
}

function initFbsOrdersRefreshButton() {
    const btn = document.getElementById("btn-fbs-orders-refresh");
    if (!btn || btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", refreshFbsOrdersList);
}

function initFbsOrderActions() {
    const root = document.getElementById("main-content");
    if (!root || root.dataset.fbsActionsBound === "1") return;
    root.dataset.fbsActionsBound = "1";
    root.addEventListener("click", (e) => {
        const assembleBtn = e.target.closest(".fbs-assemble-btn");
        if (assembleBtn) {
            e.preventDefault();
            assembleFbsOrder(assembleBtn);
            return;
        }
        const labelBtn = e.target.closest(".fbs-label-btn");
        if (labelBtn) {
            e.preventDefault();
            downloadFbsLabel(labelBtn);
        }
    });
}

function initFbsOrdersPage() {
    // Период на странице фиксированный (месяц), данные обновляются кнопкой «Обновить».
    initFbsOrdersRefreshButton();
    initFbsOrderActions();
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
