"""
Script de démarrage pour l'application QR Code Print
"""
from app import app, init_db, cleanup_expired_qr

if __name__ == '__main__':
    print("=" * 50)
    print("🖨️  QR Code Print - Impression Thermique")
    print("=" * 50)
    
    # Initialisation de la base de données
    print("\n📦 Initialisation de la base de données...")
    init_db()
    print("✅ Base de données initialisée")
    
    # Nettoyage initial des QR Codes expirés
    print("🧹 Nettoyage des QR Codes expirés...")
    cleanup_expired_qr()
    print("✅ Nettoyage terminé")
    
    print("\n🚀 Démarrage du serveur Flask...")
    print("📍 Application accessible sur: http://localhost:5000")
    print("📊 Dashboard: http://localhost:5000/dashboard")
    print("\n💡 Appuyez sur Ctrl+C pour arrêter le serveur\n")
    
    # Lancer l'application
    app.run(debug=app.config['DEBUG'], host='0.0.0.0', port=5000)

