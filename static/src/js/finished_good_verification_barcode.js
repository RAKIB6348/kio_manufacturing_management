/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { formView } from "@web/views/form/form_view";
import { FormController } from "@web/views/form/form_controller";
import { onMounted, onWillUnmount } from "@odoo/owl";

function isBarcodeScanField(element) {
    return Boolean(element?.closest?.(".o_field_widget[name='barcode_scan']"));
}

export class FinishedGoodVerificationBarcodeFormController extends FormController {
    setup() {
        super.setup();
        this.barcode = useService("barcode");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.scanBuffer = "";
        this.scanTarget = null;
        this.scanInitialValue = null;
        this.scanTimeout = null;
        this.isProcessingScan = false;
        this.maxTimeBetweenKeysInMs = 100;
        this.editableBarcodeKeydown = this.onEditableBarcodeKeydown.bind(this);

        useBus(this.barcode.bus, "barcode_scanned", this.onBarcodeScanned.bind(this));
        onMounted(() => {
            document.body.addEventListener("keydown", this.editableBarcodeKeydown, true);
        });
        onWillUnmount(() => {
            document.body.removeEventListener("keydown", this.editableBarcodeKeydown, true);
            clearTimeout(this.scanTimeout);
        });
    }

    resetEditableBarcodeBuffer() {
        this.scanBuffer = "";
        this.scanTarget = null;
        this.scanInitialValue = null;
        clearTimeout(this.scanTimeout);
        this.scanTimeout = null;
    }

    restoreEditableTarget() {
        if (this.scanTarget && "value" in this.scanTarget && this.scanInitialValue !== null) {
            this.scanTarget.value = this.scanInitialValue;
            this.scanTarget.dispatchEvent(new Event("input", { bubbles: true }));
        }
    }

    focusScanInput() {
        setTimeout(() => {
            const input = document.querySelector(
                ".kio_finished_good_verification_form .o_field_widget[name='barcode_scan'] input"
            );
            input?.focus();
            input?.select?.();
        }, 0);
    }

    onEditableBarcodeKeydown(ev) {
        if (!isBarcodeScanField(ev.target) || !ev.key || ev.metaKey) {
            return;
        }

        const isEndCharacter = ev.key === "Enter" || ev.key === "Tab";
        const isSpecialKey = !["Control", "Alt", "Shift"].includes(ev.key) && ev.key.length > 1;
        if (isSpecialKey && !isEndCharacter) {
            this.resetEditableBarcodeBuffer();
            return;
        }

        if (!this.scanBuffer) {
            this.scanTarget = ev.target;
            this.scanInitialValue = "value" in ev.target ? ev.target.value : null;
        }

        clearTimeout(this.scanTimeout);
        if (isEndCharacter) {
            const barcode = this.scanBuffer.replace(/Alt|Shift|Control/g, "");
            if (barcode.length >= 3) {
                ev.preventDefault();
                ev.stopPropagation();
                this.restoreEditableTarget();
                this.onBarcodeScanned({ detail: { barcode } });
            }
            this.resetEditableBarcodeBuffer();
            return;
        }

        this.scanBuffer += ev.key;
        this.scanTimeout = setTimeout(
            () => this.resetEditableBarcodeBuffer(),
            this.maxTimeBetweenKeysInMs
        );
    }

    async onBarcodeScanned(ev) {
        const barcode = (ev.detail.barcode || "").trim();
        const record = this.model.root;
        if (
            !barcode ||
            this.isProcessingScan ||
            this.props.resModel !== "kio.finished.good.verification" ||
            !record?.resId
        ) {
            return;
        }

        this.isProcessingScan = true;
        try {
            if (record.save && !(await record.save())) {
                return;
            }
            const result = await this.orm.call(
                "kio.finished.good.verification",
                "action_scan_barcode_from_scanner",
                [[record.resId], barcode],
                { context: this.props.context }
            );
            await record.load();
            this.render(true);
            this.notification.add(
                _t("%s verified").replace("%s", result.serial_number),
                {
                    title: _t("Barcode scanned"),
                    type: "success",
                }
            );
        } catch (error) {
            this.notification.add(error.message || _t("Unable to verify product serial number."), {
                title: _t("Barcode scan failed"),
                type: "danger",
            });
        } finally {
            this.isProcessingScan = false;
            this.focusScanInput();
        }
    }
}

export const finishedGoodVerificationBarcodeFormView = {
    ...formView,
    Controller: FinishedGoodVerificationBarcodeFormController,
};

registry.category("views").add(
    "kio_finished_good_verification_barcode_form",
    finishedGoodVerificationBarcodeFormView
);
