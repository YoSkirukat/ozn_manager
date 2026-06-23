/** Регламентные задания в профиле */
let scheduledTasksLogModal = null;
let scheduledTasksLogSlug = null;

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function formatDateTime(iso) {
    if (typeof formatAppDateTime === "function") {
        return formatAppDateTime(iso);
    }
    const d = typeof parseAppDateTime === "function" ? parseAppDateTime(iso) : new Date(iso);
    if (!d || Number.isNaN(d.getTime())) return iso || "—";
    return d.toLocaleString("ru-RU", {
        timeZone: window.APP_TIMEZONE || "Europe/Moscow",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    });
}

function statusBadge(status) {
    const map = {
        success: ["Успех", "success"],
        error: ["Ошибка", "danger"],
        running: ["Выполняется", "primary"],
        skipped: ["Пропущено", "secondary"],
    };
    const [label, cls] = map[status] || [status, "secondary"];
    return `<span class="badge text-bg-${cls}">${label}</span>`;
}

function renderScheduledTasksList(tasks, intervals) {
    const root = document.getElementById("scheduled-tasks-list");
    if (!root) return;

    if (!tasks.length) {
        root.innerHTML = '<div class="text-muted small">Нет заданий.</div>';
        return;
    }

    root.innerHTML = tasks.map((task) => {
        const disabled = !task.implemented;
        const rowClass = disabled ? "scheduled-task-row scheduled-task-row--disabled" : "scheduled-task-row";
        const checked = task.enabled ? "checked" : "";
        const selectDisabled = disabled ? "disabled" : "";
        const switchDisabled = disabled ? "disabled" : "";
        const hint = disabled
            ? `<div class="small text-muted mt-1">${escapeHtml(task.description)}</div>`
            : "";

        const actionsHtml = task.implemented
            ? `<div class="scheduled-task-row-actions">
                <select class="form-select form-select-sm scheduled-task-interval"
                        data-slug="${escapeHtml(task.slug)}" ${selectDisabled}
                        aria-label="Периодичность для ${escapeHtml(task.title)}">
                    ${intervals.map((i) => {
                        const sel = i.key === task.interval_key ? "selected" : "";
                        return `<option value="${escapeHtml(i.key)}" ${sel}>${escapeHtml(i.label)}</option>`;
                    }).join("")}
                </select>
                <button type="button" class="btn btn-sm btn-outline-primary scheduled-task-run-btn"
                        data-slug="${escapeHtml(task.slug)}"
                        data-title="${escapeHtml(task.title)}"
                        title="Запустить сейчас" aria-label="Запустить задание ${escapeHtml(task.title)}">
                    <i class="bi bi-play-fill" aria-hidden="true"></i>
                </button>
                <button type="button" class="btn btn-sm btn-outline-secondary scheduled-task-log-btn"
                        data-slug="${escapeHtml(task.slug)}"
                        data-title="${escapeHtml(task.title)}">Журнал</button>
            </div>`
            : "";

        return `<div class="${rowClass}" data-task-slug="${escapeHtml(task.slug)}">
            <div class="scheduled-task-row-main">
                <div class="form-check form-switch mb-0">
                    <input class="form-check-input scheduled-task-enabled" type="checkbox"
                           id="task-enabled-${escapeHtml(task.slug)}"
                           data-slug="${escapeHtml(task.slug)}" ${checked} ${switchDisabled}>
                    <label class="form-check-label fw-semibold" for="task-enabled-${escapeHtml(task.slug)}">
                        ${escapeHtml(task.title)}
                    </label>
                </div>
                ${actionsHtml}
            </div>
            ${hint}
        </div>`;
    }).join("");

    root.querySelectorAll(".scheduled-task-enabled, .scheduled-task-interval").forEach((el) => {
        el.addEventListener("change", () => saveScheduledTaskSetting(el.dataset.slug));
    });

    root.querySelectorAll(".scheduled-task-log-btn").forEach((btn) => {
        btn.addEventListener("click", () => openScheduledTaskLog(btn.dataset.slug, btn.dataset.title));
    });

    root.querySelectorAll(".scheduled-task-run-btn").forEach((btn) => {
        btn.addEventListener("click", () => runScheduledTaskNow(btn));
    });
}

async function saveScheduledTaskSetting(slug) {
    const row = document.querySelector(`.scheduled-task-row[data-task-slug="${slug}"]`);
    if (!row) return;

    const enabledEl = row.querySelector(".scheduled-task-enabled");
    const intervalEl = row.querySelector(".scheduled-task-interval");
    if (!enabledEl || !intervalEl) return;

    enabledEl.disabled = true;
    intervalEl.disabled = true;

    try {
        const res = await fetch(`/api/profile/scheduled-tasks/${encodeURIComponent(slug)}`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify({
                enabled: enabledEl.checked,
                interval_key: intervalEl.value,
            }),
        });
        const data = await res.json();
        if (!data.ok && typeof showToast === "function") {
            showToast(data.error || "Ошибка сохранения", "danger");
            await loadScheduledTasks();
            return;
        }
        if (data.ok) {
            if (typeof showToast === "function") {
                showToast("Настройки задания сохранены", "success");
            }
            await loadScheduledTasks();
        }
    } catch (err) {
        if (typeof showToast === "function") showToast(err.message, "danger");
        await loadScheduledTasks();
    } finally {
        enabledEl.disabled = false;
        intervalEl.disabled = false;
    }
}

function updateSchedulerWarning(tasks, scheduler) {
    const warnEl = document.getElementById("scheduled-tasks-scheduler-warn");
    if (!warnEl) return;

    const scheduledSlugs = new Set((scheduler?.jobs || []).map((j) => j.task_slug));
    const missing = (tasks || []).filter(
        (t) => t.implemented && t.enabled && !scheduledSlugs.has(t.slug),
    );

    if (!scheduler?.active) {
        warnEl.textContent =
            "Планировщик не запущен. Остановите все процессы python run.py (все терминалы) и запустите снова: python run.py";
        warnEl.classList.remove("d-none");
        return;
    }

    if (!scheduler?.local && scheduler?.active) {
        warnEl.textContent =
            "Планировщик работает в другом процессе. Для разработки оставьте один python run.py и FLASK_USE_RELOADER=0 в .env.";
        warnEl.classList.remove("d-none");
        return;
    }

    if (missing.length) {
        const names = missing.map((t) => t.title).join(", ");
        warnEl.textContent =
            `В планировщике нет заданий: ${names}. Они подключатся в течение ~30 с или после пересохранения настроек.`;
        warnEl.classList.remove("d-none");
        return;
    }

    warnEl.classList.add("d-none");
    warnEl.textContent = "";
}

async function runScheduledTaskNow(btn) {
    const slug = btn?.dataset?.slug;
    const title = btn?.dataset?.title || "Задание";
    if (!slug || !btn) return;

    const row = btn.closest(".scheduled-task-row");
    const controls = row
        ? row.querySelectorAll("button, select, .scheduled-task-enabled")
        : [btn];

    controls.forEach((el) => {
        el.disabled = true;
    });
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';

    try {
        const res = await fetch(`/api/profile/scheduled-tasks/${encodeURIComponent(slug)}/run`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: "{}",
        });
        const data = await res.json();
        const text = data.message || data.error || (data.ok ? "Выполнено" : "Ошибка");
        if (typeof showToast === "function") {
            showToast(text, data.ok ? "success" : "danger");
        }
        if (scheduledTasksLogModal && scheduledTasksLogSlug === slug) {
            await loadScheduledTasksLog(slug);
        }
    } catch (err) {
        if (typeof showToast === "function") showToast(err.message, "danger");
    } finally {
        controls.forEach((el) => {
            el.disabled = false;
        });
        btn.innerHTML = '<i class="bi bi-play-fill" aria-hidden="true"></i>';
    }
}

async function loadScheduledTasks() {
    const root = document.getElementById("scheduled-tasks-list");
    if (!root) return;

    try {
        const res = await fetch("/api/profile/scheduled-tasks", {
            headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Ошибка загрузки");
        renderScheduledTasksList(data.tasks || [], data.intervals || []);
        updateSchedulerWarning(data.tasks, data.scheduler);
    } catch (err) {
        root.innerHTML = `<div class="alert alert-danger py-2 mb-0">${escapeHtml(err.message)}</div>`;
    }
}

async function loadScheduledTasksLog(taskSlug) {
    const body = document.getElementById("scheduled-tasks-log-body");
    if (!body || !taskSlug) return;

    body.innerHTML = '<tr><td colspan="3" class="text-muted text-center py-4">Загрузка…</td></tr>';

    try {
        const res = await fetch(
            `/api/profile/scheduled-tasks/runs?task_slug=${encodeURIComponent(taskSlug)}`,
            { headers: { "X-Requested-With": "XMLHttpRequest" } },
        );
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Ошибка загрузки");

        const runs = data.runs || [];
        if (!runs.length) {
            body.innerHTML = '<tr><td colspan="3" class="text-muted text-center py-4">Запусков пока нет.</td></tr>';
            return;
        }

        body.innerHTML = runs.map((run) => `<tr>
            <td class="text-nowrap small">${formatDateTime(run.started_at)}</td>
            <td>${statusBadge(run.status)}</td>
            <td class="small">${escapeHtml(run.message || "—")}</td>
        </tr>`).join("");
    } catch (err) {
        body.innerHTML = `<tr><td colspan="3" class="text-danger text-center py-4">${escapeHtml(err.message)}</td></tr>`;
    }
}

function openScheduledTaskLog(slug, title) {
    const modalEl = document.getElementById("scheduled-tasks-log-modal");
    const titleEl = document.getElementById("scheduledTasksLogLabel");
    if (!modalEl || !slug) return;

    scheduledTasksLogSlug = slug;
    if (titleEl) {
        titleEl.textContent = title ? `Журнал: ${title}` : "Журнал";
    }

    scheduledTasksLogModal = bootstrap.Modal.getOrCreateInstance(modalEl);
    loadScheduledTasksLog(slug);
    scheduledTasksLogModal.show();
}

function initScheduledTasksUi() {
    loadScheduledTasks();
}

document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("scheduled-tasks-card")) {
        initScheduledTasksUi();
    }
});
