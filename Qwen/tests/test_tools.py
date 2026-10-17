"""运行：python -m unittest tests.test_tools"""
import unittest
from unittest.mock import patch
from agent.tools.math.calculator import calculate, calculate_verified, result_footer, TOOL, parse, bounded
from fractions import Fraction
from agent.tools.math.verifier import verify


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

    def test_percent_exact_results(self):
        cases = [("200*10%", "20"), ("200/10%", "2000"),
                 ("100+10%", "1001/10"), ("(20+30)%", "1/2"),
                 ("-10%", "-1/10"), ("0%", "0"), ("0.1%", "1/1000"),
                 (".5%", "1/200"), ("1e2%", "1"), ("1e-2%", "1/10000"),
                 ("x*(1+20%)=120", "100"), ("x%=1", "100"),
                 ("(x+20)%=1", "80")]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                result = calculate_verified(expression)
                self.assertEqual(result["calculation"]["result"], expected)
                self.assertTrue(result["verification"]["valid"])
                calculation = result["calculation"].copy()
                calculation["result"] = "99" if expected != "99" else "98"
                self.assertFalse(verify(calculation)["valid"])

    def test_percent_contract_and_forced_verification(self):
        expression = " 200 * 10% "
        result = calculate_verified(expression)
        self.assertEqual(result["calculation"]["expression"], expression)
        self.assertIn(expression, result_footer(result))
        self.assertEqual(TOOL.name, "calculator")
        self.assertIn("%", TOOL.description)
        with patch("agent.tools.math.verifier.verify", return_value={"valid": False}):
            with self.assertRaises(ValueError):
                calculate_verified("200*10%")

    def test_percent_rejects_invalid_and_unsafe(self):
        cases = ["5%2", "%", "10%%", "%10", "10%2", "(10)%2", "1+%", "()",
                 "x*x%=4", "1/x%=2", "y%=1", "x%", "x=x", "x=x+1", "x=1=2",
                 "1/0%", "True%", "[10]%", "abs(10)%", "2**3%", "'10'%",
                 "10% # comment", "1 0%", "1\n+2%", "10% 2", "2(10%)",
                 "(10%)x=1", "ｘ%=1", "𝑥%=1", "１０%", "10％", "10%\u200b",
                 "(10%", "10%)", "\"10%\"", "10%\\\n+2", "1e101%", "1e-101%"]
        for expression in cases:
            with self.subTest(expression=expression):
                with self.assertRaises(ValueError):
                    calculate(expression)

    def test_percent_limits(self):
        self.assertEqual(calculate(" " * 253 + "10%")["result"], "1/10")
        with self.assertRaises(ValueError):
            calculate(" " * 254 + "10%")
        self.assertEqual(calculate("1e100%")["result"], str(Fraction("1e100") / 100))
        self.assertEqual(calculate("1e-100%")["result"], str(Fraction("1e-100") / 100))
        parse("+".join(["1%"] * 16))
        with self.assertRaises(ValueError):
            parse("+".join(["1%"] * 17))
        self.assertEqual(calculate("(" * 125 + "1%" + ")" * 125)["result"], "1/100")
        with self.assertRaises(ValueError):
            calculate("(" * 128 + "1%" + ")" * 128)
        self.assertEqual(bounded(Fraction(1 << 4095)), Fraction(1 << 4095))
        with self.assertRaises(ValueError):
            bounded(Fraction(1 << 4096))

    def test_reject_unsafe_or_unsupported(self):
        for expression in ["__import__('os').system('whoami')", "x*x=4", "1/0",
                           "x=x", "x=x+1", "2**100", "[1,2]", "True", "1/x=2",
                           "1e999999", "x+2", "y=3", "x=1=2", "9"*257]:
            with self.subTest(expression=expression):
                with self.assertRaises(ValueError):
                    calculate(expression)


if __name__ == "__main__":
    unittest.main()
