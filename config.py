import os
from datetime import timedelta

class Config:
    """Configuration de l'application Flask"""
    
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production-2024'
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    
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
    QR_SIGNATURE_KEY = os.environ.get('QR_SIGNATURE_KEY') or 'qr-signature-key-2024'
    
    @staticmethod
    def init_app(app):
        """Initialisation de l'application"""
        # Créer le dossier pour les QR codes s'il n'existe pas
        os.makedirs(Config.QR_CODE_DIR, exist_ok=True)

