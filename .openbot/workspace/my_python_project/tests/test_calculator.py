"""Tests for calculator module."""
import pytest
from my_module import calculator


class TestCalculator:
    """Test cases for calculator functions."""
    
    def test_add(self):
        """Test addition."""
        assert calculator.add(2, 3) == 5
        assert calculator.add(-1, 1) == 0
        assert calculator.add(0, 0) == 0
    
    def test_subtract(self):
        """Test subtraction."""
        assert calculator.subtract(5, 3) == 2
        assert calculator.subtract(0, 0) == 0
        assert calculator.subtract(-1, -1) == 0
    
    def test_multiply(self):
        """Test multiplication."""
        assert calculator.multiply(2, 3) == 6
        assert calculator.multiply(0, 5) == 0
        assert calculator.multiply(-2, 3) == -6
    
    def test_divide(self):
        """Test division."""
        assert calculator.divide(6, 2) == 3
        assert calculator.divide(5, 2) == 2.5
        assert calculator.divide(-6, 2) == -3
    
    def test_divide_by_zero(self):
        """Test division by zero raises error."""
        with pytest.raises(ValueError):
            calculator.divide(5, 0)
