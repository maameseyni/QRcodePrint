import os
from datetime import timedelta

class Config:
    """Configuration de l'application Flask"""

    @staticmethod
    def _to_bool(value, default=False):
        """Convertit une variable d'environnement en booléen."""
        if value is None:
            return default
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on')
    
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or os.urandom(32).hex()
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DEBUG = _to_bool.__func__(os.environ.get('FLASK_DEBUG'), default=False)
    # Render/Heroku définissent PORT ; en local on utilise APP_PORT (ex. 5055).
    APP_PORT = int(os.environ.get('PORT') or os.environ.get('APP_PORT', '5055'))
    
    # Base de données
    DATABASE_PATH = os.path.join(BASE_DIR, 'database.db')
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{DATABASE_PATH}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # QR Code
    QR_CODE_DIR = os.path.join(BASE_DIR, 'static', 'qr')
    QR_CODE_SIZE = 300
    QR_CODE_BORDER = 4
    
    # Expiration par défaut
    DEFAULT_EXPIRATION_HOURS = 24
    EXPIRATION_OPTIONS = {
        '24h': timedelta(hours=24),
        '7j': timedelta(days=7),
        '30j': timedelta(days=30)
    }
    
    # Imprimante thermique
    PRINTER_USB_VENDOR_ID = None  # Laissez None pour auto-détection
    PRINTER_USB_PRODUCT_ID = None
    PRINTER_NETWORK_IP = None  # Exemple: "192.168.1.100"
    PRINTER_NETWORK_PORT = 9100
    PRINTER_WIDTH_MM = 80
    PRINTER_ENCODING = 'cp850'  # Encodage pour caractères spéciaux
    # Réduit les sondes USB/réseau répétées (route /api/status uniquement ; l’impression ignore ce cache).
    PRINTER_STATUS_CACHE_SECONDS = float(os.environ.get('PRINTER_STATUS_CACHE_SECONDS', '25'))
    
    # Sécurité
    QR_SIGNATURE_KEY = os.environ.get('QR_SIGNATURE_KEY') or os.urandom(32).hex()
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME') or 'admin'
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
    ADMIN_FULL_NAME = os.environ.get('ADMIN_FULL_NAME') or 'Administrateur'
    ADMIN_GYM_NAME = os.environ.get('ADMIN_GYM_NAME') or 'Salle principale'
    ADMIN_PHONE = os.environ.get('ADMIN_PHONE') or ''
    ADMIN_ADDRESS = os.environ.get('ADMIN_ADDRESS') or ''
    SUPERADMIN_USERNAME = os.environ.get('SUPERADMIN_USERNAME') or ''
    SUPERADMIN_PASSWORD = os.environ.get('SUPERADMIN_PASSWORD')
    SUPERADMIN_FULL_NAME = os.environ.get('SUPERADMIN_FULL_NAME') or 'Super Administrateur'
    SUPERADMIN_PHONE = os.environ.get('SUPERADMIN_PHONE') or ''
    SUPERADMIN_ADDRESS = os.environ.get('SUPERADMIN_ADDRESS') or ''
    OPERATOR_USERNAME = os.environ.get('OPERATOR_USERNAME') or 'operator'
    OPERATOR_PASSWORD = os.environ.get('OPERATOR_PASSWORD')
    SESSION_HOURS = int(os.environ.get('SESSION_HOURS', '12'))
    PERMANENT_SESSION_LIFETIME = timedelta(hours=SESSION_HOURS)
    EXPORT_MAX_ROWS = int(os.environ.get('EXPORT_MAX_ROWS', '5000'))
    # Tableau dashboard : documents Firestore max lus avant filtres Python, puis pagination.
    # Rétrocompat : LIST_QR_MAX_ROWS utilisé si LIST_QR_FETCH_MAX absent.
    LIST_QR_FETCH_MAX = int(os.environ.get('LIST_QR_FETCH_MAX') or os.environ.get('LIST_QR_MAX_ROWS') or '3000')
    LIST_QR_PER_PAGE = int(os.environ.get('LIST_QR_PER_PAGE', '15'))
    DASHBOARD_REFRESH_MS = int(os.environ.get('DASHBOARD_REFRESH_MS', '120000'))
    # Réduit les lectures Firestore répétées sur GET /api/list_qr (même filtres). 0 = désactivé.
    LIST_QR_RESPONSE_CACHE_SECONDS = float(os.environ.get('LIST_QR_RESPONSE_CACHE_SECONDS', '15'))
    # Entre deux exécutions de attach_owner_to_unowned_qr (scan coûteux). 0 = à chaque appel (dev).
    ATTACH_UNOWNED_QR_COOLDOWN_SECONDS = int(os.environ.get('ATTACH_UNOWNED_QR_COOLDOWN_SECONDS', '86400'))

    # Mise en page ticket thermique (80 mm ≈ 32 caractères)
    TICKET_WIDTH_CHARS = int(os.environ.get('TICKET_WIDTH_CHARS', '32'))
    # Aperçu à l’écran (plus large pour emails / libellés sans troncature excessive)
    TICKET_PREVIEW_WIDTH_CHARS = int(os.environ.get('TICKET_PREVIEW_WIDTH_CHARS', '52'))
    TICKET_SUBTITLE = os.environ.get('TICKET_SUBTITLE', 'SALLE DE GYM')
    TICKET_THANKS = os.environ.get('TICKET_THANKS', 'MERCI DE VOTRE FIDÉLITÉ')
    TICKET_CAISSE_LABEL = os.environ.get('TICKET_CAISSE_LABEL', 'CAISSE')
    TICKET_RECEIPT_TITLE = os.environ.get('TICKET_RECEIPT_TITLE', 'REÇU')

    # Firestore (base principale)
    FIRESTORE_PROJECT_ID = (
        os.environ.get('FIRESTORE_PROJECT_ID')
        or os.environ.get('GOOGLE_CLOUD_PROJECT')
        or os.environ.get('GCLOUD_PROJECT')
    )
    FIRESTORE_COLLECTION_PREFIX = os.environ.get('FIRESTORE_COLLECTION_PREFIX', 'qrprint')
    GOOGLE_APPLICATION_CREDENTIALS = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    # Corps JSON du compte de service (Render / PaaS sans fichier sur disque). Prioritaire sur le chemin fichier.
    GOOGLE_APPLICATION_CREDENTIALS_JSON = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')

    # OAuth Google (connexion « Continuer avec Google »)
    GOOGLE_CLIENT_ID = (os.environ.get('GOOGLE_CLIENT_ID') or '').strip() or None
    GOOGLE_CLIENT_SECRET = (os.environ.get('GOOGLE_CLIENT_SECRET') or '').strip() or None

    @staticmethod
    def init_app(app):
        """Initialisation de l'application"""
        # Créer le dossier pour les QR codes s'il n'existe pas
        os.makedirs(Config.QR_CODE_DIR, exist_ok=True)
        app.permanent_session_lifetime = Config.PERMANENT_SESSION_LIFETIME
        # Render : HTTPS public ; cookies de session marqués Secure (évite envoi en clair).
        if os.environ.get('RENDER') or str(os.environ.get('FORCE_SECURE_COOKIES', '')).strip().lower() in (
            '1', 'true', 'yes', 'on',
        ):
            app.config['SESSION_COOKIE_SECURE'] = True
            app.config['SESSION_COOKIE_HTTPONLY'] = True
            app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
        # OAuth Google en http://127.0.0.1 (dev) : oauthlib refuse HTTP sans ce réglage.
        if app.debug:
            os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '1')

