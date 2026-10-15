/**
 * Plural rule for ru/uk. Messages list forms as `one | few | many`
 * (1, 21… | 2–4, 22–24… | 0, 5–20, 11–14…), optionally with a leading
 * zero form: `none | one | few | many`.
 */
export function slavicPlural(choice, choicesLength) {
  const n = Math.abs(Number(choice) || 0)
  const zeroForm = choicesLength === 4
  if (zeroForm && n === 0) return 0
  const mod10 = n % 10
  const mod100 = n % 100
  let idx
  if (mod10 === 1 && mod100 !== 11) idx = 0
  else if (mod10 >= 2 && mod10 <= 4 && !(mod100 >= 12 && mod100 <= 14)) idx = 1
  else idx = 2
  if (zeroForm) idx += 1
  return Math.min(idx, choicesLength - 1)
}
