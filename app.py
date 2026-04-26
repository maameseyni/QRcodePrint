"""
Application Flask pour génération et impression de QR Codes thermiques
"""
import os
import sqlite3
import uuid
import hashlib
import hmac
import json
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file, abort, Response
from flask_wtf.csrf import CSRFProtect
import qrcode
from PIL import Image, ImageDraw, ImageFont
from escpos.printer import Usb, Network, Serial
from escpos.exceptions import USBNotFoundError
import base64
from io import BytesIO

from config import Config

app = Flask(__name__)
app.config.from_object(Config)
Config.init_app(app)
csrf = CSRFProtect(app)


def check_admin_auth():
    """Vérifie l'authentification admin HTTP Basic."""
    expected_password = app.config.get('ADMIN_PASSWORD')
    if not expected_password:
        app.logger.warning("ADMIN_PASSWORD non défini: routes admin non protégées.")
        return True

    auth = request.authorization
    if not auth:
        return False

    expected_username = app.config.get('ADMIN_USERNAME', 'admin')
    return (
        hmac.compare_digest(auth.username or '', expected_username)
        and hmac.compare_digest(auth.password or '', expected_password)
    )


def admin_auth_required():
    """Retourne une réponse 401 pour déclencher l'auth HTTP Basic."""
    return Response(
        'Authentification requise',
        401,
        {'WWW-Authenticate': 'Basic realm="Dashboard Admin"'}
    )


def require_admin(func):
    """Décorateur pour protéger les routes administrateur."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not check_admin_auth():
            return admin_auth_required()
        return func(*args, **kwargs)
    return wrapper

# Initialisation de la base de données
def init_db():
    """Initialise la base de données SQLite"""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS qr_codes (
            id TEXT PRIMARY KEY,
            client_name TEXT NOT NULL,
            client_firstname TEXT,
            client_phone TEXT,
            client_email TEXT,
            client_id TEXT,
            comment TEXT,
            service TEXT,
            ticket_number TEXT,
            qr_data TEXT NOT NULL,
            qr_hash TEXT NOT NULL UNIQUE,
            expiration_date DATETIME NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            printed_at DATETIME,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    c.execute('''
        CREATE INDEX IF NOT EXISTS idx_expiration ON qr_codes(expiration_date)
    ''')
    
    c.execute('''
        CREATE INDEX IF NOT EXISTS idx_active ON qr_codes(is_active)
    ''')
    
    conn.commit()
    conn.close()

def get_db():
    """Obtient une connexion à la base de données"""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    return conn

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

def get_printer():
    """Obtient une instance de l'imprimante thermique"""
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

def format_expiration_text(expiration_date):
    """Formate la date d'expiration pour l'affichage"""
    now = datetime.now()
    delta = expiration_date - now
    
    if delta.days > 0:
        return f"{delta.days} jour(s)"
    elif delta.seconds > 3600:
        hours = delta.seconds // 3600
        return f"{hours} heure(s)"
    else:
        minutes = delta.seconds // 60
        return f"{minutes} minute(s)"

# Routes principales
@app.route('/')
def index():
    """Page d'accueil avec formulaire de génération"""
    return render_template('index.html')

@app.route('/dashboard')
@require_admin
def dashboard():
    """Dashboard administrateur"""
    return render_template('dashboard.html')

# APIs REST
@app.route('/api/create_qr', methods=['POST'])
def create_qr():
    """API pour créer un nouveau QR Code"""
    try:
        data = request.get_json(silent=True) or {}
        
        # Validation des données
        client_name = data.get('client_name', '').strip()
        if not client_name:
            return jsonify({'success': False, 'error': 'Le nom est obligatoire'}), 400
        
        client_firstname = data.get('client_firstname', '').strip()
        client_phone = data.get('client_phone', '').strip()
        client_email = data.get('client_email', '').strip()
        client_id = data.get('client_id', '').strip()
        comment = data.get('comment', '').strip()
        service = data.get('service', '').strip()
        ticket_number = data.get('ticket_number', '').strip()
        
        # Gestion de l'expiration
        expiration_option = data.get('expiration', '24h')
        custom_hours = data.get('custom_hours')
        
        if expiration_option == 'custom' and custom_hours:
            custom_hours_int = int(custom_hours)
            if custom_hours_int < 1 or custom_hours_int > 8760:
                return jsonify({'success': False, 'error': "L'expiration personnalisée doit être entre 1h et 8760h"}), 400
            expiration_delta = timedelta(hours=custom_hours_int)
        else:
            expiration_delta = app.config['EXPIRATION_OPTIONS'].get(
                expiration_option, 
                app.config['EXPIRATION_OPTIONS']['24h']
            )
        
        expiration_date = datetime.now() + expiration_delta
        
        # Génération du QR Code unique
        qr_uuid = str(uuid.uuid4())
        timestamp = int(expiration_date.timestamp())
        
        qr_data_dict = {
            'uuid': qr_uuid,
            'name': client_name,
            'firstname': client_firstname,
            'phone': client_phone,
            'email': client_email,
            'client_id': client_id,
            'ticket': ticket_number,
            'expires': timestamp
        }
        
        qr_data_json = json.dumps(qr_data_dict, sort_keys=True)
        signed_qr_data = sign_qr_data(qr_data_json)
        qr_hash = generate_qr_hash(signed_qr_data)
        
        # Vérifier l'unicité du hash
        conn = get_db()
        existing = conn.execute(
            'SELECT id FROM qr_codes WHERE qr_hash = ?', (qr_hash,)
        ).fetchone()
        
        if existing:
            conn.close()
            return jsonify({'success': False, 'error': 'Erreur: hash duplicata'}), 500
        
        # Génération de l'image QR Code
        qr_image = generate_qr_code_image(signed_qr_data)
        qr_base64 = qr_to_base64(qr_image)
        
        # Sauvegarde en base de données
        conn.execute('''
            INSERT INTO qr_codes 
            (id, client_name, client_firstname, client_phone, client_email, 
             client_id, comment, service, ticket_number, qr_data, qr_hash, expiration_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (qr_uuid, client_name, client_firstname, client_phone, client_email,
              client_id, comment, service, ticket_number, signed_qr_data, 
              qr_hash, expiration_date))
        
        conn.commit()
        qr_id = qr_uuid
        conn.close()
        
        return jsonify({
            'success': True,
            'qr_id': qr_id,
            'qr_image': qr_base64,
            'qr_data': signed_qr_data,
            'expiration_date': expiration_date.isoformat(),
            'expiration_text': format_expiration_text(expiration_date)
        })
        
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': "Format de données invalide"}), 400
    except Exception as e:
        app.logger.error(f"Erreur lors de la création du QR Code: {e}")
        return jsonify({'success': False, 'error': "Erreur interne"}), 500

@app.route('/api/print_qr/<qr_id>', methods=['POST'])
def print_qr(qr_id):
    """API pour imprimer un QR Code"""
    try:
        conn = get_db()
        qr_record = conn.execute(
            'SELECT * FROM qr_codes WHERE id = ?', (qr_id,)
        ).fetchone()
        conn.close()
        
        if not qr_record:
            return jsonify({'success': False, 'error': 'QR Code non trouvé'}), 404

        if not verify_qr_signature(qr_record['qr_data']):
            return jsonify({'success': False, 'error': 'Signature QR invalide'}), 400
        
        # Vérifier si expiré
        expiration_date = datetime.fromisoformat(qr_record['expiration_date'])
        if datetime.now() > expiration_date:
            return jsonify({'success': False, 'error': 'QR Code expiré'}), 400
        
        printer = get_printer()
        if not printer:
            return jsonify({
                'success': False, 
                'error': 'Imprimante non connectée. Vérifiez la connexion USB ou réseau.'
            }), 503
        
        try:
            # Configuration de l'imprimante
            printer.set(align='center', font='a', width=1, height=1)
            
            # En-tête (optionnel: logo si disponible)
            printer.text("\n")
            printer.text("=" * 32 + "\n")
            printer.set(align='center', font='b', width=2, height=2)
            printer.text("TICKET QR CODE\n")
            printer.set(align='center', font='a', width=1, height=1)
            printer.text("=" * 32 + "\n\n")
            
            # Informations client
            printer.set(align='left')
            printer.text(f"Nom: {qr_record['client_name']}\n")
            if qr_record['client_firstname']:
                printer.text(f"Prenom: {qr_record['client_firstname']}\n")
            if qr_record['client_phone']:
                printer.text(f"Tel: {qr_record['client_phone']}\n")
            if qr_record['client_email']:
                printer.text(f"Email: {qr_record['client_email']}\n")
            if qr_record['client_id']:
                printer.text(f"ID: {qr_record['client_id']}\n")
            if qr_record['ticket_number']:
                printer.set(align='center', font='b')
                printer.text(f"\nTicket #{qr_record['ticket_number']}\n")
                printer.set(align='left', font='a')
            if qr_record['service']:
                printer.text(f"Service: {qr_record['service']}\n")
            if qr_record['comment']:
                printer.text(f"Note: {qr_record['comment']}\n")
            
            printer.text("\n" + "-" * 32 + "\n\n")
            
            # QR Code (impression de l'image)
            printer.set(align='center')
            qr_image = generate_qr_code_image(qr_record['qr_data'], size=256)
            
            # Imprimer l'image QR Code
            try:
                # La méthode image() accepte directement une PIL Image
                # Elle convertit automatiquement pour l'imprimante thermique
                printer.image(qr_image, impl='bitImageRaster', center=True)
            except AttributeError:
                # Fallback pour les anciennes versions d'escpos
                try:
                    printer.image(qr_image, center=True)
                except:
                    # Dernier recours: imprimer le texte du hash
                    printer.text(f"\nQR CODE\n")
                    printer.text(f"{qr_record['qr_hash'][:32]}\n")
            except Exception as e:
                app.logger.warning(f"Erreur impression image QR: {e}")
                # Fallback: imprimer le texte du hash
                printer.text(f"\nQR CODE\n")
                printer.text(f"{qr_record['qr_hash'][:32]}\n")
            
            printer.text("\n")
            printer.set(align='center', font='b')
            printer.text("SCANNEZ LE QR CODE\n")
            printer.set(align='center', font='a')
            
            # Date d'expiration
            exp_text = expiration_date.strftime("%d/%m/%Y %H:%M")
            printer.text(f"\nExpire le: {exp_text}\n")
            
            # Pied de page
            printer.text("\n" + "=" * 32 + "\n")
            printer.text(f"Date: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
            printer.text("=" * 32 + "\n\n\n")
            
            # Couper le papier
            printer.cut()
            
            # Mettre à jour la date d'impression
            conn = get_db()
            conn.execute(
                'UPDATE qr_codes SET printed_at = ? WHERE id = ?',
                (datetime.now().isoformat(), qr_id)
            )
            conn.commit()
            conn.close()
            
            return jsonify({'success': True, 'message': 'Impression réussie'})
            
        except Exception as e:
            app.logger.error(f"Erreur lors de l'impression: {e}")
            return jsonify({'success': False, 'error': f'Erreur impression: {str(e)}'}), 500
        finally:
            try:
                printer.close()
            except:
                pass
                
    except Exception as e:
        app.logger.error(f"Erreur lors de l'impression du QR Code: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/list_qr', methods=['GET'])
@require_admin
def list_qr():
    """API pour lister tous les QR Codes"""
    try:
        filter_type = request.args.get('filter', 'all')  # all, active, expired
        
        conn = get_db()
        query = 'SELECT * FROM qr_codes'
        
        if filter_type == 'active':
            query += ' WHERE is_active = 1 AND expiration_date > datetime("now")'
        elif filter_type == 'expired':
            query += ' WHERE expiration_date <= datetime("now") OR is_active = 0'
        
        query += ' ORDER BY created_at DESC LIMIT 100'
        
        rows = conn.execute(query).fetchall()
        conn.close()
        
        qr_list = []
        for row in rows:
            expiration_date = datetime.fromisoformat(row['expiration_date'])
            is_expired = datetime.now() > expiration_date
            
            qr_list.append({
                'id': row['id'],
                'client_name': row['client_name'],
                'client_firstname': row['client_firstname'],
                'client_phone': row['client_phone'],
                'client_email': row['client_email'],
                'ticket_number': row['ticket_number'],
                'service': row['service'],
                'created_at': row['created_at'],
                'expiration_date': row['expiration_date'],
                'printed_at': row['printed_at'],
                'is_active': bool(row['is_active']),
                'is_expired': is_expired,
                'expiration_text': format_expiration_text(expiration_date) if not is_expired else 'Expiré'
            })
        
        return jsonify({'success': True, 'qr_codes': qr_list})
        
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération des QR Codes: {e}")
        return jsonify({'success': False, 'error': "Erreur interne"}), 500

@app.route('/api/delete_qr/<qr_id>', methods=['DELETE', 'POST'])
@require_admin
def delete_qr(qr_id):
    """API pour supprimer un QR Code"""
    try:
        if not qr_id:
            return jsonify({'success': False, 'error': 'ID manquant'}), 400
            
        conn = get_db()
        result = conn.execute('DELETE FROM qr_codes WHERE id = ?', (qr_id,))
        conn.commit()
        deleted = result.rowcount > 0
        conn.close()
        
        if deleted:
            return jsonify({'success': True, 'message': 'QR Code supprimé'})
        else:
            return jsonify({'success': False, 'error': 'QR Code non trouvé'}), 404
            
    except Exception as e:
        app.logger.error(f"Erreur lors de la suppression: {e}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Erreur serveur'}), 500

@app.route('/api/qr_image/<qr_id>')
@require_admin
def qr_image(qr_id):
    """API pour obtenir l'image du QR Code"""
    try:
        conn = get_db()
        qr_record = conn.execute(
            'SELECT qr_data FROM qr_codes WHERE id = ?', (qr_id,)
        ).fetchone()
        conn.close()
        
        if not qr_record:
            abort(404)
        
        if not verify_qr_signature(qr_record['qr_data']):
            abort(400)

        qr_image = generate_qr_code_image(qr_record['qr_data'])
        img_io = BytesIO()
        qr_image.save(img_io, format='PNG')
        img_io.seek(0)
        
        return send_file(img_io, mimetype='image/png')
        
    except Exception as e:
        app.logger.error(f"Erreur lors de la génération de l'image: {e}")
        abort(500)

@app.route('/api/status')
def status():
    """API pour vérifier le statut de l'application et de l'imprimante"""
    printer_connected = False
    printer_info = None
    
    try:
        printer = get_printer()
        if printer:
            printer_connected = True
            printer_info = "Imprimante connectée"
            printer.close()
        else:
            printer_info = "Aucune imprimante détectée"
    except Exception as e:
        printer_info = f"Erreur: {str(e)}"
    
    return jsonify({
        'success': True,
        'printer_connected': printer_connected,
        'printer_info': printer_info
    })

# Scheduler pour nettoyer les QR Codes expirés (optionnel, peut être lancé via cron)
def cleanup_expired_qr():
    """Marque comme inactifs les QR Codes expirés"""
    try:
        conn = get_db()
        conn.execute(
            'UPDATE qr_codes SET is_active = 0 WHERE expiration_date <= datetime("now") AND is_active = 1'
        )
        conn.commit()
        conn.close()
        app.logger.info("Nettoyage des QR Codes expirés effectué")
    except Exception as e:
        app.logger.error(f"Erreur lors du nettoyage: {e}")

if __name__ == '__main__':
    # Initialisation de la base de données
    init_db()
    
    # Nettoyage initial
    cleanup_expired_qr()
    
    # Lancer l'application
    app.run(debug=app.config['DEBUG'], host='0.0.0.0', port=5000)

