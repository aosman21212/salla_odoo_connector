from odoo import _, fields, models


class SallaSchedulerWizard(models.TransientModel):
    _name = 'salla.scheduler.wizard'
    _description = 'Salla Scheduler Configuration'

    instance_id = fields.Many2one('salla.instance', string='Salla Instance', required=True)

    auto_sync_products = fields.Boolean('Auto Sync Products')
    auto_sync_customers = fields.Boolean('Auto Sync Customers')
    auto_sync_orders = fields.Boolean('Auto Sync Orders')
    auto_sync_interval = fields.Integer('Sync Interval (hours)', default=1)
    enable_cron = fields.Boolean('Enable Scheduled Sync', default=True)

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        inst_id = self.env.context.get('default_instance_id')
        if inst_id:
            inst = self.env['salla.instance'].browse(inst_id)
            res.update({
                'instance_id': inst_id,
                'auto_sync_products': inst.auto_sync_products,
                'auto_sync_customers': inst.auto_sync_customers,
                'auto_sync_orders': inst.auto_sync_orders,
                'auto_sync_interval': inst.auto_sync_interval,
            })
        return res

    def action_save(self):
        self.ensure_one()
        self.instance_id.write({
            'auto_sync_products': self.auto_sync_products,
            'auto_sync_customers': self.auto_sync_customers,
            'auto_sync_orders': self.auto_sync_orders,
            'auto_sync_interval': self.auto_sync_interval,
        })
        # Update the cron job interval
        cron = self.env.ref('leapai_salla_odoo_connector.ir_cron_salla_sync', raise_if_not_found=False)
        if cron:
            cron.write({
                'active': self.enable_cron,
                'interval_number': self.auto_sync_interval,
                'interval_type': 'hours',
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Scheduler Updated'),
                'message': _('Auto-sync settings saved.'),
                'type': 'success',
                'sticky': False,
            },
        }
