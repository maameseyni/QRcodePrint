// Script principal pour la page d'accueil (génération de QR Codes)

let currentQRId = null;
let currentQRImage = null;

function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

// Initialisation
document.addEventListener('DOMContentLoaded', function() {
    checkPrinterStatus();
    
    // Gestion du formulaire
    document.getElementById('qrForm').addEventListener('submit', handleFormSubmit);
    
    // Gestion de l'expiration personnalisée
    document.getElementById('expiration').addEventListener('change', function() {
        const container = document.getElementById('custom_hours_container');
        if (this.value === 'custom') {
            container.style.display = 'block';
            document.getElementById('custom_hours').required = true;
        } else {
            container.style.display = 'none';
            document.getElementById('custom_hours').required = false;
        }
    });
    
    // Boutons d'action
    document.getElementById('printBtn').addEventListener('click', handlePrint);
    document.getElementById('downloadBtn').addEventListener('click', handleDownload);
    document.getElementById('resetBtn').addEventListener('click', handleReset);
    
    // Vérifier le statut de l'imprimante toutes les 30 secondes
    setInterval(checkPrinterStatus, 30000);
});

// Vérification du statut de l'imprimante
async function checkPrinterStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        const statusEl = document.getElementById('printerStatus');
        const iconEl = document.getElementById('printerIcon');
        
        if (data.success && data.printer_connected) {
            statusEl.textContent = data.printer_info || 'Connectée';
            iconEl.className = 'bi bi-printer me-2 connected';
        } else {
            statusEl.textContent = data.printer_info || 'Aucune imprimante détectée';
            iconEl.className = 'bi bi-printer me-2 disconnected';
        }
    } catch (error) {
        console.error('Erreur lors de la vérification de l\'imprimante:', error);
        const statusEl = document.getElementById('printerStatus');
        statusEl.textContent = 'Erreur de vérification';
    }
}

// Soumission du formulaire
async function handleFormSubmit(e) {
    e.preventDefault();
    
    const btn = document.getElementById('generateBtn');
    const originalText = btn.innerHTML;
    
    // Désactiver le bouton et afficher le chargement
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Génération...';
    
    try {
        // Collecter les données du formulaire
        const formData = {
            client_name: document.getElementById('client_name').value,
            client_firstname: document.getElementById('client_firstname').value,
            client_phone: document.getElementById('client_phone').value,
            client_email: document.getElementById('client_email').value,
            client_id: document.getElementById('client_id').value,
            ticket_number: document.getElementById('ticket_number').value,
            service: document.getElementById('service').value,
            comment: document.getElementById('comment').value,
            expiration: document.getElementById('expiration').value
        };
        
        // Ajouter les heures personnalisées si nécessaire
        if (formData.expiration === 'custom') {
            formData.custom_hours = document.getElementById('custom_hours').value;
        }
        
        // Envoyer la requête
        const response = await fetch('/api/create_qr', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            },
            body: JSON.stringify(formData)
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Afficher le QR Code
            currentQRId = data.qr_id;
            currentQRImage = data.qr_image;
            
            displayQRCode(data);
            showToast('Succès', 'QR Code généré avec succès !', 'success');
        } else {
            showToast('Erreur', data.error || 'Erreur lors de la génération', 'danger');
        }
    } catch (error) {
        console.error('Erreur:', error);
        showToast('Erreur', 'Une erreur est survenue lors de la génération', 'danger');
    } finally {
        // Réactiver le bouton
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// Affichage du QR Code
function displayQRCode(data) {
    const resultDiv = document.getElementById('qrResult');
    const emptyState = document.getElementById('qrEmptyState');
    const imageContainer = document.getElementById('qrImageContainer');
    const expirationText = document.getElementById('expirationText');
    
    // Cacher l'état vide et afficher le QR Code
    emptyState.style.display = 'none';
    resultDiv.style.display = 'block';
    
    // Créer l'image
    const img = document.createElement('img');
    img.src = 'data:image/png;base64,' + data.qr_image;
    img.alt = 'QR Code';
    img.className = 'img-fluid';
    img.style.maxWidth = '100%';
    
    imageContainer.innerHTML = '';
    imageContainer.appendChild(img);
    
    // Afficher le texte d'expiration
    expirationText.textContent = `Expire dans: ${data.expiration_text}`;
}

// Impression du QR Code
async function handlePrint() {
    if (!currentQRId) {
        showToast('Erreur', 'Aucun QR Code à imprimer', 'warning');
        return;
    }
    
    const btn = document.getElementById('printBtn');
    const originalText = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Impression...';
    
    try {
        const response = await fetch(`/api/print_qr/${currentQRId}`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken()
            }
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Succès', 'Impression réussie !', 'success');
        } else {
            showToast('Erreur', data.error || 'Erreur lors de l\'impression', 'danger');
        }
    } catch (error) {
        console.error('Erreur:', error);
        showToast('Erreur', 'Impossible de se connecter à l\'imprimante', 'danger');
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// Téléchargement du QR Code
function handleDownload() {
    if (!currentQRImage) {
        showToast('Erreur', 'Aucun QR Code à télécharger', 'warning');
        return;
    }
    
    try {
        // Créer un lien de téléchargement
        const link = document.createElement('a');
        link.href = 'data:image/png;base64,' + currentQRImage;
        link.download = `qr-code-${currentQRId || 'download'}.png`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        showToast('Succès', 'QR Code téléchargé !', 'success');
    } catch (error) {
        console.error('Erreur:', error);
        showToast('Erreur', 'Erreur lors du téléchargement', 'danger');
    }
}

// Réinitialisation du formulaire
function handleReset() {
    document.getElementById('qrForm').reset();
    const qrResult = document.getElementById('qrResult');
    const emptyState = document.getElementById('qrEmptyState');
    
    // Réinitialiser l'affichage du QR Code
    qrResult.style.display = 'none';
    emptyState.style.display = 'block';
    document.getElementById('custom_hours_container').style.display = 'none';
    
    currentQRId = null;
    currentQRImage = null;
}

// Affichage des notifications Toast
function showToast(title, message, type = 'info') {
    const toast = document.getElementById('toast');
    const toastTitle = document.getElementById('toastTitle');
    const toastBody = document.getElementById('toastBody');
    
    // Définir les classes selon le type
    toast.className = 'toast';
    if (type === 'success') {
        toast.classList.add('text-bg-success');
    } else if (type === 'danger' || type === 'error') {
        toast.classList.add('text-bg-danger');
    } else if (type === 'warning') {
        toast.classList.add('text-bg-warning');
    } else {
        toast.classList.add('text-bg-info');
    }
    
    toastTitle.textContent = title;
    toastBody.textContent = message;
    
    // Afficher le toast
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
}

