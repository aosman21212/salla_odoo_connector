from odoo import _, fields, models
from odoo.exceptions import UserError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    salla_id = fields.Char('Salla Product ID', index=True, copy=False)
    salla_instance_id = fields.Many2one('salla.instance', string='Salla Instance',
                                         ondelete='set null', copy=False)
    salla_status = fields.Selection([
        ('active', 'Active'),
        ('out_of_stock', 'Out of Stock'),
        ('hidden', 'Hidden'),
        ('deleted', 'Deleted'),
    ], string='Salla Status', default='active', copy=False)
    salla_url = fields.Char('Salla Product URL', copy=False)
    salla_brand_id = fields.Many2one('salla.brand', string='Salla Brand', copy=False)

    def action_export_to_salla(self):
        self.ensure_one()
        if not self.salla_instance_id:
            raise UserError(_('No Salla instance linked to this product.'))
        self.salla_instance_id._export_product(self)
        return self.salla_instance_id._notify(
            'Exported', f'Product "{self.name}" exported to Salla.')

    def action_open_salla(self):
        self.ensure_one()
        if not self.salla_url:
            raise UserError(_('No Salla URL stored for this product.'))
        return {'type': 'ir.actions.act_url', 'url': self.salla_url, 'target': 'new'}

    def action_sync_from_salla(self):
        """Refresh this single product from Salla."""
        self.ensure_one()
        if not self.salla_id or not self.salla_instance_id:
            raise UserError(_('This product is not linked to a Salla product.'))
        resp = self.salla_instance_id._api_call('GET', f'/products/{self.salla_id}')
        self.salla_instance_id._upsert_product(resp.get('data', {}))
        return self.salla_instance_id._notify('Synced', f'Product "{self.name}" refreshed from Salla.')
