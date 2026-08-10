from odoo import fields, models


class SallaOrderStatus(models.Model):
    _name = 'salla.order.status'
    _description = 'Salla Order Status'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char('Status Name', required=True)
    salla_id = fields.Char('Salla Status ID', index=True)
    salla_instance_id = fields.Many2one('salla.instance', string='Salla Instance',
                                         ondelete='cascade')
    color = fields.Char('Colour', default='#6c757d')
    order_count = fields.Integer(compute='_compute_order_count', string='Orders')

    def _compute_order_count(self):
        for rec in self:
            rec.order_count = self.env['sale.order'].search_count([
                ('salla_status', '=', rec.name)])
