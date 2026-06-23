/**
 * SPA-подобная навигация: подгрузка фрагментов в #main-content без полной перезагрузки.
 */

const mainEl = document.getElementById("main-content");
const loaderEl = document.getElementById("page-loader");
const toastContainer = document.getElementById("toast-container");

function showLoader(show = true) {
    if (!loaderEl) return;
    loaderEl.classList.toggle("d-none", !show);
}

function showToast(message, variant = "primary") {
    if (!toastContainer) return;
    const id = `toast-${Date.now()}`;
    const html = [
        `<div id="${id}" class="toast align-items-center text-bg-${variant} border-0" role="alert">`,
        '<div class="d-flex">',
        `<div class="toast-body">${message}</div>`,
        '<button type="button" class="btn-close btn-close-white me-2 m-auto"',
        ' data-bs-dismiss="toast" aria-label="Закрыть"></button>',
        "</div>",
        "</div>",
    ].join("");
    toastContainer.insertAdjacentHTML("beforeend", html);
    const el = document.getElementById(id);
    const toast = bootstrap.Toast.getOrCreateInstance(el, { delay: 4000 });
    toast.show();
    el.addEventListener("hidden.bs.toast", () => el.remove());
}

function navLinkPrefixes(link) {
    const raw = link.dataset.navPrefixes || link.dataset.navPrefix || "";
    return raw.split(",").map((part) => part.trim()).filter(Boolean);
}

function setActiveNav(path) {
    document.querySelectorAll(
        "#app-nav .nav-link, #app-nav .dropdown-item, #user-nav .nav-link, #user-nav .dropdown-item"
    ).forEach((link) => {
        if (link.classList.contains("dropdown-toggle")) {
            const prefixes = navLinkPrefixes(link);
            link.classList.toggle("active", prefixes.some((prefix) => path.startsWith(prefix)));
            return;
        }
        const nav = link.dataset.nav;
        const href = link.getAttribute("href");
        const matchPath = nav || (href && href.startsWith("/") ? href.split("?")[0] : null);
        if (!matchPath) return;
        link.classList.toggle(
            "active",
            path === matchPath || (matchPath !== "/" && path.startsWith(`${matchPath}/`))
        );
    });
}

const FULL_PAGE_PREFIXES = ["/login", "/register", "/logout", "/profile", "/admin"];

function applyMainContentLayout(pathname) {
    if (!mainEl) return;
    const wide = pathname === "/products";
    mainEl.classList.toggle("container-fluid", wide);
    mainEl.classList.toggle("container", !wide);
    mainEl.classList.toggle("main-content--products", wide);
    mainEl.classList.toggle("px-3", wide);
    mainEl.classList.toggle("px-md-4", wide);
}

async function loadPage(path, pushState = true) {
    if (!mainEl || FULL_PAGE_PREFIXES.some((p) => path.startsWith(p))) {
        window.location.href = path;
        return;
    }
    showLoader(true);
    try {
        const res = await fetch(path, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
            cache: "no-store",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const html = await res.text();
        mainEl.innerHTML = html;
        const titleEl = mainEl.querySelector("[data-page-title]");
        const pageTitle = titleEl ? titleEl.dataset.pageTitle : null;
        if (pageTitle) {
            document.title = pageTitle;
        }
        if (pushState) history.pushState({ path, title: pageTitle || document.title }, "", path);
        const pathname = path.split("?")[0];
        applyMainContentLayout(pathname);
        setActiveNav(pathname);
        document.dispatchEvent(new CustomEvent("page:loaded", { detail: { path: pathname } }));
        if (pathname === "/" && typeof loadDashboardStats === "function") {
            loadDashboardStats();
        }
    } catch (err) {
        showToast(`Ошибка загрузки: ${err.message}`, "danger");
    } finally {
        showLoader(false);
    }
}

document.addEventListener("click", (e) => {
    const link = e.target.closest("[data-nav]");
    if (!link || e.metaKey || e.ctrlKey) return;
    const path = link.getAttribute("href") || link.dataset.nav;
    if (!path || path === "#" || path.startsWith("http")) return;
    e.preventDefault();
    loadPage(path);
});

window.addEventListener("popstate", (e) => {
    const path = (e.state && e.state.path) || (window.location.pathname + window.location.search);
    if (e.state && e.state.title) {
        document.title = e.state.title;
    }
    loadPage(path, false);
});

document.addEventListener("DOMContentLoaded", () => {
    setActiveNav(window.location.pathname);
    applyMainContentLayout(window.location.pathname);
});
