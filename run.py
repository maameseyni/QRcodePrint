"""
Script de démarrage pour l'application QR Code Print
"""
from dotenv import load_dotenv

load_dotenv()

from app import app, init_db, cleanup_expired_qr

if __name__ == '__main__':
    print("=" * 50)
    print("QR Code Print - Impression Thermique")
    print("=" * 50)
    
    # Initialisation de la base de données
    print("\nInitialisation de la base de donnees...")
    init_db()
    print("Base de donnees initialisee")
    
    # Nettoyage initial des QR Codes expirés
    print("Nettoyage des QR Codes expires...")
    cleanup_expired_qr()
    print("Nettoyage termine")
    
    port = int(app.config.get('APP_PORT', 5055))
    print("\nDemarrage du serveur Flask...")
    print(f"Application accessible sur: http://localhost:{port}")
    print(f"Accueil: http://localhost:{port}/")
    print(f"Tickets (liste): http://localhost:{port}/tickets")
    print(f"Dashboard (propriétaire): http://localhost:{port}/dashboard")
    print("\nAppuyez sur Ctrl+C pour arreter le serveur\n")
    
    # Lancer l'application
    app.run(debug=app.config['DEBUG'], host='0.0.0.0', port=port)

