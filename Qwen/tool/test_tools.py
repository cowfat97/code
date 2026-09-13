"""运行：python -m unittest tool.test_tools"""
import unittest
from .calculator import calculate
from .verifier import verify


class MathToolsTests(unittest.TestCase):
    def test_exact_arithmetic(self):
        for expression, expected in [("0.1+0.2", "3/10"), ("1/3+1/6", "1/2"),
                                     ("-(2+3)*4/2", "-10")]:
            result = calculate(expression)
            self.assertEqual(result["result"], expected)
            self.assertTrue(verify(result)["valid"])

    def test_equation(self):
        result = calculate("x*(1+20/100)*(1-20/100)=96")
        self.assertEqual(result["result"], "100")
        self.assertTrue(verify(result)["valid"])
        result["result"] = "99"
        self.assertFalse(verify(result)["valid"])

    def test_wrong_arithmetic(self):
        result = calculate("1+2")
        result["result"] = "4"
        self.assertFalse(verify(result)["valid"])

    def test_reject_unsafe_or_unsupported(self):
        for expression in ["__import__('os').system('whoami')", "x*x=4", "1/0",
                           "x=x", "x=x+1", "2**100", "[1,2]", "True", "1/x=2",
                           "1e999999", "x+2", "y=3", "x=1=2", "9"*257]:
            with self.subTest(expression=expression):
                with self.assertRaises(ValueError):
                    calculate(expression)


if __name__ == "__main__":
    unittest.main()
