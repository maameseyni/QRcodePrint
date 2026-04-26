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
    
    # Sécurité
    QR_SIGNATURE_KEY = os.environ.get('QR_SIGNATURE_KEY') or os.urandom(32).hex()
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME') or 'admin'
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
    
    @staticmethod
    def init_app(app):
        """Initialisation de l'application"""
        # Créer le dossier pour les QR codes s'il n'existe pas
        os.makedirs(Config.QR_CODE_DIR, exist_ok=True)

