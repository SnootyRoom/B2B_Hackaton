// Разбор списка реестровых номеров, который пользователь вставил в поле.
// Принимаем номера через пробел, запятую, точку с запятой или с новой строки,
// а также ссылки с zakupki.gov.ru (берём из них regNumber=…).

/** 44-ФЗ — 19 цифр, 223-ФЗ — 11 цифр, старые извещения 223-ФЗ — 18 (REG_NUMBER_PATTERN на бэкенде) */
const VALID = /^(\d{11}|\d{18}|\d{19})$/;

export interface ParsedNumbers {
  /** Правильные номера без повторов, в порядке ввода */
  valid: string[];
  /** То, что похоже на номер, но не подходит (неверная длина и т. п.) — как ввёл пользователь */
  invalid: string[];
  /** Сколько повторов убрали */
  duplicates: number;
}

export function lawOfNumber(n: string): '44' | '223' {
  return n.length === 19 ? '44' : '223';
}

export function parseRegNumbers(text: string): ParsedNumbers {
  const valid: string[] = [];
  const invalid: string[] = [];
  const seen = new Set<string>();
  let duplicates = 0;

  for (const raw of text.split(/[\s,;]+/)) {
    if (!raw) continue;
    // Ссылка на карточку закупки: …?regNumber=0338300012324000045
    const fromUrl = /regNumber=(\d+)/i.exec(raw)?.[1];
    const token = fromUrl ?? raw.replace(/^№/, '');
    // Слова без цифр («номер», «закупки») молча пропускаем — пользователь мог вставить кусок текста
    if (!/\d/.test(token)) continue;
    const digits = token.replace(/[\s-]/g, '');
    if (!VALID.test(digits)) {
      invalid.push(raw.length > 40 ? raw.slice(0, 40) + '…' : raw);
      continue;
    }
    if (seen.has(digits)) {
      duplicates++;
      continue;
    }
    seen.add(digits);
    valid.push(digits);
  }
  return { valid, invalid, duplicates };
}
