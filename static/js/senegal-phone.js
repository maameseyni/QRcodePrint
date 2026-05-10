/**
 * Numéro mobile Sénégal : 9 chiffres après +221 (préfixes opérateur locaux).
 * Partagé : formulaire QR (main.js), inscription, compléter le profil.
 */
(function (global) {
    'use strict';

    var PREFIXES = ['77', '75', '76', '71', '78', '33', '70'];
    var LEN = 9;

    function validateSenegalPhoneLocal(digits) {
        if (!digits || digits.length !== LEN) return false;
        return PREFIXES.indexOf(digits.slice(0, 2)) !== -1;
    }

    global.SN_LOCAL_PREFIXES = PREFIXES;
    global.SN_LOCAL_LENGTH = LEN;
    global.SN_PHONE_ERR = 'Veuillez saisir un bon numéro';
    global.validateSenegalPhoneLocal = validateSenegalPhoneLocal;

    /** Ne garde que les chiffres, maximum 9 */
    global.filterSenegalPhoneLocalDigits = function (inputEl) {
        if (!inputEl) return;
        inputEl.value = String(inputEl.value || '').replace(/\D/g, '').slice(0, LEN);
    };

    /**
     * Remplit un champ hidden avec +221 + 9 chiffres si valide, sinon ''.
     * optionalField : true pour 2e numéro (vide autorisé).
     */
    global.syncSenegalPhoneHiddenField = function (localInput, hiddenInput, optionalField) {
        if (!localInput || !hiddenInput) return;
        global.filterSenegalPhoneLocalDigits(localInput);
        var d = localInput.value;
        if (d.length === LEN && validateSenegalPhoneLocal(d)) {
            hiddenInput.value = '+221' + d;
        } else {
            hiddenInput.value = '';
        }
    };

    global.attachSenegalPhonePair = function (localInput, hiddenInput, optionalField) {
        if (!localInput || !hiddenInput) return;
        localInput.addEventListener('input', function () {
            global.syncSenegalPhoneHiddenField(localInput, hiddenInput, optionalField);
        });
        global.syncSenegalPhoneHiddenField(localInput, hiddenInput, optionalField);
    };

    /**
     * Formulaires inscription / compléter profil : paires local + hidden, validation au submit.
     */
    global.bindSenegalDualPhoneForm = function (
        formEl,
        primaryLocalId,
        primaryHiddenId,
        secondaryLocalId,
        secondaryHiddenId
    ) {
        if (!formEl) return;
        var pl = document.getElementById(primaryLocalId);
        var ph = document.getElementById(primaryHiddenId);
        var sl = secondaryLocalId ? document.getElementById(secondaryLocalId) : null;
        var sh = secondaryHiddenId ? document.getElementById(secondaryHiddenId) : null;
        if (pl && ph) {
            global.attachSenegalPhonePair(pl, ph, false);
        }
        if (sl && sh) {
            global.attachSenegalPhonePair(sl, sh, true);
        }
        formEl.addEventListener('submit', function (e) {
            if (!pl || !ph) return;
            global.filterSenegalPhoneLocalDigits(pl);
            var d = pl.value;
            if (!validateSenegalPhoneLocal(d)) {
                e.preventDefault();
                alert(global.SN_PHONE_ERR);
                pl.focus();
                return;
            }
            ph.value = '+221' + d;
            if (sl && sh) {
                global.filterSenegalPhoneLocalDigits(sl);
                var d2 = sl.value;
                if (d2.length > 0 && d2.length < LEN) {
                    e.preventDefault();
                    alert(global.SN_PHONE_ERR);
                    sl.focus();
                    return;
                }
                if (d2.length === LEN) {
                    if (!validateSenegalPhoneLocal(d2)) {
                        e.preventDefault();
                        alert(global.SN_PHONE_ERR);
                        sl.focus();
                        return;
                    }
                    if ('+221' + d2 === ph.value) {
                        e.preventDefault();
                        alert('Le 2e numéro doit être différent du numéro principal.');
                        sl.focus();
                        return;
                    }
                    sh.value = '+221' + d2;
                } else {
                    sh.value = '';
                }
            }
        });
    };

    function autoBindDualPhoneForms() {
        var signup = document.querySelector('.neumo-signup-form');
        if (signup) {
            global.bindSenegalDualPhoneForm(
                signup,
                'signup_phone_local',
                'signup_phone_hidden',
                'signup_secondary_phone_local',
                'signup_secondary_phone_hidden'
            );
        }
        var complete = document.querySelector('.neumo-complete-profile-form');
        if (complete) {
            global.bindSenegalDualPhoneForm(
                complete,
                'complete_phone_local',
                'complete_phone_hidden',
                'complete_secondary_local',
                'complete_secondary_hidden'
            );
        }
    }

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', autoBindDualPhoneForms);
        } else {
            autoBindDualPhoneForms();
        }
    }
})(typeof window !== 'undefined' ? window : globalThis);
