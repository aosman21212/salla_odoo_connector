from odoo import _, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    salla_id = fields.Char('Salla Order ID', index=True, copy=False)
    salla_instance_id = fields.Many2one('salla.instance', string='Salla Instance',
                                         ondelete='set null', copy=False)
    salla_reference = fields.Char('Salla Reference', copy=False)
    salla_status = fields.Char('Salla Status', copy=False)

    def action_open_salla_order(self):
        """Open the order in the Salla admin panel."""
        self.ensure_one()
        if not self.salla_id:
            raise UserError(_('This order has no Salla ID.'))
        domain = self.salla_instance_id.salla_store_domain if self.salla_instance_id else ''
        if domain:
            url = f'https://{domain}/admin/orders/{self.salla_id}'
        else:
            url = 'https://s.salla.sa/apps/orders'
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'new'}

    def action_push_status_to_salla(self):
        """Push the current Odoo status to Salla."""
        self.ensure_one()
        if not self.salla_id or not self.salla_instance_id:
            raise UserError(_('This order is not linked to a Salla order.'))
        # Map Odoo state to a meaningful Salla status update
        # (Salla requires a numeric status_id; use a default for now)
        status_rec = self.env['salla.order.status'].search(
            [('salla_instance_id', '=', self.salla_instance_id.id)], limit=1)
        if not status_rec:
            raise UserError(_('No Salla order statuses found. '
                              'Please import order statuses first.'))
        self.salla_instance_id._update_order_status(self, status_rec.salla_id)
        return self.salla_instance_id._notify('Status Pushed', 'Order status updated on Salla.')
