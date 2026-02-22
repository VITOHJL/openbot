/**
 * Tests for calculator module.
 */
const { add, subtract, multiply, divide } = require('../calculator');

describe('Calculator', () => {
  describe('add', () => {
    test('adds two positive numbers', () => {
      expect(add(2, 3)).toBe(5);
    });

    test('adds negative and positive number', () => {
      expect(add(-1, 1)).toBe(0);
    });

    test('adds two zeros', () => {
      expect(add(0, 0)).toBe(0);
    });
  });

  describe('subtract', () => {
    test('subtracts two numbers', () => {
      expect(subtract(5, 3)).toBe(2);
    });

    test('subtracts zeros', () => {
      expect(subtract(0, 0)).toBe(0);
    });

    test('subtracts negative numbers', () => {
      expect(subtract(-1, -1)).toBe(0);
    });
  });

  describe('multiply', () => {
    test('multiplies two numbers', () => {
      expect(multiply(2, 3)).toBe(6);
    });

    test('multiplies by zero', () => {
      expect(multiply(0, 5)).toBe(0);
    });

    test('multiplies negative numbers', () => {
      expect(multiply(-2, 3)).toBe(-6);
    });
  });

  describe('divide', () => {
    test('divides two numbers', () => {
      expect(divide(6, 2)).toBe(3);
    });

    test('divides decimal numbers', () => {
      expect(divide(5, 2)).toBe(2.5);
    });

    test('divides negative numbers', () => {
      expect(divide(-6, 2)).toBe(-3);
    });

    test('throws error when dividing by zero', () => {
      expect(() => divide(5, 0)).toThrow("Cannot divide by zero");
    });
  });
});
