/* Landing page publique : menu mobile, ancres douces, animations d'entrée (GSAP) et révélation au scroll. */
(function () {
    var REDUCE_MOTION = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var hasGsap = typeof gsap !== 'undefined';

    function setupMobileNav() {
        var toggle = document.getElementById('landingNavToggle');
        var links = document.getElementById('landingNavLinks');
        if (!toggle || !links) return;
        toggle.addEventListener('click', function () {
            var open = links.classList.toggle('show');
            toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
        links.querySelectorAll('a').forEach(function (a) {
            a.addEventListener('click', function () {
                links.classList.remove('show');
                toggle.setAttribute('aria-expanded', 'false');
            });
        });
    }

    function setupSmoothScroll() {
        document.documentElement.style.scrollBehavior = REDUCE_MOTION ? 'auto' : 'smooth';
    }

    function setupFooterYear() {
        var el = document.getElementById('landingYear');
        if (el) el.textContent = String(new Date().getFullYear());
    }

    function setupContactFormState() {
        var form = document.getElementById('landingContactForm');
        var btn = document.getElementById('landingContactSubmit');
        if (!form || !btn) return;
        form.addEventListener('submit', function () {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Envoi…';
        });
    }

    function setupHeroEntrance() {
        if (!hasGsap || REDUCE_MOTION) return;
        var tl = gsap.timeline({ defaults: { opacity: 0, duration: 0.6, ease: 'power3.out' } });
        tl.from('#landingHeroText > *', { y: 18, stagger: 0.07 }, 0);
        tl.from('#landingHeroVisual .landing-ticket-glow', { opacity: 0, scale: 0.9, duration: 0.8 }, 0.1);
        tl.from('#landingHeroVisual .landing-ticket-mock', {
            y: 22,
            scale: 0.97,
            clearProps: 'all',
        }, 0.18);
    }

    function setupTicketFloat() {
        if (!hasGsap || REDUCE_MOTION) return;
        var ticket = document.querySelector('#landingHeroVisual .landing-ticket-mock');
        if (!ticket) return;
        gsap.to(ticket, {
            y: -6,
            duration: 3.6,
            ease: 'sine.inOut',
            repeat: -1,
            yoyo: true,
        });
    }

    function setupScrollReveal() {
        var groups = [
            '#landingFeaturesHead',
            '#landingFeaturesGrid > [class*="col-"]',
            '#landingPricingHead',
            '#landingPricingGrid > [class*="col-"]',
            '#landingFaqHead',
            '#landingFaqAccordion .accordion-item',
            '#landingContactHead',
            '#landingContactCard .landing-contact-info',
            '#landingContactCard .landing-contact-form-card',
        ];

        if (!hasGsap || REDUCE_MOTION || typeof IntersectionObserver === 'undefined') {
            return; // Contenu déjà visible par défaut (pas de classe "masqué" posée en CSS) : rien à faire.
        }

        groups.forEach(function (sel) {
            var els = document.querySelectorAll(sel);
            if (!els.length) return;
            gsap.set(els, { opacity: 0, y: 24 });
            var observer = new IntersectionObserver(
                function (entries) {
                    entries.forEach(function (entry) {
                        if (!entry.isIntersecting) return;
                        gsap.to(entry.target, {
                            opacity: 1,
                            y: 0,
                            duration: 0.6,
                            ease: 'power3.out',
                            clearProps: 'transform,opacity',
                        });
                        observer.unobserve(entry.target);
                    });
                },
                { threshold: 0.15, rootMargin: '0px 0px -60px 0px' }
            );
            els.forEach(function (el) { observer.observe(el); });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        setupMobileNav();
        setupSmoothScroll();
        setupFooterYear();
        setupContactFormState();
        setupHeroEntrance();
        setupTicketFloat();
        setupScrollReveal();
    });
})();
