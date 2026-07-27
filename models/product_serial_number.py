# -*- coding: utf-8 -*-

from odoo import api, fields, models


class KioMrpProductSerialNumber(models.Model):
    _name = 'kio.mrp.product.serial.number'
    _description = 'KIO Manufacturing Product Serial Number'
    _order = 'production_id, sequence_number'

    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        ondelete='cascade',
        index=True,
    )
    source = fields.Selection(
        [
            ('manufacturing', 'Manufacturing'),
            ('on_hand', 'On Hand Stock'),
        ],
        string='Source Type',
        default='manufacturing',
        copy=False,
    )
    sequence_number = fields.Integer(string='Sequence', required=True)
    serial_number = fields.Char(string='Serial Number Barcode', required=True, index=True)
    is_verified = fields.Boolean(string='Verified', copy=False)
    verification_status = fields.Selection(
        [
            ('unverified', 'Unverified'),
            ('verified', 'Verified'),
        ],
        string='Verified',
        compute='_compute_verification_status',
        store=True,
    )
    sold_status = fields.Selection(
        [
            ('not_available', 'Not Available'),
            ('available', 'Available'),
            ('sold', 'Sold'),
        ],
        string='Sold Status',
        compute='_compute_sold_status',
    )
    verification_date = fields.Datetime(string='Verification Date', copy=False)
    product_tmpl_id = fields.Many2one(
        related='product_id.product_tmpl_id',
        string='Product Template',
        store=True,
        readonly=True,
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        index=True,
    )
    date_start = fields.Datetime(
        related='production_id.date_start',
        string='Start',
        store=True,
        readonly=True,
    )
    scan_date = fields.Datetime(
        related='verification_date',
        string='Scan Date',
        store=True,
        readonly=True,
    )
    product_default_code = fields.Char(
        related='product_id.default_code',
        string='Internal Reference',
        store=True,
        readonly=True,
    )
    product_variant_values = fields.Char(
        string='Variant Values',
        compute='_compute_product_variant_values',
        store=True,
    )
    company_id = fields.Many2one(
        related='production_id.company_id',
        string='Company',
        store=True,
        readonly=True,
    )
    origin = fields.Char(
        related='production_id.origin',
        string='Source',
        store=True,
        readonly=True,
    )
    components_availability = fields.Char(
        related='production_id.components_availability',
        string='Component Status',
        readonly=True,
    )
    product_qty = fields.Float(string='Quantity', compute='_compute_product_qty', store=True)
    product_on_hand_qty = fields.Float(
        string='On Hand',
        compute='_compute_product_on_hand_qty',
        store=True,
    )
    state = fields.Selection(
        related='production_id.state',
        string='State',
        store=True,
        readonly=True,
    )

    @api.depends('product_id.product_template_attribute_value_ids')
    def _compute_product_variant_values(self):
        for serial in self:
            values = serial.product_id.product_template_attribute_value_ids
            serial.product_variant_values = ', '.join(values.mapped('display_name'))

    @api.depends('is_verified')
    def _compute_verification_status(self):
        for serial in self:
            serial.verification_status = 'verified' if serial.is_verified else 'unverified'

    def _compute_sold_status(self):
        has_pos_sold_field = 'is_sold' in self._fields
        for serial in self:
            if has_pos_sold_field and serial.is_sold:
                serial.sold_status = 'sold'
            elif serial.is_verified:
                serial.sold_status = 'available'
            else:
                serial.sold_status = 'not_available'

    @api.depends('serial_number')
    def _compute_product_qty(self):
        for serial in self:
            serial.product_qty = 1.0

    @api.depends('is_verified')
    def _compute_product_on_hand_qty(self):
        for serial in self:
            serial.product_on_hand_qty = 1.0 if serial.is_verified else 0.0

    def _get_label_product_name(self):
        self.ensure_one()
        product = self.product_id
        if not product:
            return ''
        return product.product_tmpl_id.name or product.name or ''

    def _get_label_product_display_name(self):
        self.ensure_one()
        product = self.product_id
        if not product:
            return ''
        return product.with_context(display_default_code=False).display_name or product.display_name or ''

    def _get_label_product_attribute(self, attribute_name):
        self.ensure_one()
        product = self.product_id
        if not product:
            return ''
        attribute_name = (attribute_name or '').strip().lower()
        values = product.product_template_attribute_value_ids or product.product_template_variant_value_ids
        for value in values:
            if (value.attribute_id.name or '').strip().lower() == attribute_name:
                return value.name or ''
        return ''

    def _get_label_product_size(self):
        return self._get_label_product_attribute('Size')

    def _get_label_product_color(self):
        return self._get_label_product_attribute('Color')

    def _get_label_product_code(self):
        self.ensure_one()
        return self.product_id.default_code or ''

    def _get_label_product_mrp(self):
        self.ensure_one()
        product = self.product_id
        if not product:
            return ''
        currency = product.currency_id
        decimal_places = int(getattr(currency, 'decimal_places', 2) or 2) if currency else 2
        return f'{product.lst_price or 0.0:.{decimal_places}f}'

    def _get_label_barcode_value(self):
        self.ensure_one()
        value = getattr(self, 'barcode', False) or self.serial_number or ''
        return str(value).replace('\r', '').replace('\n', '').replace('\t', '').strip()

    def _get_label_product_image(self):
        self.ensure_one()
        product = self.product_id
        if not product:
            return False
        return product.image_1920 or product.product_tmpl_id.image_1920 or False
