/**
 * Mise à l’échelle proportionnelle du ticket (56ch) comme une « image » responsive.
 * Utilisé par la page d’accueil et la liste Tickets (modales + carte QR).
 */

function ticketViewportMetrics() {
    const vv = window.visualViewport;
    const vw = vv ? vv.width : window.innerWidth;
    const vh = vv ? vv.height : window.innerHeight;
    return {
        vw,
        vh,
        handheld: vw <= 640,
        narrow: vw <= 520,
        tiny: vw <= 400,
        mini: vw <= 360,
        micro: vw <= 320,
    };
}

function measureTicketAvailHeightInline(outerEl) {
    const { vw, vh, handheld, narrow, tiny, mini, micro } = ticketViewportMetrics();
    const band = outerEl && outerEl.closest ? outerEl.closest('.ticket-index-scroll-band') : null;
    /** Hauteur réelle de la bande scroll (flex) — alignée sur ce que l’utilisateur peut voire faire défiler */
    if (band) {
        const bh = band.clientHeight;
        if (bh > 72) {
            return Math.max(96, bh - 10);
        }
    }
    const exp = document.getElementById('expirationText');
    const actions = document.getElementById('qrResultActions');
    const gap = micro ? 2 : mini ? 4 : tiny ? 5 : narrow ? 7 : 10;
    const safety = micro ? 28 : mini ? 24 : tiny ? 20 : narrow ? 18 : handheld ? 12 : 8;

    if (exp && actions) {
        const top = exp.getBoundingClientRect().bottom + gap;
        const bot = actions.getBoundingClientRect().top - gap;
        let space = bot - top - safety;
        if (space > 48) {
            let out = Math.max(48, space);
            if (handheld) {
                const cap = vh * (
                    micro ? 0.21 : mini ? 0.23 : tiny ? 0.26 : narrow ? 0.29 : vw <= 600 ? 0.31 : 0.33
                );
                out = Math.min(out, cap);
            }
            return out;
        }
    }
    const r = outerEl.getBoundingClientRect();
    if (r.height > 48) {
        let h = Math.max(48, r.height - (handheld ? 24 : 12));
        if (handheld) {
            h = Math.min(h, vh * (micro ? 0.23 : mini ? 0.25 : tiny ? 0.28 : narrow ? 0.31 : 0.33));
        }
        return h;
    }
    return Math.min(
        vh * (micro ? 0.19 : mini ? 0.21 : tiny ? 0.25 : narrow ? 0.29 : handheld ? 0.31 : 0.44),
        micro ? 190 : mini ? 210 : tiny ? 250 : 300
    );
}

function measureTicketAvailHeightModal(outerEl) {
    const { vw, vh, handheld, narrow, tiny, mini, micro } = ticketViewportMetrics();
    const r = outerEl.getBoundingClientRect();
    let h = r.height > 48 ? Math.max(48, r.height - (handheld ? 20 : 12)) : Math.min(vh * 0.62, 720);
    if (handheld) {
        /* Plafond ~64vh : un peu plus d’espace pour le ticket ; largeur gérée par scroll horizontal. */
        h = Math.min(h, vh * (micro ? 0.54 : mini ? 0.57 : tiny ? 0.6 : narrow ? 0.62 : vw <= 600 ? 0.63 : 0.64));
    } else {
        h = Math.min(h, vh * 0.72);
    }
    return Math.max(120, h);
}

/**
 * Largeur utile dans une modale Bootstrap : corps du modal + marges écran (mobile).
 */
function measureModalTicketAvailWidth(outerEl, pad) {
    const { vw, handheld, narrow, tiny } = ticketViewportMetrics();
    const outerRect = outerEl.getBoundingClientRect();
    let inner = Math.min(outerRect.width, vw);

    const modalBody = outerEl.closest('.modal-body');
    if (modalBody) {
        const br = modalBody.getBoundingClientRect();
        const cs = getComputedStyle(modalBody);
        const pl = parseFloat(cs.paddingLeft) || 0;
        const pr = parseFloat(cs.paddingRight) || 0;
        inner = Math.min(inner, br.width - pl - pr);
    }

    const dialog = outerEl.closest('.modal-dialog');
    if (dialog) {
        const dr = dialog.getBoundingClientRect();
        inner = Math.min(inner, dr.width - (handheld ? 4 : 4));
    }

    const edge = handheld ? (tiny ? 16 : narrow ? 14 : 12) : 10;
    inner = Math.min(inner, vw - edge);

    /* Pad réduit dans les modales : le corps du modal encadre déjà le contenu */
    const modalPad = Math.max(4, Math.round(pad * 0.45));
    let avail = Math.max(0, inner - modalPad * 2);
    if (handheld) {
        avail *= tiny ? 0.96 : narrow ? 0.97 : 0.98;
    }
    return avail;
}

/**
 * Ticket affiché comme une « image » : échelle uniforme pour tenir dans la largeur ET la hauteur.
 */
function applyProportionalTicketScale(outerEl) {
    if (!outerEl) return;
    const clip = outerEl.querySelector(':scope > .ticket-scale-clip');
    const stage = clip
        ? clip.querySelector('.ticket-scale-stage')
        : outerEl.querySelector(':scope > .ticket-scale-stage');
    const sheet = stage && stage.querySelector('.ticket-receipt-sheet');
    if (!stage || !sheet || !sheet.classList.contains('ticket-receipt-modern')) {
        outerEl.style.height = '';
        outerEl.style.minHeight = '';
        outerEl.style.maxWidth = '';
        if (clip) {
            clip.style.width = '';
            clip.style.height = '';
            clip.style.maxWidth = '';
            clip.style.overflow = '';
            clip.style.marginLeft = '';
            clip.style.marginRight = '';
        }
        if (stage) {
            stage.style.transform = '';
            stage.style.transformOrigin = '';
            stage.style.width = '';
            stage.style.height = '';
        }
        return;
    }

    stage.style.transform = 'none';
    stage.style.width = '';
    stage.style.height = '';
    outerEl.style.height = '';
    outerEl.style.minHeight = '';
    if (clip) {
        clip.style.width = '';
        clip.style.height = '';
    }

    void sheet.offsetHeight;

    let w = Math.max(
        sheet.scrollWidth || 0,
        sheet.offsetWidth || 0,
        Math.ceil(sheet.getBoundingClientRect().width || 0)
    );
    let h = Math.max(
        sheet.scrollHeight || 0,
        sheet.offsetHeight || 0,
        Math.ceil(sheet.getBoundingClientRect().height || 0)
    );
    w = Math.max(w, stage.scrollWidth || 0, stage.offsetWidth || 0);
    h = Math.max(h, stage.scrollHeight || 0, stage.offsetHeight || 0);

    const { vw, handheld, narrow, tiny, mini, micro } = ticketViewportMetrics();
    const pad = micro ? 22 : mini ? 20 : tiny ? 18 : narrow ? 17 : handheld ? 16 : 10;

    const isModal = outerEl.classList.contains('ticket-modal-scale-outer');
    const outerRect = outerEl.getBoundingClientRect();

    /** Uniquement modale sur mobile : échelle sur la hauteur + scroll horizontal dans la bande modale. Page accueil : mise à l’échelle uniforme pour tout voir dans le clip. */
    const modalScrollMobile = isModal && handheld;
    const scrollBandHeightOnly = modalScrollMobile;

    let availW;
    if (isModal) {
        availW = measureModalTicketAvailWidth(outerEl, pad);
    } else {
        const bandEl = outerEl.closest('.ticket-index-scroll-band');
        const wrapW = bandEl ? bandEl.clientWidth : outerRect.width;
        /* Marge latérale un peu plus serrée dans la carte → ticket un peu plus grand */
        const padBox = Math.max(8, pad - 4);
        availW = Math.max(0, Math.min(wrapW, vw) - padBox * 2);
        if (vw <= 560) availW *= 0.9;
        else if (vw <= 640) availW *= 0.94;
        availW = Math.max(0, availW);
    }

    let availH = isModal
        ? measureTicketAvailHeightModal(outerEl)
        : measureTicketAvailHeightInline(outerEl);

    let s = 1;
    if (scrollBandHeightOnly) {
        if (w > 0 && h > 0 && availH > 0) {
            s = Math.min(1, availH / h);
        }
    } else if (w > 0 && h > 0 && availW > 0 && availH > 0) {
        s = Math.min(1, availW / w, availH / h);
    } else if (w > 0 && availW > 0) {
        s = Math.min(1, availW / w);
    }
    /* Réduction « sécurité » sur mobile (carte accueil uniquement ; pas la modale). */
    if (handheld && s > 0 && !isModal) {
        if (micro) s *= 0.84;
        else if (mini) s *= 0.88;
        else if (tiny) s *= 0.9;
        else if (narrow) s *= 0.92;
        else if (vw <= 600) s *= 0.95;
        else s *= 0.98;
    }

    /* Carte accueil : léger zoom supplémentaire dans la boîte (scroll si besoin). */
    if (!isModal && outerEl.closest('.ticket-index-scroll-band') && s > 0) {
        s = Math.min(1, s * 1.06);
    }

    /* Marge anti-coupe : derniers pixels du ticket parfois masqués par transform / sous-pixels */
    const scaledW = Math.max(1, Math.ceil(w * s) + 1);
    const scaledH = Math.max(1, Math.ceil(h * s) + 2);

    stage.style.width = `${w}px`;
    stage.style.height = `${h}px`;
    stage.style.transformOrigin = 'top left';
    stage.style.transform = `scale(${s})`;

    if (clip) {
        clip.style.width = `${scaledW}px`;
        clip.style.height = `${scaledH}px`;
        clip.style.overflow = 'hidden';
        if (scrollBandHeightOnly) {
            clip.style.maxWidth = 'none';
            clip.style.marginLeft = '0';
            clip.style.marginRight = '0';
        } else {
            clip.style.maxWidth = '100%';
            clip.style.marginLeft = 'auto';
            clip.style.marginRight = 'auto';
        }
    } else {
        outerEl.style.height = `${scaledH}px`;
        outerEl.style.minHeight = `${scaledH}px`;
    }
    if (scrollBandHeightOnly) {
        outerEl.style.maxWidth = 'none';
    } else {
        outerEl.style.maxWidth = '100%';
    }
}

/**
 * Capture PNG du ticket avec html2canvas. Sur petit écran, scale()/clip sur les parents
 * produisent un rendu incorrect ; on neutralise stage + clip le temps du raster (aperçu = rendu « pleine » mise en page).
 */
async function html2canvasTicketSheet(sheetEl, extraOptions) {
    if (!sheetEl || typeof window.html2canvas !== 'function') {
        throw new Error('Bibliothèque de capture non chargée');
    }

    const stage = sheetEl.closest('.ticket-scale-stage');
    const clip = sheetEl.closest('.ticket-scale-clip');
    const stageCss = stage ? stage.style.cssText : '';
    const clipCss = clip ? clip.style.cssText : '';

    try {
        sheetEl.scrollIntoView({ block: 'nearest', inline: 'nearest' });

        if (stage) {
            stage.style.transform = 'none';
            stage.style.transformOrigin = 'top left';
            stage.style.width = '';
            stage.style.height = '';
            stage.style.willChange = 'auto';
        }
        if (clip) {
            clip.style.width = '';
            clip.style.height = '';
            clip.style.maxWidth = 'none';
            clip.style.overflow = 'visible';
            clip.style.marginLeft = '';
            clip.style.marginRight = '';
        }

        if (document.fonts && document.fonts.ready) {
            await document.fonts.ready.catch(function () {});
        }

        await new Promise(function (resolve) {
            requestAnimationFrame(function () {
                requestAnimationFrame(resolve);
            });
        });

        const dpr = window.devicePixelRatio || 1;
        const rasterScale = Math.min(2.5, Math.max(2, dpr));

        return await window.html2canvas(sheetEl, Object.assign(
            {
                backgroundColor: '#ffffff',
                scale: rasterScale,
                useCORS: true,
                allowTaint: false,
                logging: false,
            },
            extraOptions || {}
        ));
    } finally {
        if (stage) stage.style.cssText = stageCss;
        if (clip) clip.style.cssText = clipCss;
    }
}
