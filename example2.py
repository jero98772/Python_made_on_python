# Functions — recursion and closures


def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)


def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


def is_even(n):
    return n % 2 == 0


def power(base, exp):
    result = 1
    for i in range(exp):
        result = result * base
    return result


print("Factorials:")
for i in range(1, 8):
    print(factorial(i))

print("Fibonacci sequence:")
for i in range(10):
    print(fibonacci(i))

print("Evens in 0..9:")
for i in range(10):
    if is_even(i):
        print(i)

print("2 ** 10 =")
print(power(2, 10))
