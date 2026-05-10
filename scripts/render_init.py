"""
Tâches avant chaque mise en ligne sur Render (preDeployCommand).
Initialise le schéma Firestore et nettoie les QR expirés — sans lancer le serveur HTTP.
"""
from __future__ import annotations

import os

# Render injecte les variables d'environnement ; pas de fichier .env sur le disque.
os.environ.setdefault('PYTHONUNBUFFERED', '1')

from app import cleanup_expired_qr, init_db


def main() -> None:
    init_db()
    cleanup_expired_qr()


if __name__ == '__main__':
    main()
