/** Страница «Заказы FBS»: карточка заказа по клику на номер отправления. */

function initFbsOrdersPage() {
    // Период на странице фиксированный (месяц), данные обновляются синхронизацией и перезагрузкой.
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
