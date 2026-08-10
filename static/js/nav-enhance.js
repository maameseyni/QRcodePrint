/* Améliorations visuelles du menu : indicateur glissant + rétrécissement au scroll. */
(function () {
    function setupScrollShrink(nav) {
        if (!nav) return;
        var lastState = false;
        function onScroll() {
            var scrolled = window.scrollY > 8;
            if (scrolled !== lastState) {
                nav.classList.toggle('navbar-scrolled', scrolled);
                lastState = scrolled;
            }
        }
        window.addEventListener('scroll', onScroll, { passive: true });
        onScroll();
    }

    function setupSlidingIndicator(nav) {
        if (!nav) return;
        var navList = nav.querySelector('.navbar-nav');
        if (!navList) return;
        var links = Array.prototype.slice.call(navList.querySelectorAll('.nav-link:not(.btn-link)'));
        if (!links.length) return;

        var indicator = document.createElement('span');
        indicator.className = 'nav-indicator';
        indicator.setAttribute('aria-hidden', 'true');
        navList.appendChild(indicator);

        var hasGsap = typeof gsap !== 'undefined';

        function place(el) {
            if (!el) {
                if (hasGsap) {
                    gsap.to(indicator, { opacity: 0, duration: 0.15, overwrite: true });
                } else {
                    indicator.style.opacity = '0';
                }
                return;
            }
            var lr = el.getBoundingClientRect();
            var cr = navList.getBoundingClientRect();
            var x = lr.left - cr.left;
            var y = lr.top - cr.top;
            if (hasGsap) {
                gsap.to(indicator, {
                    x: x,
                    y: y,
                    width: lr.width,
                    height: lr.height,
                    opacity: 1,
                    duration: 0.35,
                    ease: 'back.out(1.7)',
                    overwrite: true,
                });
            } else {
                indicator.style.opacity = '1';
                indicator.style.width = lr.width + 'px';
                indicator.style.height = lr.height + 'px';
                indicator.style.transform = 'translate(' + x + 'px,' + y + 'px)';
            }
        }

        var activeLink = navList.querySelector('.nav-link.active');
        function resetToActive() { place(activeLink); }

        links.forEach(function (link) {
            link.addEventListener('mouseenter', function () { place(link); });
            link.addEventListener('focus', function () { place(link); });
        });
        navList.addEventListener('mouseleave', resetToActive);
        window.addEventListener('resize', resetToActive);
        nav.addEventListener('shown.bs.collapse', resetToActive);
        nav.addEventListener('hidden.bs.collapse', resetToActive);
        // Laisse les icônes/polices se poser avant de mesurer (évite un indicateur à largeur 0).
        setTimeout(resetToActive, 60);
    }

    document.addEventListener('DOMContentLoaded', function () {
        var nav = document.querySelector('.custom-navbar');
        setupScrollShrink(nav);
        setupSlidingIndicator(nav);
    });
})();
