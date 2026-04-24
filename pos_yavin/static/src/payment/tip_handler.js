/** @odoo-module */
/*
    Copyright 2026 Raphaël HUCK
    @author: Raphaël HUCK
    License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
*/

/**
 * Handler for Yavin payment tips.
 * Responsible for finding tip products and managing tip-related operations.
 */
export class YavinTipHandler {
    static _saveTipUpdate(env, model, method, args) {
        env.services.orm.silent.call(model, method, args).catch(() => {
            // Best-effort persistence: do not block POS flow on async sync issues.
        });
    }

    /**
     * Get the tip product, even if iface_tipproduct is disabled.
     * This method tries multiple strategies to find the tip product:
     * 1. Use pos.config.tip_product_id if configured
     * 2. Search for product with code "TIPS" in local database
     * 3. Request from server the default tip product (point_of_sale.product_product_tip)
     *
     * @param {Object} pos - The POS store instance
     * @param {Object} env - The Odoo environment with services
     * @returns {Promise<Object|null>} The tip product or null if not found
     */
    static async getTipProduct(pos, env) {
        // Strategy 1: Use configured tip_product_id if available
        if (pos.config.tip_product_id && pos.config.tip_product_id[0]) {
            const tipProduct = pos.db.get_product_by_id(pos.config.tip_product_id[0]);
            if (tipProduct) {
                return tipProduct;
            }
        }

        // Strategy 2: Search for product with code "TIPS" in local database
        // The POS database might have the product even if not configured
        const allProducts = pos.db.search_product("TIPS");
        if (allProducts && allProducts.length > 0) {
            // Find exact match by code
            const tipProduct = allProducts.find((product) => product.default_code === "TIPS");
            if (tipProduct) {
                return tipProduct;
            }
        }

        // Strategy 3: Request from server the default tip product
        // This is a fallback if the product is not in the local database
        try {
            const tipProductIds = await env.services.orm.silent.call(
                "product.product",
                "search",
                [[["default_code", "=", "TIPS"]]],
                { limit: 1 }
            );
            if (tipProductIds && tipProductIds.length > 0) {
                // Load the product into POS database
                await pos._addProducts(tipProductIds, false);
                return pos.db.get_product_by_id(tipProductIds[0]);
            }
        } catch {
            // Keep local fallback behavior when server-side lookup fails.
        }

        return null;
    }

    /**
     * Handle tip from Yavin payment terminal response.
     *
     * @param {Object} params - Parameters object
     * @param {Object} params.order - The POS order
     * @param {Object} params.pay_line - The payment line
     * @param {number} params.gift_amount - The tip amount from terminal
     * @param {Object} params.pos - The POS store instance
     * @param {Object} params.env - The Odoo environment with services
     * @param {Object} params.yavinPaymentMethod - The Yavin payment method
     * @returns {Promise<void>}
     */
    static async handleTipFromResponse({ order, pay_line, gift_amount, pos, env, yavinPaymentMethod }) {
        // Completely ignore tip if tips are disabled globally in POS config
        if (!pos.config.iface_tipproduct) {
            return;
        }

        // Check if Yavin tip display is enabled
        const displayTip = yavinPaymentMethod?.yavin_display_tip !== false;

        if (displayTip) {
            // If yavin_display_tip = true: create a tip product line
            // (visible in order lines + included in total for accounting)
            const tipProduct = await this.getTipProduct(pos, env);
            if (tipProduct) {
                // Temporarily allow order modification to add tip
                const was_finalized = order.finalized;
                order.finalized = false;
                // Add tip to order (creates a product line)
                // set_tip() expects the full accumulated tip amount.
                // When split payments each include a tip, we must accumulate.
                order.set_tip((order.tip_amount || 0) + gift_amount);
                order.finalized = was_finalized;

                // IMPORTANT: Update payment amount to include tip
                // The tip is already included in the payment made on the terminal
                if (pay_line.set_amount) {
                    pay_line.set_amount(pay_line.amount + gift_amount);
                } else {
                    pay_line.amount += gift_amount;
                }

                // Save tip on server if order is already synchronized
                const serverId = pos.validated_orders_name_server_id_map[order.name];
                if (serverId) {
                    const tip_line = order.selected_orderline;
                    if (tip_line) {
                        // Save tip asynchronously without blocking
                        this._saveTipUpdate(env, "pos.order", "set_tip", [
                            serverId,
                            tip_line.export_as_JSON(),
                        ]);
                    }
                }
            }
        } else {
            // If yavin_display_tip = false: do not create product line
            // Tip is NOT included in payment amount nor in total
            // Payment amount remains "amount" (without giftAmount)
            // Note: Terminal charged amount + giftAmount, but we only record amount
            // Store tip in tip_amount for reference (but not accounted)
            order.tip_amount = gift_amount;
            order.is_tipped = true;

            // Save tip on server if order is already synchronized
            const serverId = pos.validated_orders_name_server_id_map[order.name];
            if (serverId) {
                // Update tip_amount without creating product line
                this._saveTipUpdate(env, "pos.order", "write", [[serverId], {
                        tip_amount: gift_amount,
                        is_tipped: true,
                    }]);
            }
        }
    }
}

