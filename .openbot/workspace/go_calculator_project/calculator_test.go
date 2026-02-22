package calculator

import (
	"testing"
)

func TestAdd(t *testing.T) {
	tests := []struct {
		name     string
		a, b     float64
		expected float64
	}{
		{"positive numbers", 2, 3, 5},
		{"negative numbers", -1, -1, -2},
		{"mixed numbers", -5, 10, 5},
		{"zero", 0, 5, 5},
		{"decimals", 1.5, 2.5, 4.0},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := Add(tt.a, tt.b)
			if result != tt.expected {
				t.Errorf("Add(%f, %f) = %f; want %f", tt.a, tt.b, result, tt.expected)
			}
		})
	}
}

func TestSubtract(t *testing.T) {
	tests := []struct {
		name     string
		a, b     float64
		expected float64
	}{
		{"positive numbers", 10, 3, 7},
		{"negative numbers", -5, -3, -2},
		{"mixed numbers", 10, -5, 15},
		{"zero", 5, 0, 5},
		{"decimals", 5.5, 2.0, 3.5},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := Subtract(tt.a, tt.b)
			if result != tt.expected {
				t.Errorf("Subtract(%f, %f) = %f; want %f", tt.a, tt.b, result, tt.expected)
			}
		})
	}
}

func TestMultiply(t *testing.T) {
	tests := []struct {
		name     string
		a, b     float64
		expected float64
	}{
		{"positive numbers", 4, 5, 20},
		{"negative numbers", -3, -4, 12},
		{"mixed numbers", -2, 5, -10},
		{"zero", 0, 100, 0},
		{"decimals", 2.5, 4.0, 10.0},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := Multiply(tt.a, tt.b)
			if result != tt.expected {
				t.Errorf("Multiply(%f, %f) = %f; want %f", tt.a, tt.b, result, tt.expected)
			}
		})
	}
}

func TestDivide(t *testing.T) {
	tests := []struct {
		name        string
		a, b        float64
		expected    float64
		expectError bool
	}{
		{"normal division", 10, 2, 5, false},
		{"division with decimals", 7, 2, 3.5, false},
		{"negative numbers", -10, 2, -5, false},
		{"both negative", -10, -2, 5, false},
		{"divide by zero", 10, 0, 0, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result, err := Divide(tt.a, tt.b)

			if tt.expectError {
				if err == nil {
					t.Errorf("Divide(%f, %f) expected error but got none", tt.a, tt.b)
				}
			} else {
				if err != nil {
					t.Errorf("Divide(%f, %f) unexpected error: %v", tt.a, tt.b, err)
				}
				if result != tt.expected {
					t.Errorf("Divide(%f, %f) = %f; want %f", tt.a, tt.b, result, tt.expected)
				}
			}
		})
	}
}
