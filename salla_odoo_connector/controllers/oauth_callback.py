import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class SallaOAuthCallback(http.Controller):

    @http.route('/salla/callback', type='http', auth='user', methods=['GET'], website=False)
    def oauth_callback(self, code=None, state=None, error=None, **kwargs):
        """
        Salla OAuth2 redirect URI handler.
        Receives ?code=XXX&state=<instance_id> after user authorises the app.
        """
        if error:
            _logger.warning('Salla OAuth error: %s', error)
            return request.redirect(
                '/web#action=salla_odoo_connector.action_salla_instance_list'
                '&notification=oauth_error',
            )

        if not code or not state:
            return request.redirect('/web')

        try:
            instance_id = int(state)
        except (ValueError, TypeError):
            _logger.error('Salla callback: invalid state %s', state)
            return request.redirect('/web')

        instance = request.env['salla.instance'].sudo().browse(instance_id)
        if not instance.exists():
            _logger.error('Salla callback: instance %s not found', instance_id)
            return request.redirect('/web')

        try:
            instance._exchange_code(code)
            _logger.info('Salla: OAuth successful for instance %s', instance.name)
        except Exception as e:
            _logger.error('Salla OAuth token exchange failed: %s', e)

        # Redirect back to the instance form
        return request.redirect(
            f'/odoo/salla-connector/{instance_id}'
        )
