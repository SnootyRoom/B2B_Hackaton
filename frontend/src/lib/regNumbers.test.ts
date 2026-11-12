import { describe, expect, it } from 'vitest';
import { lawOfNumber, parseRegNumbers } from './regNumbers';

describe('разбор реестровых номеров', () => {
  it('принимает номера 44-ФЗ и 223-ФЗ через любые разделители', () => {
    const r = parseRegNumbers('0338300012324000045, 32616487757;\n0365100009826000031');
    expect(r.valid).toEqual(['0338300012324000045', '32616487757', '0365100009826000031']);
    expect(r.invalid).toEqual([]);
  });

  it('достаёт номер из ссылки на zakupki.gov.ru', () => {
    const r = parseRegNumbers(
      'https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=0338300012324000045',
    );
    expect(r.valid).toEqual(['0338300012324000045']);
  });

  it('убирает повторы и считает их', () => {
    const r = parseRegNumbers('32616487757 32616487757 №32616487757');
    expect(r.valid).toEqual(['32616487757']);
    expect(r.duplicates).toBe(2);
  });

  it('неправильные номера показывает отдельно, слова без цифр пропускает', () => {
    const r = parseRegNumbers('номера закупок: 12345 24100000509410101001 32616487757');
    expect(r.valid).toEqual(['32616487757']);
    // 20 цифр — это ИКУ заказчика, а не номер закупки
    expect(r.invalid).toEqual(['12345', '24100000509410101001']);
  });

  it('старые номера 223-ФЗ из 18 цифр тоже подходят', () => {
    expect(parseRegNumbers('31807123456789012 318071234567890123').valid).toEqual(['318071234567890123']);
  });

  it('закон определяется по длине номера', () => {
    expect(lawOfNumber('32616487757')).toBe('223');
    expect(lawOfNumber('318071234567890123')).toBe('223');
    expect(lawOfNumber('0338300012324000045')).toBe('44');
  });
});
