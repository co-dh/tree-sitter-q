/ From code.kx.com/q/learn/tour/ and code.kx.com/q/learn/startingkdb/language/
/ Validated against q -q on 2026-04-01

/ Arithmetic
x: 2 5 4 7 5
count x
sum x
sums x

/ Functions
f: {2 + 3 * x}
f 5
f til 5

/ Multi-arg lambda
sumamt: {sum x*y}

/ Assignments
sales: 6 8 0 3
prices: 10 20 15 20

/ Application
sumamt[sales;prices]

/ Division
wprice: (sum sales*prices) % sum sales

/ Aggregation with adverb
total: (+/) sales*prices

/ Fibonacci via scan
fib: {x,sum -2#x}

/ Conditional (signum)
sign: {$[x>0;1;x<0;neg 1;0]}

/ Bool arithmetic
gt200: sales > 3

/ Negation
neg 5
