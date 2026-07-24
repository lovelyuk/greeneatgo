export function contractFormFromItem(item) {
  const unitPrice = item.unit_price ?? item.contract?.unit_price;
  return {
    settlement_cycle: item.settlement_cycle ?? item.contract?.settlement_cycle ?? 'month_end',
    settlement_day: String(item.settlement_day ?? item.contract?.settlement_day ?? 25),
    unit_price: unitPrice == null ? '' : String(unitPrice),
    subsidy_enabled: !!(item.subsidy_enabled ?? item.contract?.subsidy_enabled),
    company_subsidy_amount: String(item.company_subsidy_amount ?? item.contract?.company_subsidy_amount ?? 0),
    restaurant_subsidy_amount: String(item.restaurant_subsidy_amount ?? item.contract?.restaurant_subsidy_amount ?? 0),
  };
}

export function subsidyContractInvalid(form) {
  if (!form.subsidy_enabled) return false;
  const unitPrice = Number(form.unit_price || 0);
  const subsidyTotal = Number(form.company_subsidy_amount || 0) + Number(form.restaurant_subsidy_amount || 0);
  return unitPrice <= 0 || subsidyTotal >= unitPrice;
}
