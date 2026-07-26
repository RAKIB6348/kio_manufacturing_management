# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FinishedGoodVerification(models.Model):
    _name = 'kio.finished.good.verification'
    _description = 'Finished Good Verification'

    name = fields.Char(default='Finished Good Verification', required=True)
    selected_production_id = fields.Many2one(
        'mrp.production',
        string='Unverified Products Manufacturing Order',
        domain="[('state', '=', 'done'), ('finished_good_product_status', '=', 'unverified')]",
    )
    selected_serial_number_ids = fields.Many2many(
        'kio.mrp.product.serial.number',
        'kio_finished_good_verification_selected_serial_rel',
        'verification_id',
        'serial_id',
        string='Product List',
        compute='_compute_selected_serial_number_ids',
    )
    barcode_scan = fields.Char(string='Product Serial Number')
    scanned_line_ids = fields.One2many(
        'kio.finished.good.verification.line',
        'verification_id',
        string='Verified Products',
    )

    @api.depends('selected_production_id')
    def _compute_selected_serial_number_ids(self):
        for verification in self:
            verification.selected_serial_number_ids = verification.selected_production_id.product_serial_number_ids

    def action_open_workspace(self):
        self.ensure_one()
        self.write({
            'selected_production_id': False,
            'barcode_scan': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Verified Products'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('kio_manufacturing_management.view_finished_good_verification_form').id,
            'target': 'current',
        }

    def _verify_product_serial_number(self, serial_number):
        self.ensure_one()
        serial_number = (serial_number or '').strip()
        if not serial_number:
            raise UserError(_('Please scan or enter a product serial number.'))
        if not self.selected_production_id:
            raise UserError(_('Please select an unverified manufacturing order first.'))

        serial = self.env['kio.mrp.product.serial.number'].search([
            ('serial_number', '=', serial_number),
        ], limit=1)
        production = serial.production_id
        if not production:
            raise UserError(_('No product serial number found for %s.') % serial_number)
        if production != self.selected_production_id:
            raise UserError(_('Product serial number %s does not belong to the selected manufacturing order.') % serial_number)
        if production.state != 'done':
            raise UserError(_('Product serial number %s is not linked to a done manufacturing order.') % serial_number)
        if serial.is_verified:
            raise UserError(_('Product serial number %s is already verified.') % serial_number)

        production._post_finished_good_stock_for_serial(serial)
        serial.write({
            'is_verified': True,
            'verification_date': fields.Datetime.now(),
        })
        production._sync_finished_good_status_from_serials()
        line = self.env['kio.finished.good.verification.line'].search([
            ('verification_id', '=', self.id),
            ('serial_number_id', '=', serial.id),
        ], limit=1)
        if not line:
            self.env['kio.finished.good.verification.line'].create({
                'verification_id': self.id,
                'production_id': production.id,
                'serial_number_id': serial.id,
                'product_qty': 1.0,
            })

        return serial

    def action_scan_barcode(self):
        self.ensure_one()
        self._verify_product_serial_number(self.barcode_scan)
        self.barcode_scan = False
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('kio_manufacturing_management.view_finished_good_verification_form').id,
            'target': 'current',
        }

    def action_scan_barcode_from_scanner(self, serial_number):
        self.ensure_one()
        serial = self._verify_product_serial_number(serial_number)
        self.barcode_scan = False
        return {
            'serial_number': serial.serial_number,
            'product': serial.product_id.display_name,
        }


class FinishedGoodVerificationLine(models.Model):
    _name = 'kio.finished.good.verification.line'
    _description = 'Verified Finished Good Product'
    _order = 'scan_date desc, id desc'

    verification_id = fields.Many2one('kio.finished.good.verification', required=True, ondelete='cascade')
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', required=True, ondelete='cascade')
    serial_number_id = fields.Many2one('kio.mrp.product.serial.number', string='Product Serial Number', ondelete='set null')
    product_serial_number = fields.Char(related='serial_number_id.serial_number', string='Product Serial Number', store=True)
    scan_date = fields.Datetime(string='Scan Date', default=fields.Datetime.now, required=True)
    product_id = fields.Many2one(related='production_id.product_id', string='Product', store=True)
    date_start = fields.Datetime(related='production_id.date_start', string='Start', store=True)
    product_barcode = fields.Char(related='production_id.product_barcode', string='Product Barcode', store=True)
    product_qty = fields.Float(string='Quantity', default=1.0)
    company_id = fields.Many2one(related='production_id.company_id', string='Company', store=True)
    origin = fields.Char(related='production_id.origin', string='Source', store=True)
    components_availability = fields.Char(related='production_id.components_availability', string='Component Status')
    state = fields.Selection(related='production_id.state', string='State', store=True)
    finished_good_product_status = fields.Selection([
        ('unverified', 'Unverified'),
        ('verified', 'Verified'),
    ],
        compute='_compute_finished_good_product_status',
        string='Product Status',
        store=True,
    )

    @api.depends('serial_number_id.is_verified', 'production_id.finished_good_product_status')
    def _compute_finished_good_product_status(self):
        for line in self:
            if line.serial_number_id:
                line.finished_good_product_status = 'verified' if line.serial_number_id.is_verified else 'unverified'
            else:
                line.finished_good_product_status = line.production_id.finished_good_product_status
