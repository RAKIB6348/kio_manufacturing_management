# -*- coding: utf-8 -*-

import re

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    state = fields.Selection([
        ('draft', 'Draft'),
        ('request_approval_mo', 'Request for Approval MO'),
        ('rejected', 'Rejected'),
        ('confirmed', 'Confirmed'),
        ('progress', 'In Progress'),
        ('to_close', 'To Close'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], string='State',
        compute='_compute_state', copy=False, index=True, readonly=True,
        store=True, tracking=True,
        help=" * Draft: The MO is not confirmed yet.\n"
             " * Request for Approval MO: The MO is waiting for approval.\n"
             " * Rejected: The MO approval request was rejected.\n"
             " * Confirmed: The MO is confirmed, the stock rules and the reordering of the components are triggered.\n"
             " * In Progress: The production has started (on the MO or on the WO).\n"
             " * To Close: The production is done, the MO has to be closed.\n"
             " * Done: The MO is closed, the stock moves are posted.\n"
             " * Cancelled: The MO has been cancelled, can't be confirmed anymore.")
    kio_show_factory_mo_buttons = fields.Boolean(compute='_compute_kio_mo_button_visibility')
    product_barcode = fields.Char(string='Product Barcode', copy=False, index=True)
    product_serial_number_ids = fields.One2many(
        'kio.mrp.product.serial.number',
        'production_id',
        string='Product Serial Numbers',
        copy=False,
    )
    has_product_serial_numbers = fields.Boolean(compute='_compute_has_product_serial_numbers')
    finished_good_stock_posted = fields.Boolean(string='Finished Good Stock Posted', copy=False)
    finished_good_product_status = fields.Selection([
        ('unverified', 'Unverified'),
        ('verified', 'Verified'),
    ], string='Product Status', default='unverified', required=True, copy=False)

    def _has_kio_group(self, group_xmlid):
        return self.env.user.has_group(f'kio_purchase_management.{group_xmlid}')

    def _is_kio_admin(self):
        return self._has_kio_group('group_kio_purchase_admin')

    def _can_request_mo_approval(self):
        return self._has_kio_group('group_kio_purchase_manager') or self._is_kio_admin()

    def _can_confirm_or_reject_mo(self):
        return self._has_kio_group('group_kio_purchase_ceo') or self._is_kio_admin()

    def _can_use_factory_mo_buttons(self):
        is_admin = self._is_kio_admin()
        is_head_of_factory = self._has_kio_group('group_kio_purchase_head_of_factory')
        is_coo = self._has_kio_group('group_kio_purchase_ceo')
        return is_admin or (is_head_of_factory and not is_coo)

    def _compute_kio_mo_button_visibility(self):
        can_show = self._can_use_factory_mo_buttons()
        for production in self:
            production.kio_show_factory_mo_buttons = can_show

    def _compute_has_product_serial_numbers(self):
        for production in self:
            production.has_product_serial_numbers = bool(production.product_serial_number_ids)

    def action_request_approval_mo(self):
        if not self._can_request_mo_approval():
            raise UserError(_('Only Manager or Admin users can request MO approval.'))
        for production in self:
            if production.state != 'draft':
                raise UserError(_('Only draft manufacturing orders can be submitted for approval.'))
            production.write({'state': 'request_approval_mo'})
            production.message_post(body=_('Manufacturing order approval requested.'))
        return True

    def action_reject_approval_mo(self):
        if not self._can_confirm_or_reject_mo():
            raise UserError(_('Only COO or Admin users can reject MO approval requests.'))
        for production in self:
            if production.state != 'request_approval_mo':
                raise UserError(_('Only manufacturing orders waiting for approval can be rejected.'))
            production.write({'state': 'rejected'})
            production.message_post(body=_('Manufacturing order approval request rejected.'))
        return True

    def action_confirm(self):
        if self.filtered(lambda production: production.state in ('draft', 'request_approval_mo')) and not self._can_confirm_or_reject_mo():
            raise UserError(_('Only COO or Admin users can confirm manufacturing orders.'))

        approval_orders = self.filtered(lambda production: production.state == 'request_approval_mo')
        if approval_orders:
            approval_orders.write({'state': 'draft'})
            approval_orders.message_post(body=_('Manufacturing order approval confirmed.'))
        return super().action_confirm()

    def button_mark_done(self):
        if not self._can_use_factory_mo_buttons():
            raise UserError(_('Only Head of Factory or Admin users can produce manufacturing orders.'))
        for production in self:
            production.workorder_ids.filtered(lambda workorder: workorder.state not in ('done', 'cancel')).button_finish()
            production.write({
                'date_finished': fields.Datetime.now(),
                'priority': '0',
                'is_locked': True,
                'state': 'done',
                'finished_good_product_status': 'unverified',
                'finished_good_stock_posted': False,
            })
            production.message_post(body=_('Manufacturing order completed. Finished good stock will be posted after barcode verification.'))
        return True

    def action_generate_product_barcode(self):
        for production in self:
            if production.state != 'done':
                raise UserError(_('Product barcode can only be generated for done manufacturing orders.'))
            production.product_barcode = production._generate_unique_product_barcode()
        return True

    def _generate_unique_product_barcode(self):
        MrpProduction = self.env['mrp.production']
        ProductTemplate = self.env['product.template']
        while True:
            barcode = ProductTemplate._generate_barcode()
            if not MrpProduction.search_count([('product_barcode', '=', barcode)]):
                return barcode

    def action_generate_product_serial_numbers(self):
        SerialNumber = self.env['kio.mrp.product.serial.number']
        for production in self:
            if production.state != 'done':
                raise UserError(_('Product serial numbers can only be generated for done manufacturing orders.'))

            quantity = production.qty_producing
            if float_compare(quantity, 0.0, precision_rounding=production.product_uom_id.rounding) <= 0:
                raise UserError(_('Produced Product quantity must be greater then 0.'))

            serial_count = int(quantity)
            if float_compare(
                quantity,
                serial_count,
                precision_rounding=production.product_uom_id.rounding,
            ) != 0:
                raise UserError(_('Product quantity must be a positive whole number to generate serial numbers.'))
            if production.product_serial_number_ids:
                raise UserError(_('Product serial numbers are already generated for this manufacturing order.'))

            prefix = production._get_product_serial_number_prefix()
            next_sequence = production._get_next_product_serial_number_sequence(prefix)
            SerialNumber.create([
                {
                    'production_id': production.id,
                    'source': 'manufacturing',
                    'product_id': production.product_id.id,
                    'sequence_number': index,
                    'serial_number': '%s%s' % (prefix, str(serial_sequence).zfill(4)),
                }
                for index, serial_sequence in enumerate(
                    range(next_sequence, next_sequence + serial_count),
                    start=1,
                )
            ])
        return True

    def _get_next_product_serial_number_sequence(self, prefix):
        SerialNumber = self.env['kio.mrp.product.serial.number']
        max_sequence = 0
        serials = SerialNumber.search([('serial_number', '=like', '%s%%' % prefix)])
        for serial in serials:
            suffix = (serial.serial_number or '')[len(prefix):]
            if suffix.isdigit():
                max_sequence = max(max_sequence, int(suffix))
        return max_sequence + 1

    def action_print_product_serial_number_labels(self):
        self.ensure_one()
        if not self.product_serial_number_ids:
            raise UserError(_('Please generate product serial numbers before printing labels.'))
        return self.env.ref(
            'kio_manufacturing_management.action_report_product_serial_number_labels'
        ).report_action(self.product_serial_number_ids)

    def _get_product_serial_number_prefix(self):
        self.ensure_one()
        product = self.product_id
        category_code = self._normalize_serial_part(product.categ_id.code)
        product_code = self._normalize_serial_part(product.default_code)
        size = self._get_product_attribute_value('size') or self._infer_product_size_from_variant_values()
        color_code_value = self._get_product_attribute_value_code('color')
        size_code = self._normalize_serial_part(size)
        color_code = self._normalize_serial_part(color_code_value).upper()

        missing = []
        if not category_code:
            missing.append(_('product category code'))
        if not product_code:
            missing.append(_('product code'))
        if not size_code:
            missing.append(_('product size'))
        if not color_code:
            missing.append(_('product color value code'))
        if missing:
            raise UserError(_('Please set %s before generating product serial numbers.') % ', '.join(missing))

        return '%s%s%s%s' % (category_code, product_code, size_code, color_code)

    def _get_product_attribute_value(self, attribute_name):
        self.ensure_one()
        attribute_name = attribute_name.lower()
        values = self.product_id.product_template_attribute_value_ids or self.product_id.product_template_variant_value_ids
        for value in values:
            if (value.attribute_id.name or '').strip().lower() == attribute_name:
                return value.name
        return ''

    def _get_product_attribute_value_code(self, attribute_name):
        self.ensure_one()
        attribute_name = attribute_name.lower()
        values = self.product_id.product_template_attribute_value_ids or self.product_id.product_template_variant_value_ids
        for value in values:
            if (value.attribute_id.name or '').strip().lower() == attribute_name:
                return value.value_code or ''
        return ''

    def _get_product_variant_value_names(self):
        self.ensure_one()
        values = self.product_id.product_template_attribute_value_ids or self.product_id.product_template_variant_value_ids
        value_names = [
            (value.name or '').strip()
            for value in values.sorted(
                key=lambda variant_value: (
                    variant_value.attribute_id.sequence,
                    variant_value.attribute_id.id,
                    variant_value.product_attribute_value_id.sequence,
                    variant_value.product_attribute_value_id.id,
                )
            )
            if (value.name or '').strip()
        ]
        return value_names or self._get_product_variant_value_names_from_display_name()

    def _get_product_variant_value_names_from_display_name(self):
        self.ensure_one()
        display_name = self.product_id.with_context(display_default_code=False).display_name or ''
        matches = re.findall(r'\(([^()]*)\)', display_name)
        if not matches:
            return []
        return [
            value.strip()
            for value in matches[-1].split(',')
            if value.strip()
        ]

    def _infer_product_size_from_variant_values(self):
        self.ensure_one()
        for value_name in self._get_product_variant_value_names():
            normalized = self._normalize_serial_part(value_name)
            if normalized.isdigit():
                return value_name
        return ''

    def _infer_product_color_from_variant_values(self, size):
        self.ensure_one()
        normalized_size = self._normalize_serial_part(size)
        for value_name in self._get_product_variant_value_names():
            normalized = self._normalize_serial_part(value_name)
            if normalized and normalized != normalized_size and not normalized.isdigit():
                return value_name
        return ''

    @staticmethod
    def _normalize_serial_part(value):
        return ''.join((value or '').split())

    def action_verify_finished_good_from_barcode(self):
        for production in self:
            if production.state != 'done':
                raise UserError(_('Only done manufacturing orders can be verified.'))
            if not production.product_barcode:
                raise UserError(_('Please add a product barcode before verification.'))
            production._post_finished_good_stock_on_verification()
            production.write({'finished_good_product_status': 'verified'})
            production.message_post(body=_('Finished good product verified by barcode scan.'))
        return True

    def _get_finished_good_stock_locations(self):
        self.ensure_one()
        reference_move = self.move_finished_ids.filtered(lambda move: move.product_id == self.product_id)[:1]
        source_location = (
            reference_move.location_id
            or self.production_location_id
            or self.product_id.with_company(self.company_id).property_stock_production
        )
        dest_location = reference_move.location_dest_id or self.location_dest_id
        if not source_location or not dest_location:
            raise UserError(_('Unable to post finished good stock for %s. Please check source and destination locations.') % self.name)
        return source_location, dest_location

    def _post_finished_good_stock_for_serial(self, serial):
        StockMove = self.env['stock.move'].sudo()
        for production in self:
            if serial.production_id != production:
                raise UserError(_('Product serial number %s does not belong to manufacturing order %s.') % (serial.serial_number, production.name))

            source_location, dest_location = production._get_finished_good_stock_locations()
            quantity = production.product_uom_id._compute_quantity(1.0, production.product_uom_id)
            stock_move = StockMove.create({
                'name': _('%s finished good serial verification %s') % (production.name, serial.serial_number),
                'origin': production.name,
                'company_id': production.company_id.id,
                'product_id': production.product_id.id,
                'product_uom': production.product_uom_id.id,
                'product_uom_qty': quantity,
                'quantity': quantity,
                'location_id': source_location.id,
                'location_dest_id': dest_location.id,
                'raw_material_production_id': False,
                'production_id': production.id,
                'picked': True,
            })
            stock_move = stock_move._action_confirm(merge=False)
            stock_move.quantity = quantity
            stock_move.picked = True
            stock_move._action_done(cancel_backorder=True)
            production.message_post(body=_('Finished good product serial %s verified and added to stock.') % serial.serial_number)

    def _sync_finished_good_status_from_serials(self):
        for production in self:
            serials = production.product_serial_number_ids
            if serials and all(serials.mapped('is_verified')):
                production.write({
                    'finished_good_product_status': 'verified',
                    'finished_good_stock_posted': True,
                })
            else:
                production.write({
                    'finished_good_product_status': 'unverified',
                    'finished_good_stock_posted': False,
                })

    def _post_finished_good_stock_on_verification(self):
        StockMove = self.env['stock.move'].sudo()
        for production in self:
            if production.finished_good_stock_posted:
                continue

            source_location, dest_location = production._get_finished_good_stock_locations()
            quantity = production.product_qty or production.qty_producing
            if not source_location or not dest_location or quantity <= 0:
                raise UserError(_('Unable to post finished good stock for %s. Please check source, destination, and quantity.') % production.name)

            stock_move = StockMove.create({
                'name': _('%s finished good verification') % production.name,
                'origin': production.name,
                'company_id': production.company_id.id,
                'product_id': production.product_id.id,
                'product_uom': production.product_uom_id.id,
                'product_uom_qty': quantity,
                'quantity': quantity,
                'location_id': source_location.id,
                'location_dest_id': dest_location.id,
                'raw_material_production_id': False,
                'production_id': production.id,
                'picked': True,
            })
            stock_move = stock_move._action_confirm(merge=False)
            stock_move.quantity = quantity
            stock_move.picked = True
            stock_move._action_done(cancel_backorder=True)
            production.finished_good_stock_posted = True
