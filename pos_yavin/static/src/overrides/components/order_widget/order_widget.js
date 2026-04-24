/** @odoo-module */
/*
    Copyright 2026 Raphaël HUCK
    @author: Raphaël HUCK
    License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
*/

import { OrderWidget } from "@point_of_sale/app/generic_components/order_widget/order_widget";
import { patch } from "@web/core/utils/patch";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { filterYavinTipLines } from "@pos_yavin/overrides/models/models";

patch(OrderWidget.prototype, {
    setup() {
        super.setup(...arguments);
        this.pos = usePos();
    },
    /**
     * Filter lines to exclude tip lines if tips are disabled globally or yavin_display_tip is disabled
     */
    getFilteredLines() {
        const lines = this.props.lines || [];
        const orderForFilter =
            lines.length && lines[0].order
                ? lines[0].order
                : this.pos?.get_order?.();
        const normalizedLines = lines.map((line) => ({
            product: line.get_product ? line.get_product() : (line.product || null),
        }));
        const filteredLines = filterYavinTipLines(orderForFilter, this.pos, normalizedLines);
        return lines.filter((line, index) => filteredLines.includes(normalizedLines[index]));
    },
});

