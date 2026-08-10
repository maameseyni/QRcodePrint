/*
 * Anime les compteurs numériques (attribut data-count-up) à chaque changement de leur contenu.
 * Ne modifie aucune logique existante : observe simplement le texte déjà mis à jour par ailleurs
 * (ex. tickets.js) et rejoue une transition 0 -> valeur / ancienne valeur -> nouvelle valeur.
 */
(function () {
    var REDUCE_MOTION = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function parseNum(text) {
        var cleaned = String(text || '').replace(/[^\d-]/g, '');
        if (!cleaned) return null;
        var n = parseInt(cleaned, 10);
        return Number.isFinite(n) ? n : null;
    }

    function animateCount(el, from, to, onDone) {
        if (REDUCE_MOTION) {
            el.textContent = String(to);
            onDone();
            return;
        }
        if (typeof gsap !== 'undefined') {
            var obj = { val: from };
            gsap.to(obj, {
                val: to,
                duration: 0.6,
                ease: 'power3.out',
                onUpdate: function () {
                    el.textContent = String(Math.round(obj.val));
                },
                onComplete: function () {
                    el.textContent = String(to);
                    onDone();
                },
            });
            return;
        }
        // Repli sans GSAP : même interpolation (ease-out cubique) via requestAnimationFrame.
        var duration = 550;
        var start = null;
        function step(ts) {
            if (start === null) start = ts;
            var progress = Math.min(1, (ts - start) / duration);
            var eased = 1 - Math.pow(1 - progress, 3);
            el.textContent = String(Math.round(from + (to - from) * eased));
            if (progress < 1) {
                window.requestAnimationFrame(step);
            } else {
                el.textContent = String(to);
                onDone();
            }
        }
        window.requestAnimationFrame(step);
    }

    function watch(el) {
        var lastValue = parseNum(el.textContent);
        var observer = new MutationObserver(function () {
            var newValue = parseNum(el.textContent);
            if (newValue === null) return;
            var from = lastValue === null ? 0 : lastValue;
            if (newValue === from) {
                lastValue = newValue;
                return;
            }
            lastValue = newValue;
            observer.disconnect();
            animateCount(el, from, newValue, function () {
                observer.observe(el, { childList: true, characterData: true, subtree: true });
            });
        });
        observer.observe(el, { childList: true, characterData: true, subtree: true });
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-count-up]').forEach(watch);
    });
})();
