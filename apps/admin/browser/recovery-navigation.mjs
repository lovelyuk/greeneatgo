// Recovery controls live only in the existing history tab. Keep financial
// assertions in callers unchanged; navigation is an explicit buyer action.
export async function openRecovery(page) {
  const button = page.getByRole('navigation').getByRole('button', { name: '내역', exact: true });
  if (await button.getAttribute('aria-current') !== 'page') await button.click();
}
