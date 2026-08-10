from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    salla_variant_id = fields.Char('Salla Variant ID', index=True, copy=False)
