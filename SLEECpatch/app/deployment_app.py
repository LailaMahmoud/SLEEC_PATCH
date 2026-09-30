"""Deployment entry point: empowered backend with the preserved live frontend."""
import app as backend

from services.deployment_frontend_compat import install_frontend_compatibility

install_frontend_compatibility(backend)
app = backend.app
