/* Landing page publique : menu mobile, ancres douces, animations d'entrée (GSAP) et révélation au scroll. */
(function () {
    var REDUCE_MOTION = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var hasGsap = typeof gsap !== 'undefined';

    function setupMobileNav() {
        var toggle = document.getElementById('landingNavToggle');
        var links = document.getElementById('landingNavLinks');
        if (!toggle || !links) return;
        toggle.addEventListener('click', function () {
            var open = links.classList.toggle('is-open');
            toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
        links.querySelectorAll('a').forEach(function (a) {
            a.addEventListener('click', function () {
                links.classList.remove('is-open');
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
        var tl = gsap.timeline({ defaults: { opacity: 0, duration: 0.65, ease: 'power3.out' } });
        tl.from('#landingHeroText > *', { y: 20, stagger: 0.07 }, 0);
        tl.from('#landingStage', { y: 34, scale: 0.985, duration: 0.9, clearProps: 'transform' }, 0.25);
        tl.from('.landing-stage__aside', { y: 18, stagger: 0.12, clearProps: 'transform' }, 0.7);
    }

    function setupTicketFloat() {
        if (!hasGsap || REDUCE_MOTION) return;
        var ticket = document.getElementById('landingTicket');
        if (!ticket) return;
        gsap.to(ticket, {
            y: -8,
            duration: 3.8,
            ease: 'sine.inOut',
            repeat: -1,
            yoyo: true,
        });
    }

    /* Halo qui suit le curseur sur les cartes « 3 gestes » et « Fonctionnalités ». */
    function setupCardSpotlight() {
        if (REDUCE_MOTION) return;
        if (window.matchMedia && window.matchMedia('(hover: none)').matches) return;

        var grids = document.querySelectorAll('#landingStepsGrid, #landingFeaturesGrid, #landingPricingGrid');
        if (!grids.length) return;

        var pending = null;
        grids.forEach(function (grid) {
            grid.addEventListener('pointermove', function (e) {
                var card = e.target.closest ? e.target.closest('.landing-step, .landing-feature, .landing-plan') : null;
                if (!card || pending) return;
                pending = requestAnimationFrame(function () {
                    pending = null;
                    var r = card.getBoundingClientRect();
                    card.style.setProperty('--mx', ((e.clientX - r.left) / r.width * 100).toFixed(2) + '%');
                    card.style.setProperty('--my', ((e.clientY - r.top) / r.height * 100).toFixed(2) + '%');
                });
            });
        });
    }

    /* Chaque groupe s'anime quand son conteneur entre dans l'écran ; les enfants se décalent. */
    function setupScrollReveal() {
        var groups = [
            { sel: '#landingStepsHead' },
            { sel: '#landingStepsGrid', children: '.landing-step', stagger: 0.1, scale: 0.97 },
            { sel: '#landingFeaturesHead' },
            { sel: '#landingFeaturesGrid', children: '.landing-feature', stagger: 0.08, scale: 0.97 },
            { sel: '#landingPricingHead' },
            { sel: '#landingPricingGrid', children: '.landing-plan', stagger: 0.1, scale: 0.97 },
            { sel: '#landingFaqIntro' },
            { sel: '#landingFaqAccordion', children: '.accordion-item', stagger: 0.06 },
            { sel: '#landingContactHead' },
            { sel: '#landingContactCard', children: '.landing-contact__panel, .landing-form-card', stagger: 0.12 },
            { sel: '#landingCtaBand', scale: 0.98 },
        ];

        if (!hasGsap || REDUCE_MOTION || typeof IntersectionObserver === 'undefined') {
            return; // Contenu déjà visible par défaut (pas de classe "masqué" posée en CSS) : rien à faire.
        }

        groups.forEach(function (cfg) {
            var root = document.querySelector(cfg.sel);
            if (!root) return;
            var targets = cfg.children ? root.querySelectorAll(cfg.children) : [root];
            if (!targets.length) return;

            gsap.set(targets, { opacity: 0, y: 26, scale: cfg.scale || 1 });

            var observer = new IntersectionObserver(
                function (entries) {
                    entries.forEach(function (entry) {
                        if (!entry.isIntersecting) return;
                        observer.unobserve(entry.target);
                        gsap.to(targets, {
                            opacity: 1,
                            y: 0,
                            scale: 1,
                            duration: 0.7,
                            ease: 'power3.out',
                            stagger: cfg.stagger || 0,
                            clearProps: 'transform,opacity',
                        });
                    });
                },
                { threshold: 0.12, rootMargin: '0px 0px -70px 0px' }
            );
            observer.observe(root);
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        setupMobileNav();
        setupSmoothScroll();
        setupFooterYear();
        setupContactFormState();
        setupHeroEntrance();
        setupTicketFloat();
        setupCardSpotlight();
        setupScrollReveal();
    });
})();
