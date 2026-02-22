/**
 * Calculator module for basic math operations.
 */

/**
 * Add two numbers.
 * @param {number} a - First number
 * @param {number} b - Second number
 * @returns {number} Sum of a and b
 */
function add(a, b) {
  return a + b;
}

/**
 * Subtract b from a.
 * @param {number} a - First number
 * @param number} b - Second number
 * @returns {number} Difference of a and b
 */
function subtract(a, b) {
  return a - b;
}

/**
 * Multiply two numbers.
 * @param {number} a - First number
 * @param {number} b - Second number
 * @returns {number} Product of a and b
 */
function multiply(a, b) {
  return a * b;
}

/**
 * Divide a by b.
 * @param {number} a - Dividend
 * @param {number} b - Divisor
 * @returns {number} Quotient of a and b
 * @throws {Error} If b is zero
 */
function divide(a, b) {
  if (b === 0) {
    throw new Error("Cannot divide by zero");
  }
  return a / b;
}

module.exports = {
  add,
  subtract,
  multiply,
  divide
};
