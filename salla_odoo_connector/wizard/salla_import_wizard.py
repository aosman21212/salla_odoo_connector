from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SallaImportWizard(models.TransientModel):
    _name = 'salla.import.wizard'
    _description = 'Salla Import Wizard'

    instance_id = fields.Many2one('salla.instance', string='Salla Instance',
                                   required=True, domain=[('state', '=', 'connected')])

    # What to import
    import_customer_groups = fields.Boolean('Customer Groups', default=True)
    import_customers = fields.Boolean('Customers', default=True)
    import_brands = fields.Boolean('Brands', default=True)
    import_categories = fields.Boolean('Categories', default=True)
    import_products = fields.Boolean('Products', default=True)
    import_order_statuses = fields.Boolean('Order Statuses', default=True)
    import_orders = fields.Boolean('Orders', default=False)

    # Order date filter
    order_date_from = fields.Date('Orders From')
    order_date_to = fields.Date('Orders To')

    # Pre-set operation (from context)
    operation = fields.Selection([
        ('all', 'All'),
        ('orders', 'Orders Only'),
        ('products', 'Products Only'),
        ('customers', 'Customers Only'),
    ], default='all')

    @api.onchange('operation')
    def _onchange_operation(self):
        if self.operation == 'orders':
            self.import_customer_groups = False
            self.import_customers = False
            self.import_brands = False
            self.import_categories = False
            self.import_products = False
            self.import_order_statuses = False
            self.import_orders = True
        elif self.operation == 'products':
            self.import_customer_groups = False
            self.import_customers = False
            self.import_brands = True
            self.import_categories = True
            self.import_products = True
            self.import_order_statuses = False
            self.import_orders = False
        elif self.operation == 'customers':
            self.import_customer_groups = True
            self.import_customers = True
            self.import_brands = False
            self.import_categories = False
            self.import_products = False
            self.import_order_statuses = False
            self.import_orders = False

    def action_import(self):
        self.ensure_one()
        inst = self.instance_id
        messages = []

        if self.import_customer_groups:
            result = inst.action_import_customer_groups()
            messages.append(result['params']['message'])

        if self.import_customers:
            result = inst.action_import_customers()
            messages.append(result['params']['message'])

        if self.import_brands:
            result = inst.action_import_brands()
            messages.append(result['params']['message'])

        if self.import_categories:
            result = inst.action_import_categories()
            messages.append(result['params']['message'])

        if self.import_products:
            result = inst.action_import_products()
            messages.append(result['params']['message'])

        if self.import_order_statuses:
            result = inst.action_import_order_statuses()
            messages.append(result['params']['message'])

        if self.import_orders:
            count = inst._import_orders(
                date_from=self.order_date_from,
                date_to=self.order_date_to,
            )
            messages.append(f'{count} order(s) imported.')

        if not messages:
            raise UserError(_('Please select at least one data type to import.'))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Complete'),
                'message': '\n'.join(messages),
                'type': 'success',
                'sticky': True,
            },
        }
