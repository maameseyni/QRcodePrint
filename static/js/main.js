// Script principal pour la page d'accueil (génération de QR Codes)

let currentQRId = null;
let currentQRImage = null;
let lastTicketPreviewLines = [];
let lastTicketPreviewBefore = [];
let lastTicketPreviewAfter = [];
let ticketPreviewModalInstance = null;

function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

function redirectToLoginIfUnauthorized(response) {
    if (response.status === 401) {
        window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname || '/');
        return true;
    }
    return false;
}

/**
 * Peut la zone ticket (carte QR ou modal) avec texte + image QR + pied de page.
 * @param {HTMLElement|null} container - ex. #inlineTicketSheet ou #ticketFullPreview
 */
function renderTicketSheet(container) {
    if (!container) return;
    container.classList.add('ticket-receipt-modern');
    container.innerHTML = '';

    const hasSegments =
        (lastTicketPreviewBefore && lastTicketPreviewBefore.length) ||
        (lastTicketPreviewAfter && lastTicketPreviewAfter.length);

    if (hasSegments) {
        const beforeLines = (lastTicketPreviewBefore || []).slice();
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

        const afterLines = (lastTicketPreviewAfter || []).slice();
        const scanIdx = afterLines.findIndex((line) => (line || '').includes('SCANNEZ'));
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
            for (const w of words) {
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
        rightOfQrLines.forEach((line) => {
            rightFormatted.push(...wrapSideLine(line, rightMaxChars));
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
    } else if (lastTicketPreviewLines && lastTicketPreviewLines.length) {
        const pre = document.createElement('pre');
        pre.className = 'ticket-preview-pre mb-0';
        pre.textContent = lastTicketPreviewLines.join('\n');
        container.appendChild(pre);
    } else {
        container.innerHTML = '<p class="text-muted text-center small mb-0">Générez un QR code pour voir l’aperçu du ticket.</p>';
    }
}

let _ticketScaleRaf = 0;

function scheduleTicketScale() {
    if (_ticketScaleRaf) cancelAnimationFrame(_ticketScaleRaf);
    _ticketScaleRaf = requestAnimationFrame(() => {
        _ticketScaleRaf = requestAnimationFrame(() => {
            _ticketScaleRaf = 0;
            const qrRes = document.getElementById('qrResult');
            const inlineOuter = document.querySelector('.ticket-inline-scale-outer');
            if (inlineOuter && qrRes && !qrRes.classList.contains('d-none')) {
                applyProportionalTicketScale(inlineOuter);
            }
            const modal = document.getElementById('ticketPreviewModal');
            const modalOuter = document.querySelector('.ticket-modal-scale-outer');
            if (modalOuter && modal && modal.classList.contains('show')) {
                applyProportionalTicketScale(modalOuter);
            }
        });
    });
}

function openTicketPreviewModal() {
    const modalEl = document.getElementById('ticketPreviewModal');
    const sheet = document.getElementById('ticketFullPreview');
    if (!modalEl || !sheet) return;

    renderTicketSheet(sheet);

    if (!ticketPreviewModalInstance) {
        ticketPreviewModalInstance = new bootstrap.Modal(modalEl);
    }
    ticketPreviewModalInstance.show();
    /* Mise à l’échelle après ouverture : voir shown.bs.modal → scheduleTicketScale */
}

async function sendPrintRequest() {
    if (!currentQRId) {
        showToast('Erreur', 'Aucun QR Code à imprimer', 'warning');
        return false;
    }
    const response = await fetch(`/api/print_qr/${currentQRId}`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCSRFToken()
        }
    });
    if (redirectToLoginIfUnauthorized(response)) return false;
    const data = await response.json().catch(() => ({}));
    if (data.success) {
        showToast('Succès', 'Impression réussie !', 'success');
        return true;
    }
    showToast('Erreur', data.error || 'Erreur lors de l\'impression', 'danger');
    return false;
}

const PAYMENT_MODE_LABELS = {
    '': 'Choisir…',
    especes: 'Espèces',
    orange_money: 'Orange Money',
    wave: 'Wave'
};

const EXPIRATION_LABELS = {
    '24h': '24 heures',
    '7j': '7 jours',
    '30j': '30 jours',
    custom: 'Personnalisé'
};

function closeQrDropdownByTarget(targetId) {
    const toggle = document.getElementById(`${targetId}_toggle`);
    if (toggle && window.bootstrap?.Dropdown) {
        const inst = bootstrap.Dropdown.getInstance(toggle);
        if (inst) inst.hide();
    }
}

function syncQrFormDropdownLabelsFromHidden() {
    const pm = document.getElementById('payment_mode');
    const ex = document.getElementById('expiration');
    const pmLabel = document.getElementById('payment_mode_label');
    const exLabel = document.getElementById('expiration_label');
    if (pm && pmLabel) pmLabel.textContent = PAYMENT_MODE_LABELS[pm.value] ?? 'Choisir…';
    if (ex && exLabel) exLabel.textContent = EXPIRATION_LABELS[ex.value] ?? '24 heures';
}

function syncCustomExpirationUi() {
    const expirationEl = document.getElementById('expiration');
    const customHoursEl = document.getElementById('custom_hours');
    const customHoursContainer = document.getElementById('custom_hours_container');
    if (!expirationEl || !customHoursEl || !customHoursContainer) return;
    if (expirationEl.value === 'custom') {
        customHoursContainer.style.display = 'block';
        customHoursEl.required = true;
    } else {
        customHoursContainer.style.display = 'none';
        customHoursEl.required = false;
    }
}

function initQrFormDropdowns() {
    document.querySelectorAll('.qrp-dd-opt').forEach((btn) => {
        btn.addEventListener('click', function () {
            const targetId = this.dataset.target;
            const val = this.dataset.value;
            const label = this.dataset.label;
            const hidden = document.getElementById(targetId);
            const labelEl = document.getElementById(`${targetId}_label`);
            if (hidden) hidden.value = val;
            if (labelEl) labelEl.textContent = label;
            closeQrDropdownByTarget(targetId);
            if (targetId === 'expiration') syncCustomExpirationUi();
        });
    });
}

// Initialisation
document.addEventListener('DOMContentLoaded', function() {
    checkPrinterStatus();

    document.getElementById('qrForm').addEventListener('submit', handleFormSubmit);

    const phoneLocal = document.getElementById('client_phone_local');
    if (phoneLocal && typeof filterSenegalPhoneLocalDigits === 'function') {
        phoneLocal.addEventListener('input', function () {
            filterSenegalPhoneLocalDigits(phoneLocal);
        });
    }

    initQrFormDropdowns();
    syncQrFormDropdownLabelsFromHidden();
    syncCustomExpirationUi();

    const viewTicketBtn = document.getElementById('viewTicketBtn');
    if (viewTicketBtn) {
        viewTicketBtn.addEventListener('click', function () {
            if (!currentQRId) {
                showToast('Erreur', 'Générez d\'abord un QR code', 'warning');
                return;
            }
            openTicketPreviewModal();
        });
    }

    document.getElementById('printBtn').addEventListener('click', function() {
        if (!currentQRId) {
            showToast('Erreur', 'Générez d\'abord un QR code', 'warning');
            return;
        }
        openTicketPreviewModal();
    });

    const confirmPrintBtn = document.getElementById('confirmPrintBtn');
    if (confirmPrintBtn) {
        confirmPrintBtn.addEventListener('click', async function() {
            const btn = confirmPrintBtn;
            const prev = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML =
                '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
            btn.setAttribute('aria-busy', 'true');
            try {
                const ok = await sendPrintRequest();
                if (ok && ticketPreviewModalInstance) {
                    ticketPreviewModalInstance.hide();
                }
            } finally {
                btn.disabled = false;
                btn.innerHTML = prev;
                btn.removeAttribute('aria-busy');
            }
        });
    }

    const ticketPreviewDownloadBtn = document.getElementById('ticketPreviewDownloadBtn');
    if (ticketPreviewDownloadBtn) {
        ticketPreviewDownloadBtn.addEventListener('click', function () {
            handleTicketPreviewModalDownload();
        });
    }

    document.getElementById('downloadBtn').addEventListener('click', handleDownload);
    document.getElementById('resetBtn').addEventListener('click', handleReset);

    const ticketModalEl = document.getElementById('ticketPreviewModal');
    if (ticketModalEl) {
        ticketModalEl.addEventListener('shown.bs.modal', () => scheduleTicketScale());
    }

    let resizeScaleT = null;
    window.addEventListener('resize', () => {
        clearTimeout(resizeScaleT);
        resizeScaleT = setTimeout(() => scheduleTicketScale(), 100);
    });

    const inlineScaleOuter = document.querySelector('.ticket-inline-scale-outer');
    if (inlineScaleOuter && typeof ResizeObserver !== 'undefined') {
        new ResizeObserver(() => scheduleTicketScale()).observe(inlineScaleOuter);
    }
    const ticketIndexScrollBand = document.querySelector('.ticket-index-scroll-band');
    if (ticketIndexScrollBand && typeof ResizeObserver !== 'undefined') {
        new ResizeObserver(() => scheduleTicketScale()).observe(ticketIndexScrollBand);
    }
    const qrDisplayCard = document.getElementById('qrDisplayCard');
    if (qrDisplayCard && typeof ResizeObserver !== 'undefined') {
        new ResizeObserver(() => scheduleTicketScale()).observe(qrDisplayCard);
    }

    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', () => scheduleTicketScale());
        window.visualViewport.addEventListener('scroll', () => scheduleTicketScale());
    }

    setInterval(checkPrinterStatus, 30000);
});

async function checkPrinterStatus() {
    try {
        const response = await fetch('/api/status');
        if (redirectToLoginIfUnauthorized(response)) return;
        const data = await response.json();

        const statusEl = document.getElementById('printerStatus');
        const iconEl = document.getElementById('printerIcon');

        if (data.success && data.printer_connected) {
            statusEl.textContent = data.printer_info || 'Connectée';
            iconEl.className = 'bi bi-printer me-2 connected';
        } else {
            statusEl.textContent = data.printer_info || 'Aucune imprimante détectée';
            iconEl.className = 'bi bi-printer me-2 disconnected';
        }
    } catch (error) {
        console.error('Erreur lors de la vérification de l\'imprimante:', error);
        const statusEl = document.getElementById('printerStatus');
        statusEl.textContent = 'Erreur de vérification';
    }
}

async function handleFormSubmit(e) {
    e.preventDefault();

    const localEl = document.getElementById('client_phone_local');
    const localDigits = localEl ? localEl.value.replace(/\D/g, '').slice(0, SN_LOCAL_LENGTH) : '';
    if (typeof validateSenegalPhoneLocal !== 'function' || !validateSenegalPhoneLocal(localDigits)) {
        showToast('Erreur', typeof SN_PHONE_ERR !== 'undefined' ? SN_PHONE_ERR : 'Veuillez saisir un bon numéro', 'warning');
        return;
    }

    const amountTotalEl = document.getElementById('amount_total');
    const amountPaidEl = document.getElementById('amount_paid');
    const total = parseFloat(String(amountTotalEl.value).replace(',', '.'));
    const paid = parseFloat(String(amountPaidEl.value).replace(',', '.'));
    if (!Number.isFinite(total) || !Number.isFinite(paid)) {
        showToast('Erreur', 'Montants invalides.', 'warning');
        return;
    }
    if (paid > total + 1e-9) {
        showToast('Erreur', 'Le montant payé ne peut pas dépasser le montant dû.', 'warning');
        return;
    }

    const paymentModeEl = document.getElementById('payment_mode');
    if (!paymentModeEl || !paymentModeEl.value) {
        showToast('Erreur', 'Choisissez un mode de paiement.', 'warning');
        return;
    }

    const expirationSelect = document.getElementById('expiration');
    if (expirationSelect && expirationSelect.value === 'custom') {
        const chRaw = document.getElementById('custom_hours').value.trim();
        if (!chRaw) {
            showToast(
                'Erreur',
                'Indiquez le nombre d\'heures pour une expiration personnalisée.',
                'warning'
            );
            return;
        }
        const hi = parseInt(chRaw, 10);
        if (!Number.isFinite(hi) || hi < 1 || hi > 8760) {
            showToast(
                'Erreur',
                "L'expiration personnalisée doit être entre 1 et 8760 heures.",
                'warning'
            );
            return;
        }
    }

    const btn = document.getElementById('generateBtn');
    const originalText = btn.innerHTML;

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-generate me-2" role="status" aria-hidden="true"></span>Génération...';

    try {
        const formData = {
            client_name: document.getElementById('client_name').value,
            client_firstname: '',
            client_phone: '+221' + localDigits,
            client_email: document.getElementById('client_email').value,
            client_address: document.getElementById('client_address').value,
            service: document.getElementById('service').value,
            subscription_type: document.getElementById('subscription_type').value,
            amount_total: document.getElementById('amount_total').value,
            amount_paid: document.getElementById('amount_paid').value,
            payment_mode: document.getElementById('payment_mode').value,
            expiration: document.getElementById('expiration').value
        };

        if (formData.expiration === 'custom') {
            formData.custom_hours = document.getElementById('custom_hours').value;
        }

        const response = await fetch('/api/create_qr', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            },
            body: JSON.stringify(formData)
        });

        if (redirectToLoginIfUnauthorized(response)) return;

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            const msg = data.error || `Erreur serveur (${response.status})`;
            showToast('Erreur', msg, 'danger');
            return;
        }

        if (data.success) {
            currentQRId = data.qr_id;
            currentQRImage = data.qr_image;
            lastTicketPreviewLines = data.ticket_preview_lines || [];
            lastTicketPreviewBefore = data.ticket_preview_before_qr || [];
            lastTicketPreviewAfter = data.ticket_preview_after_qr || [];

            displayQRCode(data);
            showToast('Succès', 'Ticket généré — voir la carte à droite.', 'success');
        } else {
            showToast('Erreur', data.error || 'Erreur lors de la génération', 'danger');
        }
    } catch (error) {
        console.error('Erreur:', error);
        showToast('Erreur', 'Une erreur est survenue lors de la génération', 'danger');
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

function displayQRCode(data) {
    const resultDiv = document.getElementById('qrResult');
    const emptyState = document.getElementById('qrEmptyState');
    const expirationText = document.getElementById('expirationText');
    const inlineSheet = document.getElementById('inlineTicketSheet');

    emptyState.classList.add('d-none');
    resultDiv.classList.remove('d-none');
    resultDiv.classList.add('d-flex');

    const ticketInfo = data.ticket_number
        ? `Ticket n° ${data.ticket_number} · `
        : '';
    expirationText.textContent = `${ticketInfo}Expire dans : ${data.expiration_text}`;

    renderTicketSheet(inlineSheet);
    scheduleTicketScale();
    setTimeout(() => scheduleTicketScale(), 80);
    setTimeout(() => scheduleTicketScale(), 280);

    const previewBtn = document.getElementById('previewBtn');
    const printBtn = document.getElementById('printBtn');
    const viewTicketBtnEl = document.getElementById('viewTicketBtn');
    if (previewBtn) previewBtn.disabled = false;
    if (printBtn) printBtn.disabled = false;
    if (viewTicketBtnEl) viewTicketBtnEl.disabled = false;
}

function handleDownload() {
    if (!currentQRImage || ((!lastTicketPreviewBefore || !lastTicketPreviewBefore.length) && (!lastTicketPreviewAfter || !lastTicketPreviewAfter.length))) {
        showToast('Erreur', 'Aucun ticket à télécharger', 'warning');
        return;
    }

    try {
        downloadFullTicketImage()
            .then(() => {
                showToast('Succès', 'Ticket complet téléchargé !', 'success');
            })
            .catch((error) => {
                console.error('Erreur:', error);
                showToast('Erreur', 'Erreur lors du téléchargement du ticket', 'danger');
            });
    } catch (error) {
        console.error('Erreur:', error);
        showToast('Erreur', 'Erreur lors du téléchargement', 'danger');
    }
}

async function downloadFullTicketImage() {
    const source = document.getElementById('inlineTicketSheet');
    if (!source || !source.childElementCount) {
        throw new Error('Aperçu ticket indisponible');
    }

    const canvas = await html2canvasTicketSheet(source);
    scheduleTicketScale();

    const link = document.createElement('a');
    link.href = canvas.toDataURL('image/png');
    link.download = `ticket-${currentQRId || 'download'}.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function handleTicketPreviewModalDownload() {
    if (!currentQRId) {
        showToast('Erreur', 'Générez d\'abord un QR code', 'warning');
        return;
    }
    downloadTicketPreviewModalPng()
        .then(() => {
            showToast('Succès', 'Ticket complet téléchargé !', 'success');
        })
        .catch((error) => {
            console.error('Erreur:', error);
            showToast('Erreur', error.message || 'Erreur lors du téléchargement du ticket', 'danger');
        });
}

async function downloadTicketPreviewModalPng() {
    const source = document.getElementById('ticketFullPreview');
    if (!source || !source.childElementCount) {
        throw new Error('Aperçu ticket indisponible');
    }

    const canvas = await html2canvasTicketSheet(source);
    scheduleTicketScale();

    const link = document.createElement('a');
    link.href = canvas.toDataURL('image/png');
    link.download = `ticket-${currentQRId || 'download'}.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function handleReset() {
    document.getElementById('qrForm').reset();
    const qrResult = document.getElementById('qrResult');
    const emptyState = document.getElementById('qrEmptyState');

    qrResult.classList.add('d-none');
    qrResult.classList.remove('d-flex');
    emptyState.classList.remove('d-none');
    document.getElementById('custom_hours_container').style.display = 'none';

    syncQrFormDropdownLabelsFromHidden();
    syncCustomExpirationUi();

    currentQRId = null;
    currentQRImage = null;
    lastTicketPreviewLines = [];
    lastTicketPreviewBefore = [];
    lastTicketPreviewAfter = [];

    const sheet = document.getElementById('inlineTicketSheet');
    if (sheet) sheet.innerHTML = '';
    const scaleOuter = document.querySelector('.ticket-inline-scale-outer');
    if (scaleOuter) {
        scaleOuter.style.height = '';
        scaleOuter.style.minHeight = '';
        scaleOuter.style.maxWidth = '';
        const clipEl = scaleOuter.querySelector('.ticket-scale-clip');
        if (clipEl) {
            clipEl.style.width = '';
            clipEl.style.height = '';
            clipEl.style.maxWidth = '';
            clipEl.style.overflow = '';
            clipEl.style.marginLeft = '';
            clipEl.style.marginRight = '';
        }
        const st = scaleOuter.querySelector('.ticket-scale-stage');
        if (st) {
            st.style.transform = '';
            st.style.transformOrigin = '';
            st.style.width = '';
            st.style.height = '';
        }
    }

    const previewBtn = document.getElementById('previewBtn');
    const printBtn = document.getElementById('printBtn');
    const viewTicketBtnEl = document.getElementById('viewTicketBtn');
    if (previewBtn) previewBtn.disabled = true;
    if (printBtn) printBtn.disabled = true;
    if (viewTicketBtnEl) viewTicketBtnEl.disabled = true;
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
