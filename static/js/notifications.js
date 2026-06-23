/** Колокольчик уведомлений в шапке */
const NOTIFICATIONS_POLL_MS = 60000;
const BROWSER_NOTIF_STORAGE_KEY = "ozn_notifications_last_browser_id";

let notificationsPollTimer = null;
let notificationsLastUnread = 0;
let notificationsBaselineReady = false;

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function formatNotificationTime(iso) {
    if (typeof formatAppDateTime === "function") {
        return formatAppDateTime(iso);
    }
    const d = typeof parseAppDateTime === "function" ? parseAppDateTime(iso) : new Date(iso);
    if (!d || Number.isNaN(d.getTime())) return iso || "—";
    return d.toLocaleString("ru-RU", {
        timeZone: window.APP_TIMEZONE || "Europe/Moscow",
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });
}

function browserNotificationsSupported() {
    return typeof window !== "undefined" && "Notification" in window;
}

function browserNotificationPermission() {
    if (!browserNotificationsSupported()) return "unsupported";
    return Notification.permission;
}

async function requestBrowserNotificationPermission() {
    if (!browserNotificationsSupported()) return "unsupported";
    if (Notification.permission === "granted") return "granted";
    if (Notification.permission === "denied") return "denied";
    return Notification.requestPermission();
}

function getLastBrowserNotifiedId() {
    return Number(localStorage.getItem(BROWSER_NOTIF_STORAGE_KEY) || 0);
}

function setLastBrowserNotifiedId(id) {
    localStorage.setItem(BROWSER_NOTIF_STORAGE_KEY, String(Math.max(0, Number(id) || 0)));
}

function showBrowserNotification(item) {
    if (browserNotificationPermission() !== "granted" || !item) return;

    const notification = new Notification(item.title || "Ozon Manager", {
        body: item.body || "",
        icon: "/favicon.ico",
        tag: `ozn-notification-${item.id}`,
    });

    notification.onclick = () => {
        window.focus();
        notification.close();
        navigateToNotification(item.target_url);
    };
}

function notifyNewBrowserNotifications(items) {
    if (browserNotificationPermission() !== "granted") return;

    const lastId = getLastBrowserNotifiedId();
    const fresh = (items || [])
        .filter((item) => !item.is_read && Number(item.id) > lastId)
        .sort((a, b) => Number(a.id) - Number(b.id));

    for (const item of fresh) {
        showBrowserNotification(item);
        setLastBrowserNotifiedId(Math.max(getLastBrowserNotifiedId(), Number(item.id)));
    }
}

function baselineBrowserNotificationsFromItems(items, unreadCount) {
    const ids = (items || []).map((item) => Number(item.id) || 0);
    const maxId = ids.length ? Math.max(...ids) : 0;
    if (maxId > getLastBrowserNotifiedId()) {
        setLastBrowserNotifiedId(maxId);
    }
    notificationsLastUnread = Number(unreadCount) || 0;
    notificationsBaselineReady = true;
}

function updateNotificationsBadge(count) {
    const badge = document.getElementById("notifications-unread-badge");
    if (!badge) return;
    const value = Math.max(0, Number(count) || 0);
    badge.textContent = value > 99 ? "99+" : String(value);
    badge.classList.toggle("d-none", value <= 0);
}

function renderNotificationsDropdown(items) {
    const root = document.getElementById("notifications-dropdown-list");
    if (!root) return;

    if (!items.length) {
        root.innerHTML = '<div class="text-muted small text-center py-3">Нет уведомлений</div>';
        return;
    }

    root.innerHTML = items.map((item) => {
        const unreadClass = item.is_read ? "" : " notifications-item--unread";
        return `
        <div class="notifications-item${unreadClass}" data-notification-id="${item.id}">
            <a href="${escapeHtml(item.target_url || "#")}" class="notifications-item-link"
               data-notification-id="${item.id}" data-target-url="${escapeHtml(item.target_url || "")}">
                <div class="notifications-item-title">${escapeHtml(item.title)}</div>
                <div class="notifications-item-body">${escapeHtml(item.body)}</div>
                <div class="notifications-item-time">${escapeHtml(formatNotificationTime(item.created_at))}</div>
            </a>
            <div class="notifications-item-actions">
                ${item.is_read ? "" : `
                <button type="button" class="notifications-action-btn notifications-mark-read-btn"
                        data-notification-id="${item.id}"
                        title="Пометить прочитанным" aria-label="Пометить прочитанным">
                    <i class="bi bi-check2" aria-hidden="true"></i>
                </button>`}
                <button type="button" class="notifications-action-btn notifications-delete-btn"
                        data-notification-id="${item.id}"
                        title="Удалить" aria-label="Удалить">
                    <i class="bi bi-trash" aria-hidden="true"></i>
                </button>
            </div>
        </div>`;
    }).join("");
}

async function fetchNotificationsList(limit = 50) {
    const res = await fetch(`/api/notifications?limit=${limit}`, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
}

async function fetchNotificationsUnreadCount() {
    const res = await fetch("/api/notifications/unread-count", {
        headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return Number(data.unread_count) || 0;
}

async function loadNotificationsDropdown() {
    const data = await fetchNotificationsList(50);
    renderNotificationsDropdown(data.items || []);
    updateNotificationsBadge(data.unread_count);
    notificationsLastUnread = Number(data.unread_count) || 0;
}

async function baselineNotifications() {
    try {
        const data = await fetchNotificationsList(50);
        updateNotificationsBadge(data.unread_count);
        baselineBrowserNotificationsFromItems(data.items, data.unread_count);
    } catch (_err) {
        notificationsBaselineReady = true;
        try {
            notificationsLastUnread = await fetchNotificationsUnreadCount();
            updateNotificationsBadge(notificationsLastUnread);
        } catch (_innerErr) {
            // тихий старт
        }
    }
}

async function pollNotifications() {
    if (!document.getElementById("notifications-nav-item")) return;
    if (!notificationsBaselineReady) return;

    try {
        const count = await fetchNotificationsUnreadCount();
        if (count > notificationsLastUnread) {
            const data = await fetchNotificationsList(20);
            notifyNewBrowserNotifications(data.items);
            if (typeof showToast === "function") {
                showToast("Новое уведомление", "info");
            }
        }
        notificationsLastUnread = count;
        updateNotificationsBadge(count);
    } catch (_err) {
        // тихий опрос
    }
}

async function markNotificationRead(notificationId) {
    const res = await fetch(`/api/notifications/${notificationId}/read`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    await loadNotificationsDropdown();
}

async function markAllNotificationsRead() {
    const res = await fetch("/api/notifications/read-all", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    await loadNotificationsDropdown();
}

async function deleteNotification(notificationId) {
    const res = await fetch(`/api/notifications/${notificationId}`, {
        method: "DELETE",
        headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    await loadNotificationsDropdown();
}

async function deleteAllNotifications() {
    const res = await fetch("/api/notifications/clear-all", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    await loadNotificationsDropdown();
}

function navigateToNotification(targetUrl) {
    if (!targetUrl) return;
    if (targetUrl.startsWith("/")) {
        window.location.assign(targetUrl);
        return;
    }
    window.location.assign(targetUrl);
}

function browserPermissionLabel(permission) {
    if (permission === "granted") return "Разрешены";
    if (permission === "denied") return "Заблокированы в браузере";
    if (permission === "default") return "Не запрошены";
    return "Недоступны в этом браузере";
}

function updateBrowserNotificationPermissionUI() {
    const statusEl = document.getElementById("notification-browser-status");
    const btn = document.getElementById("btn-notification-browser-enable");
    if (!statusEl && !btn) return;

    const permission = browserNotificationPermission();
    if (statusEl) {
        statusEl.textContent = browserPermissionLabel(permission);
    }
    if (btn) {
        btn.disabled = permission === "unsupported" || permission === "granted" || permission === "denied";
        btn.textContent = permission === "granted"
            ? "Разрешено"
            : permission === "denied"
                ? "Заблокировано"
                : "Разрешить";
        btn.classList.toggle("btn-outline-primary", permission === "default");
        btn.classList.toggle("btn-outline-secondary", permission !== "default");
    }
}

function bindNotificationsNav() {
    const item = document.getElementById("notifications-nav-item");
    if (!item || item.dataset.bound === "1") return;
    item.dataset.bound = "1";

    const dropdownToggle = document.getElementById("notifications-nav-dropdown");
    if (dropdownToggle) {
        dropdownToggle.addEventListener("show.bs.dropdown", () => {
            loadNotificationsDropdown().catch((err) => {
                const root = document.getElementById("notifications-dropdown-list");
                if (root) {
                    root.innerHTML = `<div class="text-danger small text-center py-3">${escapeHtml(err.message)}</div>`;
                }
            });
        });
    }

    item.addEventListener("click", async (event) => {
        const readAllBtn = event.target.closest(".notifications-read-all-btn");
        if (readAllBtn) {
            event.preventDefault();
            try {
                await markAllNotificationsRead();
            } catch (err) {
                if (typeof showToast === "function") showToast(err.message, "danger");
            }
            return;
        }

        const clearAllBtn = event.target.closest(".notifications-clear-all-btn");
        if (clearAllBtn) {
            event.preventDefault();
            try {
                await deleteAllNotifications();
            } catch (err) {
                if (typeof showToast === "function") showToast(err.message, "danger");
            }
            return;
        }

        const markReadBtn = event.target.closest(".notifications-mark-read-btn");
        if (markReadBtn) {
            event.preventDefault();
            event.stopPropagation();
            const id = Number(markReadBtn.dataset.notificationId);
            if (!id) return;
            try {
                await markNotificationRead(id);
            } catch (err) {
                if (typeof showToast === "function") showToast(err.message, "danger");
            }
            return;
        }

        const deleteBtn = event.target.closest(".notifications-delete-btn");
        if (deleteBtn) {
            event.preventDefault();
            event.stopPropagation();
            const id = Number(deleteBtn.dataset.notificationId);
            if (!id) return;
            try {
                await deleteNotification(id);
            } catch (err) {
                if (typeof showToast === "function") showToast(err.message, "danger");
            }
            return;
        }

        const link = event.target.closest(".notifications-item-link");
        if (link) {
            event.preventDefault();
            const id = Number(link.dataset.notificationId);
            const targetUrl = link.dataset.targetUrl || link.getAttribute("href");
            if (id) {
                try {
                    await markNotificationRead(id);
                } catch (_err) {
                    // переход всё равно выполним
                }
            }
            navigateToNotification(targetUrl);
        }
    });
}

async function initNotifications() {
    if (!document.getElementById("notifications-nav-item")) return;
    bindNotificationsNav();
    updateBrowserNotificationPermissionUI();
    await baselineNotifications();
    if (notificationsPollTimer) clearInterval(notificationsPollTimer);
    notificationsPollTimer = setInterval(pollNotifications, NOTIFICATIONS_POLL_MS);
}

window.OznNotifications = {
    browserNotificationsSupported,
    browserNotificationPermission,
    requestBrowserNotificationPermission,
    updateBrowserNotificationPermissionUI,
    showTestBrowserNotification() {
        showBrowserNotification({
            id: "test",
            title: "Ozon Manager",
            body: "Уведомления браузера включены",
            target_url: "/",
        });
    },
};

document.addEventListener("DOMContentLoaded", () => {
    initNotifications();
});
