"""
Application Flask pour génération et impression de QR Codes thermiques
"""
import os
import csv
import secrets
import textwrap
import uuid
import hashlib
import hmac
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from io import BytesIO, StringIO

from dotenv import load_dotenv

load_dotenv()

from flask import (
    Flask,
    g,
    render_template,
    request,
    jsonify,
    send_file,
    abort,
    session,
    redirect,
    url_for,
)
from authlib.integrations.flask_client import OAuth
from flask_wtf.csrf import CSRFError, CSRFProtect
import qrcode
from PIL import Image, ImageDraw, ImageFont
from google.api_core.exceptions import GoogleAPICallError, PermissionDenied
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
import base64

from config import Config
from services.datastore import FirestoreDataStore, QueryFilters

app = Flask(__name__)
app.config.from_object(Config)
Config.init_app(app)

# Derrière Render / reverse proxy : URLs externes HTTPS et OAuth corrects (X-Forwarded-*).
if (
    os.environ.get('RENDER')
    or os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    or str(os.environ.get('TRUST_PROXY_HEADERS', '')).strip().lower() in ('1', 'true', 'yes', 'on')
):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

csrf = CSRFProtect(app)
store = FirestoreDataStore(app.config)


@app.before_request
def _assign_request_id():
    g.request_id = secrets.token_hex(8)


@app.after_request
def _echo_request_id(resp):
    rid = getattr(g, 'request_id', None)
    if rid:
        resp.headers['X-Request-ID'] = rid
    return resp

oauth = OAuth(app)
if app.config.get('GOOGLE_CLIENT_ID') and app.config.get('GOOGLE_CLIENT_SECRET'):
    oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )


def _google_oauth_configured() -> bool:
    return bool(app.config.get('GOOGLE_CLIENT_ID') and app.config.get('GOOGLE_CLIENT_SECRET'))


def _google_oauth_redirect_uri() -> str:
    """Doit être identique à une « URI de redirection autorisée » dans Google Cloud (erreur 400 redirect_uri_mismatch sinon)."""
    base = app.config.get('PUBLIC_URL')
    if base:
        return f"{base}/auth/google/callback"
    return url_for('auth_google_callback', _external=True)


def jsonify_firestore_error(operation: str, exc: GoogleAPICallError):
    """Réponse JSON homogène pour les erreurs d'API Firestore (évite un 500 « Erreur interne »)."""
    app.logger.warning("Firestore %s: %s", operation, exc)
    msg = (str(exc) or "").strip() or type(exc).__name__
    if isinstance(exc, PermissionDenied) or "insufficient permissions" in msg.lower():
        detail = (
            "Firestore refuse l'accès. Vérifiez les rôles IAM du compte de service "
            "(rôle « Cloud Datastore User » sur le projet défini par FIRESTORE_PROJECT_ID)."
        )
    else:
        detail = f"Firestore ({type(exc).__name__}): {msg}"
    return jsonify({"success": False, "error": detail}), 503


def _safe_next_url(nxt):
    if not nxt or not isinstance(nxt, str):
        return None
    nxt = nxt.strip()
    if not nxt.startswith('/') or nxt.startswith('//'):
        return None
    return nxt


def site_auth_required():
    """Connexion obligatoire en mode multi-comptes."""
    return True


def admin_login_required():
    """Compatibilité template: authentification applicative toujours active."""
    return True


def _legacy_admin_profile():
    return {
        'full_name': app.config.get('ADMIN_FULL_NAME') or 'Administrateur',
        'gym_name': app.config.get('ADMIN_GYM_NAME') or 'Salle principale',
        'phone': app.config.get('ADMIN_PHONE') or '',
        'address': app.config.get('ADMIN_ADDRESS') or '',
    }


def ensure_legacy_admin_user():
    """Crée/met à jour le compte historique comme utilisateur standard."""
    username = (app.config.get('ADMIN_USERNAME') or 'admin').strip().lower()
    admin_pass = app.config.get('ADMIN_PASSWORD')
    if not username or not admin_pass:
        return
    existing = store.get_user_by_username(username)
    profile = _legacy_admin_profile()
    if not existing:
        user_id = store.create_user({
            'id': str(uuid.uuid4()),
            'username': username,
            'password_hash': generate_password_hash(admin_pass),
            'role': 'user',
            'full_name': profile['full_name'],
            'gym_name': profile['gym_name'],
            'phone': profile['phone'],
            'address': profile['address'],
            'is_active': True,
            'created_at': datetime.utcnow().isoformat(),
            'source': 'legacy-env',
        })
        n_attach = store.attach_owner_to_unowned_qr(user_id)
        if n_attach:
            _invalidate_list_qr_cache_for_owner(user_id)
        return
    updates = {}
    if str(existing.get('role') or '').strip().lower() in ('admin', 'operator', ''):
        updates['role'] = 'user'
    for key in ('full_name', 'gym_name', 'phone', 'address'):
        if not str(existing.get(key) or '').strip() and str(profile[key] or '').strip():
            updates[key] = profile[key]
    if updates:
        store.update_user(existing['id'], updates)
    n_attach = _maybe_attach_owner_to_unowned_qr(existing['id'])
    if n_attach:
        _invalidate_list_qr_cache_for_owner(existing['id'])


def ensure_superadmin_user():
    """Compte superadmin global (optionnel, piloté via .env)."""
    username = (app.config.get('SUPERADMIN_USERNAME') or '').strip().lower()
    password = app.config.get('SUPERADMIN_PASSWORD')
    if not username or not password:
        return
    existing = store.get_user_by_username(username)
    if not existing:
        store.create_user({
            'id': str(uuid.uuid4()),
            'username': username,
            'password_hash': generate_password_hash(password),
            'role': 'superadmin',
            'full_name': app.config.get('SUPERADMIN_FULL_NAME') or 'Super Administrateur',
            'gym_name': 'Plateforme',
            'phone': app.config.get('SUPERADMIN_PHONE') or '',
            'address': app.config.get('SUPERADMIN_ADDRESS') or '',
            'is_active': True,
            'created_at': datetime.utcnow().isoformat(),
            'source': 'superadmin-env',
        })
        return
    if str(existing.get('role') or '').strip().lower() != 'superadmin':
        store.update_user(existing['id'], {'role': 'superadmin'})


def ensure_operator_user():
    """Compte caisse (Firestore) : création QR / impression, sans liste tickets / export."""
    username = (app.config.get('OPERATOR_USERNAME') or 'operator').strip().lower()
    password = app.config.get('OPERATOR_PASSWORD')
    if not username or not password:
        return
    gym = str(app.config.get('OPERATOR_GYM_NAME') or 'Caisse').strip()
    phone = str(app.config.get('OPERATOR_PHONE') or '+221770000000').strip()
    addr = str(app.config.get('OPERATOR_ADDRESS') or '-').strip()
    existing = store.get_user_by_username(username)
    if not existing:
        uid = str(uuid.uuid4())
        store.create_user({
            'id': uid,
            'username': username,
            'password_hash': generate_password_hash(password),
            'role': 'operator',
            'full_name': gym,
            'gym_name': gym,
            'phone': phone,
            'address': addr,
            'is_active': True,
            'created_at': datetime.utcnow().isoformat(),
            'source': 'legacy-operator-env',
        })
        return
    updates = {'role': 'operator'}
    if not str(existing.get('gym_name') or '').strip():
        updates['gym_name'] = gym
    if not str(existing.get('phone') or '').strip():
        updates['phone'] = phone
    if not str(existing.get('address') or '').strip():
        updates['address'] = addr
    if not str(existing.get('full_name') or '').strip():
        updates['full_name'] = gym
    store.update_user(existing['id'], updates)


def try_login(username, password):
    """Retourne le profil utilisateur Firestore si authentifié, sinon None."""
    if not username or password is None:
        return None
    user = store.get_user_by_username((username or '').strip().lower())
    if not user:
        return None
    if not bool(user.get('is_active', True)):
        return None
    pwd_hash = str(user.get('password_hash') or '')
    if not pwd_hash:
        return None
    if check_password_hash(pwd_hash, password):
        return user
    return None


def _session_account_id():
    """ID Firestore du compte connecté (propriétaire ou caissier)."""
    return str(session.get('user_id') or '')


def _current_owner_id():
    """Propriétaire structure pour QR / tickets (caissier → owner_id en session)."""
    return str(session.get('owner_id') or session.get('user_id') or '')


def _user_can_export_tickets(user) -> bool:
    """Export CSV/Excel depuis la liste des tickets : autorisé pour tous sauf caissiers avec allow_export désactivé."""
    if not user:
        return False
    if str(user.get('role') or '').strip().lower() != 'cashier':
        return True
    return bool(user.get('allow_export', True))


def _user_dict_from_session(uid: str):
    """
    Repli si Firestore est temporairement indisponible : reprend les champs copiés en session à la connexion.
    Évite une déconnexion immédiate lors de timeouts / quotas GCP.
    """
    suid = str(uid or '').strip()
    if not suid or str(session.get('user_id') or '').strip() != suid:
        return None
    return {
        'id': suid,
        'role': str(session.get('role') or 'user'),
        'username': str(session.get('username') or ''),
        'full_name': str(session.get('full_name') or ''),
        'gym_name': str(session.get('gym_name') or ''),
        'phone': str(session.get('phone') or ''),
        'secondary_phone': str(session.get('secondary_phone') or ''),
        'email': str(session.get('email') or ''),
        'address': str(session.get('address') or ''),
        'owner_id': str(session.get('owner_id') or suid),
        'is_active': True,
        'allow_export': bool(session.get('allow_export', True)),
    }


def _current_user():
    """Un seul aller-retour Firestore par requête HTTP (décorateurs + context_processor)."""
    if '_qrprint_user' in g:
        return g._qrprint_user
    uid = _session_account_id()
    if not uid:
        g._qrprint_user = None
        return None

    user = None
    firestore_failed = False
    for attempt in range(3):
        try:
            user = store.get_user_by_id(uid)
            firestore_failed = False
            break
        except GoogleAPICallError as e:
            firestore_failed = True
            if attempt < 2:
                time.sleep(0.12 * (attempt + 1))
            else:
                app.logger.warning(
                    "Firestore: lecture utilisateur %s impossible après 3 tentatives: %s",
                    uid,
                    e,
                )

    if user is None and firestore_failed:
        user = _user_dict_from_session(uid)
        if user:
            g._qrprint_user = user
            return user

    if not user:
        g._qrprint_user = None
        return None
    if not bool(user.get('is_active', True)):
        g._qrprint_user = None
        return None
    db_sv = int(user.get('session_version') or 0)
    sess_sv = int(session.get('session_version', 0))
    if sess_sv != db_sv:
        session.clear()
        g._qrprint_user = None
        return None
    if 'phone' not in session or 'address' not in session:
        session['phone'] = str(user.get('phone') or '')
        session['address'] = str(user.get('address') or '')
    if 'secondary_phone' not in session:
        session['secondary_phone'] = str(user.get('secondary_phone') or '')
    if 'email' not in session:
        session['email'] = str(user.get('email') or '')
    oid = str(user.get('owner_id') or user.get('id') or '').strip()
    if str(session.get('owner_id') or '') != oid:
        session['owner_id'] = oid
    if str(user.get('role') or '').strip().lower() == 'cashier':
        session['allow_export'] = bool(user.get('allow_export', True))
    else:
        session.pop('allow_export', None)
    g._qrprint_user = user
    return user


def _is_authenticated():
    return _current_user() is not None


def _profile_complete(user: dict) -> bool:
    if not user:
        return False
    # Pour les comptes salle (user), ces champs sont obligatoires.
    role = str(user.get('role') or '').strip().lower()
    if role == 'superadmin':
        return True
    if role == 'operator':
        return True
    if role == 'cashier':
        return True
    required = [
        str(user.get('gym_name') or '').strip(),
        str(user.get('phone') or '').strip(),
        str(user.get('address') or '').strip(),
    ]
    return all(required)


def redirect_to_login():
    if session.get('user_id') and not _is_authenticated():
        session.clear()
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Authentification requise', 'auth_required': True}), 401
    nxt = request.path if request.method == 'GET' else None
    return redirect(url_for('login', next=nxt or ''))


def require_tickets_list_session(func):
    """Liste / export des tickets : compte gestion (user, superadmin), pas le compte caisse « operator »."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not site_auth_required():
            return func(*args, **kwargs)
        if _is_authenticated():
            u = _current_user()
            if u and str(u.get('role') or '').strip().lower() == 'operator':
                if request.path.startswith('/api/'):
                    return jsonify({
                        'success': False,
                        'error': 'Accès réservé aux comptes gestion (liste des tickets et export). Le compte caisse crée des QR depuis l’accueil.',
                    }), 403
                return redirect(url_for('index'))
            # Caissier : même liste que le propriétaire (données via owner_id) ; export CSV/Excel selon allow_export.
            if not _profile_complete(u):
                if request.endpoint == 'complete_profile':
                    return func(*args, **kwargs)
                if request.path.startswith('/api/'):
                    return jsonify({
                        'success': False,
                        'error': 'Profil incomplet. Complétez votre profil structure.',
                        'profile_incomplete': True,
                    }), 428
                return redirect(url_for('complete_profile'))
            return func(*args, **kwargs)
        return redirect_to_login()
    return wrapper


# Alias historique : même garde que la liste des tickets (pas un rôle « admin » système).
require_admin_session = require_tickets_list_session


def require_operator_or_admin_session(func):
    """Pages caisse + APIs création/impression : session requise (y compris rôle operator)."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not site_auth_required():
            return func(*args, **kwargs)
        if _is_authenticated():
            u = _current_user()
            if not _profile_complete(u):
                if request.endpoint == 'complete_profile':
                    return func(*args, **kwargs)
                if request.path.startswith('/api/'):
                    return jsonify({
                        'success': False,
                        'error': 'Profil incomplet. Complétez votre profil structure.',
                        'profile_incomplete': True,
                    }), 428
                return redirect(url_for('complete_profile'))
            return func(*args, **kwargs)
        return redirect_to_login()
    return wrapper


def require_gym_owner_session(func):
    """Paramètres / gestion caissiers : propriétaire ou admin global, pas operator ni caissier."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not site_auth_required():
            return func(*args, **kwargs)
        if not _is_authenticated():
            return redirect_to_login()
        u = _current_user()
        if not u:
            return redirect_to_login()
        role = str(u.get('role') or '').strip().lower()
        if role in ('operator', 'cashier'):
            if request.path.startswith('/api/'):
                return jsonify({
                    'success': False,
                    'error': 'Accès réservé au propriétaire de la salle (dashboard).',
                }), 403
            if role == 'cashier':
                return redirect(url_for('tickets'))
            return redirect(url_for('index'))
        if not _profile_complete(u):
            if request.endpoint == 'complete_profile':
                return func(*args, **kwargs)
            return redirect(url_for('complete_profile'))
        return func(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_session():
    sa = site_auth_required()
    u = _current_user()
    return {
        'current_role': session.get('role'),
        'current_user': session.get('username'),
        'current_gym_name': session.get('gym_name'),
        'current_full_name': session.get('full_name'),
        'site_auth_required': sa,
        'operator_login_required': sa,
        'admin_login_required': admin_login_required(),
        'tickets_refresh_ms': app.config.get('DASHBOARD_REFRESH_MS', 120000),
        'list_qr_per_page': app.config.get('LIST_QR_PER_PAGE', 15),
        'profile_incomplete': bool(u and not _profile_complete(u)),
        'can_manage_settings': str(session.get('role') or '').strip().lower() not in ('operator', 'cashier'),
        'tickets_can_export': _user_can_export_tickets(u) if u else True,
    }

def _warn_operator_admin_username_collision():
    """Évite la confusion si deux mots de passe .env ciblent le même identifiant Firestore."""
    a = (app.config.get('ADMIN_USERNAME') or 'admin').strip().lower()
    o = (app.config.get('OPERATOR_USERNAME') or 'operator').strip().lower()
    if a == o and (app.config.get('ADMIN_PASSWORD') and app.config.get('OPERATOR_PASSWORD')):
        app.logger.warning(
            "ADMIN_USERNAME et OPERATOR_USERNAME sont identiques (%s) alors que les deux mots de passe sont "
            "définis : un seul compte Firestore existe ; utilisez des identifiants distincts.",
            a,
        )


# Initialisation de la base de données
def init_db():
    """Initialise les collections Firestore (schema-less)."""
    store.init_schema()
    _warn_operator_admin_username_collision()
    ensure_legacy_admin_user()
    ensure_superadmin_user()
    ensure_operator_user()


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """Évite un 400 brut: retour à login avec message clair."""
    app.logger.warning("CSRF invalide: %s", e.description)
    return redirect(url_for('login', error='csrf'))

def generate_qr_hash(data):
    """Génère un hash unique pour le QR Code"""
    return hashlib.sha256(data.encode()).hexdigest()

def sign_qr_data(data):
    """Signe cryptographiquement les données du QR Code avec HMAC"""
    signature = hmac.new(
        app.config['QR_SIGNATURE_KEY'].encode(),
        data.encode(),
        hashlib.sha256
    ).hexdigest()
    return f"{data}|{signature}"

def verify_qr_signature(signed_data):
    """Vérifie la signature d'un QR Code"""
    try:
        data, signature = signed_data.rsplit('|', 1)
        expected_signature = hmac.new(
            app.config['QR_SIGNATURE_KEY'].encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected_signature)
    except (ValueError, TypeError):
        return False

def generate_qr_code_image(data, size=None):
    """Génère une image QR Code"""
    if size is None:
        size = app.config['QR_CODE_SIZE']
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=app.config['QR_CODE_BORDER'],
    )
    qr.add_data(data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    
    return img

def qr_to_base64(img):
    """Convertit une image PIL en base64"""
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return img_str


def _import_escpos_printer_classes():
    """
    Import différé de python-escpos (charge pkg_resources via setuptools).
    Évite d’importer au chargement du module : démarrage Gunicorn / Render plus fiable.
    """
    from escpos.exceptions import USBNotFoundError
    from escpos.printer import Network, Usb

    return Usb, Network, USBNotFoundError


def get_printer():
    """Obtient une instance de l'imprimante thermique"""
    Usb, Network, USBNotFoundError = _import_escpos_printer_classes()
    printer = None
    
    # Tentative de connexion USB
    if app.config.get('PRINTER_NETWORK_IP'):
        try:
            printer = Network(app.config['PRINTER_NETWORK_IP'], 
                            port=app.config.get('PRINTER_NETWORK_PORT', 9100))
            return printer
        except Exception as e:
            app.logger.warning(f"Impossible de se connecter à l'imprimante réseau: {e}")
    
    # Tentative de connexion USB (auto-détection)
    try:
        # Auto-détection de l'imprimante USB ESC/POS
        printer = Usb()
        return printer
    except (USBNotFoundError, ValueError, AttributeError) as e:
        # USBNotFoundError pour python-escpos, ValueError/AttributeError pour autres erreurs USB
        app.logger.warning(f"Aucune imprimante USB trouvée: {e}")
    except Exception as e:
        app.logger.warning(f"Erreur lors de la connexion USB: {e}")
    
    return None


# Cache léger pour /api/status uniquement (évite timeouts USB à chaque polling client).
_printer_status_lock = threading.Lock()
_printer_status_until_monotonic = 0.0
_printer_status_cached = {'connected': False, 'info': None}

# Réduction lectures Firestore : réponses GET /api/list_qr (invalidées après mutation).
_list_qr_resp_cache_lock = threading.Lock()
_list_qr_resp_cache = {}
_LIST_QR_CACHE_MAX_KEYS = 64

# Migration QR sans owner_id : évite de rescanner jusqu'à 10k docs à chaque login.
_attach_unowned_lock = threading.Lock()
_attach_unowned_last_monotonic = 0.0


def _maybe_attach_owner_to_unowned_qr(owner_id: str) -> int:
    """
    Migration QR sans owner_id — scan potentiellement très coûteux en lectures Firestore.
    Cooldown process-local : évite de répéter à chaque ouverture de /login (voir config).
    """
    cooldown = int(app.config.get('ATTACH_UNOWNED_QR_COOLDOWN_SECONDS') or 0)
    if cooldown <= 0:
        return store.attach_owner_to_unowned_qr(owner_id)
    global _attach_unowned_last_monotonic
    with _attach_unowned_lock:
        now = time.monotonic()
        if now - _attach_unowned_last_monotonic < cooldown:
            return 0
        count = store.attach_owner_to_unowned_qr(owner_id)
        _attach_unowned_last_monotonic = time.monotonic()
        return count


def _invalidate_list_qr_cache_for_owner(owner_id):
    """Après création / suppression / impression : évite une liste tickets obsolète si cache activé."""
    oid = str(owner_id or '').strip()
    if not oid:
        return
    prefix = oid + '|'
    with _list_qr_resp_cache_lock:
        for k in list(_list_qr_resp_cache.keys()):
            if k.startswith(prefix):
                _list_qr_resp_cache.pop(k, None)


def _invalidate_list_qr_cache_all():
    """Nettoyage global (ex. job expiration_ts) : tout compte peut être impacté."""
    with _list_qr_resp_cache_lock:
        _list_qr_resp_cache.clear()


def _probe_printer_status():
    """Sonde réelle de l’imprimante (réseau/USB). Utilisé par /api/status et non mis en cache côté appelant impression."""
    printer_connected = False
    printer_info = None
    try:
        printer = get_printer()
        if printer:
            printer_connected = True
            printer_info = 'Imprimante connectée'
            printer.close()
        else:
            printer_info = 'Aucune imprimante détectée'
    except Exception as e:
        printer_info = f'Erreur: {str(e)}'
    return printer_connected, printer_info


PAYMENT_MODES = frozenset({'especes', 'orange_money', 'wave'})


def payment_mode_label(code: str) -> str:
    m = (code or '').strip().lower()
    return {
        'especes': 'Espèces',
        'orange_money': 'Orange Money',
        'wave': 'Wave',
    }.get(m, (code or '').strip())


def parse_amount_field(val, field_label: str):
    """Montant >= 0 (€ ou devise locale)."""
    if val is None:
        raise ValueError(f'{field_label} obligatoire')
    if isinstance(val, str) and not val.strip():
        raise ValueError(f'{field_label} obligatoire')
    try:
        x = float(val)
    except (TypeError, ValueError):
        raise ValueError(f'{field_label} invalide')
    if x < 0:
        raise ValueError(f'{field_label} doit être positif ou nul')
    return round(x, 2)


_SN_MOBILE_PREFIXES = frozenset({'77', '75', '76', '71', '78', '33', '70'})
_SN_PHONE_ERR_MSG = 'Veuillez saisir un bon numéro'


def normalize_sn_mobile_phone(raw) -> str:
    """Normalise en +221 + partie locale : 9 chiffres (221 / indicatif pays exclus du décompte)."""
    if raw is None:
        raise ValueError(_SN_PHONE_ERR_MSG)
    all_digits = ''.join(c for c in str(raw) if c.isdigit())
    if not all_digits:
        raise ValueError(_SN_PHONE_ERR_MSG)
    if len(all_digits) == 12 and all_digits.startswith('221'):
        local = all_digits[3:12]
    elif len(all_digits) == 9:
        local = all_digits
    else:
        raise ValueError(_SN_PHONE_ERR_MSG)
    if len(local) != 9 or local[:2] not in _SN_MOBILE_PREFIXES:
        raise ValueError(_SN_PHONE_ERR_MSG)
    return '+221' + local


def sn_phone_local_display(raw) -> str:
    """Partie locale 9 chiffres pour formulaires (+221…, 221… ou déjà 9 chiffres)."""
    if raw is None:
        return ''
    s = str(raw).strip()
    digits = ''.join(c for c in s if c.isdigit())
    if len(digits) >= 12 and digits.startswith('221'):
        return digits[3:12]
    if len(digits) == 9:
        return digits
    if s.startswith('+221') and len(s) >= 13:
        return ''.join(c for c in s[4:13] if c.isdigit())[:9]
    return ''


@app.template_filter('sn_phone_local')
def sn_phone_local_filter(raw):
    return sn_phone_local_display(raw)


def format_iso_datetime_display(val):
    """Affichage court pour created_at (ISO Firestore / Python)."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt.strftime('%d/%m/%Y à %H:%M')
    except (ValueError, TypeError, OSError):
        return s


def expiration_delta_minus_one_second(delta: timedelta) -> timedelta:
    """
    Durée effective stockée = durée choisie moins 1 seconde
    (ex. 2 h → affichage du temps restant ~ 1 h 59 min 59 s ; 1 j → ~ 23 h 59 min 59 s).
    """
    out = delta - timedelta(seconds=1)
    if out.total_seconds() < 1:
        return timedelta(seconds=1)
    return out


def format_expiration_text(expiration_date):
    """Temps restant jusqu'à l'expiration : jour(s), heure(s), minute(s) (sans secondes)."""
    now = datetime.now()
    delta = expiration_date - now
    total_secs = int(delta.total_seconds())
    if total_secs <= 0:
        return 'Expiré'
    days, rem = divmod(total_secs, 86400)
    hours, rem2 = divmod(rem, 3600)
    minutes = rem2 // 60
    parts = []
    if days:
        parts.append(f'{days} jour(s)')
    if hours:
        parts.append(f'{hours} heure(s)')
    if minutes:
        parts.append(f'{minutes} minute(s)')
    if not parts:
        parts.append("moins d'1 minute")
    return ' '.join(parts)


def ticket_width():
    """Caractères par ligne pour l’imprimante thermique (80 mm)."""
    return max(24, min(48, int(app.config.get('TICKET_WIDTH_CHARS') or 32)))


def ticket_preview_width():
    """Caractères par ligne pour l’aperçu web (peut être plus large que le papier)."""
    d = int(app.config.get('TICKET_PREVIEW_WIDTH_CHARS') or 52)
    return max(32, min(80, d))


def format_amount_ticket(val):
    """Montant affiché type caisse (ex. 20 000 ou 1 250,50)."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return '0'
    try:
        x = float(val)
    except (TypeError, ValueError):
        return str(val).strip()
    if abs(x - round(x, 2)) < 0.001:
        n = int(round(x))
        return '{:,}'.format(n).replace(',', ' ')
    intpart = int(abs(x))
    frac = int(round((abs(x) - intpart) * 100))
    sign = '-' if x < 0 else ''
    return sign + '{:,}'.format(intpart).replace(',', ' ') + ',{:02d}'.format(frac)


def ticket_row_lr_lines(left, right, width=None, *, left_max=None, right_numeric=False):
    """
    Une ou plusieurs lignes : libellé + valeur sur la même ligne tant que possible ;
    si la valeur dépasse la colonne droite, les suites restent alignées sous la valeur (pas de libellé seul).
    """
    w = width or ticket_width()
    L = (left or '').strip()
    R = (str(right) if right is not None else '').strip()
    if not R:
        return [(L or '')[:w].ljust(w)[:w]]
    if left_max is not None:
        mid = max(7, min(w - 8, int(left_max)))
    else:
        mid = w // 2
    rc = w - mid
    if len(R) <= rc:
        Lfit = L[:mid].ljust(mid)
        Rfit = R.rjust(rc) if right_numeric else R.ljust(rc)
        return [(Lfit + Rfit)[:w]]
    Lfit = L[:mid].ljust(mid)
    out = []
    pos = 0
    first = True
    while pos < len(R):
        chunk = R[pos : pos + rc]
        pos += len(chunk)
        rfit = chunk.rjust(rc) if right_numeric else chunk.ljust(rc)
        if first:
            out.append((Lfit + rfit)[:w])
            first = False
        else:
            out.append((' ' * mid + chunk.ljust(rc))[:w])
    return out


def ticket_header_salle_block(sub_label, gym_name, address, phone, width=None):
    """
    En-tête sous REÇU :
    - gauche : libellé (ex. SALLE DE GYM) puis adresse sur les lignes suivantes ;
    - droite : nom de la salle puis téléphone (alignés à droite).
    """
    w = width or ticket_width()
    sub_label = (sub_label or 'SALLE DE GYM').strip().upper()
    gn = (gym_name or '-').strip()
    addr = (address or '').strip() or '-'
    ph = (phone or '-').strip()
    rc = max(len(ph), min(len(gn), w - 8), 10)
    rc = min(rc, w - 8)
    lc = w - rc
    right_parts = []
    pos = 0
    while pos < len(gn):
        chunk = gn[pos : pos + rc]
        pos += len(chunk)
        right_parts.append(chunk.rjust(rc))
    if not right_parts:
        right_parts = ['-'.rjust(rc)]
    right_parts.append(ph.rjust(rc))
    left_parts = [sub_label[:lc].ljust(lc)]
    pos = 0
    while pos < len(addr):
        left_parts.append(addr[pos : pos + lc].ljust(lc))
        pos += lc
    n = max(len(left_parts), len(right_parts))
    out = []
    for i in range(n):
        L = left_parts[i] if i < len(left_parts) else (' ' * lc)
        Rcol = right_parts[i] if i < len(right_parts) else (' ' * rc)
        out.append((L[:lc].ljust(lc) + Rcol[:rc].rjust(rc))[:w])
    return out


def ticket_client_info_lines(
    client_phone,
    who,
    email,
    client_address,
    width=None,
    *,
    include_client_phone=False,
):
    """
    Bloc client : même principe que l'en-tête salle (colonnes lc / rc, valeurs alignées à droite).
    Gauche : Nom, [Numéro si demandé], Mail, Adresse.
    Droite : valeurs alignées à droite (le numéro client n'est pas imprimé sur le ticket par défaut).
    """
    w = width or ticket_width()
    who = ((who or '').strip() or '-')
    num = ((str(client_phone).strip() if client_phone else '') or '-')
    email = ((email or '').strip() or '-')
    addr = ((client_address or '').strip() or '-')

    rights_raw = ([who, num, email, addr] if include_client_phone else [who, email, addr])
    rc = max(len(s) for s in rights_raw)
    rc = max(10, min(rc, w - 8))
    lc = w - rc

    left_parts = []
    right_parts = []

    def append_field(label, value):
        v = (value or '').strip() or '-'
        first = True
        pos = 0
        while pos < len(v):
            chunk = v[pos : pos + rc]
            pos += len(chunk)
            right_parts.append(chunk.rjust(rc))
            if first:
                left_parts.append(label[:lc].ljust(lc))
                first = False
            else:
                left_parts.append(' ' * lc)

    append_field('Nom:', who)
    if include_client_phone:
        append_field('Numéro:', num)
    append_field('Mail:', email)
    append_field('Adresse:', addr)

    n = max(len(left_parts), len(right_parts))
    out = []
    for i in range(n):
        L = left_parts[i] if i < len(left_parts) else (' ' * lc)
        Rcol = right_parts[i] if i < len(right_parts) else (' ' * rc)
        out.append((L[:lc].ljust(lc) + Rcol[:rc].rjust(rc))[:w])
    return out


def ticket_row_lr(left, right, width=None, *, left_max=None, right_numeric=False):
    """Première ligne seulement (compat)."""
    return ticket_row_lr_lines(left, right, width, left_max=left_max, right_numeric=right_numeric)[0]


def ticket_item_lines(qty, description, amount_str, width=None):
    """Ligne(s) article : libellé sur une ou plusieurs lignes, montant sur la dernière ligne à droite."""
    w = width or ticket_width()
    qty_s = str(qty).strip() or '1'
    desc = (description or '').strip()
    amt = (amount_str or '').strip()
    prefix = f'{qty_s}  '
    reserve = len(amt) + 1
    max_desc = max(4, w - len(prefix) - reserve)
    if not desc:
        line = prefix.rstrip()
        pad = w - len(line) - len(amt)
        return [line + (' ' * max(1, pad)) + amt]
    if len(prefix) + len(desc) + reserve <= w:
        line = (prefix + desc).strip()
        pad = w - len(line) - len(amt)
        pad = max(1, pad)
        return [line + (' ' * pad) + amt]
    chunks = []
    i = 0
    while i < len(desc):
        chunks.append(desc[i : i + max_desc])
        i += max_desc
    if not chunks:
        chunks = ['']
    out = []
    for idx, dch in enumerate(chunks):
        pre = prefix if idx == 0 else ' ' * len(prefix)
        is_last = idx == len(chunks) - 1
        if is_last:
            line = pre + dch
            pad = w - len(line) - len(amt)
            if pad < 1:
                dch = dch[: max(0, len(dch) - 1)]
                line = pre + dch
                pad = w - len(line) - len(amt)
                pad = max(1, pad)
            out.append(line + (' ' * pad) + amt)
        else:
            out.append((pre + dch).ljust(w)[:w])
    return out


def ticket_item_line(qty, description, amount_str, width=None):
    """Une seule ligne (rétrocompat) : tronque si nécessaire."""
    return ticket_item_lines(qty, description, amount_str, width)[0]


def _parse_iso_datetime(val):
    if not val:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _ticket_branding_from_owner(owner_user):
    u = owner_user or {}
    return {
        'gym_name': (u.get('gym_name') or app.config.get('ADMIN_GYM_NAME') or 'Salle de sport').strip(),
        'subtitle': (app.config.get('TICKET_SUBTITLE') or 'SALLE DE GYM').strip(),
        'phone_line': (u.get('phone') or app.config.get('ADMIN_PHONE') or '').strip(),
        'gym_address': (u.get('address') or app.config.get('ADMIN_ADDRESS') or '').strip(),
    }


def _wrap_center_lines(text, width):
    t = (text or '').strip()
    if not t:
        return []
    lines = []
    for line in textwrap.wrap(t, width=width, break_long_words=True, break_on_hyphens=False):
        lines.append(line.center(width))
    return lines


def build_ticket_preview_parts(rec, expiration_date, owner_user=None, session_dict=None, *, emis_label=True):
    """
    Lignes du ticket découpées : (avant le QR, après le QR), pour l'aperçu écran.
    """
    w = ticket_preview_width()
    branding = _ticket_branding_from_owner(owner_user)

    def g(key):
        try:
            v = rec[key]
        except (KeyError, TypeError, IndexError):
            return ''
        if v is None:
            return ''
        return str(v).strip()

    before = []

    title = 'Reçu  de paiement'
    if title:
        before.append(title.center(w))
        before.append('')

    who = (g('client_name') + (' ' + g('client_firstname') if g('client_firstname') else '')).strip()
    before.extend(
        ticket_client_info_lines(
            g('client_phone') or '-',
            who,
            g('client_email') or '-',
            g('client_address') or '',
            w,
            include_client_phone=False,
        )
    )

    before.append('')

    prest = g('subscription_type') or 'Prestation'
    amt_paid = f"{format_amount_ticket(rec.get('amount_paid'))} F CFA"
    before.extend(ticket_row_lr_lines('Prestation:', prest, w, right_numeric=True))
    before.extend(ticket_row_lr_lines('Somme versée:', amt_paid, w, right_numeric=True))
    before.append('')

    thanks = (app.config.get('TICKET_THANKS') or 'Merci de votre fidélité').strip()
    if thanks and not thanks.endswith('!'):
        thanks = f'{thanks} !'
    after = []

    def append_block_with_gap(text):
        t = (text or '').strip()
        if not t:
            return
        after.extend(textwrap.wrap(t, width=w, break_long_words=True, break_on_hyphens=False))
        after.append('')

    append_block_with_gap((branding['gym_name'] or '-').strip() or '-')
    append_block_with_gap((branding.get('phone_line') or '').strip())
    append_block_with_gap((branding.get('gym_address') or '').strip())
    append_block_with_gap(thanks)
    if after and after[-1] == '':
        after.pop()
    after.append('SCANNEZ À L\'ENTRÉE'.center(w))
    exp_txt = f"Expire le {expiration_date.strftime('%d/%m/%Y %H:%M')}"
    for ln in textwrap.wrap(exp_txt, width=w, break_long_words=True, break_on_hyphens=False):
        after.append(ln.center(w))
    return before, after


def format_ticket_text_lines(rec, expiration_date, owner_user=None, session_dict=None, *, emis_label=True):
    """Texte du ticket (aperçu), avec placeholder à la place du QR (légacy / copie)."""
    w = ticket_preview_width()
    before, after = build_ticket_preview_parts(
        rec, expiration_date, owner_user, session_dict, emis_label=emis_label
    )
    ph = '[ QR code imprimé sous ce bloc ]'.center(w)
    return before + [ph, ''] + after


def print_receipt_escpos(printer, qr_record, expiration_date, owner_user=None):
    """Impression thermique type reçu de caisse + QR en bas."""
    w = ticket_width()
    branding = _ticket_branding_from_owner(owner_user)

    def emit(txt):
        printer.text(txt)

    def emit_lr(left, right, **kw):
        for line in ticket_row_lr_lines(left, right, width=w, **kw):
            emit(line + '\n')

    client_name = str(qr_record.get('client_name') or '').strip()
    firstn = str(qr_record.get('client_firstname') or '').strip()
    who = (client_name + (' ' + firstn if firstn else '')).strip()
    client_phone = str(qr_record.get('client_phone') or '').strip()
    client_email = str(qr_record.get('client_email') or '').strip()
    client_address = str(qr_record.get('client_address') or '').strip()
    prest = str(qr_record.get('subscription_type') or 'Prestation').strip()
    prest_line = prest

    printer.set(align='center', font='a', width=1, height=1)
    emit('\n')

    title_rx = 'Reçu  de paiement'
    if title_rx:
        printer.set(align='center', font='b', width=1, height=1)
        emit(title_rx[: w + 4] + '\n')
        emit('\n')
    printer.set(align='left', font='a', width=1, height=1)

    for line in ticket_client_info_lines(
        client_phone or '-',
        who,
        client_email or '-',
        client_address or '',
        w,
        include_client_phone=False,
    ):
        emit(line + '\n')

    emit('\n')

    amt_paid = f"{format_amount_ticket(qr_record.get('amount_paid'))} F CFA"
    emit_lr('Prestation:', prest_line, right_numeric=True)
    emit_lr('Somme versée:', amt_paid, right_numeric=True)
    emit('\n')

    printer.set(align='center')
    qr_img = generate_qr_code_image(qr_record['qr_data'], size=220)
    try:
        printer.image(qr_img, impl='bitImageRaster', center=True)
    except AttributeError:
        try:
            printer.image(qr_img, center=True)
        except Exception:
            emit('\nQR\n')
            emit(str(qr_record.get('qr_hash') or '')[:32] + '\n')
    except Exception as e:
        app.logger.warning('Erreur impression image QR: %s', e)
        emit('\nQR\n')
        emit(str(qr_record.get('qr_hash') or '')[:32] + '\n')

    emit('\n')
    printer.set(align='center', font='b', width=1, height=1)
    emit(branding['gym_name'][: w + 8] + '\n')
    printer.set(align='center', font='a', width=1, height=1)
    phone_salle = (branding.get('phone_line') or '').strip()
    gym_addr = (branding.get('gym_address') or '').strip()
    for chunk in textwrap.wrap(phone_salle, width=w, break_long_words=True):
        emit(chunk.center(w) + '\n')
    for chunk in textwrap.wrap(gym_addr, width=w, break_long_words=True):
        emit(chunk.center(w) + '\n')
    thanks = (app.config.get('TICKET_THANKS') or 'MERCI DE VOTRE FIDÉLITÉ').strip()
    if thanks and not thanks.endswith('!'):
        thanks = f'{thanks} !'
    for chunk in textwrap.wrap(thanks, width=w, break_long_words=True):
        emit(chunk.center(w) + '\n')

    printer.set(align='center', font='b', width=1, height=1)
    emit("SCANNEZ A L'ENTREE\n")
    printer.set(align='center', font='a', width=1, height=1)
    exp_block = f"Expire le {expiration_date.strftime('%d/%m/%Y %H:%M')}"
    for chunk in textwrap.wrap(exp_block, width=w, break_long_words=True, break_on_hyphens=False):
        emit(chunk.center(w) + '\n')
    emit('\n\n')


def _normalize_tickets_author_id(requested: str, owner_id: str) -> str:
    """Paramètre `author` des listes / exports : uniquement le propriétaire de la salle ou un de ses caissiers."""
    req = (requested or '').strip()
    oid = str(owner_id or '').strip()
    if not req or not oid:
        return ''
    if req == oid:
        return oid
    try:
        target = store.get_user_by_id(req)
    except Exception:
        return ''
    if not target:
        return ''
    if str(target.get('role') or '').strip().lower() != 'cashier':
        return ''
    if str(target.get('owner_id') or '').strip() != oid:
        return ''
    return req


def _tickets_author_filter_choices(owner_id: str) -> list:
    """Options du filtre Auteur (propriétaire + caissiers de la salle)."""
    oid = str(owner_id or '').strip()
    if not oid:
        return []
    out = [{'id': oid, 'label': 'Owner'}]
    try:
        cashiers = store.list_cashiers_for_owner(oid) or []
    except Exception:
        cashiers = []
    cashiers = sorted(
        cashiers,
        key=lambda x: (str(x.get('full_name') or x.get('username') or '')).lower(),
    )
    for c in cashiers:
        cid = str(c.get('id') or '').strip()
        if not cid:
            continue
        lab = ' '.join(str(c.get('full_name') or '').split()).strip() or str(c.get('username') or '')
        out.append({'id': cid, 'label': lab})
    return out


def _fetch_qr_list_rows(filter_type, search, ticket, date_from, date_to, limit, owner_id, author_id=""):
    oid = str(owner_id or "").strip()
    norm_author = _normalize_tickets_author_id(author_id, oid) if oid else ""
    filters = QueryFilters(
        filter_type=filter_type,
        search=search,
        ticket=ticket,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        author_account_id=norm_author,
        author_scope_owner_id=oid if norm_author else "",
    )
    return store.list_qr(filters, owner_id=owner_id)


_AUTHOR_SNAPSHOT_MAX_LEN = 120


def _created_by_snapshot_label(acting_user) -> str:
    """Libellé persisté sur le QR à la création : nom affiché du compte (full_name), sinon repli."""
    if not acting_user:
        return 'Owner'
    role_l = str(acting_user.get('role') or '').strip().lower()
    fn = ' '.join(str(acting_user.get('full_name') or '').split()).strip()
    if fn:
        return fn[:_AUTHOR_SNAPSHOT_MAX_LEN]
    if role_l == 'cashier':
        un = str(acting_user.get('username') or '').strip()
        parts = un.rsplit('-', 1)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip().upper()
        return (un[:16] or '?').upper()
    gn = ' '.join(str(acting_user.get('gym_name') or '').split()).strip()
    if gn:
        return gn[:_AUTHOR_SNAPSHOT_MAX_LEN]
    return 'Owner'


def _created_by_cell_for_qr_row(row: dict, viewer_user: dict, owner_id: str) -> str:
    """Texte colonne « Auteur » : vous / nom persisté à la création / Owner (QR anciens)."""
    vid = str((viewer_user or {}).get('id') or '').strip()
    oid = str(owner_id or '').strip()
    raw_creator = str(row.get('created_by_user_id') or '').strip()
    snap = str(row.get('created_by_display') or '').strip()
    cid = raw_creator or oid
    if vid and cid == vid:
        return 'vous'
    if snap:
        return snap
    if cid == oid:
        return 'Owner'
    return '—'


def _row_amount(val):
    """Montant numérique depuis un champ Firestore (QR)."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _row_created_date_key(row) -> str:
    """Date locale YYYY-MM-DD (created_at stocké en UTC naïf) pour agrégats jour / mois."""
    created_str = str(row.get('created_at') or '').strip()
    if not created_str:
        return ''
    s = created_str
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return created_str[:10] if len(created_str) >= 10 else ''


def _dashboard_stats_from_rows(rows, now=None):
    """Statistiques financières et suivi pour le dashboard propriétaire (une passe sur les lignes déjà filtrées)."""
    if now is None:
        now = datetime.now()
    today_key = now.strftime('%Y-%m-%d')
    month_key = now.strftime('%Y-%m')

    total_tickets = 0
    active_count = 0
    expired_count = 0
    revenue_total = 0.0
    revenue_today = 0.0
    revenue_month = 0.0
    amount_due_total = 0.0
    outstanding_total = 0.0
    printed_count = 0
    payment_totals = {m: 0.0 for m in PAYMENT_MODES}
    payment_counts = {m: 0 for m in PAYMENT_MODES}

    for row in rows:
        total_tickets += 1
        is_active_flag = bool(row.get('is_active', True))
        expiration_raw = str(row.get('expiration_date') or '')
        try:
            expiration_date = datetime.fromisoformat(expiration_raw)
            is_expired = now > expiration_date
        except ValueError:
            is_expired = True
        if not is_expired and is_active_flag:
            active_count += 1
        else:
            expired_count += 1

        paid = _row_amount(row.get('amount_paid'))
        due = _row_amount(row.get('amount_total'))
        revenue_total += paid
        amount_due_total += due
        outstanding_total += max(0.0, round(due - paid, 2))

        created_key = _row_created_date_key(row)
        if created_key == today_key:
            revenue_today += paid
        if created_key.startswith(month_key):
            revenue_month += paid

        if str(row.get('printed_at') or '').strip():
            printed_count += 1

        pm = str(row.get('payment_mode') or '').strip().lower()
        if pm in PAYMENT_MODES:
            payment_totals[pm] += paid
            payment_counts[pm] += 1

    avg_ticket = round(revenue_total / total_tickets, 2) if total_tickets else 0.0

    return {
        'total_tickets': total_tickets,
        'active': active_count,
        'expired': expired_count,
        'revenue_total': round(revenue_total, 2),
        'revenue_today': round(revenue_today, 2),
        'revenue_month': round(revenue_month, 2),
        'amount_due_total': round(amount_due_total, 2),
        'outstanding': round(outstanding_total, 2),
        'avg_ticket': avg_ticket,
        'printed_count': printed_count,
        'payment_breakdown': {
            mode: {
                'count': payment_counts[mode],
                'amount': round(payment_totals[mode], 2),
                'label': payment_mode_label(mode),
            }
            for mode in PAYMENT_MODES
        },
    }


def _qr_list_stats_from_rows(rows, now=None):
    """Compteurs actifs / expirés alignés sur la logique de _rows_to_qr_json_list (une passe, sans construire les dicts)."""
    if now is None:
        now = datetime.now()
    active_count = 0
    expired_count = 0
    for row in rows:
        is_active_flag = bool(row.get('is_active', True))
        expiration_raw = str(row.get('expiration_date') or '')
        try:
            expiration_date = datetime.fromisoformat(expiration_raw)
            is_expired = now > expiration_date
        except ValueError:
            is_expired = True
        if not is_expired and is_active_flag:
            active_count += 1
        else:
            expired_count += 1
    return active_count, expired_count


def _rows_to_qr_json_list(rows, now=None, viewer_user=None, owner_id=None):
    if now is None:
        now = datetime.now()
    viewer_user = viewer_user or {}
    oid = str(owner_id or '').strip()
    qr_list = []
    for row in rows:
        expiration_raw = str(row.get('expiration_date') or '')
        try:
            expiration_date = datetime.fromisoformat(expiration_raw)
            is_expired = now > expiration_date
        except ValueError:
            expiration_date = now
            is_expired = True
        qr_list.append({
            'id': row.get('id'),
            'client_name': row.get('client_name'),
            'client_firstname': row.get('client_firstname'),
            'client_phone': row.get('client_phone'),
            'client_email': row.get('client_email'),
            'client_address': row.get('client_address'),
            'ticket_number': row.get('ticket_number'),
            'subscription_type': row.get('subscription_type'),
            'amount_total': row.get('amount_total'),
            'amount_paid': row.get('amount_paid'),
            'payment_mode': row.get('payment_mode'),
            'service': row.get('service'),
            'created_at': row.get('created_at'),
            'created_by': _created_by_cell_for_qr_row(row, viewer_user, oid),
            'expiration_date': row.get('expiration_date'),
            'printed_at': row.get('printed_at'),
            'is_active': bool(row.get('is_active', True)),
            'is_expired': is_expired,
            'expiration_text': format_expiration_text(expiration_date) if not is_expired else 'Expiré'
        })
    return qr_list


def _login_session_from_user(user):
    """Écrit la session Flask comme après une connexion classique."""
    session.clear()
    session['role'] = str(user.get('role') or 'admin')
    uid = str(user.get('id') or '').strip()
    owner_scope = str(user.get('owner_id') or '').strip()
    session['user_id'] = uid
    session['owner_id'] = owner_scope if owner_scope else uid
    session['username'] = str(user.get('username') or '')
    session['full_name'] = str(user.get('full_name') or '')
    session['gym_name'] = str(user.get('gym_name') or '')
    session['phone'] = str(user.get('phone') or '')
    session['secondary_phone'] = str(user.get('secondary_phone') or '')
    session['email'] = str(user.get('email') or '')
    session['address'] = str(user.get('address') or '')
    session['session_version'] = int(user.get('session_version') or 0)
    if str(user.get('role') or '').strip().lower() == 'cashier':
        session['allow_export'] = bool(user.get('allow_export', True))
    else:
        session.pop('allow_export', None)
    session.permanent = True


def _resolve_or_create_google_user(userinfo):
    """
    Retourne (user_dict, None) ou (None, code_erreur).
    Codes : missing_claims, email_not_verified
    """
    sub = str(userinfo.get('sub') or '').strip()
    email = (userinfo.get('email') or '').strip().lower()
    name = (userinfo.get('name') or userinfo.get('given_name') or '').strip()
    email_verified = userinfo.get('email_verified')

    if not sub or not email:
        return None, 'missing_claims'
    if email_verified is False:
        return None, 'email_not_verified'

    user = store.get_user_by_google_sub(sub)
    if user:
        return user, None

    user = store.get_user_by_email(email)
    if user:
        store.update_user(user['id'], {'google_sub': sub})
        return store.get_user_by_id(user['id']), None

    local = email.split('@')[0]
    base_username = ''.join(c if c.isalnum() or c in '_-' else '_' for c in local)[:40]
    base_username = base_username.strip('_') or 'user'
    username = base_username
    while store.get_user_by_username(username):
        username = f'{base_username}_{secrets.token_hex(3)}'[:64]

    user_id = str(uuid.uuid4())
    store.create_user({
        'id': user_id,
        'username': username,
        'password_hash': generate_password_hash(secrets.token_urlsafe(32)),
        'role': 'user',
        'full_name': name or base_username,
        'gym_name': '',
        'phone': '',
        'address': '',
        'email': email,
        'google_sub': sub,
        'is_active': True,
        'created_at': datetime.utcnow().isoformat(),
        'source': 'google-oauth',
    })
    return store.get_user_by_id(user_id), None


# Routes principales
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Connexion / inscription des salles (multi-comptes)."""
    try:
        ensure_legacy_admin_user()
        ensure_superadmin_user()
        ensure_operator_user()
    except Exception as e:
        app.logger.warning("Synchronisation comptes au login ignorée: %s", e)

    # Session résiduelle (ex. ancienne version sans user_id) : évite boucles et menu « connecté » fantôme.
    if session.get('role') and not session.get('user_id'):
        session.clear()

    # Aligné avec index/API : session « role » seule peut boucler avec / si user_id absent ou utilisateur inconnu.
    if _is_authenticated():
        nxt = _safe_next_url(request.args.get('next')) or _safe_next_url(request.form.get('next'))
        return redirect(nxt or url_for('index'))

    error = None
    success = None
    active_tab = 'login'
    err_arg = (request.args.get('error') or '').strip().lower()
    if err_arg == 'csrf':
        error = "Session expirée. Rechargez la page puis réessayez."
    elif err_arg == 'google_oauth_disabled':
        error = "La connexion Google n'est pas configurée (identifiants OAuth manquants)."
    elif err_arg == 'google_email_not_verified':
        error = "Votre adresse Google n'est pas vérifiée. Vérifiez votre compte Google puis réessayez."
    elif err_arg == 'google_auth_failed':
        error = "La connexion Google a échoué. Réessayez ou utilisez identifiant / mot de passe."
    if (request.args.get('registered') or '').strip() == '1':
        success = "Inscription réussie. Connectez-vous."
    if request.method == 'POST':
        action = (request.form.get('action') or 'login').strip().lower()
        if action == 'register':
            active_tab = 'signup'
            gym_name = (request.form.get('gym_name') or '').strip()
            phone = (request.form.get('phone') or '').strip()
            secondary_phone = (request.form.get('secondary_phone') or '').strip()
            email = (request.form.get('email') or '').strip().lower()
            address = (request.form.get('address') or '').strip()
            username = (request.form.get('username') or '').strip().lower()
            password = request.form.get('password') or ''
            password_confirm = request.form.get('password_confirm') or ''

            if not all([gym_name, phone, address, username, password, password_confirm]):
                error = "Tous les champs d'inscription sont obligatoires."
            elif len(password) < 8:
                error = 'Le mot de passe doit contenir au moins 8 caractères.'
            elif password != password_confirm:
                error = 'La confirmation du mot de passe ne correspond pas.'
            elif email and '@' not in email:
                error = "L'email saisi est invalide."
            elif store.get_user_by_username(username):
                error = 'Cet identifiant existe déjà.'
            elif store.get_user_by_phone(phone):
                error = 'Ce numéro de téléphone existe déjà.'
            elif secondary_phone and secondary_phone == phone:
                error = 'Le 2e numéro doit être différent du numéro principal.'
            else:
                store.create_user({
                    'id': str(uuid.uuid4()),
                    'username': username,
                    'password_hash': generate_password_hash(password),
                    'role': 'user',
                    'full_name': gym_name,
                    'gym_name': gym_name,
                    'phone': phone,
                    'secondary_phone': secondary_phone,
                    'email': email,
                    'address': address,
                    'is_active': True,
                    'created_at': datetime.utcnow().isoformat(),
                    'source': 'self-signup',
                })
                return redirect(url_for('login', registered='1'))
        else:
            username = (request.form.get('username') or '').strip()
            password = request.form.get('password') or ''
            user = try_login(username, password)
            if user:
                _login_session_from_user(user)
                session['username'] = str(user.get('username') or username)
                nxt = _safe_next_url(request.form.get('next'))
                return redirect(nxt or url_for('index'))
            error = 'Identifiants invalides.'
            active_tab = 'login'

    next_arg = _safe_next_url(request.args.get('next')) or ''
    return render_template('login.html', error=error, success=success, next_url=next_arg, active_tab=active_tab)


@app.route('/auth/google')
def auth_google():
    """Démarre le flux OAuth Google (Authlib)."""
    if not _google_oauth_configured():
        return redirect(url_for('login', error='google_oauth_disabled'))
    nxt = _safe_next_url(request.args.get('next'))
    if nxt:
        session['oauth_next'] = nxt
    else:
        session.pop('oauth_next', None)
    redirect_uri = _google_oauth_redirect_uri()
    return oauth.google.authorize_redirect(redirect_uri)


@app.route('/auth/google/callback')
def auth_google_callback():
    """Callback OAuth Google — doit correspondre à l'URI enregistrée dans Google Cloud Console."""
    if not _google_oauth_configured():
        return redirect(url_for('login', error='google_oauth_disabled'))
    try:
        token = oauth.google.authorize_access_token()
    except Exception as exc:
        app.logger.warning('OAuth Google (authorize_access_token): %s', exc)
        return redirect(url_for('login', error='google_auth_failed'))

    userinfo = token.get('userinfo')
    if not userinfo:
        try:
            resp = oauth.google.get('https://openidconnect.googleapis.com/v1/userinfo', token=token)
            userinfo = resp.json()
        except Exception as exc:
            app.logger.warning('OAuth Google (userinfo): %s', exc)
            return redirect(url_for('login', error='google_auth_failed'))

    user, err = _resolve_or_create_google_user(userinfo)
    if err == 'email_not_verified':
        return redirect(url_for('login', error='google_email_not_verified'))
    if err == 'missing_claims' or not user:
        return redirect(url_for('login', error='google_auth_failed'))

    if not bool(user.get('is_active', True)):
        return redirect(url_for('login', error='google_auth_failed'))

    _login_session_from_user(user)

    nxt = _safe_next_url(session.pop('oauth_next', None))
    if not _profile_complete(user):
        return redirect(url_for('complete_profile'))
    return redirect(nxt or url_for('index'))


csrf.exempt(auth_google_callback)


@app.route('/complete-profile', methods=['GET', 'POST'])
@require_operator_or_admin_session
def complete_profile():
    """Compléter les infos structure après connexion (ex: OAuth)."""
    user = _current_user()
    if not user:
        return redirect_to_login()
    if _profile_complete(user):
        return redirect(url_for('index'))

    error = None
    if request.method == 'POST':
        gym_name = (request.form.get('gym_name') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        secondary_phone = (request.form.get('secondary_phone') or '').strip()
        address = (request.form.get('address') or '').strip()
        if not all([gym_name, phone, address]):
            error = 'Nom de la structure, téléphone et adresse sont obligatoires.'
        elif secondary_phone and secondary_phone == phone:
            error = 'Le 2e numéro doit être différent du numéro principal.'
        else:
            store.update_user(user['id'], {
                'gym_name': gym_name,
                'full_name': gym_name,
                'phone': phone,
                'secondary_phone': secondary_phone,
                'address': address,
            })
            session['gym_name'] = gym_name
            session['full_name'] = gym_name
            session['phone'] = phone
            session['secondary_phone'] = secondary_phone
            session['address'] = address
            session['owner_id'] = str(user.get('id') or '')
            return redirect(url_for('index'))

    return render_template(
        'complete_profile.html',
        error=error,
        user=user,
    )


def _can_manage_cashiers(user):
    """Propriétaire salle (user) ou admin / superadmin — pas caissier ni opérateur."""
    if not user:
        return False
    return str(user.get('role') or '').strip().lower() in ('user', 'admin', 'superadmin')


def _owned_cashier_for_owner(owner_user, cashier_id: str):
    """Document caissier si `cashier_id` appartient à la salle de `owner_user`, sinon None."""
    if not owner_user or not _can_manage_cashiers(owner_user):
        return None
    cid = str(cashier_id or '').strip()
    if not cid:
        return None
    target = store.get_user_by_id(cid)
    if not target:
        return None
    if str(target.get('role') or '').strip().lower() != 'cashier':
        return None
    if str(target.get('owner_id') or '').strip() != str(owner_user.get('id') or '').strip():
        return None
    return target


def _max_cashier_numeric_suffix(owner_username: str, cashiers: list) -> int:
    """Plus grand N pour des identifiants « owner-cN » (N entier) parmi les caissiers listés."""
    base = (owner_username or '').strip().lower()
    if not base:
        return 0
    pat = re.compile(r'^' + re.escape(base) + r'-c(\d+)$')
    highest = 0
    for row in cashiers or []:
        u = str((row or {}).get('username') or '').strip().lower()
        m = pat.match(u)
        if m:
            highest = max(highest, int(m.group(1)))
    return highest


def _allocate_cashier_username(store, owner_username: str, cashiers: list):
    """Premier identifiant libre du type owner-c01, owner-c02, … (vérifie aussi l’unicité en base)."""
    owner_un = (owner_username or '').strip().lower()
    if not owner_un:
        return None
    n = _max_cashier_numeric_suffix(owner_un, cashiers) + 1
    for _ in range(500):
        candidate = f'{owner_un}-c{n:02d}'
        if not store.get_user_by_username(candidate):
            return candidate
        n += 1
    return None


def _create_owned_cashier_account(store, owner_user, owner_un: str, c_pw: str, cashier_display_name: str):
    """
    Crée un caissier rattaché au propriétaire avec identifiant owner-cNN.
    `cashier_display_name` : nom affiché (colonne Auteur de la liste tickets, full_name en base).
    Retourne (username, None) en cas de succès, (None, message) en cas d’échec.
    Recharge la liste des caissiers à chaque tentative et gère les courses / erreurs Firestore.
    """
    owner_id = str(owner_user.get('id') or '').strip()
    ou = str(owner_un or '').strip().lower()
    if not owner_id or not ou:
        return None, 'Impossible de créer le caissier (données propriétaire manquantes).'
    c_disp = ' '.join(str(cashier_display_name or '').split()).strip()
    if not c_disp:
        return None, 'Indiquez un nom pour le caissier.'
    if len(c_disp) > _AUTHOR_SNAPSHOT_MAX_LEN:
        return None, f'Le nom du caissier ne peut pas dépasser {_AUTHOR_SNAPSHOT_MAX_LEN} caractères.'

    for attempt in range(15):
        uid = None
        try:
            cashiers_fresh = store.list_cashiers_for_owner(owner_id)
            c_username = _allocate_cashier_username(store, ou, cashiers_fresh)
            if not c_username:
                return None, 'Impossible d’attribuer un identifiant caissier (réessayez ou contactez le support).'
            if store.get_user_by_username(c_username):
                time.sleep(0.04)
                continue
            uid = str(uuid.uuid4())
            store.create_user({
                'id': uid,
                'username': c_username,
                'password_hash': generate_password_hash(c_pw),
                'role': 'cashier',
                'owner_id': owner_id,
                'full_name': c_disp,
                'gym_name': str(owner_user.get('gym_name') or ''),
                'phone': str(owner_user.get('phone') or ''),
                'secondary_phone': str(owner_user.get('secondary_phone') or ''),
                'email': '',
                'address': str(owner_user.get('address') or ''),
                'is_active': True,
                'allow_export': False,
                'session_version': 0,
                'created_at': datetime.utcnow().isoformat(),
                'source': 'owner-created-cashier',
            })
            snap = store.get_user_by_id(uid)
            if not snap or str(snap.get('username') or '').strip().lower() != c_username.lower():
                try:
                    store.delete_user_document(uid)
                except Exception:
                    pass
                time.sleep(0.04)
                continue
            by_name = store.get_user_by_username(c_username)
            if by_name and str(by_name.get('id')) != uid:
                try:
                    store.delete_user_document(uid)
                except Exception:
                    pass
                time.sleep(0.04)
                continue
            return c_username, None
        except GoogleAPICallError as e:
            if uid:
                try:
                    store.delete_user_document(uid)
                except Exception:
                    pass
            app.logger.warning('create_cashier tentative %s: Firestore %s', attempt + 1, e)
            if attempt >= 14:
                return None, 'Erreur temporaire Firestore. Réessayez dans un instant.'
            time.sleep(0.06 * (attempt + 1))

    return None, 'La création du caissier a échoué après plusieurs tentatives. Réessayez.'


@app.route('/settings', methods=['GET', 'POST'])
@require_gym_owner_session
def settings():
    """Paramètres compte + structure ; gestion des caissiers pour le propriétaire."""
    user = _current_user()
    if not user:
        return redirect_to_login()
    if not _profile_complete(user):
        return redirect(url_for('complete_profile'))

    cashiers = store.list_cashiers_for_owner(str(user.get('id') or '')) if _can_manage_cashiers(user) else []
    owner_un = str(user.get('username') or '').strip().lower()
    next_cashier_username = (
        _allocate_cashier_username(store, owner_un, cashiers) or '' if _can_manage_cashiers(user) else ''
    )
    error = None
    if request.method == 'POST':
        action = (request.form.get('action') or '').strip().lower()

        if action == 'create_cashier':
            if not _can_manage_cashiers(user):
                error = 'Action non autorisée.'
            else:
                c_pw = request.form.get('cashier_password') or ''
                c_pw2 = request.form.get('cashier_password_confirm') or ''
                c_display = ' '.join((request.form.get('cashier_name') or '').split()).strip()
                if not c_display:
                    error = 'Indiquez un nom pour le caissier.'
                elif len(c_display) > _AUTHOR_SNAPSHOT_MAX_LEN:
                    error = f'Le nom du caissier ne peut pas dépasser {_AUTHOR_SNAPSHOT_MAX_LEN} caractères.'
                elif len(c_pw) < 8:
                    error = 'Le mot de passe du caissier doit contenir au moins 8 caractères.'
                elif c_pw != c_pw2:
                    error = 'La confirmation du mot de passe ne correspond pas.'
                else:
                    c_username, create_err = _create_owned_cashier_account(
                        store, user, owner_un, c_pw, c_display
                    )
                    if create_err:
                        error = create_err
                    else:
                        return redirect(
                            url_for(
                                'settings',
                                cashier_created='1',
                                cashier_username=c_username,
                                cashier_display_name=c_display,
                            )
                        )

        elif action == 'delete_cashier':
            cid = (request.form.get('cashier_id') or '').strip()
            if not _can_manage_cashiers(user):
                error = 'Action non autorisée.'
            else:
                target = _owned_cashier_for_owner(user, cid)
                if not target:
                    error = 'Caissier introuvable.'
                else:
                    store.delete_user_document(cid)
                    return redirect(url_for('settings', cashier_deleted='1'))

        elif action == 'reset_cashier_password':
            cid = (request.form.get('cashier_id') or '').strip()
            new_pw = request.form.get('reset_password') or ''
            new_pw2 = request.form.get('reset_password_confirm') or ''
            target = _owned_cashier_for_owner(user, cid)
            if not target:
                error = 'Caissier introuvable ou action non autorisée.'
            elif len(new_pw) < 8:
                error = 'Le mot de passe doit contenir au moins 8 caractères.'
            elif new_pw != new_pw2:
                error = 'La confirmation ne correspond pas au mot de passe.'
            else:
                new_sv = int(target.get('session_version') or 0) + 1
                store.update_user(
                    cid,
                    {
                        'password_hash': generate_password_hash(new_pw),
                        'session_version': new_sv,
                    },
                )
                un = str(target.get('username') or '')
                return redirect(url_for('settings', cashier_password_reset='1', cashier_username=un))

        elif action == 'toggle_cashier_active':
            cid = (request.form.get('cashier_id') or '').strip()
            target = _owned_cashier_for_owner(user, cid)
            if not target:
                error = 'Caissier introuvable ou action non autorisée.'
            else:
                new_active = not bool(target.get('is_active', True))
                store.update_user(cid, {'is_active': new_active})
                return redirect(
                    url_for(
                        'settings',
                        cashier_access_updated='1',
                        active='1' if new_active else '0',
                    )
                )

        elif action == 'toggle_cashier_export':
            cid = (request.form.get('cashier_id') or '').strip()
            target = _owned_cashier_for_owner(user, cid)
            if not target:
                error = 'Caissier introuvable ou action non autorisée.'
            else:
                cur_exp = bool(target.get('allow_export', True))
                store.update_user(cid, {'allow_export': not cur_exp})
                return redirect(url_for('settings', cashier_export_updated='1'))

        else:
            username = str(user.get('username') or '').strip().lower()[:64]
            email = (request.form.get('email') or '').strip().lower()
            gym_name = (request.form.get('gym_name') or '').strip()
            address = (request.form.get('address') or '').strip()

            if not username:
                error = 'Identifiant de compte manquant (contactez le support).'
            elif email and ('@' not in email or len(email) < 5):
                error = 'Adresse email invalide.'
            elif not all([gym_name, address]):
                error = 'Le nom de la structure et l’adresse sont obligatoires.'
            if not error and email:
                other = store.get_user_by_email(email)
                if other and str(other.get('id')) != str(user.get('id')):
                    error = 'Cette adresse email est déjà utilisée.'
            if not error:
                try:
                    phone = normalize_sn_mobile_phone(request.form.get('phone', ''))
                except ValueError:
                    error = _SN_PHONE_ERR_MSG
                secondary_phone = ''
                if not error:
                    raw_sec = (request.form.get('secondary_phone') or '').strip()
                    if raw_sec:
                        try:
                            secondary_phone = normalize_sn_mobile_phone(raw_sec)
                        except ValueError:
                            error = _SN_PHONE_ERR_MSG
                    if not error and secondary_phone == phone:
                        error = 'Le 2e numéro doit être différent du numéro principal.'
                if not error:
                    by_phone = store.get_user_by_phone(phone)
                    if by_phone and str(by_phone.get('id')) != str(user.get('id')):
                        error = 'Ce numéro de téléphone est déjà utilisé par un autre compte.'
                if not error:
                    updates = {
                        'email': email,
                        'gym_name': gym_name,
                        'full_name': gym_name,
                        'phone': phone,
                        'secondary_phone': secondary_phone,
                        'address': address,
                    }
                    new_pw = (request.form.get('new_password') or '').strip()
                    new_pw2 = (request.form.get('new_password_confirm') or '').strip()
                    cur_pw = request.form.get('current_password') or ''
                    if new_pw or new_pw2 or cur_pw:
                        if not new_pw:
                            error = 'Saisissez le nouveau mot de passe.'
                        elif len(new_pw) < 8:
                            error = 'Le nouveau mot de passe doit contenir au moins 8 caractères.'
                        elif new_pw != new_pw2:
                            error = 'La confirmation ne correspond pas au nouveau mot de passe.'
                        elif not cur_pw:
                            error = 'Saisissez votre mot de passe actuel pour le modifier.'
                        else:
                            pwd_hash = str(user.get('password_hash') or '')
                            if not pwd_hash or not check_password_hash(pwd_hash, cur_pw):
                                error = 'Mot de passe actuel incorrect.'
                            else:
                                updates['password_hash'] = generate_password_hash(new_pw)
                    if not error:
                        store.update_user(user['id'], updates)
                        session['email'] = email
                        session['gym_name'] = gym_name
                        session['full_name'] = gym_name
                        session['phone'] = phone
                        session['secondary_phone'] = secondary_phone
                        session['address'] = address
                        oid = str(user.get('owner_id') or user.get('id') or '').strip()
                        session['owner_id'] = oid
                        if hasattr(g, '_qrprint_user'):
                            g.pop('_qrprint_user', None)
                        return redirect(url_for('settings', updated='1'))

    return render_template(
        'settings.html',
        error=error,
        user=user,
        cashiers=cashiers,
        next_cashier_username=next_cashier_username,
        settings_created_display=format_iso_datetime_display(user.get('created_at')),
    )


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@require_operator_or_admin_session
def index():
    """Page d'accueil (création QR) après connexion."""
    return render_template('index.html')


@app.route('/tickets')
@require_admin_session
def tickets():
    """Liste des tickets QR (filtres, export)."""
    return render_template(
        'tickets.html',
        tickets_author_options=_tickets_author_filter_choices(_current_owner_id()),
    )


@app.route('/dashboard')
@require_gym_owner_session
def dashboard():
    """Tableau de bord propriétaire : finances et suivi."""
    return render_template(
        'dashboard.html',
        dashboard_fetch_max=app.config.get('LIST_QR_FETCH_MAX', 3000),
    )


@app.route('/api/dashboard_stats', methods=['GET'])
@require_gym_owner_session
def dashboard_stats():
    """Agrégats financiers et suivi pour les cartes du dashboard (données du propriétaire connecté)."""
    try:
        fetch_max = app.config.get('LIST_QR_FETCH_MAX', 3000)
        rows = _fetch_qr_list_rows('all', '', '', '', '', fetch_max, _current_owner_id())
        stats = _dashboard_stats_from_rows(rows)
        return jsonify({
            'success': True,
            'stats': stats,
            'meta': {
                'rows_analyzed': len(rows),
                'fetch_max': fetch_max,
                'capped': len(rows) >= fetch_max,
            },
        })
    except GoogleAPICallError as e:
        return jsonify_firestore_error('dashboard_stats', e)
    except Exception as e:
        app.logger.error('dashboard_stats: %s', e)
        return jsonify({'success': False, 'error': 'Erreur interne'}), 500


# APIs REST
@app.route('/api/create_qr', methods=['POST'])
@require_operator_or_admin_session
def create_qr():
    """API pour créer un nouveau QR Code"""
    try:
        data = request.get_json(silent=True) or {}
        
        # Validation des données
        client_name = data.get('client_name', '').strip()
        if not client_name:
            return jsonify({'success': False, 'error': 'Le nom est obligatoire'}), 400
        
        client_firstname = data.get('client_firstname', '').strip()
        if not str(data.get('client_phone') or '').strip():
            return jsonify({'success': False, 'error': 'Le téléphone est obligatoire'}), 400
        try:
            client_phone = normalize_sn_mobile_phone(data.get('client_phone', ''))
        except ValueError:
            return jsonify({'success': False, 'error': _SN_PHONE_ERR_MSG}), 400
        client_email = data.get('client_email', '').strip()
        client_address = data.get('client_address', '').strip()
        service = data.get('service', '').strip()
        subscription_type = data.get('subscription_type', '').strip()
        payment_mode = (data.get('payment_mode') or '').strip().lower()

        if not subscription_type:
            return jsonify({'success': False, 'error': 'La prestation est obligatoire'}), 400
        if payment_mode not in PAYMENT_MODES:
            return jsonify({'success': False, 'error': 'Le mode de paiement est obligatoire (Espèces, Orange Money ou Wave)'}), 400
        try:
            amount_total = parse_amount_field(data.get('amount_total'), 'Le montant dû')
            amount_paid = parse_amount_field(data.get('amount_paid'), 'Le montant payé')
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        if round(amount_paid, 2) > round(amount_total, 2):
            return jsonify({
                'success': False,
                'error': 'Le montant payé ne peut pas dépasser le montant dû.',
            }), 400
        
        # Gestion de l'expiration
        expiration_option = data.get('expiration', '24h')
        custom_hours = data.get('custom_hours')
        
        if expiration_option == 'custom':
            if custom_hours is None:
                return jsonify({
                    'success': False,
                    'error': 'Indiquez le nombre d\'heures pour une expiration personnalisée.',
                }), 400
            ch_str = str(custom_hours).strip()
            if not ch_str:
                return jsonify({
                    'success': False,
                    'error': 'Indiquez le nombre d\'heures pour une expiration personnalisée.',
                }), 400
            try:
                custom_hours_int = int(ch_str)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': "Nombre d'heures invalide."}), 400
            if custom_hours_int < 1 or custom_hours_int > 8760:
                return jsonify({'success': False, 'error': "L'expiration personnalisée doit être entre 1h et 8760h"}), 400
            expiration_delta = timedelta(hours=custom_hours_int)
        else:
            expiration_delta = app.config['EXPIRATION_OPTIONS'].get(
                expiration_option, 
                app.config['EXPIRATION_OPTIONS']['24h'],
            )
        
        expiration_delta = expiration_delta_minus_one_second(expiration_delta)
        expiration_date = datetime.now() + expiration_delta
        
        owner_id = _current_owner_id()
        if not owner_id:
            return jsonify({'success': False, 'error': 'Session invalide, reconnectez-vous.'}), 401

        try:
            ticket_number = store.allocate_ticket_number(owner_id)
        except Exception as e:
            app.logger.exception("allocate_ticket_number: %s", e)
            return jsonify({'success': False, 'error': 'Impossible d\'attribuer un numéro de ticket. Réessayez.'}), 503

        # Génération du QR Code unique
        qr_uuid = str(uuid.uuid4())
        timestamp = int(expiration_date.timestamp())
        
        qr_data_dict = {
            'uuid': qr_uuid,
            'name': client_name,
            'firstname': client_firstname,
            'phone': client_phone,
            'email': client_email,
            'address': client_address,
            'ticket': ticket_number,
            'expires': timestamp,
            'subscription_type': subscription_type,
            'service': service,
            'amount_total': amount_total,
            'amount_paid': amount_paid,
            'payment_mode': payment_mode,
        }
        
        qr_data_json = json.dumps(qr_data_dict, sort_keys=True)
        signed_qr_data = sign_qr_data(qr_data_json)
        qr_hash = generate_qr_hash(signed_qr_data)
        
        if store.qr_hash_exists(qr_hash, owner_id=owner_id):
            return jsonify({
                'success': False,
                'error': 'Un QR identique existe déjà. Modifiez les données ou réessayez.',
            }), 409
        
        # Génération de l'image QR Code
        qr_image = generate_qr_code_image(signed_qr_data)
        qr_base64 = qr_to_base64(qr_image)
        
        created_iso = datetime.utcnow().isoformat()

        _act = _current_user()
        cb_uid = str(_act.get('id') or '').strip() if _act else ''
        cb_disp = _created_by_snapshot_label(_act) if _act else 'Owner'

        # Sauvegarde Firestore
        qr_id = store.create_qr({
            'id': qr_uuid,
            'owner_id': owner_id,
            'created_by_user_id': cb_uid,
            'created_by_display': cb_disp,
            'client_name': client_name,
            'client_firstname': client_firstname,
            'client_phone': client_phone,
            'client_email': client_email,
            'client_address': client_address,
            'service': service,
            'subscription_type': subscription_type,
            'amount_total': amount_total,
            'amount_paid': amount_paid,
            'payment_mode': payment_mode,
            'ticket_number': ticket_number,
            'qr_data': signed_qr_data,
            'qr_hash': qr_hash,
            'expiration_date': expiration_date.isoformat(),
            'expiration_ts': int(expiration_date.timestamp()),
            'created_at': created_iso,
            'printed_at': None,
            'is_active': True,
        })

        preview_row = {
            'client_name': client_name,
            'client_firstname': client_firstname,
            'client_phone': client_phone,
            'client_email': client_email,
            'client_address': client_address,
            'ticket_number': ticket_number,
            'service': service,
            'subscription_type': subscription_type,
            'amount_total': amount_total,
            'amount_paid': amount_paid,
            'payment_mode': payment_mode,
            'created_at': created_iso,
        }
        _owner = _current_user()
        _sess = dict(session)
        before_qr, after_qr = build_ticket_preview_parts(
            preview_row,
            expiration_date,
            owner_user=_owner,
            session_dict=_sess,
        )
        ticket_preview_lines = format_ticket_text_lines(
            preview_row,
            expiration_date,
            owner_user=_owner,
            session_dict=_sess,
        )

        _invalidate_list_qr_cache_for_owner(owner_id)

        return jsonify({
            'success': True,
            'qr_id': qr_id,
            'qr_image': qr_base64,
            'qr_data': signed_qr_data,
            'expiration_date': expiration_date.isoformat(),
            'expiration_text': format_expiration_text(expiration_date),
            'ticket_preview_lines': ticket_preview_lines,
            'ticket_preview_before_qr': before_qr,
            'ticket_preview_after_qr': after_qr,
            'ticket_number': ticket_number,
        })
        
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': "Format de données invalide"}), 400
    except GoogleAPICallError as e:
        return jsonify_firestore_error("create_qr", e)
    except Exception as e:
        app.logger.exception("Erreur lors de la création du QR Code: %s", e)
        if app.config.get('DEBUG'):
            return jsonify({'success': False, 'error': f"Erreur interne: {e}"}), 500
        return jsonify({'success': False, 'error': "Erreur interne (voir logs serveur)"}), 500

@app.route('/api/print_qr/<qr_id>', methods=['POST'])
@require_operator_or_admin_session
def print_qr(qr_id):
    """API pour imprimer un QR Code"""
    try:
        qr_record = store.get_qr(qr_id, owner_id=_current_owner_id())
        
        if not qr_record:
            return jsonify({'success': False, 'error': 'QR Code non trouvé'}), 404

        if not verify_qr_signature(qr_record['qr_data']):
            return jsonify({'success': False, 'error': 'Signature QR invalide'}), 400
        
        # Vérifier si expiré ou désactivé (cleanup / révocation)
        expiration_date = datetime.fromisoformat(qr_record['expiration_date'])
        if datetime.now() > expiration_date:
            return jsonify({'success': False, 'error': 'QR Code expiré'}), 400
        if not bool(qr_record.get('is_active', True)):
            return jsonify({'success': False, 'error': 'QR Code désactivé, impression impossible'}), 400

        printer = get_printer()
        if not printer:
            return jsonify({
                'success': False, 
                'error': 'Imprimante non connectée. Vérifiez la connexion USB ou réseau.'
            }), 503
        
        try:
            print_receipt_escpos(
                printer,
                qr_record,
                expiration_date,
                owner_user=_current_user(),
            )
            printer.cut()
            
            # Mettre à jour la date d'impression
            store.update_qr_printed_at(qr_id, datetime.now().isoformat(), owner_id=_current_owner_id())
            _invalidate_list_qr_cache_for_owner(_current_owner_id())

            return jsonify({'success': True, 'message': 'Impression réussie'})
            
        except Exception as e:
            app.logger.error(f"Erreur lors de l'impression: {e}")
            return jsonify({'success': False, 'error': f'Erreur impression: {str(e)}'}), 500
        finally:
            try:
                printer.close()
            except Exception:
                pass

    except GoogleAPICallError as e:
        return jsonify_firestore_error("print_qr", e)
    except Exception as e:
        app.logger.error(f"Erreur lors de l'impression du QR Code: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/extend_qr/<qr_id>', methods=['POST'])
@require_admin_session
def extend_qr(qr_id):
    """
    Prolonge un ticket **expiré** : le document Firestore est mis à jour (pas de nouveau ticket),
    avec un nouveau `qr_data` signé, `qr_hash`, dates d'expiration et `is_active` à True pour réimpression.
    """
    if not qr_id:
        return jsonify({'success': False, 'error': 'ID manquant'}), 400

    data = request.get_json(silent=True) or {}
    expiration_option = (data.get('expiration') or '24h').strip().lower()
    custom_hours = data.get('custom_hours')

    if expiration_option == 'custom':
        if custom_hours is None:
            return jsonify({'success': False, 'error': 'Indiquez le nombre d\'heures pour une prolongation personnalisée.'}), 400
        ch_str = str(custom_hours).strip()
        if not ch_str:
            return jsonify({'success': False, 'error': 'Indiquez le nombre d\'heures pour une prolongation personnalisée.'}), 400
        try:
            custom_hours_int = int(ch_str)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': "Nombre d'heures invalide."}), 400
        if custom_hours_int < 1 or custom_hours_int > 8760:
            return jsonify({'success': False, 'error': "La prolongation personnalisée doit être entre 1h et 8760h."}), 400
        expiration_delta = timedelta(hours=custom_hours_int)
    else:
        expiration_delta = app.config['EXPIRATION_OPTIONS'].get(
            expiration_option,
            app.config['EXPIRATION_OPTIONS']['24h'],
        )

    expiration_delta = expiration_delta_minus_one_second(expiration_delta)
    new_expiration_date = datetime.now() + expiration_delta

    oid = _current_owner_id()
    if not oid:
        return jsonify({'success': False, 'error': 'Session invalide, reconnectez-vous.'}), 401

    try:
        qr_record = store.get_qr(qr_id, owner_id=oid)
        if not qr_record:
            return jsonify({'success': False, 'error': 'QR Code introuvable'}), 404
        if not verify_qr_signature(qr_record.get('qr_data') or ''):
            return jsonify({'success': False, 'error': 'Signature QR invalide'}), 400

        exp_raw = str(qr_record.get('expiration_date') or '').strip()
        if exp_raw.endswith('Z'):
            exp_raw = exp_raw[:-1] + '+00:00'
        try:
            current_expiration = datetime.fromisoformat(exp_raw)
        except ValueError:
            return jsonify({'success': False, 'error': "Date d'expiration actuelle invalide"}), 400

        if datetime.now() <= current_expiration:
            return jsonify({'success': False, 'error': "Ce ticket n'est pas expiré : prolongation impossible."}), 400

        def _amount_override_provided(d, key):
            v = d.get(key)
            if v is None:
                return False
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return True
            return bool(str(v).strip())

        use_body_amounts = _amount_override_provided(data, 'amount_total') or _amount_override_provided(
            data, 'amount_paid'
        )
        try:
            if use_body_amounts:
                amount_total = parse_amount_field(data.get('amount_total'), 'Le montant dû')
                amount_paid = parse_amount_field(data.get('amount_paid'), 'Le montant payé')
            else:
                amount_total = parse_amount_field(qr_record.get('amount_total'), 'Montant dû')
                amount_paid = parse_amount_field(qr_record.get('amount_paid'), 'Montant payé')
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400

        if round(amount_paid, 2) > round(amount_total, 2):
            return jsonify({
                'success': False,
                'error': 'Le montant payé ne peut pas dépasser le montant dû.',
            }), 400

        payment_mode = str(qr_record.get('payment_mode') or '').strip().lower()
        if payment_mode not in PAYMENT_MODES:
            payment_mode = 'especes'

        subscription_type = str(qr_record.get('subscription_type') or '').strip()
        if not subscription_type:
            subscription_type = 'Séance'

        qr_uuid = str(qr_record.get('id') or qr_id).strip()
        ts_new = int(new_expiration_date.timestamp())

        qr_data_dict = {
            'uuid': qr_uuid,
            'name': str(qr_record.get('client_name') or ''),
            'firstname': str(qr_record.get('client_firstname') or ''),
            'phone': str(qr_record.get('client_phone') or ''),
            'email': str(qr_record.get('client_email') or ''),
            'address': str(qr_record.get('client_address') or ''),
            'ticket': str(qr_record.get('ticket_number') or ''),
            'expires': ts_new,
            'subscription_type': subscription_type,
            'service': str(qr_record.get('service') or ''),
            'amount_total': amount_total,
            'amount_paid': amount_paid,
            'payment_mode': payment_mode,
        }

        qr_data_json = json.dumps(qr_data_dict, sort_keys=True)
        signed_qr_data = sign_qr_data(qr_data_json)
        qr_hash = generate_qr_hash(signed_qr_data)

        if store.qr_hash_exists(qr_hash, owner_id=oid, exclude_qr_id=qr_uuid):
            return jsonify({
                'success': False,
                'error': 'Un autre QR identique existe déjà. Réessayez avec une autre durée.',
            }), 409

        updated = store.update_qr_fields(
            qr_uuid,
            {
                'qr_data': signed_qr_data,
                'qr_hash': qr_hash,
                'expiration_date': new_expiration_date.isoformat(),
                'expiration_ts': ts_new,
                'is_active': True,
                'printed_at': None,
                'amount_total': amount_total,
                'amount_paid': amount_paid,
            },
            owner_id=oid,
        )
        if not updated:
            return jsonify({'success': False, 'error': 'QR Code introuvable'}), 404

        _invalidate_list_qr_cache_for_owner(oid)

        return jsonify({
            'success': True,
            'message': 'Ticket prolongé. Vous pouvez réimprimer le ticket avec le nouveau QR.',
            'expiration_date': new_expiration_date.isoformat(),
            'expiration_text': format_expiration_text(new_expiration_date),
        })

    except GoogleAPICallError as e:
        return jsonify_firestore_error('extend_qr', e)
    except Exception as e:
        app.logger.exception('extend_qr: %s', e)
        return jsonify({'success': False, 'error': 'Erreur serveur'}), 500


@app.route('/api/list_qr', methods=['GET'])
@require_admin_session
def list_qr():
    """API pour lister les QR Codes (filtres + recherche + pagination)."""
    try:
        ttl_cache = float(app.config.get('LIST_QR_RESPONSE_CACHE_SECONDS') or 0)
        owner_for_cache = _current_owner_id()
        qs_key = request.query_string.decode('utf-8')
        cache_key = f'{owner_for_cache}|{qs_key}'
        if ttl_cache > 0:
            with _list_qr_resp_cache_lock:
                hit = _list_qr_resp_cache.get(cache_key)
                if hit and time.monotonic() < hit[0]:
                    return jsonify(hit[1])

        filter_type = request.args.get('filter', 'all')
        search = (request.args.get('search') or '').strip()
        ticket = (request.args.get('ticket') or '').strip()
        date_from = (request.args.get('date_from') or '').strip()
        date_to = (request.args.get('date_to') or '').strip()
        author = (request.args.get('author') or '').strip()
        fetch_max = app.config.get('LIST_QR_FETCH_MAX', 3000)
        default_per_page = app.config.get('LIST_QR_PER_PAGE', 15)

        try:
            per_page = int(request.args.get('per_page', default_per_page))
        except (TypeError, ValueError):
            per_page = default_per_page
        per_page = min(100, max(5, per_page))

        try:
            page = int(request.args.get('page', 1))
        except (TypeError, ValueError):
            page = 1
        page = max(1, page)

        rows = _fetch_qr_list_rows(
            filter_type,
            search,
            ticket,
            date_from,
            date_to,
            fetch_max,
            _current_owner_id(),
            author,
        )
        total = len(rows)
        list_now = datetime.now()
        active_count, expired_count = _qr_list_stats_from_rows(rows, list_now)

        total_pages = (total + per_page - 1) // per_page if total else 0
        if total_pages and page > total_pages:
            page = total_pages
        offset = (page - 1) * per_page
        qr_page = _rows_to_qr_json_list(
            rows[offset : offset + per_page],
            list_now,
            viewer_user=_current_user(),
            owner_id=_current_owner_id(),
        )

        payload = {
            'success': True,
            'qr_codes': qr_page,
            'stats': {
                'total': total,
                'active': active_count,
                'expired': expired_count,
            },
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
            },
        }
        if ttl_cache > 0:
            with _list_qr_resp_cache_lock:
                _list_qr_resp_cache[cache_key] = (time.monotonic() + ttl_cache, payload)
                while len(_list_qr_resp_cache) > _LIST_QR_CACHE_MAX_KEYS:
                    _list_qr_resp_cache.pop(next(iter(_list_qr_resp_cache)), None)
        return jsonify(payload)

    except GoogleAPICallError as e:
        return jsonify_firestore_error("list_qr", e)
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération des QR Codes: {e}")
        return jsonify({'success': False, 'error': "Erreur interne"}), 500


@app.route('/api/export_qr', methods=['GET'])
@require_admin_session
def export_qr():
    """Export CSV ou Excel des QR codes (mêmes filtres que la liste)."""
    u = _current_user()
    if not _user_can_export_tickets(u):
        return jsonify(
            {
                'success': False,
                'error': (
                    'L’export de la liste des tickets (CSV / Excel) n’est pas activé pour votre compte caissier. '
                    'Demandez au responsable de la salle de le permettre dans Paramètres.'
                ),
                'export_forbidden': True,
            }
        ), 403
    fmt = (request.args.get('format') or 'csv').lower().strip()
    filter_type = request.args.get('filter', 'all')
    search = (request.args.get('search') or '').strip()
    ticket = (request.args.get('ticket') or '').strip()
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    author = (request.args.get('author') or '').strip()
    max_rows = app.config.get('EXPORT_MAX_ROWS', 5000)

    try:
        rows = _fetch_qr_list_rows(
            filter_type,
            search,
            ticket,
            date_from,
            date_to,
            max_rows,
            _current_owner_id(),
            author,
        )
    except GoogleAPICallError as e:
        return jsonify_firestore_error("export_qr", e)
    headers = [
        'id', 'client_name', 'client_firstname', 'client_phone', 'client_email', 'client_address',
        'ticket_number', 'subscription_type', 'amount_total', 'amount_paid', 'payment_mode',
        'service', 'created_at', 'auteur', 'expiration_date', 'printed_at', 'is_active', 'qr_hash',
    ]

    if fmt == 'csv':
        si = StringIO()
        writer = csv.writer(si, delimiter=';', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        oid = _current_owner_id()
        for row in rows:
            writer.writerow(
                [
                    _created_by_cell_for_qr_row(row, u, oid) if h == 'auteur' else row.get(h)
                    for h in headers
                ]
            )
        data = si.getvalue().encode('utf-8-sig')
        bio = BytesIO(data)
        bio.seek(0)
        return send_file(
            bio,
            as_attachment=True,
            download_name='qr_codes_export.csv',
            mimetype='text/csv; charset=utf-8',
        )

    if fmt == 'xlsx':
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = 'QR codes'
        ws.append(headers)
        oid = _current_owner_id()
        for row in rows:
            ws.append(
                [
                    _created_by_cell_for_qr_row(row, u, oid) if h == 'auteur' else row.get(h)
                    for h in headers
                ]
            )
        bio = BytesIO()
        wb.save(bio)
        bio.seek(0)
        return send_file(
            bio,
            as_attachment=True,
            download_name='qr_codes_export.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

    abort(400)


@app.route('/api/delete_qr/<qr_id>', methods=['DELETE', 'POST'])
@require_admin_session
def delete_qr(qr_id):
    """API pour supprimer un QR Code"""
    try:
        if not qr_id:
            return jsonify({'success': False, 'error': 'ID manquant'}), 400
            
        oid = _current_owner_id()
        deleted = store.delete_qr(qr_id, owner_id=oid)

        if deleted:
            _invalidate_list_qr_cache_for_owner(oid)
            return jsonify({'success': True, 'message': 'QR Code supprimé'})
        else:
            return jsonify({'success': False, 'error': 'QR Code non trouvé'}), 404
            
    except GoogleAPICallError as e:
        return jsonify_firestore_error("delete_qr", e)
    except Exception as e:
        app.logger.error(f"Erreur lors de la suppression: {e}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Erreur serveur'}), 500


@app.route('/api/qr_ticket_preview/<qr_id>', methods=['GET'])
@require_admin_session
def qr_ticket_preview(qr_id):
    """Données JSON pour afficher le ticket complet dans l’application (sans nouvel onglet)."""
    try:
        qr_record = store.get_qr(qr_id, owner_id=_current_owner_id())
        if not qr_record:
            return jsonify({'success': False, 'error': 'QR Code non trouvé'}), 404
        if not verify_qr_signature(qr_record['qr_data']):
            return jsonify({'success': False, 'error': 'Signature QR invalide'}), 400

        expiration_raw = str(qr_record.get('expiration_date') or '')
        try:
            expiration_date = datetime.fromisoformat(expiration_raw)
        except ValueError:
            return jsonify({'success': False, 'error': "Date d'expiration invalide"}), 400

        preview_row = {
            'client_name': qr_record.get('client_name'),
            'client_firstname': qr_record.get('client_firstname'),
            'client_phone': qr_record.get('client_phone'),
            'client_email': qr_record.get('client_email'),
            'client_address': qr_record.get('client_address'),
            'ticket_number': qr_record.get('ticket_number'),
            'service': qr_record.get('service'),
            'subscription_type': qr_record.get('subscription_type'),
            'amount_total': qr_record.get('amount_total'),
            'amount_paid': qr_record.get('amount_paid'),
            'payment_mode': qr_record.get('payment_mode'),
        }
        _owner = _current_user()
        _sess = dict(session)
        before_qr, after_qr = build_ticket_preview_parts(
            preview_row,
            expiration_date,
            owner_user=_owner,
            session_dict=_sess,
        )
        qr_image = generate_qr_code_image(qr_record['qr_data'])
        qr_base64 = qr_to_base64(qr_image)

        now = datetime.now()
        is_expired = now > expiration_date
        is_active = bool(qr_record.get('is_active', True))

        return jsonify({
            'success': True,
            'qr_id': qr_id,
            'qr_image': qr_base64,
            'ticket_preview_before_qr': before_qr,
            'ticket_preview_after_qr': after_qr,
            'expiration_text': format_expiration_text(expiration_date),
            'ticket_number': qr_record.get('ticket_number'),
            'is_expired': is_expired,
            'is_active': is_active,
        })
    except GoogleAPICallError as e:
        return jsonify_firestore_error('qr_ticket_preview', e)
    except Exception as e:
        app.logger.error('qr_ticket_preview: %s', e)
        return jsonify({'success': False, 'error': 'Erreur serveur'}), 500


@app.route('/api/qr_image/<qr_id>')
@require_admin_session
def qr_image(qr_id):
    """API pour obtenir l'image du QR Code"""
    try:
        qr_record = store.get_qr(qr_id, owner_id=_current_owner_id())
        
        if not qr_record:
            abort(404)
        
        if not verify_qr_signature(qr_record['qr_data']):
            abort(400)
        
        qr_image = generate_qr_code_image(qr_record['qr_data'])
        img_io = BytesIO()
        qr_image.save(img_io, format='PNG')
        img_io.seek(0)
        
        return send_file(img_io, mimetype='image/png')
        
    except GoogleAPICallError as e:
        app.logger.warning("qr_image Firestore: %s", e)
        abort(503)
    except Exception as e:
        app.logger.error(f"Erreur lors de la génération de l'image: {e}")
        abort(500)

@app.route('/api/status')
@require_operator_or_admin_session
def status():
    """API pour vérifier le statut de l'application et de l'imprimante"""
    global _printer_status_until_monotonic, _printer_status_cached
    ttl = float(app.config.get('PRINTER_STATUS_CACHE_SECONDS') or 0)
    now_m = time.monotonic()
    if ttl > 0:
        with _printer_status_lock:
            if now_m < _printer_status_until_monotonic:
                c = _printer_status_cached
                return jsonify({
                    'success': True,
                    'printer_connected': c['connected'],
                    'printer_info': c['info'],
                })

    printer_connected, printer_info = _probe_printer_status()

    if ttl > 0:
        with _printer_status_lock:
            _printer_status_cached = {'connected': printer_connected, 'info': printer_info}
            _printer_status_until_monotonic = time.monotonic() + ttl

    return jsonify({
        'success': True,
        'printer_connected': printer_connected,
        'printer_info': printer_info
    })

# Scheduler pour nettoyer les QR Codes expirés (optionnel, peut être lancé via cron)
def cleanup_expired_qr():
    """Marque comme inactifs les QR Codes expirés"""
    try:
        count = store.cleanup_expired_qr()
        if count:
            _invalidate_list_qr_cache_all()
        app.logger.info(f"Nettoyage des QR Codes expirés effectué ({count} mis à jour)")
    except GoogleAPICallError as e:
        app.logger.warning("Nettoyage Firestore ignoré: %s", e)
    except Exception as e:
        app.logger.warning(f"Nettoyage Firestore non exécuté: {e}")

if __name__ == '__main__':
    # Initialisation de la base de données
    init_db()
    
    # Nettoyage initial
    cleanup_expired_qr()
    
    # Lancer l'application
    app.run(debug=app.config['DEBUG'], host='0.0.0.0', port=app.config.get('APP_PORT', 5055))

