/*
 * Animations d'entrée au chargement, pilotées par GSAP (cartes de chaque page — pas la navbar).
 * Ce script est chargé sur toutes les pages ; chaque sélecteur n'existe que sur certaines
 * d'entre elles (ex. .dashboard-stats-row uniquement sur /dashboard) — les sélecteurs absents
 * ne produisent simplement aucune animation, sans erreur.
 *
 * Progressive enhancement : si GSAP ne se charge pas (CDN indisponible, bloqueur), on ne touche
 * à rien — le contenu reste visible normalement via la cascade CSS habituelle.
 */
(function () {
    if (typeof gsap === 'undefined') return;

    var REDUCE_MOTION = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (REDUCE_MOTION) return;

    document.addEventListener('DOMContentLoaded', function () {
        var tl = gsap.timeline({
            defaults: { opacity: 0, y: 18, duration: 0.55, ease: 'power3.out', clearProps: 'transform,opacity' }
        });

        function add(selector, position, opts) {
            var els = document.querySelectorAll(selector);
            if (!els.length) return;
            tl.from(els, opts || { stagger: 0.07 }, position);
        }

        // Navbar volontairement non animée (évite un glissement au rechargement / « Réinitialiser tout »).
        // Accueil
        add('.index-qr-main-row > .col-lg-6:first-child .index-qr-card', 0);
        add('.index-qr-main-row > .col-lg-6:last-child .index-qr-card', 0.08);

        // En-têtes de page : fondu seul (pas de translateY sous le menu fixe)
        add('.tickets-page-head, .dashboard-page-head, .settings-page-head', 0.05, { y: 0, stagger: 0 });

        // Tickets
        add('.row.mb-4 > .col-md-4 > .card', 0.12, { stagger: 0.07 });
        add('.tickets-filters-card', 0.24);
        add('.card.card-qr-table', 0.32);

        // Dashboard
        add('.dashboard-stats-row > div', 0.12, { stagger: 0.06 });
        add('.dashboard-payment-row', 0.3);

        // Paramètres
        add('.settings-account-card', 0.1);
        add('.settings-branding-card', 0.18);
        add('.settings-cashiers-card', 0.26);

        // Connexion / Compléter le profil
        add('.login-page .neumo-card', 0, { duration: 0.6, y: 24 });
    });
})();
