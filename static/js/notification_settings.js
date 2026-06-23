/** Настройки уведомлений в профиле */

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function renderNotificationSettingsList(settings) {
    const root = document.getElementById("notification-settings-list");
    if (!root) return;

    if (!settings.length) {
        root.innerHTML = '<div class="text-muted small">Нет типов уведомлений.</div>';
        return;
    }

    root.innerHTML = settings.map((item) => {
        const disabled = !item.implemented;
        const rowClass = disabled ? "notification-setting-row notification-setting-row--disabled" : "notification-setting-row";
        const checked = item.enabled ? "checked" : "";
        const switchDisabled = disabled ? "disabled" : "";
        return `
        <div class="${rowClass}">
            <div class="notification-setting-row-main">
                <div class="fw-semibold">${escapeHtml(item.title)}</div>
                <div class="small text-muted">${escapeHtml(item.description)}</div>
            </div>
            <div class="form-check form-switch mb-0 notification-setting-switch">
                <input class="form-check-input notification-setting-toggle" type="checkbox"
                       id="notification-setting-${escapeHtml(item.slug)}"
                       data-slug="${escapeHtml(item.slug)}"
                       ${checked} ${switchDisabled}
                       aria-label="Включить уведомление ${escapeHtml(item.title)}">
            </div>
        </div>`;
    }).join("");
}

async function loadNotificationSettings() {
    const res = await fetch("/api/notifications/settings", {
        headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    renderNotificationSettingsList(data.settings || []);
}

async function updateNotificationSetting(slug, enabled) {
    const res = await fetch(`/api/notifications/settings/${encodeURIComponent(slug)}`, {
        method: "PUT",
        headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({ enabled }),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    if (typeof showToast === "function") {
        showToast(enabled ? "Уведомление включено" : "Уведомление отключено", "success");
    }
}

function bindNotificationSettings() {
    const root = document.getElementById("notification-settings-list");
    if (!root || root.dataset.bound === "1") return;
    root.dataset.bound = "1";

    root.addEventListener("change", async (event) => {
        const input = event.target.closest(".notification-setting-toggle");
        if (!input || input.disabled) return;
        const slug = input.dataset.slug;
        if (!slug) return;
        const enabled = input.checked;
        try {
            await updateNotificationSetting(slug, enabled);
            if (enabled && window.OznNotifications?.browserNotificationPermission?.() === "default") {
                const permission = await window.OznNotifications.requestBrowserNotificationPermission();
                window.OznNotifications?.updateBrowserNotificationPermissionUI?.();
                if (permission === "granted" && typeof showToast === "function") {
                    showToast("Уведомления браузера включены", "success");
                }
            }
        } catch (err) {
            input.checked = !enabled;
            if (typeof showToast === "function") showToast(err.message, "danger");
        }
    });

    const browserBtn = document.getElementById("btn-notification-browser-enable");
    if (browserBtn && browserBtn.dataset.bound !== "1") {
        browserBtn.dataset.bound = "1";
        browserBtn.addEventListener("click", async () => {
            if (!window.OznNotifications?.requestBrowserNotificationPermission) return;
            try {
                const permission = await window.OznNotifications.requestBrowserNotificationPermission();
                window.OznNotifications.updateBrowserNotificationPermissionUI?.();
                if (permission === "granted") {
                    window.OznNotifications.showTestBrowserNotification?.();
                    if (typeof showToast === "function") {
                        showToast("Уведомления браузера включены", "success");
                    }
                } else if (permission === "denied" && typeof showToast === "function") {
                    showToast("Браузер заблокировал уведомления. Разрешите их в настройках сайта.", "warning");
                }
            } catch (err) {
                if (typeof showToast === "function") showToast(err.message, "danger");
            }
        });
    }
}

function initNotificationSettingsPage() {
    const card = document.getElementById("notification-settings-card");
    if (!card) return;
    bindNotificationSettings();
    window.OznNotifications?.updateBrowserNotificationPermissionUI?.();
    loadNotificationSettings().catch((err) => {
        const root = document.getElementById("notification-settings-list");
        if (root) {
            root.innerHTML = `<div class="text-danger small">${escapeHtml(err.message)}</div>`;
        }
    });
}

document.addEventListener("DOMContentLoaded", initNotificationSettingsPage);
