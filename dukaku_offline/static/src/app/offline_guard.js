/**
 * Shared helper: counts locally-queued POS sales that haven't synced yet.
 * Both Task-1 guard sites (reloadData and loadInitialData) call this so
 * they can never drift apart.
 *
 * Uses getPendingOrder() which already filters to orders that have actual
 * content (lines or pay_later payments) — exactly what syncAllOrders() would
 * push.  Empty draft orders are not counted.
 *
 * @param {PosStore} pos
 * @returns {number}
 */
export function countUnsyncedSales(pos) {
    const { orderToCreate, orderToUpdate } = pos.getPendingOrder();
    return orderToCreate.length + orderToUpdate.length;
}
