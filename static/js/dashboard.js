/**
 * Dashboard propriétaire — cartes finances (API /api/dashboard_stats).
 */

function formatCfaAmount(val) {
    const n = Number(val);
    if (!Number.isFinite(n)) return '0';
    if (Math.abs(n - Math.round(n)) < 0.001) {
        return Math.round(n).toLocaleString('fr-FR');
    }
    const parts = n.toFixed(2).split('.');
    const intPart = Number(parts[0]).toLocaleString('fr-FR');
    return intPart + ',' + parts[1];
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function redirectToLoginIfUnauthorized(response) {
    if (response.status === 401) {
        window.location.href = '/login?next=' + encodeURIComponent('/dashboard');
        return true;
    }
    return false;
}

function getPaymentModeImages() {
    return window.DASHBOARD_PAYMENT_IMAGES || {};
}

function escapeAttr(value) {
    return escapeHtml(value);
}

function paymentModeVisualHtml(modeKey) {
    const src = getPaymentModeImages()[modeKey];
    if (!src) {
        return (
            '<span class="dashboard-stat-card__icon-slot" aria-hidden="true">' +
            '<i class="bi bi-credit-card fs-1 opacity-50 text-muted"></i></span>'
        );
    }
    return (
        '<span class="dashboard-payment-mode__frame dashboard-payment-mode__frame--' +
        escapeHtml(modeKey) +
        '" aria-hidden="true">' +
        '<img src="' +
        escapeAttr(src) +
        '" alt="" class="dashboard-payment-mode__img" loading="lazy" decoding="async">' +
        '</span>'
    );
}

function renderPaymentBreakdown(breakdown) {
    const row = document.getElementById('dashPaymentBreakdown');
    if (!row) return;
    if (!breakdown || typeof breakdown !== 'object') {
        row.innerHTML = '<div class="col-12"><p class="text-muted small mb-0">Aucune donnée</p></div>';
        return;
    }
    const order = ['especes', 'orange_money', 'wave'];
    const items = order
        .filter((k) => breakdown[k])
        .map((k) => {
            const data = breakdown[k];
            const label = data.label || k;
            const count = data.count ?? 0;
            const amount = formatCfaAmount(data.amount ?? 0);
            return (
                '<div class="col-sm-6 col-lg-4">' +
                '<div class="card h-100 shadow-sm border-0 dashboard-stat-card dashboard-stat-card--plain dashboard-payment-card">' +
                '<div class="card-body">' +
                '<div class="d-flex justify-content-between align-items-center">' +
                '<div>' +
                '<h6 class="card-subtitle mb-2 text-muted">' +
                escapeHtml(label) +
                '</h6>' +
                '<h3 class="mb-0 dashboard-stat-value text-primary-dark">' +
                escapeHtml(amount) +
                '</h3>' +
                '<span class="small text-muted opacity-75">' +
                'F CFA · ' +
                count +
                ' ticket' +
                (count > 1 ? 's' : '') +
                '</span>' +
                '</div>' +
                paymentModeVisualHtml(k) +
                '</div></div></div></div>'
            );
        });
    row.innerHTML = items.length
        ? items.join('')
        : '<div class="col-12"><p class="text-muted small mb-0">Aucun paiement enregistré</p></div>';
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function updateDashboardCards(stats) {
    if (!stats) return;

    setText('dashRevenueTotal', formatCfaAmount(stats.revenue_total));
    setText('dashRevenueMonth', formatCfaAmount(stats.revenue_month));
    setText('dashRevenueToday', formatCfaAmount(stats.revenue_today));
    setText('dashOutstanding', formatCfaAmount(stats.outstanding));

    renderPaymentBreakdown(stats.payment_breakdown);
}

function setDashboardLoading(loading) {
    const btn = document.getElementById('dashboardRefreshBtn');
    if (btn) {
        btn.disabled = loading;
        btn.classList.toggle('disabled', loading);
    }
}

async function loadDashboardStats() {
    setDashboardLoading(true);
    try {
        const response = await fetch('/api/dashboard_stats');
        if (redirectToLoginIfUnauthorized(response)) return;

        let data = {};
        try {
            data = await response.json();
        } catch (e) {
            data = {};
        }

        if (response.ok && data.success && data.stats) {
            updateDashboardCards(data.stats);
        } else {
            console.error(data.error || 'Impossible de charger les statistiques.');
        }
    } catch (err) {
        console.error(err);
    } finally {
        setDashboardLoading(false);
    }
}

function formatDashboardMonthShort(date) {
    return new Intl.DateTimeFormat('fr-FR', { month: 'short' })
        .format(date)
        .replace(/\.$/, '');
}

function initDashboardCalendarIcons() {
    const now = new Date();
    const monthShort = formatDashboardMonthShort(now);
    const day = now.getDate();

    const monthBadge = document.getElementById('dashCalendarMonth');
    if (monthBadge) {
        const top = monthBadge.querySelector('.dashboard-calendar-badge__top');
        const body = monthBadge.querySelector('.dashboard-calendar-badge__body');
        if (top) top.textContent = String(now.getFullYear());
        if (body) body.textContent = monthShort;
    }

    const todayBadge = document.getElementById('dashCalendarToday');
    if (todayBadge) {
        const top = todayBadge.querySelector('.dashboard-calendar-badge__top');
        const body = todayBadge.querySelector('.dashboard-calendar-badge__body');
        if (top) top.textContent = monthShort;
        if (body) body.textContent = String(day);
    }
}

document.addEventListener('DOMContentLoaded', function () {
    initDashboardCalendarIcons();
    loadDashboardStats();
    const refreshBtn = document.getElementById('dashboardRefreshBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadDashboardStats);
    }
});
