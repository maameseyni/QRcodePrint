# Déploiement sur Vercel - Guide et Limitations

## ⚠️ Limitations Importantes

### 1. Base de données SQLite
**Problème** : SQLite ne fonctionne pas sur Vercel (système de fichiers read-only)

**Solution** : Migrer vers une base de données externe
- **PostgreSQL** : Supabase (gratuit), Neon, Railway
- **MySQL** : PlanetScale (gratuit), Railway
- Modifier `config.py` pour utiliser SQLAlchemy avec PostgreSQL/MySQL

### 2. Imprimante Thermique
**Problème** : Accès USB impossible sur un serveur cloud

**Solutions** :
- Utiliser une imprimante réseau (configurer `PRINTER_NETWORK_IP`)
- Utiliser un service d'impression cloud (ex: PrintNode, PrinterLogic)
- Désactiver l'impression automatique et seulement télécharger les QR Codes

### 3. Fonctions Serverless
**Limitation** : Timeout de 10-60 secondes selon le plan

**Impact** : Les opérations longues peuvent échouer

## 📋 Étapes de Déploiement

### 1. Préparer la base de données externe

**Exemple avec Supabase (PostgreSQL gratuit) :**

1. Créer un compte sur [supabase.com](https://supabase.com)
2. Créer un nouveau projet
3. Récupérer la connection string

Modifier `config.py` :
```python
import os

DATABASE_URL = os.environ.get('DATABASE_URL')  # Depuis Supabase
SQLALCHEMY_DATABASE_URI = DATABASE_URL.replace('postgres://', 'postgresql://')
```

### 2. Installer les dépendances SQLAlchemy

Ajouter à `requirements.txt` :
```
psycopg2-binary  # Pour PostgreSQL
# ou
pymysql  # Pour MySQL
```

### 3. Modifier app.py pour utiliser SQLAlchemy

Remplacer les appels `sqlite3` par SQLAlchemy.

### 4. Déployer sur Vercel

```bash
# Installer Vercel CLI
npm install -g vercel

# Se connecter
vercel login

# Déployer
vercel
```

### 5. Configurer les variables d'environnement

Sur le dashboard Vercel :
- `DATABASE_URL` : URL de votre base de données
- `SECRET_KEY` : Clé secrète Flask
- `QR_SIGNATURE_KEY` : Clé de signature QR

## 🚀 Alternatives Recommandées

### Railway (Recommandé pour cette app)
- Supporte SQLite avec volume persistant
- Supporte les connexions USB via tunnel
- Prix : Gratuit au début, puis ~$5/mois
- URL : [railway.app](https://railway.app)

### Render
- Supporte PostgreSQL
- Gratuit avec limitations
- URL : [render.com](https://render.com)

### PythonAnywhere
- Supporte Flask et SQLite
- Gratuit pour les petits projets
- URL : [pythonanywhere.com](https://www.pythonanywhere.com)

## ✅ Pour un déploiement simple local/réseau

Gardez l'application en local ou sur un VPS (ex: DigitalOcean, Linode) si vous avez besoin de :
- SQLite simple
- Accès à une imprimante USB
- Pas de limitations serverless


