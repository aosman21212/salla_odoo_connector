from odoo import fields, models


class SallaBrand(models.Model):
    _name = 'salla.brand'
    _description = 'Salla Brand'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char('Brand Name', required=True)
    salla_id = fields.Char('Salla ID', index=True)
    salla_instance_id = fields.Many2one('salla.instance', string='Salla Instance',
                                         ondelete='cascade')
    salla_url = fields.Char('Brand URL')
    product_count = fields.Integer(compute='_compute_product_count', string='Products')

    def _compute_product_count(self):
        for rec in self:
            rec.product_count = self.env['product.template'].search_count([
                ('salla_brand_id', '=', rec.id)])
