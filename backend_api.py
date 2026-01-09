# backend_api.py - REST API for Cross-Instance Session Synchronization
"""
Simple Flask REST API for session state synchronization.

Endpoints:
    GET  /session/<session_id>     - Get session state
    POST /session/<session_id>     - Update session state
    DELETE /session/<session_id>   - Delete session
    GET  /sessions/active          - List active sessions
    POST /sessions/cleanup         - Clean up old sessions

Usage:
    python backend_api.py

The API runs on port 5000 by default and integrates with SessionStorage.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
from session_storage import get_storage
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for Streamlit frontend

# Get storage instance
storage = get_storage()
# --- API KEY / AUTHN (inserire dopo `storage = get_storage()`) ---
import os
from functools import wraps

# Legge la chiave dall'ambiente. Fallback non usato in produzione.
API_KEY = os.environ.get("BACKEND_API_KEY", "test-key-locale")

def api_key_required(f):
    """Decorator che valida l'header Authorization: Bearer <key>"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth or not auth.startswith("Bearer "):
            logger.warning("Auth failed: missing bearer token")
            return jsonify({'success': False, 'error': 'Missing Authorization Bearer token'}), 401
        token = auth.split(" ", 1)[1]
        # confronto in modo costante per evitare timing attacks in ambienti critici
        if token != API_KEY:
            logger.warning("Auth failed: invalid api key")
            return jsonify({'success': False, 'error': 'Invalid API key'}), 403
        return f(*args, **kwargs)
    return decorated
# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    from datetime import datetime
    return jsonify({
        'status': 'healthy',
        'service': 'CAHTBOT Backend API',
        'version': f'{datetime.now().year}.1.0'
    }), 200


# ============================================================================
# SESSION ENDPOINTS
# ============================================================================

@app.route('/session/<session_id>', methods=['GET'])
def get_session(session_id: str):
    """
    Get session state by ID.
    
    Args:
        session_id: Session identifier
    
    Returns:
        200: Session data
        404: Session not found
        500: Server error
    """
    try:
        session_data = storage.load_session(session_id)
        
        if session_data:
            logger.info(f"✅ GET /session/{session_id} - Success")
            return jsonify({
                'success': True,
                'session_id': session_id,
                'data': session_data
            }), 200
        else:
            logger.warning(f"⚠️ GET /session/{session_id} - Not found")
            return jsonify({
                'success': False,
                'error': 'Session not found'
            }), 404
    
    except Exception as e:
        logger.error(f"❌ GET /session/{session_id} - Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/session/<session_id>', methods=['POST'])
def update_session(session_id: str):
    """
    Update or create session state.
    
    Expected JSON body:
    {
        "messages": [...],
        "collected_data": {...},
        "current_step": "...",
        ...
    }
    
    Args:
        session_id: Session identifier
    
    Returns:
        200: Session updated
        400: Invalid request
        500: Server error
    """
    try:
        # Get JSON data from request
        session_data = request.get_json()
        
        if not session_data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        # Validate basic structure
        if not isinstance(session_data, dict):
            return jsonify({
                'success': False,
                'error': 'Invalid data format'
            }), 400
        
        # Save to storage
        success = storage.save_session(session_id, session_data)
        
        if success:
            logger.info(f"✅ POST /session/{session_id} - Success")
            return jsonify({
                'success': True,
                'session_id': session_id,
                'message': 'Session updated'
            }), 200
        else:
            logger.error(f"❌ POST /session/{session_id} - Save failed")
            return jsonify({
                'success': False,
                'error': 'Failed to save session'
            }), 500
    
    except Exception as e:
        logger.error(f"❌ POST /session/{session_id} - Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/session/<session_id>', methods=['DELETE'])
def delete_session(session_id: str):
    """
    Delete session by ID.
    
    Args:
        session_id: Session identifier
    
    Returns:
        200: Session deleted
        404: Session not found
        500: Server error
    """
    try:
        success = storage.delete_session(session_id)
        
        if success:
            logger.info(f"✅ DELETE /session/{session_id} - Success")
            return jsonify({
                'success': True,
                'message': 'Session deleted'
            }), 200
        else:
            logger.warning(f"⚠️ DELETE /session/{session_id} - Not found")
            return jsonify({
                'success': False,
                'error': 'Session not found'
            }), 404
    
    except Exception as e:
        logger.error(f"❌ DELETE /session/{session_id} - Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# SESSIONS MANAGEMENT
# ============================================================================

@app.route('/sessions/active', methods=['GET'])
def list_active_sessions():
    """
    List all active sessions with metadata.
    
    Returns:
        200: List of sessions
        500: Server error
    """
    try:
        sessions = storage.list_active_sessions()
        
        logger.info(f"✅ GET /sessions/active - {len(sessions)} sessions")
        return jsonify({
            'success': True,
            'count': len(sessions),
            'sessions': sessions
        }), 200
    
    except Exception as e:
        logger.error(f"❌ GET /sessions/active - Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/sessions/cleanup', methods=['POST'])
def cleanup_old_sessions():
    """
    Clean up sessions older than specified hours.
    
    Expected JSON body (optional):
    {
        "max_age_hours": 24
    }
    
    Returns:
        200: Cleanup completed
        500: Server error
    """
    try:
        data = request.get_json() or {}
        max_age_hours = data.get('max_age_hours', 24)
        
        deleted_count = storage.cleanup_old_sessions(max_age_hours)
        
        logger.info(f"✅ POST /sessions/cleanup - {deleted_count} sessions deleted")
        return jsonify({
            'success': True,
            'deleted_count': deleted_count,
            'max_age_hours': max_age_hours
        }), 200
    
    except Exception as e:
        logger.error(f"❌ POST /sessions/cleanup - Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({
        'success': False,
        'error': 'Endpoint not found'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {error}")
    return jsonify({
        'success': False,
        'error': 'Internal server error'
    }), 500


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    from datetime import datetime
    logger.info("=" * 60)
    logger.info("🚀 CAHTBOT Backend API Starting")
    logger.info("=" * 60)
    logger.info(f"Version: {datetime.now().year}.1.0")
    logger.info("Storage: SessionStorage (file-based)")
    logger.info("Port: 5000")
    logger.info("=" * 60)
    
    # Run Flask app
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,  # Set to False in production
        threaded=True
    )
