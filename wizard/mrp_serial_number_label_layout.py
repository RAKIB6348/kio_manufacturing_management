# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MrpSerialNumberLabelLayout(models.TransientModel):
    _name = 'mrp.serial.number.label.layout'
    _description = 'Serial Number Label Layout'

    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        readonly=True,
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        readonly=True,
    )
    print_quantity = fields.Selection(
        [
            ('operation', 'Operation Quantities'),
            ('custom', 'Custom Quantity'),
        ],
        string='Quantity to Print',
        default='operation',
        required=True,
    )
    custom_quantity = fields.Integer(string='Custom Quantity', default=1)
    print_format = fields.Selection(
        [
            ('4cm_3_5cm_mrp', '4 cm × 3.5 cm with MRP'),
        ],
        string='Format',
        default='4cm_3_5cm_mrp',
        required=True,
    )
    extra_content = fields.Html(string='Extra Content')

    @api.constrains('production_id', 'product_tmpl_id')
    def _check_single_label_source(self):
        for wizard in self:
            has_production = bool(wizard.production_id)
            has_product = bool(wizard.product_tmpl_id)
            if has_production == has_product:
                raise ValidationError(_(
                    'Choose exactly one source for serial number label printing.'
                ))

    def fields_get(self, allfields=None, attributes=None):
        fields_description = super().fields_get(allfields=allfields, attributes=attributes)
        is_product_source = (
            self.env.context.get('active_model') == 'product.template'
            or bool(self.env.context.get('default_product_tmpl_id'))
        )
        if is_product_source and 'print_quantity' in fields_description:
            fields_description['print_quantity']['selection'] = [
                ('operation', _('Available Serial Numbers')),
                ('custom', _('Custom Quantity')),
            ]
        return fields_description

    def _get_production(self):
        self.ensure_one()
        production = self.production_id
        if not production:
            active_model = self.env.context.get('active_model')
            active_id = self.env.context.get('active_id')
            if active_model == 'mrp.production' and active_id:
                production = self.env['mrp.production'].browse(active_id)
        if not production:
            raise UserError(_('No Manufacturing Order was found for this label layout.'))
        production.ensure_one()
        return production

    def _get_product_template(self):
        self.ensure_one()
        product_tmpl = self.product_tmpl_id
        if not product_tmpl:
            active_model = self.env.context.get('active_model')
            active_id = self.env.context.get('active_id')
            if active_model == 'product.template' and active_id:
                product_tmpl = self.env['product.template'].browse(active_id)
        if not product_tmpl:
            raise UserError(_('No product was found for this label layout.'))
        product_tmpl.ensure_one()
        return product_tmpl

    def _get_unique_serial_numbers(self, serials):
        seen_serial_numbers = set()
        serial_ids = []
        for serial in serials:
            serial_number = serial.serial_number or ''
            if serial_number in seen_serial_numbers:
                continue
            seen_serial_numbers.add(serial_number)
            serial_ids.append(serial.id)
        return serials.browse(serial_ids)

    def _get_available_serial_numbers(self, production):
        serials = self.env['kio.mrp.product.serial.number'].search(
            [('production_id', '=', production.id)],
            order='sequence_number, id',
        )
        return self._get_unique_serial_numbers(serials)

    def _get_available_product_serial_numbers(self, product_tmpl):
        serials = self.env['kio.mrp.product.serial.number'].search(
            [('product_tmpl_id', '=', product_tmpl.id)],
            order='production_id, sequence_number, id',
        )
        return self._get_unique_serial_numbers(serials)

    def _get_source_serial_numbers(self):
        self.ensure_one()
        if self.production_id:
            production = self._get_production()
            serials = self._get_available_serial_numbers(production)
            if not serials:
                raise UserError(_('No serial numbers are available for this Manufacturing Order.'))
            return serials, _('Manufacturing Order')

        product_tmpl = self._get_product_template()
        serials = self._get_available_product_serial_numbers(product_tmpl)
        if not serials:
            raise UserError(_('No serial numbers are available for this product.'))
        return serials, _('product')

    def _get_serial_numbers_to_print(self):
        self.ensure_one()
        serials, source_name = self._get_source_serial_numbers()

        if self.print_quantity == 'custom':
            if self.custom_quantity <= 0:
                raise ValidationError(_('Custom Quantity must be greater than zero.'))
            if self.custom_quantity > len(serials):
                if self.product_tmpl_id:
                    raise ValidationError(_(
                        'Only %s serial numbers are available for this product.'
                    ) % len(serials))
                raise ValidationError(_(
                    'Only %s serial numbers are available for this %s.'
                ) % (len(serials), source_name))
            return serials[:self.custom_quantity]

        return serials

    def action_confirm_print(self):
        self.ensure_one()
        serials = self._get_serial_numbers_to_print()
        report_action = self.env.ref(
            'kio_manufacturing_management.action_report_product_serial_number_labels'
        ).report_action(serials)
        report_action.update({'close_on_report_download': True})
        return report_action
