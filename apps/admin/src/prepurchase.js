export const PREPURCHASE_MAX_QUANTITY = 1_000_000;
export const PREPURCHASE_MAX_UNIT_PRICE = 10_000_000;

function requiredString(item, field, index) {
  if (typeof item[field] !== 'string' || item[field].trim() === '') {
    throw new TypeError(`선구매 응답 items[${index}].${field} 값이 올바르지 않습니다.`);
  }
}

function nullableNonNegativeInteger(item, field, index) {
  const value = item[field];
  if (value !== null && (!Number.isSafeInteger(value) || value < 0)) {
    throw new TypeError(`선구매 응답 items[${index}].${field} 값이 올바르지 않습니다.`);
  }
}

export function prepurchaseItems(payload) {
  if (!payload || !Array.isArray(payload.items)) {
    throw new TypeError('선구매 응답에 items 배열이 없습니다.');
  }

  payload.items.forEach((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      throw new TypeError(`선구매 응답 items[${index}] 값이 올바르지 않습니다.`);
    }
    requiredString(item, 'merchant_company_id', index);
    requiredString(item, 'company_id', index);
    requiredString(item, 'company_name', index);
    if (typeof item.prepurchase_enabled !== 'boolean') {
      throw new TypeError(`선구매 응답 items[${index}].prepurchase_enabled 값이 올바르지 않습니다.`);
    }
    for (const field of ['purchase_quantity', 'unit_price', 'remaining_quantity']) {
      if (!Object.hasOwn(item, field)) {
        throw new TypeError(`선구매 응답 items[${index}].${field} 값이 없습니다.`);
      }
      nullableNonNegativeInteger(item, field, index);
    }
    if (item.latest_purchase_at !== null
      && (typeof item.latest_purchase_at !== 'string' || Number.isNaN(Date.parse(item.latest_purchase_at)))) {
      throw new TypeError(`선구매 응답 items[${index}].latest_purchase_at 값이 올바르지 않습니다.`);
    }
  });

  return payload.items.filter((item) => item.prepurchase_enabled);
}

export function prepurchaseChargeTotal(quantity, unitPrice) {
  const parsedQuantity = Number(quantity);
  const parsedUnitPrice = Number(unitPrice);
  if (!Number.isFinite(parsedQuantity) || !Number.isFinite(parsedUnitPrice)) return 0;
  return parsedQuantity * parsedUnitPrice;
}

export function prepurchaseChargePayload(quantity, unitPrice, idempotencyKey) {
  return {
    quantity: Number(quantity),
    unit_price: Number(unitPrice),
    idempotency_key: idempotencyKey,
  };
}

export function prepurchaseChargeInvalid(quantity, unitPrice) {
  const parsedQuantity = Number(quantity);
  const parsedUnitPrice = Number(unitPrice);
  return !Number.isInteger(parsedQuantity) || parsedQuantity <= 0 || parsedQuantity > PREPURCHASE_MAX_QUANTITY
    || !Number.isInteger(parsedUnitPrice) || parsedUnitPrice <= 0 || parsedUnitPrice > PREPURCHASE_MAX_UNIT_PRICE;
}
