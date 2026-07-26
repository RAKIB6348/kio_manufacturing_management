# -*- coding: utf-8 -*-

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    kio_product_serial_number_ids = fields.One2many(
        'kio.mrp.product.serial.number',
        'product_tmpl_id',
        string='Product Serial Number Barcodes',
        readonly=True,
    )
    has_product_serial_numbers = fields.Boolean(compute='_compute_has_product_serial_numbers')

    def _compute_has_product_serial_numbers(self):
        for template in self:
            template.has_product_serial_numbers = bool(template.kio_product_serial_number_ids)

    def action_print_product_serial_number_labels(self):
        self.ensure_one()
        serials = self.kio_product_serial_number_ids
        if not serials:
            raise UserError(_('Please generate product serial numbers before printing labels.'))
        return self.env.ref(
            'kio_manufacturing_management.action_report_product_serial_number_labels'
        ).report_action(serials)

    def action_generate_product_serial_numbers_from_on_hand(self):
        SerialNumber = self.env['kio.mrp.product.serial.number']
        for template in self:
            products = template.product_variant_ids.filtered(lambda product: product.qty_available > 0)
            if not products:
                raise UserError(_('No on hand quantity found for %s.') % template.display_name)

            serial_values = []
            for product in products:
                quantity = product.qty_available
                serial_count = int(quantity)
                if float_compare(quantity, serial_count, precision_rounding=product.uom_id.rounding) != 0:
                    raise UserError(_('On hand quantity for %s must be a whole number to generate serial numbers.') % product.display_name)

                existing_count = SerialNumber.search_count([('product_id', '=', product.id)])
                missing_count = serial_count - existing_count
                if missing_count <= 0:
                    continue

                prefix = template._get_kio_product_serial_number_prefix(product)
                next_sequence = template._get_next_kio_product_serial_number_sequence(prefix)
                serial_values.extend([
                    {
                        'source': 'on_hand',
                        'product_id': product.id,
                        'sequence_number': serial_sequence,
                        'serial_number': '%s%s' % (prefix, str(serial_sequence).zfill(4)),
                        'is_verified': True,
                        'verification_date': fields.Datetime.now(),
                    }
                    for serial_sequence in range(next_sequence, next_sequence + missing_count)
                ])

            if serial_values:
                SerialNumber.create(serial_values)
        return True

    def _get_next_kio_product_serial_number_sequence(self, prefix):
        max_sequence = 0
        serials = self.env['kio.mrp.product.serial.number'].search([('serial_number', '=like', '%s%%' % prefix)])
        for serial in serials:
            suffix = (serial.serial_number or '')[len(prefix):]
            if suffix.isdigit():
                max_sequence = max(max_sequence, int(suffix))
        return max_sequence + 1

    def _get_kio_product_serial_number_prefix(self, product):
        category_code = self._normalize_kio_serial_part(product.categ_id.code)
        product_code = self._normalize_kio_serial_part(product.default_code)
        size = self._get_kio_product_attribute_value(product, 'size') or self._infer_kio_product_size_from_variant_values(product)
        color_code_value = self._get_kio_product_attribute_value_code(product, 'color')
        size_code = self._normalize_kio_serial_part(size)
        color_code = self._normalize_kio_serial_part(color_code_value).upper()

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
            raise UserError(_('Please set %s before generating product serial numbers for %s.') % (', '.join(missing), product.display_name))

        return '%s%s%s%s' % (category_code, product_code, size_code, color_code)

    def _get_kio_product_attribute_value(self, product, attribute_name):
        attribute_name = attribute_name.lower()
        values = product.product_template_attribute_value_ids or product.product_template_variant_value_ids
        for value in values:
            if (value.attribute_id.name or '').strip().lower() == attribute_name:
                return value.name
        return ''

    def _get_kio_product_attribute_value_code(self, product, attribute_name):
        attribute_name = attribute_name.lower()
        values = product.product_template_attribute_value_ids or product.product_template_variant_value_ids
        for value in values:
            if (value.attribute_id.name or '').strip().lower() == attribute_name:
                return value.value_code or ''
        return ''

    def _get_kio_product_variant_value_names(self, product):
        values = product.product_template_attribute_value_ids or product.product_template_variant_value_ids
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
        return value_names

    def _infer_kio_product_size_from_variant_values(self, product):
        for value_name in self._get_kio_product_variant_value_names(product):
            normalized = self._normalize_kio_serial_part(value_name)
            if normalized.isdigit():
                return value_name
        return ''

    def _infer_kio_product_color_from_variant_values(self, product, size):
        normalized_size = self._normalize_kio_serial_part(size)
        for value_name in self._get_kio_product_variant_value_names(product):
            normalized = self._normalize_kio_serial_part(value_name)
            if normalized and normalized != normalized_size and not normalized.isdigit():
                return value_name
        return ''

    @staticmethod
    def _normalize_kio_serial_part(value):
        return ''.join((value or '').split())
