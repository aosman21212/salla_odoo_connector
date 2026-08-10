from odoo import _, fields, models
from odoo.exceptions import UserError


class ResPartnerCategory(models.Model):
    _inherit = 'res.partner.category'

    salla_id = fields.Char('Salla Group ID', index=True, copy=False)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    salla_id = fields.Char('Salla Customer ID', index=True, copy=False)
    salla_instance_id = fields.Many2one('salla.instance', string='Salla Instance',
                                         ondelete='set null', copy=False)

    def action_export_to_salla(self):
        self.ensure_one()
        if not self.salla_instance_id:
            raise UserError(_('No Salla instance linked to this contact.'))
        self.salla_instance_id._export_partner(self)
        return self.salla_instance_id._notify(
            'Exported', f'Customer "{self.name}" exported to Salla.')

    def action_open_salla(self):
        """Open the Salla customer page (requires store domain)."""
        self.ensure_one()
        if not self.salla_id or not self.salla_instance_id:
            raise UserError(_('This contact is not linked to a Salla customer.'))
        domain = self.salla_instance_id.salla_store_domain
        if domain:
            url = f'https://{domain}/admin/customers/{self.salla_id}'
        else:
            url = 'https://s.salla.sa/apps/orders'
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'new'}
