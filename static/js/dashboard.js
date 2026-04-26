// Script pour le dashboard administrateur

let currentDeleteId = null;

function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Initialisation
document.addEventListener('DOMContentLoaded', function() {
    loadQRCodes();
    checkPrinterStatus();
    
    // Écouter les changements de filtre
    document.getElementById('filterSelect').addEventListener('change', loadQRCodes);
    
    // Bouton de rafraîchissement
    document.getElementById('refreshBtn').addEventListener('click', loadQRCodes);
    
    // Gestion de la modal de suppression
    const deleteModal = new bootstrap.Modal(document.getElementById('deleteModal'));
    document.getElementById('confirmDeleteBtn').addEventListener('click', confirmDelete);
    
    // Actualiser toutes les 30 secondes
    setInterval(loadQRCodes, 30000);
    setInterval(checkPrinterStatus, 30000);
});

// Vérification du statut de l'imprimante
async function checkPrinterStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        const statusEl = document.getElementById('printerStatus');
        const iconEl = document.getElementById('printerIcon');
        
        if (statusEl && iconEl) {
            if (data.success && data.printer_connected) {
                statusEl.textContent = data.printer_info || 'Connectée';
                iconEl.className = 'bi bi-printer me-2 connected';
            } else {
                statusEl.textContent = data.printer_info || 'Aucune imprimante détectée';
                iconEl.className = 'bi bi-printer me-2 disconnected';
            }
        }
    } catch (error) {
        console.error('Erreur lors de la vérification de l\'imprimante:', error);
    }
}

// Chargement de la liste des QR Codes
async function loadQRCodes() {
    const filter = document.getElementById('filterSelect').value;
    const tbody = document.getElementById('qrTableBody');
    
    // Afficher le spinner
    tbody.innerHTML = `
        <tr>
            <td colspan="9" class="text-center">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Chargement...</span>
                </div>
            </td>
        </tr>
    `;
    
    try {
        const response = await fetch(`/api/list_qr?filter=${filter}`);
        const data = await response.json();
        
        if (data.success) {
            displayQRCodes(data.qr_codes);
            updateStatistics(data.qr_codes);
        } else {
            tbody.innerHTML = `
                <tr>
                    <td colspan="9" class="text-center text-danger">
                        Erreur: ${escapeHtml(data.error || 'Impossible de charger les données')}
                    </td>
                </tr>
            `;
        }
    } catch (error) {
        console.error('Erreur:', error);
        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="text-center text-danger">
                    Erreur de connexion au serveur
                </td>
            </tr>
        `;
    }
}

// Affichage des QR Codes dans le tableau
function displayQRCodes(qrCodes) {
    const tbody = document.getElementById('qrTableBody');
    
    if (qrCodes.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="text-center empty-state">
                    <i class="bi bi-inbox"></i>
                    <p class="mt-3">Aucun QR Code trouvé</p>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = qrCodes.map(qr => {
        const createdDate = escapeHtml(new Date(qr.created_at).toLocaleString('fr-FR'));
        const expirationDate = escapeHtml(new Date(qr.expiration_date).toLocaleString('fr-FR'));
        const clientNameRaw = `${qr.client_name || ''} ${qr.client_firstname || ''}`.trim() || 'N/A';
        const clientName = escapeHtml(clientNameRaw);
        const phone = escapeHtml(qr.client_phone || '-');
        const ticket = qr.ticket_number ? '#' + escapeHtml(qr.ticket_number) : '-';
        const service = escapeHtml(qr.service || '-');
        const shortId = escapeHtml((qr.id || '').substring(0, 8)) + '...';
        
        const statusBadge = qr.is_expired
            ? '<span class="badge bg-danger">Expiré</span>'
            : '<span class="badge bg-success">Actif</span>';
        
        return `
            <tr>
                <td><small class="text-muted">${shortId}</small></td>
                <td>${clientName}</td>
                <td>${phone}</td>
                <td>${ticket}</td>
                <td>${service}</td>
                <td><small>${createdDate}</small></td>
                <td><small>${expirationDate}</small></td>
                <td>${statusBadge}</td>
                <td>
                    <div class="btn-group btn-group-sm" role="group">
                        <button type="button" class="btn btn-outline-primary" 
                                onclick="viewQRCode('${qr.id}')" 
                                title="Voir">
                            <i class="bi bi-eye"></i>
                        </button>
                        <button type="button" class="btn btn-outline-success" 
                                onclick="reprintQRCode('${qr.id}')" 
                                title="Réimprimer"
                                ${qr.is_expired ? 'disabled' : ''}>
                            <i class="bi bi-printer"></i>
                        </button>
                        <button type="button" class="btn btn-outline-danger" 
                                onclick="deleteQRCode('${qr.id}')" 
                                title="Supprimer">
                            <i class="bi bi-trash"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

// Mise à jour des statistiques
function updateStatistics(qrCodes) {
    const total = qrCodes.length;
    const active = qrCodes.filter(qr => !qr.is_expired && qr.is_active).length;
    const expired = qrCodes.filter(qr => qr.is_expired || !qr.is_active).length;
    
    document.getElementById('statTotal').textContent = total;
    document.getElementById('statActive').textContent = active;
    document.getElementById('statExpired').textContent = expired;
}

// Voir un QR Code
function viewQRCode(qrId) {
    const url = `/api/qr_image/${qrId}`;
    window.open(url, '_blank');
}

// Réimprimer un QR Code
async function reprintQRCode(qrId) {
    try {
        const response = await fetch(`/api/print_qr/${qrId}`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken()
            }
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Succès', 'Réimpression réussie !', 'success');
        } else {
            showToast('Erreur', data.error || 'Erreur lors de la réimpression', 'danger');
        }
    } catch (error) {
        console.error('Erreur:', error);
        showToast('Erreur', 'Impossible de se connecter à l\'imprimante', 'danger');
    }
}

// Supprimer un QR Code
function deleteQRCode(qrId) {
    currentDeleteId = qrId;
    const deleteModal = new bootstrap.Modal(document.getElementById('deleteModal'));
    deleteModal.show();
}

// Confirmer la suppression
async function confirmDelete() {
    if (!currentDeleteId) return;
    
    try {
        const response = await fetch(`/api/delete_qr/${currentDeleteId}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            }
        });
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: 'Erreur HTTP ' + response.status }));
            throw new Error(errorData.error || 'Erreur de serveur');
        }
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Succès', 'QR Code supprimé avec succès', 'success');
            loadQRCodes(); // Recharger la liste
        } else {
            showToast('Erreur', data.error || 'Erreur lors de la suppression', 'danger');
        }
    } catch (error) {
        console.error('Erreur détaillée:', error);
        showToast('Erreur', error.message || 'Erreur de connexion', 'danger');
    } finally {
        // Fermer la modal
        const deleteModal = bootstrap.Modal.getInstance(document.getElementById('deleteModal'));
        if (deleteModal) {
            deleteModal.hide();
        }
        currentDeleteId = null;
    }
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

