import logging
import math
from datetime import timedelta

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

SALLA_API_BASE = 'https://api.salla.dev/admin/v2'
SALLA_AUTH_URL = 'https://accounts.salla.sa/oauth2/auth'
SALLA_TOKEN_URL = 'https://accounts.salla.sa/oauth2/token'
SALLA_SCOPES = 'offline_access'


class SallaInstance(models.Model):
    _name = 'salla.instance'
    _description = 'Salla Integration Instance'
    _rec_name = 'name'

    # ── Identity ──────────────────────────────────────────────────────────────

    name = fields.Char('Instance Name', required=True, default='My Salla Store')
    client_id = fields.Char('Client ID', required=True,
                             help='App Client ID from Salla Partners Portal')
    client_secret = fields.Char('Client Secret', required=True)
    state = fields.Selection([
        ('draft', 'Not Connected'),
        ('connected', 'Connected'),
        ('expired', 'Token Expired'),
    ], default='draft', string='Status')

    # ── OAuth tokens ──────────────────────────────────────────────────────────

    access_token = fields.Char('Access Token', copy=False)
    refresh_token = fields.Char('Refresh Token', copy=False)
    token_expiry = fields.Datetime('Token Expiry', readonly=True)

    # ── Store info (read from Salla) ──────────────────────────────────────────

    salla_store_id = fields.Char('Salla Store ID', readonly=True)
    salla_store_name = fields.Char('Store Name', readonly=True)
    salla_store_email = fields.Char('Store Email', readonly=True)
    salla_store_domain = fields.Char('Store Domain', readonly=True)
    salla_store_currency = fields.Char('Currency', readonly=True, default='SAR')

    # ── Sync statistics ───────────────────────────────────────────────────────

    product_count = fields.Integer(compute='_compute_counts', string='Products')
    customer_count = fields.Integer(compute='_compute_counts', string='Customers')
    order_count = fields.Integer(compute='_compute_counts', string='Orders')
    category_count = fields.Integer(compute='_compute_counts', string='Categories')

    # ── Scheduler settings ────────────────────────────────────────────────────

    auto_sync_products = fields.Boolean('Auto Sync Products', default=False)
    auto_sync_customers = fields.Boolean('Auto Sync Customers', default=False)
    auto_sync_orders = fields.Boolean('Auto Sync Orders', default=False)
    auto_sync_interval = fields.Integer('Sync Interval (hours)', default=1)
    last_order_sync = fields.Datetime('Last Order Sync', readonly=True)
    last_product_sync = fields.Datetime('Last Product Sync', readonly=True)
    last_customer_sync = fields.Datetime('Last Customer Sync', readonly=True)

    # ── Notes ─────────────────────────────────────────────────────────────────

    note = fields.Text('Notes')

    # ── Compute counts ────────────────────────────────────────────────────────

    def _compute_counts(self):
        for rec in self:
            rec.product_count = self.env['product.template'].search_count([
                ('salla_instance_id', '=', rec.id)])
            rec.customer_count = self.env['res.partner'].search_count([
                ('salla_instance_id', '=', rec.id)])
            rec.order_count = self.env['sale.order'].search_count([
                ('salla_instance_id', '=', rec.id)])
            rec.category_count = self.env['product.category'].search_count([
                ('salla_instance_id', '=', rec.id)])

    # ── Smart button actions ──────────────────────────────────────────────────

    def action_view_products(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Salla Products'),
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'domain': [('salla_instance_id', '=', self.id)],
            'context': {'default_salla_instance_id': self.id},
        }

    def action_view_customers(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Salla Customers'),
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('salla_instance_id', '=', self.id)],
        }

    def action_view_orders(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Salla Orders'),
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('salla_instance_id', '=', self.id)],
        }

    # ── OAuth helpers ─────────────────────────────────────────────────────────

    def _get_redirect_uri(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return f'{base_url}/salla/callback'

    def action_get_token(self):
        """Redirect browser to Salla OAuth2 authorisation page."""
        self.ensure_one()
        redirect_uri = self._get_redirect_uri()
        url = (
            f'{SALLA_AUTH_URL}'
            f'?client_id={self.client_id}'
            f'&redirect_uri={redirect_uri}'
            f'&scope={SALLA_SCOPES}'
            f'&response_type=code'
            f'&state={self.id}'
        )
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'self'}

    def _exchange_code(self, code):
        """Exchange OAuth2 authorisation code for tokens."""
        resp = requests.post(
            SALLA_TOKEN_URL,
            data={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': self._get_redirect_uri(),
            },
            timeout=30,
        )
        resp.raise_for_status()
        self._save_tokens(resp.json())

    def action_refresh_token(self):
        """Refresh the access token using the stored refresh token."""
        self.ensure_one()
        if not self.refresh_token:
            raise UserError(_('No refresh token stored. Please re-authorise.'))
        try:
            resp = requests.post(
                SALLA_TOKEN_URL,
                data={
                    'client_id': self.client_id,
                    'client_secret': self.client_secret,
                    'grant_type': 'refresh_token',
                    'refresh_token': self.refresh_token,
                },
                timeout=30,
            )
            resp.raise_for_status()
            self._save_tokens(resp.json())
            return self._notify('Token Refreshed', 'Access token refreshed successfully.')
        except Exception as e:
            raise UserError(_('Token refresh failed: %s') % str(e))

    def _save_tokens(self, token_data):
        expires_in = token_data.get('expires_in', 2592000)
        self.write({
            'access_token': token_data.get('access_token'),
            'refresh_token': token_data.get('refresh_token', self.refresh_token),
            'token_expiry': fields.Datetime.now() + timedelta(seconds=expires_in),
            'state': 'connected',
        })
        self._fetch_store_info()

    def action_test_connection(self):
        """Verify credentials by calling the store info endpoint."""
        self.ensure_one()
        try:
            self._fetch_store_info()
            return self._notify(
                'Connection Successful',
                f'Connected to store: {self.salla_store_name or self.salla_store_id}'
            )
        except Exception as e:
            raise UserError(_('Connection failed: %s') % str(e))

    def _fetch_store_info(self):
        data = self._api_call('GET', '/store/info')
        store = data.get('data', {})
        self.write({
            'salla_store_id': str(store.get('id', '')),
            'salla_store_name': store.get('name', ''),
            'salla_store_email': store.get('email', ''),
            'salla_store_domain': store.get('domain', ''),
            'salla_store_currency': store.get('currency', {}).get('currency', 'SAR'),
            'state': 'connected',
        })

    # ── Low-level API caller ──────────────────────────────────────────────────

    def _get_headers(self):
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

    def _api_call(self, method, endpoint, json=None, params=None, retry=True):
        """Make an authenticated call to the Salla REST API."""
        url = f'{SALLA_API_BASE}/{endpoint.lstrip("/")}'
        try:
            resp = requests.request(
                method, url,
                headers=self._get_headers(),
                json=json,
                params=params,
                timeout=30,
            )
            if resp.status_code == 401 and retry:
                # Token expired — try refresh then retry once
                _logger.info('Salla: 401 on %s, refreshing token', endpoint)
                try:
                    self.action_refresh_token()
                except Exception:
                    self.state = 'expired'
                    raise UserError(_('Access token expired and could not be refreshed. '
                                      'Please re-authorise the Salla connection.'))
                return self._api_call(method, endpoint, json=json, params=params, retry=False)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            raise UserError(_('Salla API request timed out. Please try again.'))
        except requests.exceptions.ConnectionError:
            raise UserError(_('Cannot reach Salla API. Check your internet connection.'))

    def _paginated_get(self, endpoint, params=None):
        """Generator that yields each page of results from a paginated endpoint."""
        params = dict(params or {})
        params.setdefault('per_page', 50)
        page = 1
        while True:
            params['page'] = page
            resp = self._api_call('GET', endpoint, params=params)
            items = resp.get('data', [])
            if not items:
                break
            yield items
            pagination = resp.get('pagination', {})
            total_pages = pagination.get('totalPages', 1)
            if page >= total_pages:
                break
            page += 1

    # ── Notification helper ───────────────────────────────────────────────────

    def _notify(self, title, message, n_type='success'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _(title),
                'message': _(message),
                'type': n_type,
                'sticky': False,
            },
        }

    # ══ IMPORT: Salla → Odoo ══════════════════════════════════════════════════

    # ── Customer Groups ───────────────────────────────────────────────────────

    def action_import_customer_groups(self):
        self.ensure_one()
        count = 0
        for page in self._paginated_get('/customer-groups'):
            for grp in page:
                self._upsert_partner_category(grp)
                count += 1
        return self._notify('Import Complete', f'{count} customer group(s) imported.')

    def _upsert_partner_category(self, grp):
        salla_id = str(grp['id'])
        cat = self.env['res.partner.category'].search(
            [('salla_id', '=', salla_id)], limit=1)
        vals = {'name': grp.get('name', ''), 'salla_id': salla_id}
        if cat:
            cat.write(vals)
        else:
            self.env['res.partner.category'].create(vals)

    # ── Customers ─────────────────────────────────────────────────────────────

    def action_import_customers(self):
        self.ensure_one()
        count = 0
        for page in self._paginated_get('/customers'):
            for cust in page:
                self._upsert_partner(cust)
                count += 1
        self.last_customer_sync = fields.Datetime.now()
        return self._notify('Import Complete', f'{count} customer(s) imported.')

    def _upsert_partner(self, cust):
        salla_id = str(cust['id'])
        partner = self.env['res.partner'].search(
            [('salla_id', '=', salla_id),
             ('salla_instance_id', '=', self.id)], limit=1)

        # Resolve country
        country = self.env['res.country']
        country_code = cust.get('country', {})
        if isinstance(country_code, dict):
            country_code = country_code.get('code', '')
        if country_code:
            country = self.env['res.country'].search(
                [('code', '=', country_code.upper())], limit=1)

        # Resolve customer groups → partner categories
        cat_ids = []
        for grp in cust.get('groups', []):
            grp_salla_id = str(grp.get('id', ''))
            cat = self.env['res.partner.category'].search(
                [('salla_id', '=', grp_salla_id)], limit=1)
            if cat:
                cat_ids.append(cat.id)

        vals = {
            'name': cust.get('name') or cust.get('first_name', '') + ' ' + cust.get('last_name', ''),
            'email': cust.get('email', ''),
            'phone': cust.get('mobile', '') or cust.get('phone', ''),
            'customer_rank': 1,
            'salla_id': salla_id,
            'salla_instance_id': self.id,
        }
        if country:
            vals['country_id'] = country.id
        city = cust.get('city', '')
        if isinstance(city, dict):
            city = city.get('name', '')
        if city:
            vals['city'] = city
        if cat_ids:
            vals['category_id'] = [(6, 0, cat_ids)]

        if partner:
            partner.write(vals)
        else:
            self.env['res.partner'].create(vals)

    # ── Brands ────────────────────────────────────────────────────────────────

    def action_import_brands(self):
        self.ensure_one()
        count = 0
        for page in self._paginated_get('/brands'):
            for brand in page:
                self._upsert_brand(brand)
                count += 1
        return self._notify('Import Complete', f'{count} brand(s) imported.')

    def _upsert_brand(self, brand):
        salla_id = str(brand['id'])
        rec = self.env['salla.brand'].search([('salla_id', '=', salla_id)], limit=1)
        vals = {
            'name': brand.get('name', ''),
            'salla_id': salla_id,
            'salla_instance_id': self.id,
            'salla_url': brand.get('url', ''),
        }
        if rec:
            rec.write(vals)
        else:
            self.env['salla.brand'].create(vals)

    # ── Categories ────────────────────────────────────────────────────────────

    def action_import_categories(self):
        self.ensure_one()
        count = 0
        for page in self._paginated_get('/categories'):
            for cat in page:
                self._upsert_category(cat)
                count += 1
        return self._notify('Import Complete', f'{count} categor(ies) imported.')

    def _upsert_category(self, cat, parent_id=None):
        salla_id = str(cat['id'])
        rec = self.env['product.category'].search(
            [('salla_id', '=', salla_id),
             ('salla_instance_id', '=', self.id)], limit=1)
        vals = {
            'name': cat.get('name', ''),
            'salla_id': salla_id,
            'salla_instance_id': self.id,
        }
        if parent_id:
            vals['parent_id'] = parent_id
        if rec:
            rec.write(vals)
        else:
            rec = self.env['product.category'].create(vals)

        # Recursively handle subcategories
        for sub in cat.get('children', []):
            self._upsert_category(sub, parent_id=rec.id)
        return rec

    # ── Products ──────────────────────────────────────────────────────────────

    def action_import_products(self):
        self.ensure_one()
        count = 0
        for page in self._paginated_get('/products'):
            for prod in page:
                self._upsert_product(prod)
                count += 1
        self.last_product_sync = fields.Datetime.now()
        return self._notify('Import Complete', f'{count} product(s) imported.')

    def _upsert_product(self, prod):
        salla_id = str(prod['id'])
        tmpl = self.env['product.template'].search(
            [('salla_id', '=', salla_id),
             ('salla_instance_id', '=', self.id)], limit=1)

        # Price
        price_data = prod.get('price', {})
        price = price_data.get('amount', 0.0) if isinstance(price_data, dict) else float(price_data or 0)

        sale_price_data = prod.get('sale_price', {})
        sale_price = sale_price_data.get('amount', 0.0) if isinstance(sale_price_data, dict) else 0.0

        # Category
        cat_ids = []
        for c in prod.get('categories', []):
            cat_salla_id = str(c.get('id', ''))
            cat = self.env['product.category'].search(
                [('salla_id', '=', cat_salla_id),
                 ('salla_instance_id', '=', self.id)], limit=1)
            if cat:
                cat_ids.append(cat.id)

        # Brand
        brand_data = prod.get('brand', {})
        salla_brand_id = None
        if isinstance(brand_data, dict) and brand_data.get('id'):
            brand = self.env['salla.brand'].search(
                [('salla_id', '=', str(brand_data['id']))], limit=1)
            if brand:
                salla_brand_id = brand.id

        vals = {
            'name': prod.get('name', ''),
            'description_sale': prod.get('description', ''),
            'list_price': price,
            'default_code': prod.get('sku', ''),
            'salla_id': salla_id,
            'salla_instance_id': self.id,
            'salla_status': prod.get('status', 'active'),
            'salla_url': prod.get('urls', {}).get('customer', '') if isinstance(prod.get('urls'), dict) else '',
            'salla_brand_id': salla_brand_id,
            'type': 'consu',
            'sale_ok': True,
            'purchase_ok': True,
        }
        if cat_ids:
            # Set categ_id to first matched category
            vals['categ_id'] = cat_ids[0]

        if tmpl:
            tmpl.write(vals)
        else:
            tmpl = self.env['product.template'].create(vals)

        # Sync stock quantity (simple products)
        qty = prod.get('quantity', 0)
        if qty and tmpl.product_variant_ids:
            self._update_stock(tmpl.product_variant_ids[0], float(qty))

        # Handle variants
        options = prod.get('options', [])
        variants = prod.get('variants', [])
        if options and variants:
            self._sync_product_variants(tmpl, options, variants)

        return tmpl

    def _sync_product_variants(self, tmpl, options, variants):
        """Map Salla product options/variants to Odoo attribute lines."""
        for option in options:
            attr_name = option.get('name', '')
            attr = self.env['product.attribute'].search(
                [('name', '=ilike', attr_name)], limit=1)
            if not attr:
                attr = self.env['product.attribute'].create({'name': attr_name})

            attr_line = tmpl.attribute_line_ids.filtered(
                lambda l: l.attribute_id == attr)

            values_names = [v.get('name', '') for v in option.get('values', [])]
            attr_value_ids = []
            for val_name in values_names:
                val = self.env['product.attribute.value'].search(
                    [('name', '=ilike', val_name),
                     ('attribute_id', '=', attr.id)], limit=1)
                if not val:
                    val = self.env['product.attribute.value'].create({
                        'name': val_name,
                        'attribute_id': attr.id,
                    })
                attr_value_ids.append(val.id)

            if not attr_line:
                tmpl.write({'attribute_line_ids': [(0, 0, {
                    'attribute_id': attr.id,
                    'value_ids': [(6, 0, attr_value_ids)],
                })]})
            else:
                attr_line.write({'value_ids': [(6, 0, attr_value_ids)]})

        # Tag each product.product with salla variant id
        for salla_var in variants:
            salla_var_id = str(salla_var.get('id', ''))
            # Try matching by SKU
            sku = salla_var.get('sku', '')
            variant = None
            if sku:
                variant = tmpl.product_variant_ids.filtered(
                    lambda v: v.default_code == sku)[:1]
            if not variant and tmpl.product_variant_ids:
                variant = tmpl.product_variant_ids[:1]
            if variant:
                variant.salla_variant_id = salla_var_id
                price_data = salla_var.get('price', {})
                if isinstance(price_data, dict) and price_data.get('amount'):
                    variant.lst_price = price_data['amount']
                qty = salla_var.get('quantity', 0)
                if qty:
                    self._update_stock(variant, float(qty))

    def _update_stock(self, product, qty):
        """Set on-hand quantity for a product variant."""
        location = self.env['stock.warehouse'].search([], limit=1).lot_stock_id
        if not location:
            return
        self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': product.id,
            'location_id': location.id,
            'inventory_quantity': qty,
        }).action_apply_inventory()

    # ── Order Statuses ────────────────────────────────────────────────────────

    def action_import_order_statuses(self):
        self.ensure_one()
        count = 0
        # Built-in Salla statuses
        try:
            data = self._api_call('GET', '/orders/statuses')
            for status in data.get('data', []):
                self._upsert_order_status(status)
                count += 1
        except Exception as e:
            _logger.warning('Could not fetch order statuses: %s', e)
        return self._notify('Import Complete', f'{count} order status(es) imported.')

    def _upsert_order_status(self, status):
        salla_id = str(status.get('id', ''))
        rec = self.env['salla.order.status'].search(
            [('salla_id', '=', salla_id),
             ('salla_instance_id', '=', self.id)], limit=1)
        vals = {
            'name': status.get('name', ''),
            'salla_id': salla_id,
            'salla_instance_id': self.id,
            'color': status.get('color', '#000000'),
        }
        if rec:
            rec.write(vals)
        else:
            self.env['salla.order.status'].create(vals)

    # ── Orders ────────────────────────────────────────────────────────────────

    def action_import_orders(self):
        """Open the import wizard to let the user choose date range."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import Orders from Salla'),
            'res_model': 'salla.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_instance_id': self.id,
                'default_operation': 'orders',
            },
        }

    def _import_orders(self, date_from=None, date_to=None):
        count = 0
        params = {}
        if date_from:
            params['created_at[from]'] = date_from.strftime('%Y-%m-%d')
        if date_to:
            params['created_at[to]'] = date_to.strftime('%Y-%m-%d')

        for page in self._paginated_get('/orders', params=params):
            for order in page:
                self._upsert_order(order)
                count += 1
        self.last_order_sync = fields.Datetime.now()
        return count

    def _upsert_order(self, order_data):
        salla_id = str(order_data.get('id', ''))
        ref = order_data.get('reference_id', '') or salla_id

        so = self.env['sale.order'].search(
            [('salla_id', '=', salla_id),
             ('salla_instance_id', '=', self.id)], limit=1)

        # Customer
        cust_data = order_data.get('customer', {}) or {}
        cust_salla_id = str(cust_data.get('id', '')) if cust_data.get('id') else ''
        partner = None
        if cust_salla_id:
            partner = self.env['res.partner'].search(
                [('salla_id', '=', cust_salla_id),
                 ('salla_instance_id', '=', self.id)], limit=1)
        if not partner and cust_data.get('email'):
            partner = self.env['res.partner'].search(
                [('email', '=', cust_data['email'])], limit=1)
        if not partner:
            partner = self._create_partner_from_order(cust_data)

        # Status
        status_data = order_data.get('status', {}) or {}
        salla_status_id = str(status_data.get('id', '')) if isinstance(status_data, dict) else ''
        salla_status_name = status_data.get('name', '') if isinstance(status_data, dict) else str(status_data)

        # Amounts
        amounts = order_data.get('amounts', {}) or {}
        total = amounts.get('total', {})
        total_amount = total.get('amount', 0.0) if isinstance(total, dict) else float(total or 0)

        order_date = order_data.get('date', {})
        if isinstance(order_date, dict):
            order_date = order_date.get('date', fields.Datetime.now())

        vals = {
            'partner_id': partner.id,
            'salla_id': salla_id,
            'salla_instance_id': self.id,
            'salla_reference': ref,
            'salla_status': salla_status_name,
            'client_order_ref': ref,
        }
        if order_date:
            try:
                vals['date_order'] = order_date[:19].replace('T', ' ')
            except Exception:
                pass

        if so:
            if so.state == 'draft':
                so.write(vals)
        else:
            so = self.env['sale.order'].create(vals)
            # Order lines
            self._create_order_lines(so, order_data.get('items', []) or [])

        return so

    def _create_partner_from_order(self, cust_data):
        """Create a minimal partner from order customer data."""
        vals = {
            'name': cust_data.get('name') or 'Salla Customer',
            'email': cust_data.get('email', ''),
            'phone': cust_data.get('mobile', '') or cust_data.get('phone', ''),
            'customer_rank': 1,
        }
        if cust_data.get('id'):
            vals['salla_id'] = str(cust_data['id'])
            vals['salla_instance_id'] = self.id
        return self.env['res.partner'].create(vals)

    def _create_order_lines(self, so, items):
        """Create sale.order.line records from Salla order items."""
        for item in items:
            prod_data = item.get('product', {}) or {}
            prod_salla_id = str(prod_data.get('id', ''))
            product = None
            if prod_salla_id:
                tmpl = self.env['product.template'].search(
                    [('salla_id', '=', prod_salla_id),
                     ('salla_instance_id', '=', self.id)], limit=1)
                if tmpl and tmpl.product_variant_ids:
                    product = tmpl.product_variant_ids[:1]
            if not product:
                # Fallback: search by name
                name = prod_data.get('name', '') or item.get('name', 'Salla Product')
                product = self.env['product.product'].search(
                    [('name', '=ilike', name)], limit=1)
                if not product:
                    product = self.env['product.product'].create({
                        'name': name,
                        'type': 'consu',
                    })

            unit_price = item.get('price', {})
            if isinstance(unit_price, dict):
                unit_price = unit_price.get('amount', 0.0)
            unit_price = float(unit_price or 0)

            self.env['sale.order.line'].create({
                'order_id': so.id,
                'product_id': product.id,
                'product_uom_qty': float(item.get('quantity', 1)),
                'price_unit': unit_price,
                'name': prod_data.get('name', '') or product.name,
            })

    # ══ EXPORT: Odoo → Salla ══════════════════════════════════════════════════

    # ── Export customer group ─────────────────────────────────────────────────

    def _export_partner_category(self, cat):
        if cat.salla_id:
            self._api_call('PUT', f'/customer-groups/{cat.salla_id}',
                           json={'name': cat.name})
        else:
            resp = self._api_call('POST', '/customer-groups',
                                  json={'name': cat.name})
            cat.salla_id = str(resp.get('data', {}).get('id', ''))

    # ── Export customer ───────────────────────────────────────────────────────

    def _export_partner(self, partner):
        payload = {
            'first_name': (partner.name or '').split()[0],
            'last_name': ' '.join((partner.name or '').split()[1:]) or '',
            'email': partner.email or '',
            'mobile': partner.phone or '',
        }
        if partner.salla_id:
            self._api_call('PUT', f'/customers/{partner.salla_id}', json=payload)
        else:
            resp = self._api_call('POST', '/customers', json=payload)
            partner.salla_id = str(resp.get('data', {}).get('id', ''))
            partner.salla_instance_id = self.id

    # ── Export category ───────────────────────────────────────────────────────

    def _export_category(self, cat):
        payload = {'name': cat.name}
        if cat.salla_id:
            self._api_call('PUT', f'/categories/{cat.salla_id}', json=payload)
        else:
            resp = self._api_call('POST', '/categories', json=payload)
            cat.salla_id = str(resp.get('data', {}).get('id', ''))
            cat.salla_instance_id = self.id

    # ── Export product ────────────────────────────────────────────────────────

    def _export_product(self, tmpl):
        payload = {
            'name': tmpl.name,
            'price': tmpl.list_price,
            'description': tmpl.description_sale or '',
            'sku': tmpl.default_code or '',
            'status': 'active',
        }
        if tmpl.salla_id:
            self._api_call('PUT', f'/products/{tmpl.salla_id}', json=payload)
        else:
            resp = self._api_call('POST', '/products', json=payload)
            tmpl.salla_id = str(resp.get('data', {}).get('id', ''))
            tmpl.salla_instance_id = self.id

    # ── Update order status ───────────────────────────────────────────────────

    def _update_order_status(self, so, status_id):
        if not so.salla_id:
            raise UserError(_('This order has no Salla ID.'))
        self._api_call('PUT', f'/orders/{so.salla_id}/status',
                       json={'status_id': status_id})

    # ── Cron: scheduled sync ──────────────────────────────────────────────────

    @api.model
    def _cron_sync_all(self):
        """Called by the scheduled action to sync all active instances."""
        for inst in self.search([('state', '=', 'connected')]):
            try:
                if inst.auto_sync_customers:
                    inst.action_import_customers()
                if inst.auto_sync_products:
                    inst.action_import_products()
                if inst.auto_sync_orders:
                    inst._import_orders(date_from=inst.last_order_sync)
            except Exception as e:
                _logger.error('Salla cron sync failed for instance %s: %s', inst.name, e)

    # ── Open import wizard ────────────────────────────────────────────────────

    def action_open_import_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import from Salla'),
            'res_model': 'salla.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_instance_id': self.id},
        }

    def action_open_scheduler_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Configure Scheduler'),
            'res_model': 'salla.scheduler.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_instance_id': self.id},
        }
