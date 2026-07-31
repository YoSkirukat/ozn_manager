/** Эксперименты с ценами — список, деталь, добавление товаров, срезы. */

let peCreateModal = null;
let peAddProductModal = null;
let peCommentModal = null;
let peEditModal = null;
let peRemoveItemModal = null;
let peMinPriceModal = null;
let pePendingPriceInput = null;
let peSearchTimer = null;
/** @type {Map<number, {id:number, name:string, offer_id:string, barcode:string}>} */
let peSelectedProducts = new Map();

function peEscapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function peShowMessage(text, variant = "danger") {
    const el = document.getElementById("price-experiments-message");
    if (!el) return;
    el.innerHTML = `<div class="alert alert-${variant} py-2">${peEscapeHtml(text)}</div>`;
}

function peCurrentExperimentId() {
    const root = document.getElementById("price-experiments-page");
    const raw = root?.dataset.experimentId || "";
    return raw ? Number(raw) : null;
}

function peReload(path) {
    if (typeof loadPage === "function") {
        loadPage(path, false);
    } else {
        window.location.href = path;
    }
}

async function peApi(url, options = {}) {
    const res = await fetch(url, {
        headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            ...(options.headers || {}),
        },
        ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
        throw new Error(data.error || data.message || `Ошибка ${res.status}`);
    }
    return data;
}

function peEnsureModals() {
    if (typeof bootstrap === "undefined") return;
    const createEl = document.getElementById("pe-create-modal");
    const addEl = document.getElementById("pe-add-product-modal");
    const commentEl = document.getElementById("pe-comment-modal");
    const editEl = document.getElementById("pe-edit-modal");
    const removeEl = document.getElementById("pe-remove-item-modal");
    const minPriceEl = document.getElementById("pe-min-price-modal");
    if (createEl) peCreateModal = bootstrap.Modal.getOrCreateInstance(createEl);
    if (addEl) peAddProductModal = bootstrap.Modal.getOrCreateInstance(addEl);
    if (commentEl) peCommentModal = bootstrap.Modal.getOrCreateInstance(commentEl);
    if (editEl) peEditModal = bootstrap.Modal.getOrCreateInstance(editEl);
    if (removeEl) peRemoveItemModal = bootstrap.Modal.getOrCreateInstance(removeEl);
    if (minPriceEl) peMinPriceModal = bootstrap.Modal.getOrCreateInstance(minPriceEl);
}

function peOpenEditModal(title, note) {
    const titleInput = document.getElementById("pe-edit-title");
    const noteInput = document.getElementById("pe-edit-note");
    if (titleInput) titleInput.value = title || "";
    if (noteInput) noteInput.value = note || "";
    peEditModal?.show();
}

function peBindListActions() {
    document.querySelectorAll(".pe-delete-experiment").forEach((btn) => {
        if (btn.dataset.bound === "1") return;
        btn.dataset.bound = "1";
        btn.addEventListener("click", async () => {
            const id = btn.dataset.id;
            const title = btn.dataset.title || "эксперимент";
            if (!id || !window.confirm(`Удалить эксперимент «${title}» вместе со всеми срезами?`)) {
                return;
            }
            try {
                await peApi(`/api/analytics/price-experiments/${id}`, { method: "DELETE" });
                if (typeof showToast === "function") showToast("Эксперимент удалён", "success");
                peReload("/analytics/price-experiments");
            } catch (err) {
                peShowMessage(err.message);
                if (typeof showToast === "function") showToast(err.message, "danger");
            }
        });
    });

    const createBtn = document.getElementById("btn-pe-create");
    if (createBtn && createBtn.dataset.bound !== "1") {
        createBtn.dataset.bound = "1";
        createBtn.addEventListener("click", () => {
            const title = document.getElementById("pe-create-title");
            const note = document.getElementById("pe-create-note");
            if (title) title.value = "";
            if (note) note.value = "";
            peCreateModal?.show();
        });
    }

    const createSubmit = document.getElementById("pe-create-submit");
    if (createSubmit && createSubmit.dataset.bound !== "1") {
        createSubmit.dataset.bound = "1";
        createSubmit.addEventListener("click", async () => {
            const title = (document.getElementById("pe-create-title")?.value || "").trim();
            const note = (document.getElementById("pe-create-note")?.value || "").trim();
            if (!title) {
                if (typeof showToast === "function") showToast("Укажите название", "warning");
                return;
            }
            createSubmit.disabled = true;
            try {
                const data = await peApi("/api/analytics/price-experiments", {
                    method: "POST",
                    body: JSON.stringify({ title, note }),
                });
                peCreateModal?.hide();
                const id = data.experiment?.id;
                peReload(id ? `/analytics/price-experiments?id=${id}` : "/analytics/price-experiments");
            } catch (err) {
                peShowMessage(err.message);
                if (typeof showToast === "function") showToast(err.message, "danger");
            } finally {
                createSubmit.disabled = false;
            }
        });
    }
}

function peRenderSelectedProducts() {
    const list = document.getElementById("pe-selected-products-list");
    const countEl = document.getElementById("pe-selected-count");
    const submit = document.getElementById("pe-add-product-submit");
    if (countEl) countEl.textContent = String(peSelectedProducts.size);
    if (submit) submit.disabled = peSelectedProducts.size === 0;
    if (!list) return;

    if (!peSelectedProducts.size) {
        list.innerHTML = `<div class="text-muted small pe-selected-empty">Пока пусто — нажмите товар в результатах поиска</div>`;
        return;
    }

    list.innerHTML = Array.from(peSelectedProducts.values())
        .map(
            (p) => `
        <div class="pe-selected-item" data-id="${p.id}">
            <div class="min-w-0 flex-grow-1">
                <div class="fw-semibold text-truncate">${peEscapeHtml(p.name)}</div>
                <div class="small text-muted font-monospace text-truncate">
                    ${peEscapeHtml(p.offer_id || "—")} · ${peEscapeHtml(p.barcode || "—")}
                </div>
            </div>
            <button type="button" class="btn btn-link pe-icon-btn pe-icon-btn--danger p-0 pe-selected-remove"
                    data-id="${p.id}" title="Убрать из списка" aria-label="Убрать из списка">
                <i class="bi bi-x-lg" aria-hidden="true"></i>
            </button>
        </div>`
        )
        .join("");

    list.querySelectorAll(".pe-selected-remove").forEach((btn) => {
        btn.addEventListener("click", () => {
            const id = Number(btn.dataset.id);
            peSelectedProducts.delete(id);
            peRenderSelectedProducts();
            peMarkSearchSelectionState();
        });
    });
}

function peMarkSearchSelectionState() {
    document.querySelectorAll("#pe-product-search-results .pe-search-item").forEach((btn) => {
        const id = Number(btn.dataset.id);
        btn.classList.toggle("is-selected", peSelectedProducts.has(id));
    });
}

function peRenderSearchResults(products) {
    const wrap = document.getElementById("pe-product-search-results");
    if (!wrap) return;
    if (!products.length) {
        wrap.innerHTML = `<div class="text-muted small p-2">Ничего не найдено</div>`;
        return;
    }
    wrap.innerHTML = products
        .map(
            (p) => `
        <button type="button" class="pe-search-item${peSelectedProducts.has(p.id) ? " is-selected" : ""}"
                data-id="${p.id}"
                data-name="${peEscapeHtml(p.name)}"
                data-offer="${peEscapeHtml(p.offer_id || "—")}"
                data-barcode="${peEscapeHtml(p.barcode || "—")}">
            <div class="fw-semibold text-truncate">${peEscapeHtml(p.name)}</div>
            <div class="small text-muted">
                ${peEscapeHtml(p.offer_id)} · ${peEscapeHtml(p.barcode || "—")} ·
                FBO ${p.stock_fbo} · FBS ${p.stock_fbs}
            </div>
        </button>`
        )
        .join("");

    wrap.querySelectorAll(".pe-search-item").forEach((btn) => {
        btn.addEventListener("click", () => {
            const id = Number(btn.dataset.id);
            if (!id) return;
            if (peSelectedProducts.has(id)) {
                peSelectedProducts.delete(id);
            } else {
                peSelectedProducts.set(id, {
                    id,
                    name: btn.dataset.name || "",
                    offer_id: btn.dataset.offer || "—",
                    barcode: btn.dataset.barcode || "—",
                });
            }
            peRenderSelectedProducts();
            peMarkSearchSelectionState();
        });
    });
}

function peNormalizePriceInput(value) {
    return String(value || "")
        .trim()
        .replace(/\s+/g, "")
        .replace(",", ".");
}

async function pePatchSalePrice(itemId, price, lowerMinPrice = false) {
    const res = await fetch(`/api/analytics/price-experiments/items/${itemId}/price`, {
        method: "PATCH",
        headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({ price, lower_min_price: lowerMinPrice }),
    });
    const data = await res.json().catch(() => ({}));
    return { res, data };
}

function peShowMinPriceConfirm(input, data) {
    pePendingPriceInput = input;
    const textEl = document.getElementById("pe-min-price-modal-text");
    const itemInput = document.getElementById("pe-min-price-item-id");
    const priceInput = document.getElementById("pe-min-price-new-price");
    const minDisplay = data.min_price_display || data.min_price || "—";
    if (textEl) {
        textEl.textContent =
            `Установленная вами цена ниже указанной минимальной цены (${minDisplay} ₽). ` +
            "Изменить минимальную цену на указанную вами?";
    }
    if (itemInput) itemInput.value = input.dataset.itemId || "";
    if (priceInput) priceInput.value = peNormalizePriceInput(input.value);
    peMinPriceModal?.show();
}

function peCancelMinPriceConfirm() {
    if (pePendingPriceInput) {
        pePendingPriceInput.value = pePendingPriceInput.dataset.savedValue || "";
        pePendingPriceInput.classList.remove("is-error", "is-saving");
        pePendingPriceInput.dataset.saving = "0";
    }
    pePendingPriceInput = null;
}

async function peSaveSalePrice(input, { lowerMinPrice = false } = {}) {
    const itemId = input.dataset.itemId;
    if (!itemId || input.dataset.saving === "1") return;

    const newValue = peNormalizePriceInput(input.value);
    const oldValue = input.dataset.savedValue ?? "";
    if (newValue === oldValue && !lowerMinPrice) return;

    const experimentId = peCurrentExperimentId();
    input.dataset.saving = "1";
    input.classList.add("is-saving");
    input.classList.remove("is-error");

    try {
        const { res, data } = await pePatchSalePrice(itemId, newValue, lowerMinPrice);
        if (data.needs_min_price_confirm) {
            input.dataset.saving = "0";
            input.classList.remove("is-saving");
            peShowMinPriceConfirm(input, data);
            return;
        }
        if (!res.ok || data.ok === false) {
            throw new Error(data.error || data.message || `Ошибка ${res.status}`);
        }
        if (data.unchanged) {
            input.value = data.price_display || input.value;
            input.dataset.savedValue = peNormalizePriceInput(data.price_display || input.value);
            return;
        }
        if (typeof showToast === "function") {
            showToast(data.message || "Цена обновлена", data.warning ? "warning" : "success");
        }
        if (experimentId) {
            peReload(`/analytics/price-experiments?id=${experimentId}`);
        }
    } catch (err) {
        input.classList.add("is-error");
        input.value = input.dataset.savedValue || "";
        peShowMessage(err.message);
        if (typeof showToast === "function") showToast(err.message, "danger");
    } finally {
        input.dataset.saving = "0";
        input.classList.remove("is-saving");
    }
}

function peBindSalePriceInputs(root) {
    const scope = root || document;
    scope.querySelectorAll(".pe-sale-price-input").forEach((input) => {
        if (input.dataset.bound === "1") return;
        input.dataset.bound = "1";
        input.dataset.savedValue = peNormalizePriceInput(input.value);

        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                input.blur();
            } else if (e.key === "Escape") {
                input.value = input.dataset.savedValue || "";
                input.classList.remove("is-error");
                input.blur();
            }
        });

        input.addEventListener("blur", () => {
            peSaveSalePrice(input);
        });

        input.addEventListener("click", (e) => {
            e.stopPropagation();
        });
    });
}

function peBindDetailActions() {
    const experimentId = peCurrentExperimentId();
    if (!experimentId) return;

    const openEditFromBtn = (btn) => {
        peOpenEditModal(btn.dataset.title || "", btn.dataset.note || "");
    };

    ["btn-pe-edit-title", "btn-pe-edit-note"].forEach((id) => {
        const btn = document.getElementById(id);
        if (!btn || btn.dataset.bound === "1") return;
        btn.dataset.bound = "1";
        btn.addEventListener("click", () => openEditFromBtn(btn));
    });

    const runToggle = document.getElementById("btn-pe-run-toggle");
    if (runToggle && runToggle.dataset.bound !== "1") {
        runToggle.dataset.bound = "1";
        runToggle.addEventListener("click", async () => {
            const root = document.getElementById("price-experiments-page");
            const currentlyRunning = root?.dataset.experimentRunning === "1";
            const nextRunning = !currentlyRunning;
            runToggle.disabled = true;
            try {
                const data = await peApi(`/api/analytics/price-experiments/${experimentId}`, {
                    method: "PATCH",
                    body: JSON.stringify({ running: nextRunning }),
                });
                if (typeof showToast === "function") {
                    showToast(data.message || (nextRunning ? "Запущен" : "Остановлен"), "success");
                }
                peReload(`/analytics/price-experiments?id=${experimentId}`);
            } catch (err) {
                peShowMessage(err.message);
                if (typeof showToast === "function") showToast(err.message, "danger");
                runToggle.disabled = false;
            }
        });
    }

    const editSubmit = document.getElementById("pe-edit-submit");
    if (editSubmit && editSubmit.dataset.bound !== "1") {
        editSubmit.dataset.bound = "1";
        editSubmit.addEventListener("click", async () => {
            const title = (document.getElementById("pe-edit-title")?.value || "").trim();
            const note = (document.getElementById("pe-edit-note")?.value || "").trim();
            if (!title) {
                if (typeof showToast === "function") showToast("Укажите название", "warning");
                return;
            }
            editSubmit.disabled = true;
            try {
                await peApi(`/api/analytics/price-experiments/${experimentId}`, {
                    method: "PATCH",
                    body: JSON.stringify({ title, note }),
                });
                peEditModal?.hide();
                if (typeof showToast === "function") showToast("Сохранено", "success");
                peReload(`/analytics/price-experiments?id=${experimentId}`);
            } catch (err) {
                peShowMessage(err.message);
                if (typeof showToast === "function") showToast(err.message, "danger");
            } finally {
                editSubmit.disabled = false;
            }
        });
    }

    document.querySelectorAll(".pe-toggle-history").forEach((btn) => {
        if (btn.dataset.bound === "1") return;
        btn.dataset.bound = "1";
        btn.addEventListener("click", () => {
            const itemId = btn.dataset.itemId;
            const row = document.querySelector(`.pe-history-row[data-history-for="${itemId}"]`);
            if (!row) return;
            const open = row.classList.toggle("d-none") === false;
            btn.classList.toggle("is-open", open);
            btn.setAttribute("aria-expanded", open ? "true" : "false");
            if (open) peBindSalePriceInputs(row);
        });
    });

    peBindSalePriceInputs(document.getElementById("price-experiments-page"));

    document.querySelectorAll(".pe-remove-item").forEach((btn) => {
        if (btn.dataset.bound === "1") return;
        btn.dataset.bound = "1";
        btn.addEventListener("click", () => {
            const itemId = btn.dataset.itemId || "";
            const idInput = document.getElementById("pe-remove-item-id");
            if (idInput) idInput.value = itemId;
            peRemoveItemModal?.show();
        });
    });

    const removeConfirm = document.getElementById("pe-remove-item-confirm");
    if (removeConfirm && removeConfirm.dataset.bound !== "1") {
        removeConfirm.dataset.bound = "1";
        removeConfirm.addEventListener("click", async () => {
            const itemId = document.getElementById("pe-remove-item-id")?.value;
            if (!itemId) return;
            removeConfirm.disabled = true;
            try {
                await peApi(`/api/analytics/price-experiments/items/${itemId}`, { method: "DELETE" });
                peRemoveItemModal?.hide();
                peReload(`/analytics/price-experiments?id=${experimentId}`);
            } catch (err) {
                peShowMessage(err.message);
                if (typeof showToast === "function") showToast(err.message, "danger");
            } finally {
                removeConfirm.disabled = false;
            }
        });
    }

    const minPriceConfirm = document.getElementById("pe-min-price-confirm");
    if (minPriceConfirm && minPriceConfirm.dataset.bound !== "1") {
        minPriceConfirm.dataset.bound = "1";
        minPriceConfirm.addEventListener("click", async () => {
            const input = pePendingPriceInput;
            const price = document.getElementById("pe-min-price-new-price")?.value;
            // Сбрасываем до hide, чтобы hidden.bs.modal не откатил значение
            pePendingPriceInput = null;
            if (!input || !price) {
                peMinPriceModal?.hide();
                return;
            }
            minPriceConfirm.disabled = true;
            try {
                peMinPriceModal?.hide();
                input.value = price;
                await peSaveSalePrice(input, { lowerMinPrice: true });
            } finally {
                minPriceConfirm.disabled = false;
            }
        });
    }

    const minPriceModalEl = document.getElementById("pe-min-price-modal");
    if (minPriceModalEl && minPriceModalEl.dataset.bound !== "1") {
        minPriceModalEl.dataset.bound = "1";
        minPriceModalEl.addEventListener("hidden.bs.modal", () => {
            if (pePendingPriceInput) {
                peCancelMinPriceConfirm();
            }
        });
    }

    document.querySelectorAll(".pe-edit-comment").forEach((btn) => {
        if (btn.dataset.bound === "1") return;
        btn.dataset.bound = "1";
        btn.addEventListener("click", () => {
            const itemId = btn.dataset.itemId || "";
            const comment = btn.dataset.comment || "";
            const idInput = document.getElementById("pe-comment-item-id");
            const commentInput = document.getElementById("pe-comment-input");
            if (idInput) idInput.value = itemId;
            if (commentInput) commentInput.value = comment;
            peCommentModal?.show();
        });
    });

    const commentSubmit = document.getElementById("pe-comment-submit");
    if (commentSubmit && commentSubmit.dataset.bound !== "1") {
        commentSubmit.dataset.bound = "1";
        commentSubmit.addEventListener("click", async () => {
            const itemId = document.getElementById("pe-comment-item-id")?.value;
            const comment = document.getElementById("pe-comment-input")?.value || "";
            if (!itemId) return;
            try {
                await peApi(`/api/analytics/price-experiments/items/${itemId}`, {
                    method: "PATCH",
                    body: JSON.stringify({ comment }),
                });
                peCommentModal?.hide();
                peReload(`/analytics/price-experiments?id=${experimentId}`);
            } catch (err) {
                peShowMessage(err.message);
            }
        });
    }

    const addBtn = document.getElementById("btn-pe-add-product");
    if (addBtn && addBtn.dataset.bound !== "1") {
        addBtn.dataset.bound = "1";
        addBtn.addEventListener("click", () => {
            const search = document.getElementById("pe-product-search");
            const results = document.getElementById("pe-product-search-results");
            const comment = document.getElementById("pe-product-comment");
            peSelectedProducts = new Map();
            peRenderSelectedProducts();
            if (search) search.value = "";
            if (results) results.innerHTML = "";
            if (comment) comment.value = "";
            peAddProductModal?.show();
            search?.focus();
        });
    }

    const searchInput = document.getElementById("pe-product-search");
    if (searchInput && searchInput.dataset.bound !== "1") {
        searchInput.dataset.bound = "1";
        searchInput.addEventListener("input", () => {
            clearTimeout(peSearchTimer);
            const q = searchInput.value.trim();
            if (q.length < 2) {
                const results = document.getElementById("pe-product-search-results");
                if (results) results.innerHTML = "";
                return;
            }
            peSearchTimer = setTimeout(async () => {
                try {
                    const data = await peApi(
                        `/api/analytics/price-experiments/products/search?q=${encodeURIComponent(q)}`
                    );
                    peRenderSearchResults(data.products || []);
                } catch (err) {
                    peShowMessage(err.message);
                }
            }, 250);
        });
    }

    const addSubmit = document.getElementById("pe-add-product-submit");
    if (addSubmit && addSubmit.dataset.bound !== "1") {
        addSubmit.dataset.bound = "1";
        addSubmit.addEventListener("click", async () => {
            const productIds = Array.from(peSelectedProducts.keys());
            const comment = document.getElementById("pe-product-comment")?.value || "";
            if (!productIds.length) return;
            addSubmit.disabled = true;
            try {
                const data = await peApi(`/api/analytics/price-experiments/${experimentId}/products`, {
                    method: "POST",
                    body: JSON.stringify({ product_ids: productIds, comment }),
                });
                peAddProductModal?.hide();
                if (typeof showToast === "function") {
                    showToast(data.message || "Товары добавлены", "success");
                }
                peReload(`/analytics/price-experiments?id=${experimentId}`);
            } catch (err) {
                peShowMessage(err.message);
                if (typeof showToast === "function") showToast(err.message, "danger");
                addSubmit.disabled = peSelectedProducts.size === 0;
            }
        });
    }

    const snapBtn = document.getElementById("btn-pe-snapshot-now");
    if (snapBtn && snapBtn.dataset.bound !== "1") {
        snapBtn.dataset.bound = "1";
        snapBtn.addEventListener("click", async () => {
            const spinner = document.getElementById("pe-snapshot-spinner");
            snapBtn.disabled = true;
            spinner?.classList.remove("d-none");
            try {
                const data = await peApi("/api/analytics/price-experiments/snapshot", {
                    method: "POST",
                    body: JSON.stringify({ experiment_id: experimentId }),
                });
                if (typeof showToast === "function") {
                    showToast(data.message || "Срез сохранён", "success");
                }
                peReload(`/analytics/price-experiments?id=${experimentId}`);
            } catch (err) {
                peShowMessage(err.message);
                if (typeof showToast === "function") showToast(err.message, "danger");
            } finally {
                snapBtn.disabled = false;
                spinner?.classList.add("d-none");
            }
        });
    }
}

function initPriceExperimentsPage() {
    const root = document.getElementById("price-experiments-page");
    if (!root) return;
    peEnsureModals();
    peBindListActions();
    peBindDetailActions();
}

document.addEventListener("DOMContentLoaded", () => {
    const path = window.location.pathname.split("?")[0];
    if (path === "/analytics/price-experiments") initPriceExperimentsPage();
});

document.addEventListener("page:loaded", (e) => {
    const path = (e.detail?.path || "").split("?")[0];
    if (path !== "/analytics/price-experiments") return;
    [
        "btn-pe-create",
        "pe-create-submit",
        "btn-pe-add-product",
        "pe-add-product-submit",
        "pe-comment-submit",
        "btn-pe-snapshot-now",
        "pe-product-search",
        "btn-pe-edit-title",
        "btn-pe-edit-note",
        "pe-edit-submit",
        "pe-remove-item-confirm",
        "pe-min-price-confirm",
        "btn-pe-run-toggle",
    ].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.dataset.bound = "";
    });
    document.querySelectorAll(
        ".pe-delete-experiment, .pe-toggle-history, .pe-remove-item, .pe-edit-comment, .pe-sale-price-input"
    ).forEach((el) => {
        el.dataset.bound = "";
    });
    initPriceExperimentsPage();
});
