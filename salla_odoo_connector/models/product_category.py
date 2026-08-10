from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = 'product.category'

    salla_id = fields.Char('Salla Category ID', index=True, copy=False)
    salla_instance_id = fields.Many2one('salla.instance', string='Salla Instance',
                                         ondelete='set null', copy=False)
