// Script pour le dashboard administrateur

let currentDeleteId = null;
let filtersDebounceTimer = null;
let dashboardListPage = 1;
let dashboardTicketModalInstance = null;
let dashboardTicketViewId = null;
const QR_PER_PAGE = Math.min(100, Math.max(5, Number(document.body?.dataset?.qrPerPage || 15)));
const DASHBOARD_REFRESH_MS = Math.max(
    5000,
    Number(document.body?.dataset?.dashboardRefreshMs || 120000)
);

function scheduleQrReload(delayMs = 350) {
    if (filtersDebounceTimer) clearTimeout(filtersDebounceTimer);
    dashboardListPage = 1;
    renderDashboardFilterChips();
    filtersDebounceTimer = setTimeout(loadQRCodes, delayMs);
}

function formatDashboardChipDate(iso) {
    if (!iso || iso.length < 10) return iso || '';
    const parts = iso.slice(0, 10).split('-');
    if (parts.length !== 3) return iso;
    return `${parts[2]}/${parts[1]}/${parts[0]}`;
}

/** Pastilles des filtres non par défaut (dashboard). */
function renderDashboardFilterChips() {
    const wrap = document.getElementById('dashboardFilterChipsWrap');
    const container = document.getElementById('dashboardFilterChips');
    const clearAllBtn = document.getElementById('dashboardClearFiltersBtn');
    if (!wrap || !container) return;

    const chips = [];

    const fv = document.getElementById('filterSelect')?.value || 'all';
    const flab = document.getElementById('filterSelect_label')?.textContent?.trim() || '';
    if (fv !== 'all') {
        chips.push({ key: 'filter', label: 'Statut : ' + flab });
    }

    const search = document.getElementById('searchInput')?.value?.trim() || '';
    if (search) {
        chips.push({ key: 'search', label: 'Recherche : ' + search });
    }

    const ticket = document.getElementById('ticketInput')?.value?.trim() || '';
    if (ticket) {
        chips.push({ key: 'ticket', label: 'N° ticket : ' + ticket });
    }

    const dateFrom = document.getElementById('dateFrom')?.value || '';
    if (dateFrom) {
        chips.push({ key: 'dateFrom', label: 'Créé du ' + formatDashboardChipDate(dateFrom) });
    }

    const dateTo = document.getElementById('dateTo')?.value || '';
    if (dateTo) {
        chips.push({ key: 'dateTo', label: 'Créé au ' + formatDashboardChipDate(dateTo) });
    }

    container.textContent = '';
    chips.forEach(function (c) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'dashboard-filter-chip';
        btn.setAttribute('data-chip-key', c.key);
        btn.title = 'Retirer ce filtre';
        const span = document.createElement('span');
        span.textContent = c.label;
        const icon = document.createElement('i');
        icon.className = 'bi bi-x-lg';
        icon.setAttribute('aria-hidden', 'true');
        btn.appendChild(span);
        btn.appendChild(icon);
        btn.addEventListener('click', function () {
            clearDashboardChip(c.key);
        });
        container.appendChild(btn);
    });

    const hasChips = chips.length > 0;
    wrap.classList.toggle('d-none', !hasChips);
    if (clearAllBtn) {
        clearAllBtn.classList.toggle('d-none', !hasChips);
    }
}

function clearDashboardChip(key) {
    dashboardListPage = 1;
    if (key === 'filter') {
        const h = document.getElementById('filterSelect');
        const lab = document.getElementById('filterSelect_label');
        if (h) h.value = 'all';
        if (lab) lab.textContent = 'Tous';
    } else if (key === 'search') {
        const el = document.getElementById('searchInput');
        if (el) el.value = '';
    } else if (key === 'ticket') {
        const el = document.getElementById('ticketInput');
        if (el) el.value = '';
    } else if (key === 'dateFrom') {
        const el = document.getElementById('dateFrom');
        if (el) el.value = '';
    } else if (key === 'dateTo') {
        const el = document.getElementById('dateTo');
        if (el) el.value = '';
    }
    renderDashboardFilterChips();
    loadQRCodes();
}

function clearAllDashboardFilters() {
    dashboardListPage = 1;
    const h = document.getElementById('filterSelect');
    const lab = document.getElementById('filterSelect_label');
    if (h) h.value = 'all';
    if (lab) lab.textContent = 'Tous';
    const searchInput = document.getElementById('searchInput');
    if (searchInput) searchInput.value = '';
    const ticketInput = document.getElementById('ticketInput');
    if (ticketInput) ticketInput.value = '';
    const df = document.getElementById('dateFrom');
    if (df) df.value = '';
    const dt = document.getElementById('dateTo');
    if (dt) dt.value = '';
    renderDashboardFilterChips();
    loadQRCodes();
}

function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function escapeAttr(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/'/g, '&#39;');
}

function paymentModeLabel(code) {
    const m = String(code || '').trim().toLowerCase();
    const map = { especes: 'Espèces', orange_money: 'Orange Money', wave: 'Wave' };
    return map[m] || (code ? String(code) : '-');
}

function redirectToLoginIfUnauthorized(response) {
    if (response.status === 401) {
        window.location.href = '/login?next=' + encodeURIComponent('/dashboard');
        return true;
    }
    return false;
}

/** Message lisible pour l'échec du chargement liste (évite "Erreur interne" opaque). */
function userFacingListError(status, message) {
    const m = String(message || '').trim();
    if (m === 'Erreur interne' || !m) {
        if (status === 403 || status === 503) {
            return "Impossible d'accéder à la base Firestore. Vérifiez les rôles IAM du compte de service (ex. Cloud Datastore User).";
        }
        return 'Impossible de charger les données.';
    }
    if (/firestore|IAM|permission/i.test(m)) {
        return m;
    }
    return m;
}

function getFilterQueryString() {
    const params = new URLSearchParams();
    params.set('filter', document.getElementById('filterSelect').value);
    const search = document.getElementById('searchInput').value.trim();
    const ticket = document.getElementById('ticketInput').value.trim();
    const dateFrom = document.getElementById('dateFrom').value;
    const dateTo = document.getElementById('dateTo').value;
    if (search) params.set('search', search);
    if (ticket) params.set('ticket', ticket);
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    params.set('page', String(dashboardListPage));
    params.set('per_page', String(QR_PER_PAGE));
    return params.toString();
}

async function downloadExport(format) {
    try {
        const qs = getFilterQueryString();
        const response = await fetch(`/api/export_qr?format=${encodeURIComponent(format)}&${qs}`);
        if (redirectToLoginIfUnauthorized(response)) return;
        if (!response.ok) {
            showToast('Erreur', 'Export impossible', 'danger');
            return;
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = format === 'xlsx' ? 'qr_codes_export.xlsx' : 'qr_codes_export.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('Succès', 'Fichier téléchargé', 'success');
    } catch (e) {
        console.error(e);
        showToast('Erreur', 'Export échoué', 'danger');
    }
}

document.addEventListener('DOMContentLoaded', function() {
    loadQRCodes();

    const createQrLink = document.getElementById('dashboardCreateQrLink');
    const homeUrl = document.body?.dataset?.appHome || '/';
    if (createQrLink && !createQrLink.getAttribute('href')) {
        createQrLink.setAttribute('href', homeUrl);
    }

    const filterHidden = document.getElementById('filterSelect');
    document.querySelectorAll('.dash-dd-opt').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const val = this.dataset.value;
            const lab = this.dataset.label;
            if (filterHidden) filterHidden.value = val;
            const labelEl = document.getElementById('filterSelect_label');
            if (labelEl) labelEl.textContent = lab;
            const toggle = document.getElementById('filterSelect_toggle');
            if (toggle && window.bootstrap?.Dropdown) {
                const inst = bootstrap.Dropdown.getInstance(toggle);
                if (inst) inst.hide();
            }
            if (filterHidden) filterHidden.dispatchEvent(new Event('change'));
        });
    });

    if (filterHidden) {
        filterHidden.addEventListener('change', function() {
            scheduleQrReload(150);
        });
    }
    document.getElementById('refreshBtn').addEventListener('click', loadQRCodes);
    document.getElementById('applyFiltersBtn').addEventListener('click', function () {
        dashboardListPage = 1;
        renderDashboardFilterChips();
        loadQRCodes();
    });

    const dashboardClearFiltersBtn = document.getElementById('dashboardClearFiltersBtn');
    if (dashboardClearFiltersBtn) {
        dashboardClearFiltersBtn.addEventListener('click', clearAllDashboardFilters);
    }

    const qrPagePrev = document.getElementById('qrPagePrev');
    const qrPageNext = document.getElementById('qrPageNext');
    if (qrPagePrev) {
        qrPagePrev.addEventListener('click', function () {
            if (dashboardListPage > 1) {
                dashboardListPage -= 1;
                loadQRCodes();
            }
        });
    }
    if (qrPageNext) {
        qrPageNext.addEventListener('click', function () {
            dashboardListPage += 1;
            loadQRCodes();
        });
    }

    const exportCsvBtn = document.getElementById('exportCsvBtn');
    const exportXlsxBtn = document.getElementById('exportXlsxBtn');
    if (exportCsvBtn) exportCsvBtn.addEventListener('click', () => downloadExport('csv'));
    if (exportXlsxBtn) exportXlsxBtn.addEventListener('click', () => downloadExport('xlsx'));

    ['searchInput', 'ticketInput', 'dateFrom', 'dateTo'].forEach(function(id) {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', function() {
                scheduleQrReload(350);
            });
            el.addEventListener('change', function() {
                scheduleQrReload(150);
            });
            el.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    if (filtersDebounceTimer) clearTimeout(filtersDebounceTimer);
                    renderDashboardFilterChips();
                    loadQRCodes();
                }
            });
        }
    });

    document.getElementById('confirmDeleteBtn').addEventListener('click', confirmDelete);

    renderDashboardFilterChips();

    const dashboardTicketPrintBtn = document.getElementById('dashboardTicketPrintBtn');
    if (dashboardTicketPrintBtn) {
        dashboardTicketPrintBtn.addEventListener('click', function () {
            if (dashboardTicketViewId) {
                reprintQRCode(dashboardTicketViewId);
            }
        });
    }

    const dashboardTicketDownloadBtn = document.getElementById('dashboardTicketDownloadBtn');
    if (dashboardTicketDownloadBtn) {
        dashboardTicketDownloadBtn.addEventListener('click', function () {
            downloadDashboardTicketPng();
        });
    }

    const dashboardTicketModal = document.getElementById('dashboardTicketModal');
    if (dashboardTicketModal) {
        dashboardTicketModal.addEventListener('shown.bs.modal', function () {
            scheduleDashboardTicketModalScale();
            setTimeout(scheduleDashboardTicketModalScale, 50);
        });
    }
    let dashboardTicketScaleResizeT = null;
    window.addEventListener('resize', function () {
        clearTimeout(dashboardTicketScaleResizeT);
        dashboardTicketScaleResizeT = setTimeout(scheduleDashboardTicketModalScale, 100);
    });
    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', scheduleDashboardTicketModalScale);
    }
    const dashboardTicketScaleOuter = document.querySelector('#dashboardTicketModal .ticket-modal-scale-outer');
    if (dashboardTicketScaleOuter && typeof ResizeObserver !== 'undefined') {
        new ResizeObserver(function () {
            scheduleDashboardTicketModalScale();
        }).observe(dashboardTicketScaleOuter);
    }

    setInterval(loadQRCodes, DASHBOARD_REFRESH_MS);
});

async function loadQRCodes() {
    const tbody = document.getElementById('qrTableBody');
    const qs = getFilterQueryString();

        tbody.innerHTML = `
            <tr>
                <td colspan="10" class="text-center">
                <div class="spinner-border spinner-dashboard" role="status">
                    <span class="visually-hidden">Chargement...</span>
                </div>
            </td>
        </tr>
    `;

    try {
        const response = await fetch('/api/list_qr?' + qs);
        if (redirectToLoginIfUnauthorized(response)) return;

        let data = {};
        try {
            data = await response.json();
        } catch (e) {
            data = {};
        }

        if (response.ok && data.success) {
            const list = Array.isArray(data.qr_codes) ? data.qr_codes : [];
            const pg = data.pagination || null;
            if (pg && typeof pg.page === 'number') {
                dashboardListPage = pg.page;
            }
            const rowOffset = pg ? (pg.page - 1) * (pg.per_page || QR_PER_PAGE) : 0;
            displayQRCodes(list, rowOffset);
            if (data.stats && typeof data.stats.total === 'number') {
                updateStatistics(data.stats);
            } else {
                updateStatisticsFromList(list);
            }
            renderQrPagination(pg);
        } else {
            const msg = userFacingListError(response.status, data.error);
            document.getElementById('statTotal').textContent = '0';
            document.getElementById('statActive').textContent = '0';
            document.getElementById('statExpired').textContent = '0';
            renderQrPagination(null);
            tbody.innerHTML = `
                <tr>
                    <td colspan="10" class="text-center text-danger">
                        ${escapeHtml(msg)}
                    </td>
                </tr>
            `;
        }
    } catch (error) {
        console.error('Erreur:', error);
        document.getElementById('statTotal').textContent = '0';
        document.getElementById('statActive').textContent = '0';
        document.getElementById('statExpired').textContent = '0';
        renderQrPagination(null);
        tbody.innerHTML = `
            <tr>
                <td colspan="10" class="text-center text-danger">
                    Erreur de connexion au serveur
                </td>
            </tr>
        `;
    }
}

function renderQrPagination(pg) {
    const nav = document.getElementById('qrPaginationNav');
    const info = document.getElementById('qrPaginationInfo');
    const ul = document.getElementById('qrPaginationUl');
    const compact = document.getElementById('qrPaginationCompact');
    const prevBtn = document.getElementById('qrPagePrev');
    const nextBtn = document.getElementById('qrPageNext');
    if (!nav || !info || !ul || !prevBtn || !nextBtn) return;

    if (!pg || !pg.total || pg.total_pages <= 1) {
        nav.classList.add('d-none');
        ul.innerHTML = '';
        if (compact) {
            compact.classList.add('d-none');
            compact.textContent = '';
        }
        return;
    }

    nav.classList.remove('d-none');

    const from = (pg.page - 1) * pg.per_page + 1;
    const to = Math.min(pg.page * pg.per_page, pg.total);
    info.innerHTML = `Affichage <strong>${from}–${to}</strong> sur <strong>${escapeHtml(String(pg.total))}</strong>`;

    prevBtn.disabled = pg.page <= 1;
    nextBtn.disabled = pg.page >= pg.total_pages;

    if (pg.total_pages <= 12) {
        ul.classList.remove('d-none');
        if (compact) compact.classList.add('d-none');
        ul.innerHTML = '';
        for (let n = 1; n <= pg.total_pages; n++) {
            const li = document.createElement('li');
            li.className = 'page-item' + (n === pg.page ? ' active' : '');
            const a = document.createElement('a');
            a.className = 'page-link';
            a.href = '#';
            a.textContent = String(n);
            a.addEventListener('click', function (e) {
                e.preventDefault();
                dashboardListPage = n;
                loadQRCodes();
            });
            li.appendChild(a);
            ul.appendChild(li);
        }
    } else {
        ul.classList.add('d-none');
        ul.innerHTML = '';
        if (compact) {
            compact.classList.remove('d-none');
            compact.textContent = `Page ${pg.page} / ${pg.total_pages}`;
        }
    }
}

function displayQRCodes(qrCodes, rowOffset) {
    const tbody = document.getElementById('qrTableBody');
    const list = Array.isArray(qrCodes) ? qrCodes : [];
    const base = Number(rowOffset) || 0;

    if (list.length === 0) {
        const home = escapeAttr(document.body?.dataset?.appHome || '/');
        tbody.innerHTML = `
            <tr>
                <td colspan="10" class="text-center empty-state">
                    <i class="bi bi-inbox"></i>
                    <p class="mt-3 mb-0">Aucune donnée</p>
                    <a href="${home}" class="btn btn-sm btn-primary mt-3 text-white text-decoration-none">Créer un QR code</a>
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = list.map((qr, index) => {
        const rowNum = base + index + 1;
        const createdDate = escapeHtml(new Date(qr.created_at).toLocaleString('fr-FR'));
        const expirationDate = escapeHtml(new Date(qr.expiration_date).toLocaleString('fr-FR'));
        const clientNameRaw = `${qr.client_name || ''} ${qr.client_firstname || ''}`.trim() || 'N/A';
        const clientName = escapeHtml(clientNameRaw);
        const phone = escapeHtml(qr.client_phone || '-');
        const ticket = qr.ticket_number ? '#' + escapeHtml(qr.ticket_number) : '-';
        const payment = escapeHtml(paymentModeLabel(qr.payment_mode));
        const service = escapeHtml(qr.service || '-');
        const emailRaw = (qr.client_email || '').trim();
        const rowTip = [
            'N° affiché: ' + rowNum,
            'ID technique: ' + (qr.id || ''),
            'Client: ' + clientNameRaw,
            'Tél: ' + (qr.client_phone || ''),
            'Email: ' + emailRaw,
            (qr.client_address || '').trim() ? 'Adresse: ' + (qr.client_address || '') : '',
            'Ticket: ' + (qr.ticket_number || ''),
            'Prestation: ' + (qr.subscription_type || ''),
            'Détail: ' + (qr.service || ''),
            'Paiement: ' + paymentModeLabel(qr.payment_mode),
            'Créé: ' + (qr.created_at || ''),
            'Expire: ' + (qr.expiration_date || ''),
            qr.is_expired ? 'Statut: Expiré' : 'Statut: Actif'
        ].filter(Boolean).join(' | ');
        // Pas de title sur la ligne si QR inutilisable : sinon au survol du bouton Imprimer désactivé le navigateur affiche ce bloc entier.
        const rowTitleAttr =
            qr.is_expired || qr.is_active === false ? '' : ` title="${escapeAttr(rowTip)}"`;

        let statusBadge;
        if (qr.is_active === false && !qr.is_expired) {
            statusBadge = '<span class="badge bg-secondary">Révoqué</span>';
        } else if (qr.is_expired) {
            statusBadge = '<span class="badge bg-danger">Expiré</span>';
        } else {
            statusBadge = '<span class="badge bg-success">Actif</span>';
        }

        return `
            <tr${rowTitleAttr}>
                <td class="text-center align-middle fw-semibold text-muted">${rowNum}</td>
                <td class="text-start align-middle" title="${escapeAttr(clientNameRaw)}">${clientName}</td>
                <td class="text-start align-middle" title="${escapeAttr(qr.client_phone || '')}">${phone}</td>
                <td class="text-start align-middle" title="${escapeAttr(qr.ticket_number || '')}">${ticket}</td>
                <td class="text-start align-middle" title="${escapeAttr(qr.payment_mode || '')}">${payment}</td>
                <td class="text-start align-middle" title="${escapeAttr((qr.subscription_type || '') + (qr.service ? ' — ' + qr.service : ''))}">${service}</td>
                <td class="text-start align-middle" title="${escapeAttr(qr.created_at || '')}"><small>${createdDate}</small></td>
                <td class="text-start align-middle" title="${escapeAttr(qr.expiration_date || '')}"><small>${expirationDate}</small></td>
                <td class="text-center align-middle td-qr-statut">${statusBadge}</td>
                <td class="text-center align-middle td-qr-actions">
                    <div class="btn-group btn-group-sm" role="group">
                        <button type="button" class="btn btn-outline-primary"
                                onclick="viewQRCode('${qr.id}')"
                                title="Voir">
                            <i class="bi bi-eye"></i>
                        </button>
                        <button type="button" class="btn btn-outline-success"
                                onclick="reprintQRCode('${qr.id}')"
                                title="Réimprimer"
                                ${qr.is_expired || qr.is_active === false ? 'disabled' : ''}>
                            <i class="bi bi-printer"></i>
                        </button>
                        <button type="button" class="btn btn-outline-danger"
                                onclick="deleteQRCode('${qr.id}')"
                                title="Supprimer">
                            <i class="bi bi-trash"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function updateStatistics(stats) {
    const total = stats.total ?? 0;
    const active = stats.active ?? 0;
    const expired = stats.expired ?? 0;
    document.getElementById('statTotal').textContent = total;
    document.getElementById('statActive').textContent = active;
    document.getElementById('statExpired').textContent = expired;
}

/** Fallback si l’API ne renvoie pas stats (rétrocompat). */
function updateStatisticsFromList(qrCodes) {
    const total = qrCodes.length;
    const active = qrCodes.filter(qr => !qr.is_expired && qr.is_active).length;
    const expired = qrCodes.filter(qr => qr.is_expired || !qr.is_active).length;
    document.getElementById('statTotal').textContent = total;
    document.getElementById('statActive').textContent = active;
    document.getElementById('statExpired').textContent = expired;
}

/**
 * Affiche le ticket complet dans une modale (même rendu que la page d’accueil).
 */
function renderDashboardTicketSheet(container, payload) {
    if (!container || !payload) return;
    container.classList.add('ticket-receipt-modern');
    container.innerHTML = '';

    const lastTicketPreviewBefore = payload.ticket_preview_before_qr || [];
    const lastTicketPreviewAfter = payload.ticket_preview_after_qr || [];
    const currentQRImage = payload.qr_image || '';

    const hasSegments =
        (lastTicketPreviewBefore && lastTicketPreviewBefore.length) ||
        (lastTicketPreviewAfter && lastTicketPreviewAfter.length);

    if (hasSegments) {
        const beforeLines = lastTicketPreviewBefore.slice();
        const titleLine = beforeLines.length ? (beforeLines[0] || '').trim() : '';
        const bodyBeforeLines = beforeLines.length ? beforeLines.slice(1) : [];

        if (titleLine) {
            const titleEl = document.createElement('div');
            titleEl.className = 'ticket-preview-title';
            titleEl.textContent = titleLine;
            container.appendChild(titleEl);
        }

        const preTop = document.createElement('pre');
        preTop.className = 'ticket-preview-pre ticket-preview-fragment mb-0';
        preTop.textContent = bodyBeforeLines.join('\n');

        const qrSlot = document.createElement('div');
        qrSlot.className = 'ticket-preview-qr-slot';
        if (currentQRImage) {
            const img = document.createElement('img');
            img.src = 'data:image/png;base64,' + currentQRImage;
            img.alt = 'QR Code du ticket';
            img.className = 'ticket-preview-qr-img';
            img.width = 200;
            img.height = 200;
            qrSlot.appendChild(img);
        } else {
            qrSlot.innerHTML = '<span class="text-muted small">QR non disponible</span>';
        }

        const afterLines = lastTicketPreviewAfter.slice();
        const scanIdx = afterLines.findIndex(function (line) {
            return (line || '').includes('SCANNEZ');
        });
        const rightOfQrLines = scanIdx >= 0 ? afterLines.slice(0, scanIdx) : afterLines;
        const bottomLines = scanIdx >= 0 ? afterLines.slice(scanIdx) : [];
        const rightMaxChars = 16;

        function wrapSideLine(line, maxChars) {
            const src = (line || '').trim();
            if (!src) return [''];
            if (src.length <= maxChars) return [src];
            const words = src.split(/\s+/);
            const out = [];
            let current = '';
            for (let wi = 0; wi < words.length; wi++) {
                const w = words[wi];
                if (!current) {
                    current = w;
                    continue;
                }
                if ((current.length + 1 + w.length) <= maxChars) {
                    current += ' ' + w;
                } else {
                    out.push(current);
                    current = w;
                }
            }
            if (current) out.push(current);
            return out;
        }

        const rightFormatted = [];
        rightOfQrLines.forEach(function (line) {
            rightFormatted.push.apply(rightFormatted, wrapSideLine(line, rightMaxChars));
        });

        const qrRow = document.createElement('div');
        qrRow.className = 'ticket-preview-qr-row';
        qrRow.appendChild(qrSlot);

        if (rightFormatted.length) {
            const preRight = document.createElement('pre');
            preRight.className = 'ticket-preview-pre ticket-preview-fragment ticket-preview-side mb-0';
            preRight.textContent = rightFormatted.join('\n');
            qrRow.appendChild(preRight);
        }

        container.appendChild(preTop);
        container.appendChild(qrRow);
        if (bottomLines.length) {
            const preBot = document.createElement('pre');
            preBot.className = 'ticket-preview-pre ticket-preview-fragment ticket-preview-bottom mb-0';
            preBot.textContent = bottomLines.join('\n');
            container.appendChild(preBot);
        }
    } else {
        container.innerHTML =
            '<p class="text-muted text-center small mb-0">Aperçu du ticket indisponible.</p>';
    }
}

/** Même logique que scheduleTicketScale sur l’accueil : ticket entier visible sur mobile. */
function scheduleDashboardTicketModalScale() {
    if (typeof applyProportionalTicketScale !== 'function') return;
    const modalEl = document.getElementById('dashboardTicketModal');
    const outer = document.querySelector('#dashboardTicketModal .ticket-modal-scale-outer');
    if (!modalEl || !outer || !modalEl.classList.contains('show')) return;
    requestAnimationFrame(function () {
        requestAnimationFrame(function () {
            applyProportionalTicketScale(outer);
        });
    });
}

async function viewQRCode(qrId) {
    const modalEl = document.getElementById('dashboardTicketModal');
    const sheet = document.getElementById('dashboardTicketPreview');
    const titleEl = document.getElementById('dashboardTicketModalLabel');
    if (!modalEl || !sheet) return;

    dashboardTicketViewId = qrId;
    sheet.innerHTML =
        '<div class="text-center py-5"><div class="spinner-border text-primary" role="status">' +
        '<span class="visually-hidden">Chargement...</span></div></div>';

    if (titleEl) {
        titleEl.textContent = 'Aperçu du ticket';
    }

    if (!dashboardTicketModalInstance) {
        dashboardTicketModalInstance = new bootstrap.Modal(modalEl);
    }
    dashboardTicketModalInstance.show();

    try {
        const response = await fetch('/api/qr_ticket_preview/' + encodeURIComponent(qrId));
        if (redirectToLoginIfUnauthorized(response)) {
            dashboardTicketModalInstance.hide();
            return;
        }
        const data = await response.json().catch(function () {
            return {};
        });

        if (!response.ok || !data.success) {
            dashboardTicketModalInstance.hide();
            showToast('Erreur', data.error || 'Impossible de charger le ticket', 'danger');
            return;
        }

        renderDashboardTicketSheet(sheet, data);

        if (titleEl) {
            const tn = data.ticket_number;
            titleEl.textContent = tn
                ? 'Ticket n° ' + String(tn)
                : 'Aperçu du ticket';
        }

        scheduleDashboardTicketModalScale();
        setTimeout(scheduleDashboardTicketModalScale, 80);
        setTimeout(scheduleDashboardTicketModalScale, 280);

        const printBtn = document.getElementById('dashboardTicketPrintBtn');
        if (printBtn) {
            printBtn.disabled = !!(data.is_expired || !data.is_active);
        }
    } catch (e) {
        console.error(e);
        dashboardTicketModalInstance.hide();
        showToast('Erreur', 'Impossible de charger le ticket', 'danger');
    }
}

async function downloadDashboardTicketPng() {
    const source = document.getElementById('dashboardTicketPreview');
    if (!source || source.querySelector('.spinner-border')) {
        showToast('Erreur', 'Ticket encore en chargement ou indisponible', 'warning');
        return;
    }
    if (!source.querySelector('.ticket-preview-qr-img, .ticket-preview-title')) {
        showToast('Erreur', 'Aucun ticket à télécharger', 'warning');
        return;
    }
    if (typeof window.html2canvas !== 'function') {
        showToast('Erreur', 'Bibliothèque de capture non chargée', 'danger');
        return;
    }
    try {
        const canvas = await html2canvasTicketSheet(source);
        scheduleDashboardTicketModalScale();

        const link = document.createElement('a');
        link.href = canvas.toDataURL('image/png');
        link.download = 'ticket-' + (dashboardTicketViewId || 'download') + '.png';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showToast('Succès', 'Ticket téléchargé !', 'success');
    } catch (e) {
        console.error(e);
        showToast('Erreur', 'Erreur lors du téléchargement', 'danger');
    }
}

async function reprintQRCode(qrId) {
    try {
        const response = await fetch(`/api/print_qr/${qrId}`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken()
            }
        });
        if (redirectToLoginIfUnauthorized(response)) return;
        const data = await response.json();

        if (data.success) {
            showToast('Succès', 'Réimpression réussie !', 'success');
        } else {
            showToast('Erreur', data.error || 'Erreur lors de la réimpression', 'danger');
        }
    } catch (error) {
        console.error('Erreur:', error);
        showToast('Erreur', 'Impossible de se connecter à l\'imprimante', 'danger');
    }
}

function deleteQRCode(qrId) {
    currentDeleteId = qrId;
    const deleteModal = new bootstrap.Modal(document.getElementById('deleteModal'));
    deleteModal.show();
}

async function confirmDelete() {
    if (!currentDeleteId) return;

    try {
        const response = await fetch(`/api/delete_qr/${currentDeleteId}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            }
        });
        if (redirectToLoginIfUnauthorized(response)) return;

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: 'Erreur HTTP ' + response.status }));
            throw new Error(errorData.error || 'Erreur de serveur');
        }

        const data = await response.json();

        if (data.success) {
            showToast('Succès', 'QR Code supprimé avec succès', 'success');
            loadQRCodes();
        } else {
            showToast('Erreur', data.error || 'Erreur lors de la suppression', 'danger');
        }
    } catch (error) {
        console.error('Erreur détaillée:', error);
        showToast('Erreur', error.message || 'Erreur de connexion', 'danger');
    } finally {
        const deleteModal = bootstrap.Modal.getInstance(document.getElementById('deleteModal'));
        if (deleteModal) {
            deleteModal.hide();
        }
        currentDeleteId = null;
    }
}

function showToast(title, message, type = 'info') {
    const toast = document.getElementById('toast');
    const toastTitle = document.getElementById('toastTitle');
    const toastBody = document.getElementById('toastBody');

    toast.className = 'toast';
    if (type === 'success') {
        toast.classList.add('text-bg-success');
    } else if (type === 'danger' || type === 'error') {
        toast.classList.add('text-bg-danger');
    } else if (type === 'warning') {
        toast.classList.add('text-bg-warning');
    } else {
        toast.classList.add('text-bg-info');
    }

    toastTitle.textContent = title;
    toastBody.textContent = message;

    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
}
