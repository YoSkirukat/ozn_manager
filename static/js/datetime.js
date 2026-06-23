/** Форматирование дат/времени в часовом поясе приложения (Europe/Moscow). */

function parseAppDateTime(iso) {
    if (!iso) return null;
    let text = String(iso).trim();
    if (!text) return null;
    // Naive ISO из БД (SQLite) — считаем UTC
    if (!/[zZ]$|[+-]\d{2}:\d{2}$/.test(text)) {
        text = `${text}Z`;
    }
    const d = new Date(text);
    return Number.isNaN(d.getTime()) ? null : d;
}

function formatAppDateTime(iso, options = {}) {
    const d = parseAppDateTime(iso);
    if (!d) return "—";
    const tz = window.APP_TIMEZONE || "Europe/Moscow";
    return d.toLocaleString("ru-RU", {
        timeZone: tz,
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        ...options,
    });
}
