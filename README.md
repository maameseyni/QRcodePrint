# 🖨️ QR Code Print - Application Flask pour Impression Thermique POS

Application web complète pour générer et imprimer des QR Codes via une imprimante thermique POS (80mm).

## ✨ Fonctionnalités

- ✅ Génération de QR Codes uniques signés cryptographiquement
- ✅ Impression thermique directe sur imprimante POS USB ou réseau
- ✅ Gestion d'expiration (24h, 7j, 30j, ou personnalisé)
- ✅ Dashboard administrateur pour gérer tous les QR Codes
- ✅ Interface moderne et intuitive avec Bootstrap 5
- ✅ Base de données SQLite pour stockage local
- ✅ APIs REST complètes
- ✅ Téléchargement des QR Codes en PNG
- ✅ Sécurité avec signature HMAC et protection CSRF

## 📋 Prérequis

- Python 3.8 ou supérieur
- Imprimante thermique POS compatible ESC/POS (USB ou réseau)
- Windows/Linux/macOS

## 🚀 Installation

### 1. Cloner ou télécharger le projet

```bash
cd QrCodePrint
```

### 2. Créer un environnement virtuel (recommandé)

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 4. Configurer l'imprimante (optionnel)

Si vous avez une imprimante réseau ou besoin de spécifier un périphérique USB particulier, éditez `config.py` :

```python
# Pour une imprimante réseau
PRINTER_NETWORK_IP = "192.168.1.100"  # IP de l'imprimante
PRINTER_NETWORK_PORT = 9100

# Pour une imprimante USB spécifique
PRINTER_USB_VENDOR_ID = 0x04f9  # ID fabricant (optionnel)
PRINTER_USB_PRODUCT_ID = 0x2090  # ID produit (optionnel)
```

**Note:** Pour l'auto-détection USB, laissez ces valeurs à `None`.

### 5. Lancer l'application

```bash
python app.py
```

L'application sera accessible à l'adresse: **http://localhost:5000**

## 🔧 Configuration de l'Imprimante Thermique

### Imprimante USB

1. **Branchez l'imprimante** via USB à votre ordinateur
2. **Installez les pilotes** (généralement automatique sous Windows)
3. L'application **détectera automatiquement** l'imprimante au démarrage

**Dépannage USB :**
- Vérifiez que l'imprimante est allumée et connectée
- Sur Linux, vous devrez peut-être ajouter votre utilisateur au groupe `lp` :
  ```bash
  sudo usermod -a -G lp $USER
  ```
- Sur Windows, vérifiez dans le Gestionnaire de périphériques que l'imprimante est reconnue

### Imprimante Réseau

1. **Connectez l'imprimante au réseau** (WiFi ou Ethernet)
2. **Notez l'adresse IP** de l'imprimante (généralement accessible via l'écran LCD)
3. **Configurez dans `config.py`** :
   ```python
   PRINTER_NETWORK_IP = "192.168.1.100"
   PRINTER_NETWORK_PORT = 9100  # Port par défaut pour ESC/POS
   ```
4. **Testez la connectivité** :
   ```bash
   ping 192.168.1.100
   ```

### Imprimantes Testées/Compatibles

- ✅ Epson TM-T20, TM-T82, TM-T88
- ✅ Star Micronics TSP143, TSP650
- ✅ Bixolon SRP-350, SRP-350plus
- ✅ Zjiang ZJ-5870, ZJ-5890
- ✅ Toutes les imprimantes compatibles ESC/POS

## 📖 Utilisation

### Page d'Accueil - Créer un QR Code

1. **Remplissez le formulaire** :
   - Nom (obligatoire) et Prénom
   - Téléphone et Email (optionnels)
   - Identifiant interne et Numéro de ticket
   - Service et Commentaire
   - Durée d'expiration (24h, 7j, 30j, ou personnalisé)

2. **Cliquez sur "Générer le QR Code"**

3. **Le QR Code s'affiche** avec :
   - Image du QR Code
   - Date d'expiration
   - Boutons pour imprimer, télécharger ou créer un nouveau

4. **Cliquez sur "Imprimer maintenant"** pour lancer l'impression thermique

### Dashboard Administrateur

Accédez via le menu **Dashboard** pour :

- 📊 **Voir les statistiques** : Total, Actifs, Expirés
- 📋 **Lister tous les QR Codes** générés
- 🔍 **Filtrer** par statut (Tous, Actifs, Expirés)
- 👁️ **Voir** le QR Code en grand format
- 🖨️ **Réimprimer** un QR Code existant
- 🗑️ **Supprimer** un QR Code

## 🏗️ Structure du Projet

```
QrCodePrint/
│
├── app.py                 # Application Flask principale
├── config.py              # Configuration
├── requirements.txt       # Dépendances Python
├── firestore.indexes.json  # Index Firestore (déploiement Firebase)
├── services/datastore.py   # Accès Firestore
├── tests/                  # Tests pytest (optionnel, requirements-dev.txt)
│
├── templates/             # Templates HTML
│   ├── index.html        # Page d'accueil
│   └── dashboard.html    # Dashboard admin
│
└── static/               # Fichiers statiques
    ├── css/
    │   └── style.css     # Styles personnalisés
    ├── js/
    │   ├── main.js       # Script page d'accueil
    │   └── dashboard.js  # Script dashboard
    └── qr/               # Dossier pour stocker les QR Codes (auto-créé)
```

## 🔌 APIs REST

### Créer un QR Code
```
POST /api/create_qr
Content-Type: application/json

{
  "client_name": "Dupont",
  "client_firstname": "Jean",
  "client_phone": "0612345678",
  "client_email": "jean@example.com",
  "client_id": "CLI-001",
  "ticket_number": "TKT-123",
  "service": "Réparation",
  "comment": "Urgent",
  "expiration": "24h"  // ou "7j", "30j", "custom"
  // Si "custom": "custom_hours": 48
}
```

### Imprimer un QR Code
```
POST /api/print_qr/<qr_id>
```

### Lister les QR Codes
```
GET /api/list_qr?filter=all  // ou "active", "expired"
// Filtres optionnels : search=, ticket=, date_from=YYYY-MM-DD, date_to=YYYY-MM-DD
// Export (admin, session) : GET /api/export_qr?format=csv|xlsx& (mêmes paramètres que list_qr)
```

### Supprimer un QR Code
```
DELETE /api/delete_qr/<qr_id>
```

### Obtenir l'image d'un QR Code
```
GET /api/qr_image/<qr_id>
```

### Vérifier le statut
```
GET /api/status
```

## 🔒 Sécurité

- **Signature HMAC** : Chaque QR Code est signé cryptographiquement
- **Protection CSRF** : Flask-WTF pour les formulaires
- **Validation des entrées** : Tous les inputs sont validés et filtrés
- **Expiration automatique** : Les QR Codes deviennent invalides après expiration

## 🐛 Dépannage

### L'imprimante n'est pas détectée

1. **Vérifiez la connexion** (USB ou réseau)
2. **Vérifiez les permissions** (Linux: groupe `lp`)
3. **Testez avec l'API status** : `GET /api/status`
4. **Consultez les logs** de l'application Flask

### Erreur lors de l'impression

- Assurez-vous que l'imprimante est **allumée**
- Vérifiez qu'il y a **du papier** dans l'imprimante
- Testez avec une **autre application** (Bloc-notes → Imprimer)
- Vérifiez les **pilotes** de l'imprimante

### Erreur Firestore / GCP

- Vérifiez `FIRESTORE_PROJECT_ID`, les credentials (`GOOGLE_APPLICATION_CREDENTIALS` ou JSON en env) et les **rôles IAM** du compte de service (ex. « Cloud Datastore User »).
- Déployez les **index** composites (`firebase deploy --only firestore:indexes` ou lien dans le message d’erreur Firestore).

### Le QR Code ne s'imprime pas correctement

- Vérifiez que l'imprimante supporte **l'impression d'images**
- Certaines imprimantes nécessitent des **pilotes spécifiques**
- Testez avec une **imprimante différente** si possible

## 🚀 Déploiement en Production

### Recommandations

1. **Définir `SECRET_KEY` et `QR_SIGNATURE_KEY`** dans les variables d’environnement (longues valeurs aléatoires), pas en dur dans le code.

2. **Utiliser un serveur WSGI** (Gunicorn, uWSGI) :
   ```bash
   pip install gunicorn
   gunicorn -w 4 -b 0.0.0.0:5000 app:app
   ```

3. **Configurer un reverse proxy** (Nginx, Apache)

4. **Utiliser HTTPS** avec un certificat SSL

5. **Sauvegarder** votre projet GCP / exports Firestore selon votre politique.

6. **Configurer un cron job** pour nettoyer les QR Codes expirés (optionnel ; l’app peut aussi lancer un nettoyage au démarrage)

### Variables d'environnement recommandées

Créez un fichier `.env` à partir de `.env.example` et renseignez des valeurs fortes :

```bash
# Windows PowerShell
Copy-Item .env.example .env

# Linux/macOS
cp .env.example .env
```

Variables minimales à définir en production :

- `ADMIN_PASSWORD` : obligatoire pour protéger le dashboard et les APIs admin
- `ADMIN_USERNAME` : optionnel (défaut: `admin`)
- `OPERATOR_PASSWORD` : mot de passe du **compte caisse** (créé dans Firestore au démarrage si défini). Ce compte se connecte sur `/login` comme les autres mais **n’a pas accès** au tableau de bord ni à l’export : uniquement l’accueil (formulaire + impression). Définir aussi `OPERATOR_USERNAME` (défaut `operator`) et, au besoin, `OPERATOR_GYM_NAME`, `OPERATOR_PHONE`, `OPERATOR_ADDRESS` pour le profil minimal stocké en base. **`ADMIN_USERNAME` et `OPERATOR_USERNAME` doivent être différents** (un identifiant = un document utilisateur).
- Dès que **`ADMIN_PASSWORD` ou `OPERATOR_PASSWORD`** est défini, **toute l’application** exige une connexion. Laisser les deux vides uniquement en développement local si vous acceptez l’accès sans login.
- `LIST_QR_FETCH_MAX` : plafond de lectures Firestore par chargement de liste. Les filtres **Actif** / **Expiré** utilisent des requêtes indexées (`expiration_ts`). Le filtre **Tous** reste limité aux tickets les plus récents jusqu’à ce plafond (voir commentaires dans `config.py`).
- `LIST_QR_RESPONSE_CACHE_SECONDS` : cache des réponses GET `/api/list_qr` ; invalidé après création, suppression, impression, rattachement de QR sans propriétaire, et après le nettoyage des expirés.
- `SESSION_HOURS` : durée de session en heures (défaut: `12`)
- `SECRET_KEY` : clé Flask (session/CSRF), longue et aléatoire
- `QR_SIGNATURE_KEY` : clé HMAC pour signer les QR codes, longue et aléatoire
- `FLASK_DEBUG=0` : ne pas exposer le mode debug

Connexion web : page `/login` (sessions Flask). **Comptes gestion** (inscription salle, admin `.env`, superadmin) : accueil + dashboard + export. **Compte opérateur** : accueil + APIs création/impression uniquement.

### Checklist sécurité production

- Activer HTTPS derrière un reverse proxy (Nginx/Apache/Caddy)
- Restreindre l'accès au dashboard admin (réseau interne/VPN si possible)
- Sauvegarder Firestore / votre projet GCP ; l’app ne repose plus sur `database.db` pour les données métier
- Mettre à jour les dépendances Python périodiquement
- Surveiller les logs applicatifs et les erreurs d'impression

## 📝 Notes Techniques

- **Données** : Google **Firestore** (utilisateurs, QR codes). Variable `FIRESTORE_COLLECTION_PREFIX` (défaut `qrprint`). Script optionnel `scripts/backfill_expiration_ts.py` pour les anciens documents sans champ `expiration_ts`. Index composites décrits dans `firestore.indexes.json`.
- **Traçage HTTP** : en-tête de réponse **`X-Request-ID`** (corrélation des logs).
- **QR Codes** : bibliothèque `qrcode` avec correction d'erreur niveau M
- **Impression** : Bibliothèque `python-escpos` pour compatibilité ESC/POS
- **Frontend** : Bootstrap 5 + JavaScript vanilla (pas de framework JS)

## 📄 Licence

Ce projet est fourni "tel quel" pour un usage personnel ou commercial.

## 🤝 Support

Pour toute question ou problème :
1. Vérifiez la section **Dépannage** ci-dessus
2. Consultez les logs de l'application Flask
3. Testez avec une imprimante différente si possible

---

**Développé avec ❤️ en Python/Flask**

